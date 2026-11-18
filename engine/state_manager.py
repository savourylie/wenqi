"""非侵入式狀態管理：讀寫 ~/.config/wenqi/ 與 Content Hash 自動對齊。

實作於 TICKET-002。規格：zh_polish_skill_spec_v2.md §4.1（儲存結構與兩份 Schema）、
§7（update-state CLI 參數）。

所有持久化狀態外部化於 ``~/.config/wenqi/``；文章檔案全程唯讀（僅為計算
content_hash 而開啟），絕不寫入或改動。遷移衝突採確定性規則（不加時間戳）：
路徑優先、唯一 hash 匹配才遷移、歧義時不覆寫並記錄 log。

設計決策（TICKET-002 clarify）：
- Q1：衝突時以 hash 匹配證據近似「較新」；多筆匹配不自动覆寫，保留現狀＋log。
- Q2：repo root 以 ``git rev-parse --show-toplevel`` 偵測；無 repo（或 git 不可用）
  則無狀態運行（只讀 global_config，不建 workspace），與 stdin 一致。
- Q3：content_hash 輸入域為原始檔文字（含 Markdown/frontmatter），去除所有空白後
  取前 300 個 Unicode 字元，SHA-256 前 8 碼。
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from . import LexiconError, load_default_lexicons

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "2.0.0"
CONTENT_HASH_CHARS = 300
HASH_HEX_LEN = 8
DEFAULT_PROFILE = "tech"
DEFAULT_POS = "nz"

#: §4.1A 三種語體 profile 預設（閾值、disabled_rules 與規格逐條一致）。
DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "tech": {
        "description": "技術架構與工程深度文：邏輯精確優先，放寬定語長度，保留顯性因果與技術名詞",
        "max_pre_modifier_len": 18,
        "max_clause_len": 24,
        "disabled_rules": ["L3_SHORT_CAUSAL_DROP"],
        "idiom_replacement_aggressiveness": "low",
    },
    "social": {
        "description": "社群觀點與短篇輸出（如 Threads）：強調呼吸推進與短分句，容許口語強調",
        "max_pre_modifier_len": 12,
        "max_clause_len": 16,
        "disabled_rules": ["L4_COPULA_SHI_DE"],
        "idiom_replacement_aggressiveness": "medium",
    },
    "essay": {
        "description": "人文隨筆、評論與敘事文本：全開余光中標準，嚴格執行後飾展開與零形回指",
        "max_pre_modifier_len": 12,
        "max_clause_len": 20,
        "disabled_rules": [],
        "idiom_replacement_aggressiveness": "high",
    },
}

_AGGRESSIVENESS_LEVELS = ("low", "medium", "high")


class StateError(ValueError):
    """狀態檔載入、schema 驗證或寫入失敗。"""


# ---------------------------------------------------------------------------
# 路徑與基礎工具
# ---------------------------------------------------------------------------


def default_state_dir() -> Path:
    """規格 §4.1 的狀態根目錄 ``~/.config/wenqi/``。"""
    return Path.home() / ".config" / "wenqi"


def _resolve_state_dir(state_dir: Optional[Path]) -> Path:
    return Path(state_dir) if state_dir is not None else default_state_dir()


def global_config_path(state_dir: Optional[Path] = None) -> Path:
    return _resolve_state_dir(state_dir) / "global_config.json"


def repo_hash(repo_root: Path) -> str:
    """repo 絕對路徑（resolve 後）SHA-256 前 8 碼（§4.1B workspace 檔名）。"""
    resolved = str(Path(repo_root).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:HASH_HEX_LEN]


def workspace_path(repo_root: Path, state_dir: Optional[Path] = None) -> Path:
    return _resolve_state_dir(state_dir) / "workspaces" / f"{repo_hash(repo_root)}.json"


def content_hash(text: str) -> str:
    """文章前 300 字（去除所有空白）的 SHA-256 前 8 碼（§4.1B；Q3 原始文字域）。"""
    stripped = "".join(text.split())
    payload = stripped[:CONTENT_HASH_CHARS].encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:HASH_HEX_LEN]


def file_content_hash(path: Path) -> str:
    """唯讀開啟文章計算指紋；絕不寫入文章本身。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StateError(f"無法讀取文章 {path}: {exc}") from exc
    return content_hash(text)


