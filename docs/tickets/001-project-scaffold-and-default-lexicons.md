# [TICKET-001] 專案骨架與內建詞庫 (Project Scaffold & Default Lexicons)

## Status
`done`

## Dependencies
- Requires: None

## Description
建立 `wenqi` 系統的工程骨架與共享資料基礎：規格 §3.2 的目錄拓撲、Python 專案設定（含 `jieba` 依賴與測試框架），以及 `config/default_lexicons.json` 內建基礎詞庫。後續所有引擎模組與 Skills 都依賴此骨架與詞庫；詞庫內容直接決定 L1 弱動詞/偽術語偵測與 L4 口水套語替換的覆蓋率。

## Acceptance Criteria
- [x] 存在規格 §3.2 的目錄結構：`config/`、`engine/`（含 `__init__.py` 與 `rules/`）、`skills/`；引擎模組檔可先為佔位 stub，但路徑與檔名須與規格一致。
- [x] Python 專案可安裝並執行：宣告 `jieba` 依賴與測試框架（如 pytest），`python3 -c "import jieba"` 與測試指令可跑。
- [x] `config/default_lexicons.json` 包含四類詞表，且每類至少收錄 Part I 案例庫出現的詞條：
  - 弱動詞表：進行、作出、加以、予以、給予、展開、造成。
  - 偽術語黑名單：知名度、可讀性、可看性、可聽性、前瞻性、嚴重性、必要性，及「難度很高的／熱情型的／專業性的／愛國主義的精神」等pattern。
  - 預設技術白名單：高可用性、可觀測性、可擴展性、冪等性、確定性、向量化（含 pos 與英文註記，與 §4.1A `global_whitelist` 一致）。
  - 四字格映射表：總的來說→總而言之／簡言之、不是一句話就能說清楚→一言難盡等。
- [x] 詞庫 JSON 可被程式載入並通過 schema 自檢（欄位齊全、無重複條目）。

## Design Reference
- `zh_polish_skill_spec_v2.md` §3.2（目錄結構）、§4.1A（global_whitelist 預設內容）、Part I §2.1.2／§2.4.2（詞表來源案例）。

## Implementation Notes
- Required constraints: 目錄與檔名必須與 §3.2 完全一致（後續 tickets 與 SKILL.md 的 CLI 路徑都引用它）；原始文稿 Read-Only，系統不得要求修改使用者文章。
- Suggested approach: 用 `pyproject.toml` 管理依賴；詞庫以「類別 → 條目陣列」結構組織，每條含 `term`、`pos`（如適用）、`note`／`replacement`，方便 state_manager 三級白名單合併與規則引擎直接消費。

## Testing
- 執行測試框架確認骨架可跑（至少一個詞庫載入與 schema 自檢測試通過）。
- 人工抽查四類詞表覆蓋 Part I 案例中的關鍵詞條。

## As-Built Notes
- 2026-11-19（TICKET-001 實作）：
  - 詞庫載入與 schema 自檢（`load_default_lexicons`／`validate_lexicons`）置於 `engine/__init__.py`，避免新增規格 §3.2 以外的模組檔；`LexiconError` 回報所有 schema 問題。
  - 新增 `engine/rules/__init__.py`（規格樹未列）：Python 套件發現所需，屬最小必要補充。
  - 詞庫結構：`weak_verbs`／`pseudo_jargon`（含 `is_pattern` regex 條目與 `replacements` 改寫對照）／`tech_whitelist`（與 §4.1A 逐條一致）／`idiom_map`（`replacements` 陣列）。嚴重性／必要性僅列黑名單（Part I 無明確改寫對照，改寫依上下文）。
  - 環境：`.venv`（gitignored）＋ `pip install -e ".[dev]"`；jieba 0.42.1、pytest 9.2.0。驗證指令：`.venv/bin/python -m pytest`（12 passed）。
  - 引擎模組為 docstring stub，各註明實作 ticket；`ast_scanner.main()` 以 NotImplementedError 明示 TICKET-006 邊界。
- 2026-11-19（專案改名）：依使用者決定，專案正式名稱由 codename `zh-polish` 改為 `wenqi`。pyproject name、引擎 docstring、規格文檔內容（狀態目錄 `~/.config/wenqi/`、總調度 Skill `wenqi-all`）、tickets 001/002/012/014/015 與 INDEX 同步更新；ticket 014 檔名改為 `014-skill-wenqi-all.md`。單層 Skill 名 zh-l1～zh-l4、zh-l5-guard 保留；規格檔名 `zh_polish_skill_spec_v2.md` 保留以維持引用穩定。