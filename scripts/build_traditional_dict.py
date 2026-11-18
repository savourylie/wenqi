#!/usr/bin/env python3
"""離線產生 jieba 繁體優化詞典（TICKET-003，Q1 決策）。

jieba 內建 ``dict.txt`` 偏簡體，常見繁體詞会被錯誤切分。本脚本以 opencc
（``s2twp``，簡→繁含詞組）只轉換詞典的 ``word`` 欄，保留 ``freq``／``pos``，
產出 ``config/jieba_dict_traditional.txt`` 供 ``JiebaPosAdapter`` 初始化載入。

opencc 僅為開發／建置工具（dev 依賴），執行期不需要：adapter 直接讀這份
已轉換的詞典資料檔。surface 全程保留原繁體字，绝不轉換輸入文字。

用法::

    .venv/bin/python scripts/build_traditional_dict.py [輸出_path]

輸出檔為純 ``word freq pos`` 行（jieba 格式，不可加註解行）。同詞條去重取
最大 freq；依 word 排序以求確定性輸出。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "config" / "jieba_dict_traditional.txt"


def jieba_dict_path() -> Path:
    """定位已安裝 jieba 的內建 dict.txt。"""
    import importlib.util

    spec = importlib.util.find_spec("jieba")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("找不到 jieba 套件；請先安裝 jieba。")
    return Path(spec.submodule_search_locations[0]) / "dict.txt"


def build(output: Path) -> None:
    try:
        from opencc import OpenCC
    except ImportError as exc:  # pragma: no cover - 建置工具缺依賴
        raise SystemExit(
            "需要 opencc（dev 依賴）：pip install opencc-python-reimplemented"
        ) from exc

    converter = OpenCC("s2twp")
    source = jieba_dict_path()

    # converted word -> (freq, pos)；同詞取最大 freq。
    merged: dict[str, tuple[int, str]] = {}
    total = 0
    with open(source, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            word, rest = parts
            total += 1
            converted = converter.convert(word)
            if not converted or converted.isspace():
                continue
            rest_parts = rest.split()
            if len(rest_parts) < 2:
                continue
            try:
                freq = int(rest_parts[0])
            except ValueError:
                continue
            pos = rest_parts[1]
            prev = merged.get(converted)
            if prev is None or freq > prev[0]:
                merged[converted] = (freq, pos)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as fh:
        for word in sorted(merged):
            freq, pos = merged[word]
            fh.write(f"{word} {freq} {pos}\n")

    print(f"來源: {source}")
    print(f"讀取 {total} 行 → 去重後 {len(merged)} 個繁體詞條")
    print(f"輸出: {output}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    build(out)