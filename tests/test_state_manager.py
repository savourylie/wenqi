"""TICKET-002：非侵入式狀態管理與 Content Hash 對齊驗證。

規格：zh_polish_skill_spec_v2.md §4.1（兩份 Schema）、§7（update-state 入口）。
以暫存 HOME 隔離所有狀態寫入；並驗證目標文章檔案 bytes 全程不變。
"""

import hashlib
import json
import logging
import subprocess

import pytest

from engine import load_default_lexicons
from engine.state_manager import (
    DEFAULT_PROFILES,
    SCHEMA_VERSION,
    StateError,
    add_global_whitelist,
    add_local_whitelist,
    align_document,
    content_hash,
    default_state_dir,
    file_content_hash,
    find_repo_root,
    load_global_config,
    load_settings_for_file,
    load_settings_for_stdin,
    load_workspace,
    merge_whitelists,
    repo_hash,
    resolve_profile,
    save_global_config,
    save_workspace,
    workspace_path,
)

ARTICLE = """---
title: 代理記憶系統
---

# 代理記憶系統

在系統重構的過程當中，團隊對檢索模組的高可用性進行了詳細的評估。
我們對小模型進行 Fine-tuning，透過快取提升資料存取的局部性。
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """暫存 HOME：所有 ~/.config/wenqi/ 寫入隔離於 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "blog-repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@pytest.fixture
def article(repo):
    path = repo / "posts" / "2026-11-agent-memory.md"
    path.parent.mkdir(parents=True)
    path.write_text(ARTICLE, encoding="utf-8")
    return path


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# global_config.json（§4.1A）
# ---------------------------------------------------------------------------


def test_global_config_initialized_from_defaults(home):
    config = load_global_config()
    assert (home / ".config" / "wenqi" / "global_config.json").exists()
    assert config["schema_version"] == SCHEMA_VERSION
    assert config["default_profile"] == "tech"
    assert config["profiles"] == DEFAULT_PROFILES
    # 白名單種子來自 #001 內建詞庫，與 §4.1A 逐條一致
    assert config["global_whitelist"] == load_default_lexicons()["tech_whitelist"]


def test_global_config_fills_missing_fields(home):
    _write_json(
        default_state_dir() / "global_config.json",
        {
            "schema_version": SCHEMA_VERSION,
            "default_profile": "essay",
            "profiles": {"tech": {"max_clause_len": 30}},
        },
    )
    config = load_global_config()
    assert config["default_profile"] == "essay"
    assert config["profiles"]["tech"]["max_clause_len"] == 30  # 保留自訂值
    assert config["profiles"]["tech"]["max_pre_modifier_len"] == 18  # 補預設
    assert config["profiles"]["social"] == DEFAULT_PROFILES["social"]
    assert config["global_whitelist"] == []


def test_global_config_rejects_corrupt_json(home):
    path = default_state_dir() / "global_config.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(StateError, match="無法讀取狀態檔"):
        load_global_config()


def test_global_config_rejects_unknown_version(home):
    _write_json(
        default_state_dir() / "global_config.json", {"schema_version": "1.0.0"}
    )
    with pytest.raises(StateError, match="schema_version"):
        load_global_config()


def test_add_global_whitelist_persists_and_overrides(home):
    add_global_whitelist([{"term": "混合檢索", "pos": "nz", "note": "Hybrid Retrieval"}])
    config = add_global_whitelist([{"term": "混合檢索", "note": "Hybrid Search"}])
    by_term = {e["term"]: e for e in config["global_whitelist"]}
    assert by_term["混合檢索"]["pos"] == "nz"  # 未被覆寫欄位保留
    assert by_term["混合檢索"]["note"] == "Hybrid Search"
    assert len(config["global_whitelist"]) == 7  # 6 預設＋1，無重複
    assert load_global_config()["global_whitelist"] == config["global_whitelist"]


# ---------------------------------------------------------------------------
# content_hash 與 repo 偵測
# ---------------------------------------------------------------------------


def test_content_hash_matches_definition():
    text = "  高可用性\n與冪等性  "
    expected = hashlib.sha256("高可用性與冪等性".encode("utf-8")).hexdigest()[:8]
    assert content_hash(text) == expected
    # 空白差異不影響指紋
    assert content_hash("高可用性 與\n冪等性") == expected
    # 只取前 300 字（去空白後）
    long_text = "字" * 400
    assert content_hash(long_text) == content_hash("字" * 300)
    assert content_hash("字" * 300 + "X") == content_hash("字" * 300)  # 第 301 字不影響
    assert content_hash("字" * 299 + "X") != content_hash("字" * 300)  # 前 300 字內變動即變號
    assert content_hash("") == hashlib.sha256(b"").hexdigest()[:8]


