# [TICKET-003] TokenizerAdapter 抽象層與 JiebaPosAdapter (Tokenizer Adapter)

## Status
`done`

## Dependencies
- Requires: #001 ✅

## Description
實作 `engine/tokenizer_adapter.py`：規格 §5.1A 的分詞器抽象介面與預設實作 `JiebaPosAdapter`。白名單術語必須在分詞階段「絕對冷凍」——不被拆碎、標記 `is_frozen=True`，這是 L5 保護機制在引擎層的落點，也是後續所有 POS-Regex 規則的輸入基礎。

## Acceptance Criteria
- [x] `Token` dataclass 欄位與 §5.1A 完全一致：`surface`、`pos`（ICTCLAS/Jieba 兼容標籤）、`start_char`、`end_char`、`is_frozen`、`true_de_role`（預設空字串）。
- [x] `TokenizerAdapter` Protocol 定義 `register_whitelist(terms)` 與 `tokenize(text)`。
- [x] `JiebaPosAdapter` 以 `jieba.posseg` 實作；`register_whitelist` 對每個詞條呼叫 `jieba.add_word(term, freq=999999, tag=pos)`，分詞結果中白名單詞保持完整且 `is_frozen=True`。
- [x] `start_char`／`end_char` 正確對應原句字元索引（含中英夾雜文本），可供後續 span 定位與 `de_normalization_map` 使用。
- [x] 冷啟動效能符合 §3.1 目標：初始化＋首次分詞 < 0.1s（不含 jieba 詞典首次載入的快取建立；以合理量測方式驗證並記錄）。
- [x] 支援繁體文本：載入繁體優化詞表或等效處理，常見繁體詞不被錯誤切分。

## Design Reference
- `zh_polish_skill_spec_v2.md` §5.1A（介面定義與 JiebaPosAdapter 行為）、§3.1（算力分層與冷啟動目標）。

## References
- `config/default_lexicons.json`（#001）— 預設技術白名單的 term/pos 格式。

## Implementation Notes
- Required constraints: 介面必須是可替換的抽象層（Protocol），未來可抽換分詞器而不動規則引擎；`is_frozen` 語意由 L0/L5 白名單決定，adapter 只負責註冊與標記。
- Suggested approach: 繁體優化可用 opencc 簡轉繁詞表或自訂補充詞表；以計時測試記錄冷啟動數據。

## Testing
- 單元測試：白名單詞（如「高可用性」「冪等性」）在句中不被拆碎且 `is_frozen=True`；未登錄詞正常分詞；字元索引還原正確；中英夾雜（「進行 Fine-tuning」）索引不錯位。

## As-Built Notes
- 2026-11-19（TICKET-003 實作）：
  - 使用者決策（clarify 階段）：Q1 繁體支援採「預轉繁體詞典＋離線 opencc」——opencc（`opencc-python-reimplemented`，`s2twp`）僅列 dev 依賴，離線把 jieba `dict.txt` 的 word 欄簡轉繁，產出 `config/jieba_dict_traditional.txt`（347,385 詞條，~5MB）commit 進 repo；執行期零新依賴。Q2 冷啟動採「暖機後計時＋CI 斷言」：計時區間＝adapter init（含 register_whitelist）＋首次 tokenize，詞典首次載入排除於外。
  - 關鍵實作發現：繁体詞典必須用 `jieba.posseg.initialize(path)` 載入（同時重建 tokenizer FREQ 與 posseg `word_tag_tab`），不能用 `jieba.set_dictionary`——後者不重建 `word_tag_tab`，會使已知詞詞性全變 `x` 且分段劣化。`scripts/build_traditional_dict.py` 產出的 `word freq pos` 格式與 `load_word_tag` 相容。
  - 冷啟動架構：`pseg.initialize` 每次重讀 347k 行重建 word_tag（~0.16s），故 `_ensure_dictionary` 以 module guard 保证行程層級只載入一次；首次載入（含 jieba 快取建立，實測 ~0.5s）依 AC5 排除於計時。暖機後 init＋register＋首次分詞實測 **0.10 ms**（遠低於 0.1s），`tests/test_tokenizer_adapter.py::test_cold_start_under_100ms` 斷言 <0.1s 並印出實測值。
  - 字元索引：jieba.posseg 不附 offset，以單調 cursor 依序 `text.find(surface, cursor)` 重建 start/end；jieba 会 emit 空白／标点為 `x` token，故 surface 串接可還原原文（測試固化 full-coverage 不变量，含中英夾雜、換行、空白）。
  - 邊界遵守：adapter 只做註冊＋`is_frozen` 標記＋索引；`true_de_role` 留空字串供 L0（#004）填入；DE 消歧義／Markdown 遮罩不在本票。白名單由 `state_manager.merge_whitelists`（#002）产出 `List[dict]`（必含 pos）餵入；端到端驗證 stdin ephemeral 白名單（「局部性」）正确冷凍。
  - 工程慣例：`TokenizerError(ValueError)` 沿用 `LexiconError`／`StateError` 模式；pos 驗證對齊 state_manager（缺 pos 補 `nz`；明確空 pos 報錯）；`TokenizerAdapter` 用 `runtime_checkable` Protocol（可结构 isinstance 檢查， future 抽換分詞器不動規則引擎）。
  - 已知限制／注意：(1) 詞典為行程層級 singleton——`dict_path` 僅於首次初始化生效，後續实例沿用已載入詞典；`pseg.initialize`／`add_word` 會改動全域 jieba 狀態（引擎獨占分詞器，屬預期）。(2)「網路軟體」等複合詞併為一詞是 jieba 詞典內建條目的正常行為，非缺陷。(3) 繁體詞典為離線產出之資料檔，jieba 升級時需重跑 `scripts/build_traditional_dict.py`。
  - §3.2 最小必要補充：`config/jieba_dict_traditional.txt`（詞典資源，置於 config/ 與 default_lexicons.json 同處）與 `scripts/build_traditional_dict.py`（離線建置工具，非引擎模組）；opencc 加入 pyproject dev extras。
  - 驗證：`.venv/bin/python -m pytest` **55 passed**（41 既有＋14 新增）；含 Token 欄位、Protocol 结构、白名單冷凍／增量／pos 覆寫、索引還原（中英夾雜／換行／full coverage）、冷啟動 <0.1s、繁體常見詞（資料庫／資訊／軟體）、缺詞典報錯、register 驗證等錯誤路徑。