def find_repo_root(file_path: Path) -> Optional[Path]:
    """以 git rev-parse --show-toplevel 偵測 Repo Root（Q2）。

    檔案不在任何 Git Repo 內、git 不可用或目錄不存在時回傳 None，
    呼叫端應降級為無狀態運行（只讀 global_config，不建 workspace）。
    """
    parent = Path(file_path).resolve().parent
    if not parent.is_dir():
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=parent,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    root = proc.stdout.strip()
    return Path(root).resolve() if root else None


def _read_json(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"無法讀取狀態檔 {path}: {exc}") from exc


def _atomic_write_json(path: Path, data: Any) -> None:
    """同目錄暫存檔＋os.replace 原子寫入，避免半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as fh:
            tmp_name = fh.name
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        tmp_name = None
    except OSError as exc:
        raise StateError(f"無法寫入狀態檔 {path}: {exc}") from exc
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _validate_rel_path(rel_path: str) -> str:
    """documents key 必須是相對 Repo Root 的 POSIX 路徑，不得逸出 repo。"""
    if (
        not isinstance(rel_path, str)
        or not rel_path
        or "\\" in rel_path
        or PurePosixPath(rel_path).is_absolute()
        or ".." in PurePosixPath(rel_path).parts
    ):
        raise StateError(f"document key 必須為相對 Repo Root 路徑: {rel_path!r}")
    return rel_path


def _validate_profile_name(name: Any, where: str) -> str:
    if not isinstance(name, str) or name not in DEFAULT_PROFILES:
        expected = ", ".join(DEFAULT_PROFILES)
        raise StateError(f"{where}: 未知 profile {name!r}（須為 {expected} 之一）")
    return name


def _validate_rule_list(rules: Any, where: str) -> List[str]:
    if not isinstance(rules, list) or not all(
        isinstance(r, str) and r.strip() for r in rules
    ):
        raise StateError(f"{where}: 必須為非空字串組成的陣列")
    return list(rules)


def _validate_whitelist(entries: Any, where: str) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        raise StateError(f"{where}: 白名單必須為陣列")
    result: List[Dict[str, Any]] = []
    seen: set = set()
    for idx, entry in enumerate(entries):
        loc = f"{where}[{idx}]"
        if not isinstance(entry, dict):
            raise StateError(f"{loc}: 條目必須為物件")
        term = entry.get("term")
        if not isinstance(term, str) or not term.strip():
            raise StateError(f"{loc}: 缺少 term")
        if term in seen:
            raise StateError(f"{loc}: 重複條目 {term!r}")
        seen.add(term)
        item: Dict[str, Any] = {"term": term}
        for field in ("pos", "note"):
            if field in entry:
                value = entry[field]
                if not isinstance(value, str) or not value.strip():
                    raise StateError(f"{loc}: {field} 必須為非空字串")
                item[field] = value
        result.append(item)
    return result


def _coerce_entries(entries: Any, where: str) -> List[Dict[str, Any]]:
    """寫入入口用的條目驗證：pos 缺省補 nz（專有名詞）。"""
    validated = _validate_whitelist(entries, where)
    for item in validated:
        item.setdefault("pos", DEFAULT_POS)
    return validated


def _ephemeral_entries(terms: Optional[List[str]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for term in terms or []:
        if not isinstance(term, str) or not term.strip():
            raise StateError(f"--ephemeral-whitelist 詞條必須為非空字串: {term!r}")
        entries.append({"term": term.strip()})
    return entries


# ---------------------------------------------------------------------------
# 白名單合併與 profile 解析
# ---------------------------------------------------------------------------


def merge_whitelists(*layers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """三級白名單合併：global → repo_defaults → document local_whitelist（→ ephemeral）。

    以 term 為鍵，後者逐欄覆寫前者同詞條的 pos/note；保留首次出現順序。
    輸出條目必含 pos（缺省 nz），供 JiebaPosAdapter.register_whitelist 消費
    （規格 §5.1A，TICKET-003）。無效條目（缺 term）逕行跳过。
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for layer in layers:
        for entry in layer:
            if not isinstance(entry, dict):
                continue
            term = entry.get("term")
            if not isinstance(term, str) or not term.strip():
                continue
            if term in merged:
                for field in ("pos", "note"):
                    if field in entry:
                        merged[term][field] = entry[field]
            else:
                merged[term] = {
                    k: v for k, v in entry.items() if k in ("term", "pos", "note")
                }
    result: List[Dict[str, Any]] = []
    for item in merged.values():
        item.setdefault("pos", DEFAULT_POS)
        result.append(item)
    return result


