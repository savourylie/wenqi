# [TICKET-018] L0 補語判定修正：程度副詞後的 vn 補語（N03 補語錯字漏報）

## Status
`pending`

## Dependencies
- Requires: #004 ✅
- Related: #016、#017

## Description
盲測 N03 原文為「聽完我的建議，她漸漸地放下焦慮，把採訪筆記寫得很生動，並決定先去淡水、九份與鹿港三座老城之一。」。「寫得很生動」的「得」應判 `DE_COMP`，但 Jieba 將「生動」標為 `vn`，`_is_complement` 在程度副詞（很）之後只接受 `{a, ad, b, an}` 或結果狀態詞，補語判定失敗，「得」退回 `DE_ATTR`。把原句改成錯字「寫的很生動」再跑仍零診斷，`L0_TYPO_DE_COMP` 漏報。漏報讓錯字診斷在常見補語結構失效，作者得不到「的→得」的修正指令。

## Acceptance Criteria
- [ ] 「寫得很生動」的「得」判為 `DE_COMP`，N03 原句零診斷。
- [ ] 錯字版「寫的很生動」報 `L0_TYPO_DE_COMP`，範圍為原文「的」的位置，建議為「得」。
- [ ] 「很多書」「更新內容」等名詞護欄與既有 L0「的／地／得」驗收不變；#016 R-33 的預期失敗狀態不變。
- [ ] 正反兩句以自動化測試固化，可重複執行。

## Design Reference
- [004 L0 消歧票](./004-l0-normalizer.md)
- [016 同模組修正先例](./016-l0-nominal-time-de-role.md)

## References
- `engine/l0_normalizer.py` `_is_complement` — 補語判定；`_COMPLEMENT_ADJECTIVE_POS = {a, ad, b, an}`。
- `tests/test_l0_normalizer.py`、`tests/test_ast_scanner.py` — 既有消歧與 CLI 驗收模式。

## Implementation Notes
- 必要約束：依 AGENTS.md，每份輸入先跑 L5 預檢再掃描；自動測試以題目明寫的 profile 代表作者裁決。
- 建議作法：程度副詞分支接受 `vn` 作形容性補語（很生動、很專業），以詞性規則涵蓋，不把「生動」硬編進詞庫。非程度分支的名詞護欄不動。
- 與 #016 同模組：兩票各自獨立驗收，全套回歸確認互不干擾。

## Testing
- 新增 N03 正句（得＝DE_COMP、零診斷）與錯字句（L0_TYPO_DE_COMP）成對對照，逐份先跑 L5 預檢。
- 重跑 L0 測試、Golden Case 2 對照與全套回歸；僅 #016 R-33 一項預期失敗。
