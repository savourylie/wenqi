# Wenqi 專案指引

## 層級掃描測試先跑 L5

每次測試 L1、L2、L3、L4 或 `ALL` 的掃描結果，先對同一份輸入跑 L5 預檢，再掃描指定層。題庫逐題執行此流程，CLI 和跨層整合驗收也採相同順序。

1. 執行 `--mode preflight`，讀取 `L5_PREFLIGHT` 的語體建議和待確認術語。
2. 依作者裁決確定語體及白名單。自動測試以題目明寫的 `profile` 和 `ephemeral_whitelist` 代表作者裁決。待確認術語須經核可才加入白名單。
3. 用確認後的語體與白名單執行 `--mode lint --layer <L1|L2|L3|L4|ALL>`，再核對命中、原文範圍與豁免。使用 stdin 測試時，以 `--ephemeral-whitelist` 套用單篇核可詞。

流程依據見 [wenqi 規格 §6.1–6.3](zh_polish_skill_spec_v2.md#61-zh-l5-guard-語體定調與白名單守門員)。