def resolve_profile(
    global_config: Dict[str, Any],
    workspace: Optional[Dict[str, Any]] = None,
    document: Optional[Dict[str, Any]] = None,
    override: Optional[str] = None,
) -> str:
    """有效 profile 優先序：CLI --profile > 單篇 > repo_defaults > default_profile。"""
    if override is not None:
        return _validate_profile_name(override, "--profile")
    if document is not None and document.get("profile"):
        return _validate_profile_name(document["profile"], "document.profile")
    if workspace is not None and workspace["repo_defaults"].get("profile"):
        return _validate_profile_name(
            workspace["repo_defaults"]["profile"], "repo_defaults.profile"
        )
    return _validate_profile_name(global_config["default_profile"], "default_profile")


# ---------------------------------------------------------------------------
# global_config.json（§4.1A）
# ---------------------------------------------------------------------------


def _default_global_config() -> Dict[str, Any]:
    try:
        lexicons = load_default_lexicons()
    except LexiconError as exc:
        raise StateError(f"無法初始化全域白名單（內建詞庫載入失敗）: {exc}") from exc
    return {
        "schema_version": SCHEMA_VERSION,
        "default_profile": DEFAULT_PROFILE,
        "profiles": copy.deepcopy(DEFAULT_PROFILES),
        "global_whitelist": copy.deepcopy(lexicons["tech_whitelist"]),
    }


