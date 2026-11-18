"""TICKET-001：規格 §3.2 目錄拓撲存在性驗證。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SPEC_PATHS = [
    "config/default_lexicons.json",
    "engine/__init__.py",
    "engine/ast_scanner.py",
    "engine/state_manager.py",
    "engine/tokenizer_adapter.py",
    "engine/l0_normalizer.py",
    "engine/rules/l1_vitality.py",
    "engine/rules/l2_branching.py",
    "engine/rules/l3_logic.py",
    "engine/rules/l4_cadence.py",
    "engine/rules/l5_preflight.py",
    "skills",
]


def test_spec_directory_topology():
    missing = [p for p in SPEC_PATHS if not (ROOT / p).exists()]
    assert not missing, f"缺少規格 §3.2 路徑: {missing}"


def test_engine_package_importable():
    import engine
    import engine.rules  # noqa: F401

    assert engine.__version__ == "2.0.0"