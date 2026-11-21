# [TICKET-012] Skill：zh-l5-guard 語體定調與白名單守門員

## Status
`pending`

## Dependencies
- Requires: #011 ✅

## Description
撰寫 `skills/zh-l5-guard/SKILL.md`：改文前的互動式守門員 Skill。呼叫 scanner preflight、解析疑似術語清單，以單輪互動向作者確認語體（tech/social/essay）與每個疑似專有名詞的作用域（Global/Local/Reject），並透過 update-state 寫入白名單。這是防止 L1 誤傷領域術語的第一道防線，也是 wenqi-all Stage 1 的握手對象。

## Acceptance Criteria
- [ ] SKILL.md 具備 agent skill 標準結構（名稱、觸發時機、執行步驟），可被 CLI coding agent（Claude Code/OpenCode/Codex CLI）載入執行。
- [ ] 流程依 §6.1：檔案模式 `python3 engine/ast_scanner.py --mode preflight --file <path>`；對話模式 `--stdin`；解析 L5_PREFLIGHT JSON。
- [ ] `suspect_terms_for_review` 非空或首次執行時，發起單輪互動：確認語體；每個疑似詞提供 [G] 全域永久豁免、[L] 僅限本文/本專案、[X] 非專有名詞三選項。
- [ ] [G] 呼叫 `--mode update-state --add-global-whitelist TERM:POS`；[L] 有檔案時 `--add-local-whitelist`，無檔案時以 `--ephemeral-whitelist` 傳入後續 CLI；[X] 不豁免。
- [ ] 互動文案向作者說明每個疑似詞的 reason 與 sample_sentence，以及語體推測依據；作者未確認前不得進入改寫。
- [ ] 包含 Few-Shot 互動範例（技術文含「局部性」未登錄詞的確認對話）。

## Design Reference
- `zh_polish_skill_spec_v2.md` §6.1（guard 執行步驟）、§3.1（L5 守門員優先）、§4.2 模式一（preflight payload）、§7（CLI）。

## References
- `engine/ast_scanner.py`（#006）— preflight/update-state 實際介面。
- `engine/rules/l5_preflight.py`（#005）— suspect reason 分類。

## Implementation Notes
- Required constraints: 白名單寫入必須經作者明確選擇，Skill 不得自動豁免；單輪互動（一次問完語體＋所有疑似詞），避免反覆打斷。
- Suggested approach: 以表格或條列呈現疑似詞清單供批次回覆（如「1G 2L 3X」）。

## Testing
- 人工 dogfood：對含未登錄「~性」詞的技術文執行 guard，驗證互動流程、G/L/X 三路徑寫入位置正確（global_config.json / workspace 檔 / 不落盤）。
- 驗證 Reject 的詞在後續 lint 中被 L1 規則正常偵測。