def _validate_global_config(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise StateError("global_config 必須為 JSON 物件")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise StateError(
            f"不支援的 schema_version {version!r}（預期 {SCHEMA_VERSION}；"
            "遷移機制保留供未來版本）"
        )
    config: Dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    config["default_profile"] = _validate_profile_name(
        data.get("default_profile", DEFAULT_PROFILE), "default_profile"
    )
    raw_profiles = data.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise StateError("profiles 必須為物件")
    profiles: Dict[str, Any] = {}
    for name, defaults in DEFAULT_PROFILES.items():
        raw = raw_profiles.get(name, {})
        if not isinstance(raw, dict):
            raise StateError(f"profiles.{name} 必須為物件")
        profile = copy.deepcopy(defaults)
        for field in ("max_pre_modifier_len", "max_clause_len"):
            if field in raw:
                value = raw[field]
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    raise StateError(f"profiles.{name}.{field} 必須為正整數")
                profile[field] = value
        if "disabled_rules" in raw:
            profile["disabled_rules"] = _validate_rule_list(
                raw["disabled_rules"], f"profiles.{name}.disabled_rules"
            )
        if "idiom_replacement_aggressiveness" in raw:
            value = raw["idiom_replacement_aggressiveness"]
            if value not in _AGGRESSIVENESS_LEVELS:
                raise StateError(
                    f"profiles.{name}.idiom_replacement_aggressiveness 必須為 "
                    f"{_AGGRESSIVENESS_LEVELS} 之一"
                )
            profile["idiom_replacement_aggressiveness"] = value
        if "description" in raw:
            if not isinstance(raw["description"], str):
                raise StateError(f"profiles.{name}.description 必須為字串")
            profile["description"] = raw["description"]
        profiles[name] = profile
    config["profiles"] = profiles
    config["global_whitelist"] = _validate_whitelist(
        data.get("global_whitelist", []), "global_whitelist"
    )
    return config


def load_global_config(state_dir: Optional[Path] = None) -> Dict[str, Any]:
    """讀取全域設定；檔案不存在時以內建預設初始化（白名單種子來自 #001 詞庫）。"""
    path = global_config_path(state_dir)
    if not path.exists():
        config = _default_global_config()
        _atomic_write_json(path, config)
        logger.info("以內建預設初始化全域設定: %s", path)
        return config
    return _validate_global_config(_read_json(path))


def save_global_config(
    config: Dict[str, Any], state_dir: Optional[Path] = None
) -> Dict[str, Any]:
    validated = _validate_global_config(config)
    _atomic_write_json(global_config_path(state_dir), validated)
    return validated


def add_global_whitelist(
    entries: List[Dict[str, Any]], state_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """§7 ``--mode update-state --add-global-whitelist`` 的寫入入口。

    同 term 覆寫 pos/note，不產生重複條目；寫入後回傳最新全域設定。
    """
    config = load_global_config(state_dir)
    config["global_whitelist"] = merge_whitelists(
        config["global_whitelist"], _coerce_entries(entries, "global_whitelist")
    )
    return save_global_config(config, state_dir)


# ---------------------------------------------------------------------------
# workspaces/<repo_hash>.json（§4.1B）
# ---------------------------------------------------------------------------


def _new_workspace(repo_root: Path) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "repo_root": str(Path(repo_root).resolve()),
        # profile None＝尚未設定，继承 global default_profile
        "repo_defaults": {"profile": None, "whitelist": []},
        "documents": {},
    }


def _new_document(ch: str) -> Dict[str, Any]:
    return {
        "content_hash": ch,
        "profile": None,
        "local_whitelist": [],
        "disabled_rules": [],
    }


def _validate_workspace(data: Any, repo_root: Path) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise StateError("workspace 必須為 JSON 物件")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise StateError(
            f"不支援的 schema_version {version!r}（預期 {SCHEMA_VERSION}）"
        )
    resolved = str(Path(repo_root).resolve())
    stored_root = data.get("repo_root")
    if not isinstance(stored_root, str) or not stored_root:
        raise StateError("workspace 缺少 repo_root")
    if stored_root != resolved:
        raise StateError(
            f"workspace repo_root 不符: 儲存 {stored_root!r}，目前 {resolved!r}"
            "（repo 可能已搬移；請手動遷移 workspace 檔）"
        )
    raw_defaults = data.get("repo_defaults", {})
    if not isinstance(raw_defaults, dict):
        raise StateError("repo_defaults 必須為物件")
    repo_profile = raw_defaults.get("profile")
    repo_defaults = {
        "profile": (
            _validate_profile_name(repo_profile, "repo_defaults.profile")
            if repo_profile is not None
            else None
        ),
        "whitelist": _validate_whitelist(
            raw_defaults.get("whitelist", []), "repo_defaults.whitelist"
        ),
    }
    raw_docs = data.get("documents", {})
    if not isinstance(raw_docs, dict):
        raise StateError("documents 必須為物件")
    documents: Dict[str, Any] = {}
    for rel_path, raw in raw_docs.items():
        _validate_rel_path(rel_path)
        where = f"documents[{rel_path}]"
        if not isinstance(raw, dict):
            raise StateError(f"{where}: 必須為物件")
        ch = raw.get("content_hash", "")
        if not isinstance(ch, str):
            raise StateError(f"{where}.content_hash 必須為字串")
        doc = _new_document(ch)
        if raw.get("profile") is not None:
            doc["profile"] = _validate_profile_name(raw["profile"], f"{where}.profile")
        doc["local_whitelist"] = _validate_whitelist(
            raw.get("local_whitelist", []), f"{where}.local_whitelist"
        )
        doc["disabled_rules"] = _validate_rule_list(
            raw.get("disabled_rules", []), f"{where}.disabled_rules"
        )
        documents[rel_path] = doc
    return {
        "schema_version": SCHEMA_VERSION,
        "repo_root": resolved,
        "repo_defaults": repo_defaults,
        "documents": documents,
    }


def load_workspace(
    repo_root: Path, state_dir: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """讀取 workspace；檔案不存在回傳 None（純讀取不建檔，lazy 建立）。"""
    path = workspace_path(repo_root, state_dir)
    if not path.exists():
        return None
    return _validate_workspace(_read_json(path), repo_root)


def save_workspace(
    workspace: Dict[str, Any], repo_root: Path, state_dir: Optional[Path] = None
) -> Dict[str, Any]:
    validated = _validate_workspace(workspace, repo_root)
    _atomic_write_json(workspace_path(repo_root, state_dir), validated)
    return validated


def add_local_whitelist(
    repo_root: Path,
    rel_path: str,
    entries: List[Dict[str, Any]],
    content_hash: Optional[str] = None,
    state_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """§7 ``--mode update-state --add-local-whitelist`` 的寫入入口。

    首次寫入時建立 workspace 檔；同 term 覆寫 pos/note。
    stdin 無 repo 情境不適用本函式（CLI 層應拒絕，見 TICKET-006）。
    """
    repo_root = Path(repo_root).resolve()
    _validate_rel_path(rel_path)
    workspace = load_workspace(repo_root, state_dir)
    if workspace is None:
        workspace = _new_workspace(repo_root)
    doc = workspace["documents"].get(rel_path)
    if doc is None:
        doc = _new_document(content_hash or "")
        workspace["documents"][rel_path] = doc
    elif content_hash:
        doc["content_hash"] = content_hash
    doc["local_whitelist"] = merge_whitelists(
        doc["local_whitelist"], _coerce_entries(entries, "local_whitelist")
    )
    return save_workspace(workspace, repo_root, state_dir)


def align_document(
    workspace: Dict[str, Any], rel_path: str, ch: str
) -> Tuple[Dict[str, Any], bool]:
    """路徑＋內容指紋雙重綁定與改名自動遷移（Q1 確定性規則）。

    回傳 ``(單篇設定, workspace 是否被修改)``。規則：
    1. 路徑命中且 hash 相符 → 直接使用；無指紋者補綁指紋。
    2. 路徑命中但 hash 不符（過期佔位）→ 唯一 hash 匹配則遷移取代；
       無匹配視為原文內容更新，保留設定並刷新指紋；多筆匹配不覆寫＋log。
    3. 路徑未命中 → 唯一 hash 匹配則遷移（改名／搬移）；多筆匹配不自動綁定，
       建立空設定＋log 留人工；無匹配建立新條目。
    """
    _validate_rel_path(rel_path)
    documents = workspace["documents"]
    entry = documents.get(rel_path)
    candidates = [
        p
        for p, d in documents.items()
        if p != rel_path and ch and d.get("content_hash") == ch
    ]
    if entry is not None:
        if entry.get("content_hash") == ch:
            return entry, False
        if not entry.get("content_hash"):
            entry["content_hash"] = ch
            return entry, True
        if len(candidates) == 1:
            source = candidates[0]
            displaced_hash = entry.get("content_hash")
            migrated = documents.pop(source)
            migrated["content_hash"] = ch
            documents[rel_path] = migrated
            logger.info(
                "content_hash 遷移: %s → %s（取代目標路徑過期佔位 hash %s, 新 hash %s）",
                source,
                rel_path,
                displaced_hash,
                ch,
            )
            return migrated, True
        if len(candidates) > 1:
            logger.warning(
                "content_hash 撞號 (%s): 多筆匹配 %s；保留現行路徑設定，請人工檢視",
                ch,
                candidates,
            )
            return entry, False
        logger.info(
            "文章內容指紋更新: %s (%s → %s)，保留原設定",
            rel_path,
            entry.get("content_hash"),
            ch,
        )
        entry["content_hash"] = ch
        return entry, True
    if len(candidates) == 1:
        source = candidates[0]
        migrated = documents.pop(source)
        documents[rel_path] = migrated
        logger.info("content_hash 改名遷移: %s → %s (hash %s)", source, rel_path, ch)
        return migrated, True
    if len(candidates) > 1:
        logger.warning(
            "content_hash 撞號 (%s): 多筆匹配 %s；不自動綁定，建立空設定，請人工檢視",
            ch,
            candidates,
        )
    doc = _new_document(ch)
    documents[rel_path] = doc
    return doc, True


# ---------------------------------------------------------------------------
# 高階設定讀取（所有 lint／preflight 呼叫的基礎）
# ---------------------------------------------------------------------------


def _settings_payload(
    *,
    source_type: str,
    global_config: Dict[str, Any],
    workspace: Optional[Dict[str, Any]],
    document: Optional[Dict[str, Any]],
    ch: str,
    profile: str,
    whitelist: List[Dict[str, Any]],
    repo_root: Optional[Path] = None,
    rel_path: Optional[str] = None,
) -> Dict[str, Any]:
    profile_config = global_config["profiles"][profile]
    return {
        "source_type": source_type,
        "repo_root": str(repo_root) if repo_root is not None else None,
        "rel_path": rel_path,
        "content_hash": ch,
        "effective_profile": profile,
        "profile_config": copy.deepcopy(profile_config),
        "whitelist": whitelist,
        # disabled_rules 原樣暴露（profile 級＋單篇級）；組合語義由 lint 消費者
        # （TICKET-006+）決定，本模組不越界合併。
        "disabled_rules": {
            "profile": list(profile_config["disabled_rules"]),
            "document": list(document["disabled_rules"]) if document else [],
        },
        "global_config": global_config,
        "workspace": workspace,
        "document": document,
    }


def load_settings_for_file(
    file_path: Path,
    profile_override: Optional[str] = None,
    ephemeral_terms: Optional[List[str]] = None,
    state_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """檔案模式設定讀取：repo 內走 workspace＋遷移；repo 外無狀態（Q2）。

    文章檔僅唯讀開啟計算指紋。ephemeral 白名單只於記憶體合併，永不落盤。
    """
    file_path = Path(file_path)
    ch = file_content_hash(file_path)
    global_config = load_global_config(state_dir)
    ephemeral = _ephemeral_entries(ephemeral_terms)
    repo_root = find_repo_root(file_path)
    if repo_root is None:
        logger.info("文章不在 Git Repo 內，無狀態運行（僅 global_config）: %s", file_path)
        profile = resolve_profile(global_config, override=profile_override)
        whitelist = merge_whitelists(global_config["global_whitelist"], ephemeral)
        return _settings_payload(
            source_type="file",
            global_config=global_config,
            workspace=None,
            document=None,
            ch=ch,
            profile=profile,
            whitelist=whitelist,
        )
    rel_path = file_path.resolve().relative_to(repo_root).as_posix()
    workspace = load_workspace(repo_root, state_dir)
    workspace_exists = workspace is not None
    if workspace is None:
        workspace = _new_workspace(repo_root)
    document, changed = align_document(workspace, rel_path, ch)
    if changed and workspace_exists:
        save_workspace(workspace, repo_root, state_dir)
    profile = resolve_profile(global_config, workspace, document, profile_override)
    whitelist = merge_whitelists(
        global_config["global_whitelist"],
        workspace["repo_defaults"]["whitelist"],
        document["local_whitelist"],
        ephemeral,
    )
    return _settings_payload(
        source_type="file",
        global_config=global_config,
        workspace=workspace,
        document=document,
        ch=ch,
        profile=profile,
        whitelist=whitelist,
        repo_root=repo_root,
        rel_path=rel_path,
    )


def load_settings_for_stdin(
    text: str,
    profile_override: Optional[str] = None,
    ephemeral_terms: Optional[List[str]] = None,
    state_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """``--stdin`` 隨手貼模式：不建立 workspace 檔，僅讀 global_config。

    ``--ephemeral-whitelist`` 於記憶體中合併，用完即棄（§4.1B）。
    """
    ch = content_hash(text)
    global_config = load_global_config(state_dir)
    ephemeral = _ephemeral_entries(ephemeral_terms)
    profile = resolve_profile(global_config, override=profile_override)
    whitelist = merge_whitelists(global_config["global_whitelist"], ephemeral)
    return _settings_payload(
        source_type="stdin",
        global_config=global_config,
        workspace=None,
        document=None,
        ch=ch,
        profile=profile,
        whitelist=whitelist,
    )
