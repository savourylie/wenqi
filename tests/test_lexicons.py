"""TICKET-001：詞庫載入、schema 自檢與 Part I 案例覆蓋驗證。"""

import copy

import pytest

from engine import (
    LEXICON_CATEGORIES,
    LexiconError,
    load_default_lexicons,
    validate_lexicons,
)


@pytest.fixture(scope="module")
def lexicons():
    return load_default_lexicons()


def test_load_and_validate(lexicons):
    assert lexicons["schema_version"] == "2.0.0"
    for category in LEXICON_CATEGORIES:
        assert isinstance(lexicons[category], list) and lexicons[category]


def test_weak_verbs_coverage(lexicons):
    terms = {e["term"] for e in lexicons["weak_verbs"]}
    assert {"進行", "作出", "加以", "予以", "給予", "展開", "造成"} <= terms
    assert all(e["pos"] == "v" for e in lexicons["weak_verbs"])


def test_pseudo_jargon_coverage(lexicons):
    entries = lexicons["pseudo_jargon"]
    terms = {e["term"] for e in entries}
    assert {"知名度", "可讀性", "可看性", "可聽性", "前瞻性", "嚴重性", "必要性"} <= terms
    patterns = {e["term"] for e in entries if e.get("is_pattern")}
    assert {"難度很高的?", "熱情型的?", "太?專業性的?", "愛國主義的精神"} <= patterns
    # 案例庫有明確改寫對照的詞條須附 replacements（§2.1.2）
    by_term = {e["term"]: e for e in entries}
    assert by_term["知名度"]["replacements"]
    assert by_term["可讀性"]["replacements"]
    assert by_term["前瞻性"]["replacements"] == ["更有遠見"]


def test_tech_whitelist_matches_spec_4_1_a(lexicons):
    expected = [
        ("高可用性", "nz", "High Availability"),
        ("可觀測性", "nz", "Observability"),
        ("可擴展性", "nz", "Scalability"),
        ("冪等性", "nz", "Idempotency"),
        ("確定性", "nz", "Determinism"),
        ("向量化", "vn", "Vectorization"),
    ]
    actual = [(e["term"], e["pos"], e["note"]) for e in lexicons["tech_whitelist"]]
    assert actual == expected


def test_idiom_map_coverage(lexicons):
    by_term = {e["term"]: e for e in lexicons["idiom_map"]}
    assert by_term["總的來說"]["replacements"] == ["總而言之", "簡言之"]
    assert "一言難盡" in by_term["不是一句話就能夠說得清楚的"]["replacements"]
    assert by_term["基於這個原因"]["replacements"] == ["因此", "為此"]


def test_validate_rejects_duplicate_term(lexicons):
    bad = copy.deepcopy(lexicons)
    bad["weak_verbs"].append(copy.deepcopy(bad["weak_verbs"][0]))
    with pytest.raises(LexiconError, match="重複條目"):
        validate_lexicons(bad)


def test_validate_rejects_missing_category(lexicons):
    bad = copy.deepcopy(lexicons)
    del bad["idiom_map"]
    with pytest.raises(LexiconError, match="idiom_map"):
        validate_lexicons(bad)


def test_validate_rejects_missing_required_field(lexicons):
    bad = copy.deepcopy(lexicons)
    del bad["tech_whitelist"][0]["pos"]
    with pytest.raises(LexiconError, match="pos"):
        validate_lexicons(bad)


def test_validate_rejects_empty_replacements(lexicons):
    bad = copy.deepcopy(lexicons)
    bad["idiom_map"][0]["replacements"] = []
    with pytest.raises(LexiconError, match="replacements"):
        validate_lexicons(bad)


def test_load_missing_file(tmp_path):
    with pytest.raises(LexiconError, match="無法載入詞庫"):
        load_default_lexicons(tmp_path / "nonexistent.json")