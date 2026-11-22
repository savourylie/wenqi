# [TICKET-014] Skill：wenqi-all 一鍵全修總調度器

## Status
`blocked`

## Dependencies
- Requires: #012 ✅, #013

## Description
撰寫 `skills/wenqi-all/SKILL.md`：一鍵全修總調度。三階段流程——Stage 1 自動呼叫 zh-l5-guard 完成語體與白名單握手；Stage 2 執行 `--mode lint --layer ALL` 全層掃描；Stage 3 對同句多層 Issue 以「由外而內」優先序在單次推論中折疊重構（Folded AST Rewrite），避免逐層改寫互相打架。輸出沿用雙版本 Diff 與最小手術防呆。

## Acceptance Criteria
- [ ] SKILL.md 明載三階段流程：Stage 1 preflight 握手（呼叫 zh-l5-guard 流程，含作者確認語體/白名單）；Stage 2 `--mode lint --layer ALL`；Stage 3 折疊式一次手術。
- [ ] Stage 3 優先序與 §6.3 一致：
  - Priority 1（L3）：剝介詞外框、清理「由於…使得…」、錯位「及」改「而」。
  - Priority 2（L2 & L4）：提取主語公因式、左分支長定語拆後飾竹節、成語「地/的」改逗號。
  - Priority 3（L1）：弱動詞還原強動詞、解凍名物化短句、無靈轉有靈、被動轉主動。
- [ ] 明載「同一句多層 Issue 在單次推論中折疊重構」，禁止逐層分次改寫同一句；改寫時尊重各 issue 的 priority 欄位。
- [ ] 沿用 §6.4 雙版本 Diff 輸出與防呆：must_keep_content_words 不可替換、frozen 詞不可拆改、作者未確認不寫回原文。
- [ ] 包含至少一個完整 Few-Shot：以 Golden Case 1 輸入展示 L3+L1 共現句的折疊重構與雙版本 Diff（目標改寫：「系統遷移時，我們詳加研究了檢索模組的高可用性。」）。
- [ ] 支援 `--file` 與 `--stdin` 兩種來源模式。

## Design Reference
- `zh_polish_skill_spec_v2.md` §6.3（三階段與折疊優先序）、§6.4（Diff 規範）、§8.1 Case 1（Few-Shot 素材）、§3.1（由外而內順序）。

## References
- `skills/zh-l5-guard/SKILL.md`（#012）— Stage 1 握手流程。
- #013 四份單層 SKILL.md — 共用防呆與 Diff 規範文字。

## Implementation Notes
- Required constraints: 折疊重構的理論依據是「先剝外框再動核心」——外框未剝除前動 L1 會產生錯誤 span；SKILL.md 須向 LLM 解釋此順序的 Why。
- Suggested approach: 以 Golden Case 3（四層共現）作為第二個 Few-Shot，展示 Priority 1→2→3 的完整折疊。

## Testing
- 人工 dogfood：對 Golden Case 1/3 輸入執行 wenqi-all，驗證握手→全層掃描→折疊改寫流程完整，輸出的 A/B 版與 §8.1 目標改寫方向一致（保護詞保留、無越層增飾）。
- 驗證 stdin 模式不產生 workspace 檔。