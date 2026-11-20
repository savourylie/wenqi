# [TICKET-016] L0 消歧修正：名詞性時間詞組後的「的」

## Status
`pending`

## Dependencies
- Requires: #004 ✅
- Related: #007、#008

## Description
R-33 的原文是「休息時間的減少讓實習生疲於奔命，主管已調整排班。」Jieba 將「休息時間」標為 `i`，L0 因此把「的」判為 `DE_ADV`。原句以「休息時間的減少」當主語，此處的「的」是定語標記。以 `social` 語體跑 `ALL` 時，L1 漏報無靈主語，L2 將「休息時間的減少」誤報為長狀語。

## Acceptance Criteria
- [ ] R-33 的 `de_normalization_map` 在原文句內索引 4 回報「的」為 `DE_ATTR`。
- [ ] R-33 的 L1 診斷命中 `L1_INANIMATE_SUBJECT`，範圍為「休息時間的減少讓實習生疲於奔命」。L2 不回報同一短語的 `L2_ADVERB_DI_OVERUSE`。
- [ ] Golden Case 2 的「苦口婆心的勸」仍判為 `DE_ADV` 並命中 L2 長狀語規則。其餘索引和豁免依既有驗收。
- [ ] R-33 在 L1 題庫通過後移除對應的 `known_gap`。

## Design Reference
- [004 的消歧規格](./004-l0-normalizer.md)
- [L0 詞性窗口、L1/L2 規則與 Golden Case 2](../../zh_polish_skill_spec_v2.md)

## Implementation Notes
- 先確認詞性來源，再在分詞或 L0 消歧的共用入口修正。以名詞性時間詞組與確實作狀語的成語對照，讓 L1 與 L2 取得一致的語法角色。

## Testing
- 每份輸入先執行 L5 預檢，依題庫的作者裁決跑 `L1`、`L2` 或 `ALL`。R-33 採 `social`，題目記錄的單篇暫用白名單為空。
- 覆蓋 R-33 的角色、原文範圍與 L2 豁免，並重跑 L0 的「的／地／得」和 Golden Case 2 對照。
