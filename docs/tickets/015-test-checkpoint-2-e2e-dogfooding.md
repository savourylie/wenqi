# [TICKET-015] TEST: Checkpoint 2 — E2E Dogfooding 與詞庫微調

## Status
`blocked`

## Dependencies
- Requires: #014

## Description
Milestone 4 最終驗收關卡：引擎與六個 Skills 就緒後，以真實文本端到端實測——真實技術文章（`--file` 模式，含 Markdown code block／連結／frontmatter）與隨手貼上的社群短文（`--stdin` 模式）。驗證整體系統在真實語料上的偵測品質、改寫品質與零侵入性，並據實測結果微調 `config/default_lexicons.json`。此關卡通過代表 wenqi v2.0.0 可交付日常使用。

## Acceptance Criteria
- [ ] 技術文實測（--file）：至少一篇真實技術架構文（含程式碼區塊、中英夾雜、技術術語），完整跑 wenqi-all 流程：
  - code block、inline code、連結、frontmatter、blockquote 零改動。
  - 技術白名單詞（高可用性類）零誤傷；guard 互動正確處理未登錄術語。
  - 改寫後文本經人工審視：無 AI 腔、must_keep 原詞保留、雙版本 Diff 可裁決。
- [ ] 社群短文實測（--stdin）：至少一篇 Threads 風格短文，social profile 生效（16 字呼吸閾值、「是…的」豁免），不產生 workspace 檔。
- [ ] 人文隨筆抽測（essay profile）：確認全開余光中標準的改寫方向（後飾展開、零形回指、四字格收束）。
- [ ] 原始文章檔案在整個流程中 bytes 不變（Read-Only 驗證）。
- [ ] 實測發現的誤報／漏報整理成清單，據以微調 `default_lexicons.json`（新增詞條或豁免），微調後 Golden Test Suite（Checkpoint 1）仍全數通過。
- [ ] 實測紀錄（輸入文本來源、命中規則統計、改寫前後對照、詞庫變更）保存於 repo（如 `docs/dogfooding/`）供後續回歸參考。

## Design Reference
- `zh_polish_skill_spec_v2.md` §8.2 Milestone 4、§2.5（語體邊界）、§4（零侵入性）、§6.4（改寫品質標竿）。

## Implementation Notes
- 實測文本由使用者提供或選取公開文章；若無合適技術文，可用本 repo 的規格文件自身作為測試語料（注意其為規格文，含大量刻意病句例）。
- 詞庫微調屬本關卡範圍；若實測暴露規則層級缺陷（非詞庫可解），開新 ticket 追蹤，不在本關卡內擴張實作。

## Testing
- 三種 profile 各一輪完整 dogfood，記錄於實測紀錄檔。
- 微調後重跑全部自動化測試（含 Golden Suite）確認無回歸。
- 需要使用者參與：guard 互動確認與改寫 Diff 的最終裁決由使用者（作者）驗收。