# [TICKET-011] TEST: Checkpoint 1 — Golden Test Suite 全層整合驗證

## Status
`done`

## Dependencies
- Requires: #007 ✅, #008 ✅, #009 ✅, #010 ✅

## Description
四層規則各自通過單元測試後，需要一個跨層整合關卡：以 §8.1 的四個 Golden Case 透過完整 CLI（`--mode lint --layer ALL`）端到端驗證多層共現偵測、白名單保護、L0 消歧義與 profile 閾值的協同行為。這是 Milestone 2 的完成定義；六個 Skills（Milestone 3）依賴此關卡通過，確保 SKILL.md 的 Few-Shot 與改寫指令建立在已驗證的診斷輸出上。

## Acceptance Criteria
- [x] Case 1（輸入：「在系統遷移的過程當中，我們對有關檢索模組的高可用性的問題進行了詳細的研究。」）：
  - `高可用性` `is_frozen=True` 且不觸發 L1_PSEUDO_JARGON。
  - 觸發 L3_PREPOSITIONAL_FRAME（兩處外框）與 L1_WEAK_VERB_NOMINALIZATION。
- [x] Case 2（輸入：「老師苦口婆心的勸了那個長得像你兄弟說話也有點像他的陌生男人半天，但他還是跑的很快。」）：
  - 「苦口婆心的勸」的「的」→ DE_ADV 並觸發 L2_ADVERB_DI_OVERUSE。
  - 16 字含動詞左分支觸發 L2_LEFT_BRANCH_OVERLOAD（非 tech profile）。
  - 「跑的很快」的「的」→ DE_COMP 並觸發 L0_TYPO_DE_COMP。
- [x] Case 3（輸入：「由於他的收入的減少，使得他的生活方式被徹底改變了。」）：
  - 觸發 L3_CAUSAL_MALFORMED、L1_INANIMATE_SUBJECT／L1_EVENT_NOMINALIZATION、L4_REDUNDANT_PRONOUNS、L1_PASSIVE_BEI。
- [x] Case 4（輸入：「這套架構比舊版起步更早及邁步更快，在灰暗的淒冷的天空下具有很高的可讀性。」）：
  - 觸發 L3_CONJUNCTION_MISUSE、L2_DE_CHAIN_NOISE、L1_PSEUDO_JARGON。
- [x] 四個 Case 的 payload 欄位完整（sentence_id、de_normalization_map、frozen_whitelist_hits、must_keep_content_words、每條 issue 的 theoretical_basis 與 instruction），summary 計數與 diagnostics 一致。
- [x] 全部斷言以自動化測試固化於測試套件，可重複執行。

## Design Reference
- `zh_polish_skill_spec_v2.md` §8.1（Golden Test Suite 完整斷言與目標改寫）、§4.2（payload 契約）。

## Implementation Notes
- Golden Case 的「目標改寫」是 LLM 改寫階段的品質標竿，不在本引擎關卡的自動斷言範圍（引擎只負責偵測與指令）；改寫品質由 Checkpoint 2 的 E2E dogfooding 驗證。
- Case 2 的左分支斷言須註明所用 profile（預設 tech 閾值 18 時 16 字不觸發，應以 essay/social 或 CLI --profile 驗證）。

## Testing
- 新增 `tests/test_golden_suite.py`（或等效），四個 Case 各一組斷言，執行測試指令全數通過。
- 結果記錄於本 ticket 完成時的 evidence（測試輸出摘要）。

## As-Built Notes

### 2026-11-21

- 四例在 `tests/test_ast_scanner.py` 各自走實際 CLI。每次先對同一份 stdin 跑 L5，再按案例指定的語體和暫用白名單跑 `ALL`。Case 1 採 `tech`，Case 2–4 採 `essay`，Case 2 另以 `tech` 驗證長前飾豁免。
- 採作者選定的 A。固定票面命中、原文位置與豁免，所有診斷都檢查欄位並納入摘要計數。Case 3 依 #007 的裁決驗事件名物化，Case 4 的「可讀性」交給 L1 診斷。
- `python -m pytest -q tests/test_ast_scanner.py -k golden_suite` 共 5 項通過，包含 Case 2 的語體對照。
- 全套 pytest 回歸共 814 項通過，#016 的 R-33 為 1 項既有預期失敗。逐份為舊測項補跑 L5，涵蓋 16 次 CLI 掃描與 275 次 Python 掃描。
- [PR #15](https://github.com/savourylie/wenqi/pull/15) 已合併於 `main`（`a99d004`），Checkpoint 1 通過，#012、#013 解鎖。