def test_file_content_hash_readonly(article):
    before = article.read_bytes()
    assert file_content_hash(article) == content_hash(ARTICLE)
    assert article.read_bytes() == before


def test_find_repo_root(repo, article, tmp_path):
    assert find_repo_root(article) == repo.resolve()
    loose = tmp_path / "loose.md"
    loose.write_text("隨手貼", encoding="utf-8")
    assert find_repo_root(loose) is None


# ---------------------------------------------------------------------------
# workspace（§4.1B）與遷移
# ---------------------------------------------------------------------------


def _workspace_with_doc(repo, rel_path, ch, **doc_fields):
    doc = {
        "content_hash": ch,
        "profile": None,
        "local_whitelist": [],
        "disabled_rules": [],
    }
    doc.update(doc_fields)
    return {
        "schema_version": SCHEMA_VERSION,
        "repo_root": str(repo.resolve()),
        "repo_defaults": {"profile": "tech", "whitelist": []},
        "documents": {rel_path: doc},
    }


def test_workspace_roundtrip_and_filename(repo, home):
    ch = content_hash(ARTICLE)
    ws = _workspace_with_doc(repo, "posts/a.md", ch)
    save_workspace(ws, repo)
    expected_name = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:8]
    assert workspace_path(repo).name == expected_name + ".json"
    assert repo_hash(repo) == expected_name
    loaded = load_workspace(repo)
    assert loaded["documents"]["posts/a.md"]["content_hash"] == ch
    assert load_workspace(repo.resolve()) == loaded


def test_rename_migration_preserves_settings(repo, home):
    ch = content_hash(ARTICLE)
    ws = _workspace_with_doc(
        repo,
        "posts/old.md",
        ch,
        profile="essay",
        local_whitelist=[{"term": "混合檢索", "pos": "nz"}],
        disabled_rules=["L4_COPULA_SHI_DE"],
    )
    save_workspace(ws, repo)
    loaded = load_workspace(repo)
    doc, changed = align_document(loaded, "posts/new.md", ch)
    assert changed
    assert doc["profile"] == "essay"
    assert doc["local_whitelist"] == [{"term": "混合檢索", "pos": "nz"}]
    assert doc["disabled_rules"] == ["L4_COPULA_SHI_DE"]
    assert "posts/old.md" not in loaded["documents"]
    save_workspace(loaded, repo)
    assert "posts/new.md" in load_workspace(repo)["documents"]


def test_migration_replaces_stale_occupant(repo, home):
    ch = content_hash(ARTICLE)
    ws = _workspace_with_doc(
        repo, "posts/old.md", ch, local_whitelist=[{"term": "時間衰減", "pos": "nz"}]
    )
    ws["documents"]["posts/new.md"] = {
        "content_hash": "00000000",
        "profile": None,
        "local_whitelist": [],
        "disabled_rules": [],
    }
    save_workspace(ws, repo)
    loaded = load_workspace(repo)
    doc, changed = align_document(loaded, "posts/new.md", ch)
    assert changed
    assert doc["local_whitelist"] == [{"term": "時間衰減", "pos": "nz"}]
    assert "posts/old.md" not in loaded["documents"]


def test_ambiguous_hash_no_overwrite(repo, home, caplog):
    ch = content_hash(ARTICLE)
    ws = _workspace_with_doc(repo, "posts/a.md", ch, profile="essay")
    ws["documents"]["posts/b.md"] = {
        "content_hash": ch,
        "profile": "social",
        "local_whitelist": [],
        "disabled_rules": [],
    }
    save_workspace(ws, repo)
    loaded = load_workspace(repo)
    with caplog.at_level(logging.WARNING, logger="engine.state_manager"):
        doc, changed = align_document(loaded, "posts/c.md", ch)
    assert changed  # 仅新增空設定，既有兩筆不被覆寫
    assert loaded["documents"]["posts/a.md"]["profile"] == "essay"
    assert loaded["documents"]["posts/b.md"]["profile"] == "social"
    assert doc["profile"] is None
    assert any("撞號" in r.message for r in caplog.records)


