# [TICKET-003] TokenizerAdapter 抽象層與 JiebaPosAdapter (Tokenizer Adapter)

## Status
`blocked`

## Dependencies
- Requires: #001

## Description
實作 `engine/tokenizer_adapter.py`：規格 §5.1A 的分詞器抽象介面與預設實作 `JiebaPosAdapter`。白名單術語必須在分詞階段「絕對冷凍」——不被拆碎、標記 `is_frozen=True`，這是 L5 保護機制在引擎層的落點，也是後續所有 POS-Regex 規則的輸入基礎。

## Acceptance Criteria
- [ ] `Token` dataclass 欄位與 §5.1A 完全一致：`surface`、`pos`（ICTCLAS/Jieba 兼容標籤）、`start_char`、`end_char`、`is_frozen`、`true_de_role`（預設空字串）。
- [ ] `TokenizerAdapter` Protocol 定義 `register_whitelist(terms)` 與 `tokenize(text)`。
- [ ] `JiebaPosAdapter` 以 `jieba.posseg` 實作；`register_whitelist` 對每個詞條呼叫 `jieba.add_word(term, freq=999999, tag=pos)`，分詞結果中白名單詞保持完整且 `is_frozen=True`。
- [ ] `start_char`／`end_char` 正確對應原句字元索引（含中英夾雜文本），可供後續 span 定位與 `de_normalization_map` 使用。
- [ ] 冷啟動效能符合 §3.1 目標：初始化＋首次分詞 < 0.1s（不含 jieba 詞典首次載入的快取建立；以合理量測方式驗證並記錄）。
- [ ] 支援繁體文本：載入繁體優化詞表或等效處理，常見繁體詞不被錯誤切分。

## Design Reference
- `zh_polish_skill_spec_v2.md` §5.1A（介面定義與 JiebaPosAdapter 行為）、§3.1（算力分層與冷啟動目標）。

## References
- `config/default_lexicons.json`（#001）— 預設技術白名單的 term/pos 格式。

## Implementation Notes
- Required constraints: 介面必須是可替換的抽象層（Protocol），未來可抽換分詞器而不動規則引擎；`is_frozen` 語意由 L0/L5 白名單決定，adapter 只負責註冊與標記。
- Suggested approach: 繁體優化可用 opencc 簡轉繁詞表或自訂補充詞表；以計時測試記錄冷啟動數據。

## Testing
- 單元測試：白名單詞（如「高可用性」「冪等性」）在句中不被拆碎且 `is_frozen=True`；未登錄詞正常分詞；字元索引還原正確；中英夾雜（「進行 Fine-tuning」）索引不錯位。