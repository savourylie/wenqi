# [TICKET-017] L2 左錨修正：名物化主語誤判為謂語（N02 長前飾誤報）

## Status
`pending`

## Dependencies
- Requires: #008 ✅
- Related: #011 ✅、#018

## Description
盲測 N02 原文為「服務載入這份記錄昨夜閘道攔截異常封包細節的日誌，隨即比對每筆錯誤碼，並把結果寫入備份表。」。「服務」在句中是主語，但 Jieba 標為 `vn`，`_left_anchor` 把它當成謂語動詞，左錨落在其後，「載入這份」於是被算進左分支：真實前飾「記錄昨夜閘道攔截異常封包細節的」15 字被算成 19 字，超過 `tech` 語體的 18 字門檻，誤報 `L2_LEFT_BRANCH_OVERLOAD`。只把「服務」換成「系統」（`n`），同一句就零診斷。誤報會叫作者拆掉符合語體門檻的句子，直接傷害診斷可信度；#012、#013 的 SKILL.md 改寫指令建立在診斷輸出上，必須先修正。

## Acceptance Criteria
- [ ] N02 原句以 `tech` 語體跑 `ALL` 不報 `L2_LEFT_BRANCH_OVERLOAD`，且與「系統」對照句結果一致（零診斷）。
- [ ] N02 原句以 `essay` 語體（門檻 12）仍報 `L2_LEFT_BRANCH_OVERLOAD`，範圍為「記錄昨夜閘道攔截異常封包細節的日誌」，不再含「載入這份」。
- [ ] Golden Case 2 的 16 字左分支 essay/tech 對照與既有 L2 驗收不變。
- [ ] 上述對照以自動化測試固化，可重複執行。

## Design Reference
- [008 L2 規則票](./008-l2-branching-rules.md)
- [wenqi 規格 §8.1 Golden Case 2 與語體門檻](../../zh_polish_skill_spec_v2.md)

## References
- `engine/rules/l2_branching.py` `_left_anchor` — 左錨起點判定；`_VERBS = {"v", "vn"}`。
- `tests/test_ast_scanner.py` `run_golden_case` — 先跑 L5 預檢的 CLI 驗收模式。

## Implementation Notes
- 必要約束：依 AGENTS.md，每份輸入先跑 L5 預檢再掃描；自動測試以題目明寫的 profile 代表作者裁決。
- 建議作法：左錨搜尋時，`vn` 詞若緊接另一個動詞（名物化主語＋謂語結構），不視為錨點動詞，讓左錨落到真正的謂語，再經數量詞規則起算。不改計數邏輯與門檻。
- 風險：連動結構（如「討論通過的方案」）的首個 `vn` 也會被略過，須以既有 L2 題庫與全套回歸確認沒有漏報。

## Testing
- 在 `tests/test_ast_scanner.py` 新增 N02 的 tech（原句與「系統」對照）與 essay 對照，逐份先跑 L5 預檢。
- 重跑 `python -m pytest -q tests/test_l2_branching.py tests/test_ast_scanner.py` 與全套回歸；基準為 814 項通過、僅 #016 R-33 一項預期失敗。
