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

## As-Built Notes

### 2026-11-22

- 依已確認決策維持純 `SKILL.md` 範圍（`skills/zh-l5-guard/SKILL.md`），不更動 `engine/` 與規格 §7。因現行 `--mode update-state` 不接受 `--profile`，Skill 完成單輪確認後輸出固定「L5 守門員握手摘要」，規定同對話後續 `--mode lint`（含 `wenqi-all` Stage 2 與單層 Skills）明確帶入 `--profile`（Q1 選項 A）。
- `SKILL.md` 明訂 `WENQI_ROOT`（`SKILL.md` 上兩層 → 目前工作目錄 → `$WENQI_ROOT` 環境變數）與直譯器（優先 `"$WENQI_ROOT/.venv/bin/python"`，無則退回 `python3`）解析規則，支援跨 Repo 呼叫並避開系統 `python3` 缺 `jieba` 的問題（Q2 選項 A）；CLI 參數與 §6.1 / §7 完全對齊，並註明只讀 `stdout` JSON。
- 針對 `L5_PREFLIGHT` 無 `is_first_run` 欄位的現況，定為本對話對該稿件（`target_id`＋`content_hash`）首次執行一律發起單輪確認；僅在 `suspect_terms_for_review` 為空且「作者已明示語體」或「同對話已確認過同份稿件」時免互動直接放行（Q3 選項 A）。
- 補齊實作慣例：可攜 YAML frontmatter（僅 `name` 與 `description`）；Repo 外檔案選 `[L]` 自動降級為 `--ephemeral-whitelist` 並告知僅限本會話；`--stdin` 選 `[G]` 呼叫 `update-state` 時不帶 `--stdin`；`TERM:POS` 預設規則為 `~性/~度` → `nz`、`~化` → `vn`、`CODE_SWITCH_WEAK_VERB` → `v`；含空白片語加雙引號且寫入前去重；批次回覆漏答不自動豁免、僅追問漏答項；雙作用域部分失敗回報已寫入端並只重試失敗端。
- 驗收與 dogfood 驗證（皆於隔離臨時 `HOME` 執行，並依 `AGENTS.md` 先 L5 再 lint）：
  - YAML frontmatter 與 `ast_scanner.py --help` 旗標對齊檢查通過。
  - Dogfood 1（Git Repo `--file`）：`preflight` → `1G 2L 3X` → `update-state` 正確寫入 `global_config.json`（`局部性:nz`）與 `workspaces/<repo_hash>.json`（`進行 Fine-tuning:v`），原稿 SHA-256 零變動；重跑 `preflight` 與 L1 `lint` 確認凍結詞不誤報（含「具有很高的局部性」壓力測項），拒收詞「具有很高的可讀性」觸發 `L1_PSEUDO_JARGON`。
  - Dogfood 2（`--stdin`）：`[G]` 寫入全域不帶 `--stdin`，`[L]` 改走 `--ephemeral-whitelist` 且不產生 `workspaces/`，L1 `lint` 驗證通過。
  - Dogfood 3（Repo 外獨立 `--file`）：確認 `--add-local-whitelist` 依預期拒寫並退回 `--ephemeral-whitelist`，無 `workspaces/` 產生且 L1 `lint` 行為一致。
  - 全套回歸 `.venv/bin/python -m pytest -q` 共 `820 passed, 1 xfailed`（既有的 `#016` R-33），未引入回歸。
- 備註：後續若需讓 Git Repo 檔案的確認語體跨對話持久化，可另開引擎 follow-up ticket 擴充 `--mode update-state` 寫入 `document.profile`；此外 `SKILL.md` 於外部 CLI harness（Claude Code / OpenCode / Codex CLI）實機自動探索與跨技能串接留待 `#015` E2E dogfooding 實測。