def test_in_place_content_edit_keeps_settings(repo, home):
    ws = _workspace_with_doc(
        repo, "posts/a.md", "11111111", local_whitelist=[{"term": "混合檢索", "pos": "nz"}]
    )
    save_workspace(ws, repo)
    loaded = load_workspace(repo)
    doc, changed = align_document(loaded, "posts/a.md", "22222222")
    assert changed
    assert doc["content_hash"] == "22222222"
    assert doc["local_whitelist"] == [{"term": "混合檢索", "pos": "nz"}]


def test_add_local_whitelist_lazy_creation(repo, home):
    assert load_workspace(repo) is None
    assert not workspace_path(repo).exists()
    ch = content_hash(ARTICLE)
    add_local_whitelist(repo, "posts/a.md", [{"term": "混合檢索"}], content_hash=ch)
    ws = load_workspace(repo)
    doc = ws["documents"]["posts/a.md"]
    assert doc["content_hash"] == ch
    assert doc["local_whitelist"] == [{"term": "混合檢索", "pos": "nz"}]
    add_local_whitelist(repo, "posts/a.md", [{"term": "混合檢索", "note": "Hybrid"}])
    doc = load_workspace(repo)["documents"]["posts/a.md"]
    assert doc["local_whitelist"] == [
        {"term": "混合檢索", "pos": "nz", "note": "Hybrid"}
    ]


def test_rel_path_validation(repo, home):
    with pytest.raises(StateError, match="相對 Repo Root"):
        add_local_whitelist(repo, "../escape.md", [{"term": "X"}])
    with pytest.raises(StateError, match="相對 Repo Root"):
        add_local_whitelist(repo, "/abs/path.md", [{"term": "X"}])


def test_workspace_repo_root_mismatch(repo, home, tmp_path):
    other = tmp_path / "other-repo"
    other.mkdir()
    ws = _workspace_with_doc(repo, "posts/a.md", "11111111")
    with pytest.raises(StateError, match="repo_root 不符"):
        save_workspace(ws, other)


def test_workspace_rejects_corrupt_json(repo, home):
    path = workspace_path(repo)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(StateError, match="無法讀取狀態檔"):
        load_workspace(repo)


# ---------------------------------------------------------------------------
# 三級合併與 profile 解析
# ---------------------------------------------------------------------------


def test_three_level_merge_override():
    global_layer = [{"term": "A", "pos": "nz", "note": "G"}]
    repo_layer = [{"term": "A", "pos": "n", "note": "R"}, {"term": "B", "pos": "nz"}]
    local_layer = [{"term": "A", "note": "L"}]
    ephemeral = [{"term": "C"}]
    merged = merge_whitelists(global_layer, repo_layer, local_layer, ephemeral)
    assert [e["term"] for e in merged] == ["A", "B", "C"]
    by_term = {e["term"]: e for e in merged}
    assert by_term["A"]["pos"] == "n"  # repo 覆寫 global
    assert by_term["A"]["note"] == "L"  # local 覆寫 repo
    assert by_term["C"]["pos"] == "nz"  # ephemeral 缺省 pos


def test_profile_precedence(home):
    config = load_global_config()
    ws = {
        "repo_defaults": {"profile": "essay", "whitelist": []},
        "documents": {},
    }
    doc_social = {"profile": "social"}
    assert resolve_profile(config) == "tech"
    assert resolve_profile(config, ws) == "essay"
    assert resolve_profile(config, ws, doc_social) == "social"
    assert resolve_profile(config, ws, doc_social, override="tech") == "tech"
    assert resolve_profile(config, ws, {"profile": None}) == "essay"
    unset_repo = {"repo_defaults": {"profile": None, "whitelist": []}, "documents": {}}
    assert resolve_profile(config, unset_repo) == "tech"  # None＝继承 global
    with pytest.raises(StateError, match="未知 profile"):
        resolve_profile(config, override="academic")


def test_unset_repo_profile_inherits_global_default(home, repo, article):
    config = load_global_config()
    config["default_profile"] = "essay"
    save_global_config(config)
    # 無 workspace 的 repo：skeleton 不得以 tech 覆寫全域預設
    settings = load_settings_for_file(article)
    assert settings["effective_profile"] == "essay"
    # workspace 建立後 repo profile 未設定（null）仍继承
    add_local_whitelist(repo, settings["rel_path"], [{"term": "混合檢索"}])
    assert load_workspace(repo)["repo_defaults"]["profile"] is None
    assert load_settings_for_file(article)["effective_profile"] == "essay"


# ---------------------------------------------------------------------------
# 高階讀取：file／stdin／無 repo
# ---------------------------------------------------------------------------


