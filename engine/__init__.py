"""wenqi 引擎套件。

五層中文寫作優化系統的本地確定性引擎（規格 Part II）。
本模組提供內建詞庫 `config/default_lexicons.json` 的載入與 schema 自檢，
供 state_manager（TICKET-002）初始化全域白名單、tokenizer_adapter
（TICKET-003）註冊保護詞，以及 L1/L4 規則引擎（TICKET-007/010）消費詞表。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

__version__ = "2.0.0"

DEFAULT_LEXICON_PATH = Path(__file__).resolve().parent.parent / "config" / "default_lexicons.json"

#: 詞庫四大類別（TICKET-001 驗收條件）。
LEXICON_CATEGORIES = ("weak_verbs", "pseudo_jargon", "tech_whitelist", "idiom_map")

#: 各類別條目的必填欄位。
_REQUIRED_FIELDS = {
    "weak_verbs": ("term", "pos"),
    "pseudo_jargon": ("term",),
    "tech_whitelist": ("term", "pos", "note"),
    "idiom_map": ("term", "replacements"),
}


class LexiconError(ValueError):
    """詞庫載入或 schema 自檢失敗。"""


def load_default_lexicons(path: Path | str | None = None) -> Dict[str, Any]:
    """載入內建詞庫並通過 schema 自檢；失敗時拋出 LexiconError。"""
    lexicon_path = Path(path) if path is not None else DEFAULT_LEXICON_PATH
    try:
        with open(lexicon_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise LexiconError(f"無法載入詞庫 {lexicon_path}: {exc}") from exc
    validate_lexicons(data)
    return data


def validate_lexicons(data: Any) -> None:
    """schema 自檢：類別齊全、必填欄位齊全、類別內無重複條目。"""
    problems: List[str] = []
    if not isinstance(data, dict):
        raise LexiconError("詞庫必須為 JSON 物件")
    if not isinstance(data.get("schema_version"), str) or not data["schema_version"]:
        problems.append("缺少 schema_version")
    for category in LEXICON_CATEGORIES:
        entries = data.get(category)
        if not isinstance(entries, list) or not entries:
            problems.append(f"缺少類別或類別為空: {category}")
            continue
        seen: set = set()
        for idx, entry in enumerate(entries):
            where = f"{category}[{idx}]"
            if not isinstance(entry, dict):
                problems.append(f"{where}: 條目必須為物件")
                continue
            for field in _REQUIRED_FIELDS[category]:
                value = entry.get(field)
                if field == "replacements":
                    if not isinstance(value, list) or not value or not all(
                        isinstance(r, str) and r.strip() for r in value
                    ):
                        problems.append(f"{where}: replacements 必須為非空字串陣列")
                elif not isinstance(value, str) or not value.strip():
                    problems.append(f"{where}: 缺少必填欄位 {field}")
            term = entry.get("term")
            if isinstance(term, str):
                if term in seen:
                    problems.append(f"{where}: 重複條目 {term!r}")
                seen.add(term)
            if "is_pattern" in entry and not isinstance(entry["is_pattern"], bool):
                problems.append(f"{where}: is_pattern 必須為布林值")
    if problems:
        raise LexiconError("詞庫 schema 自檢失敗:\n- " + "\n- ".join(problems))