def test_stdin_stateless(home):
    settings = load_settings_for_stdin(
        "我們對小模型進行 Fine-tuning。", ephemeral_terms=["MemFuse", "FlowDance"]
    )
    assert settings["source_type"] == "stdin"
    assert settings["repo_root"] is None
    assert settings["workspace"] is None
    assert not (default_state_dir() / "workspaces").exists()
    terms = {e["term"]: e for e in settings["whitelist"]}
    assert terms["MemFuse"]["pos"] == "nz"
    assert "高可用性" in terms  # global 白名單仍在
    assert settings["content_hash"] == content_hash("我們對小模型進行 Fine-tuning。")


def test_stdin_profile_override(home):
    settings = load_settings_for_stdin("短文", profile_override="essay")
    assert settings["effective_profile"] == "essay"
    assert settings["profile_config"]["max_clause_len"] == 20
    assert settings["profile_config"]["idiom_replacement_aggressiveness"] == "high"


def test_file_outside_repo_stateless(home, tmp_path):
    loose = tmp_path / "loose.md"
    loose.write_text(ARTICLE, encoding="utf-8")
    settings = load_settings_for_file(loose, ephemeral_terms=["TempTerm"])
    assert settings["repo_root"] is None
    assert settings["workspace"] is None
    assert not (default_state_dir() / "workspaces").exists()
    assert {"TempTerm"} <= {e["term"] for e in settings["whitelist"]}


def test_file_in_repo_full_flow(repo, home, article):
    settings = load_settings_for_file(article)
    assert settings["repo_root"] == str(repo.resolve())
    assert settings["rel_path"] == "posts/2026-11-agent-memory.md"
    assert settings["content_hash"] == content_hash(ARTICLE)
    assert settings["effective_profile"] == "tech"
    # 純讀取不建 workspace 檔（lazy）
    assert not workspace_path(repo).exists()
    add_local_whitelist(
        repo,
        settings["rel_path"],
        [{"term": "混合檢索", "pos": "nz"}],
        content_hash=settings["content_hash"],
    )
    settings = load_settings_for_file(article)
    assert {"混合檢索"} <= {e["term"] for e in settings["whitelist"]}
    assert settings["disabled_rules"] == {
        "profile": ["L3_SHORT_CAUSAL_DROP"],
        "document": [],
    }


def test_file_rename_migration_end_to_end(repo, home, article):
    settings = load_settings_for_file(article)
    add_local_whitelist(
        repo,
        settings["rel_path"],
        [{"term": "時間衰減", "pos": "nz"}],
        content_hash=settings["content_hash"],
    )
    new_path = article.parent / "renamed-memory.md"
    article.rename(new_path)
    settings = load_settings_for_file(new_path)
    assert settings["rel_path"] == "posts/renamed-memory.md"
    assert {"時間衰減"} <= {e["term"] for e in settings["whitelist"]}
    docs = load_workspace(repo)["documents"]
    assert "posts/renamed-memory.md" in docs
    assert "posts/2026-11-agent-memory.md" not in docs


def test_ephemeral_not_persisted(repo, home, article):
    settings = load_settings_for_file(article, ephemeral_terms=["TempTerm"])
    assert {"TempTerm"} <= {e["term"] for e in settings["whitelist"]}
    assert not workspace_path(repo).exists()
    add_local_whitelist(repo, settings["rel_path"], [{"term": "混合檢索"}])
    doc = load_workspace(repo)["documents"][settings["rel_path"]]
    assert {"TempTerm"} not in {e["term"] for e in doc["local_whitelist"]}


def test_article_bytes_unchanged(repo, home, article):
    """AC：全程不寫入、不改動使用者文章檔案本身。"""
    before = article.read_bytes()
    load_settings_for_file(article)
    assert article.read_bytes() == before
    settings = load_settings_for_file(article, ephemeral_terms=["MemFuse"])
    add_local_whitelist(
        repo, settings["rel_path"], [{"term": "混合檢索"}], content_hash=settings["content_hash"]
    )
    assert article.read_bytes() == before
    new_path = article.parent / "moved.md"
    article.rename(new_path)
    load_settings_for_file(new_path)
    assert new_path.read_bytes() == before
    load_settings_for_stdin(ARTICLE)
    assert new_path.read_bytes() == before


def test_non_utf8_article_raises(home, tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(StateError, match="無法讀取文章"):
        load_settings_for_file(bad)


def test_empty_article(home, tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    settings = load_settings_for_file(empty)
    assert settings["content_hash"] == content_hash("")
    assert settings["effective_profile"] == "tech"
