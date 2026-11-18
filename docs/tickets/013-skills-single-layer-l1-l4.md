# [TICKET-013] Skills：zh-l1～zh-l4 單層正交技能（含雙版本 Diff 規範）

## Status
`blocked`

## Dependencies
- Requires: #011

## Description
撰寫四個單層 Skills：`skills/zh-l1-vitality/SKILL.md`、`skills/zh-l2-branching/SKILL.md`、`skills/zh-l3-logic/SKILL.md`、`skills/zh-l4-cadence/SKILL.md`。每個 Skill 只呼叫對應 `--layer` 的 lint，並嚴格遵守正交隔離約束——即使句中同時存在其他層級病灶也絕不越層修改，讓作者能精確觀察單一層級規則的獨立效果。改寫輸出一律採 §6.4 雙版本 Diff（微調版 A／竹節重構版 B），並受 must_keep_content_words 與 frozen 詞保護。

## Acceptance Criteria
- [ ] 四份 SKILL.md 皆具備標準結構與觸發說明，各自呼叫 `python3 engine/ast_scanner.py --mode lint --layer <L1|L2|L3|L4> --file <path>`（或 --stdin）。
- [ ] 每份明載**嚴格正交隔離約束**：只修改該層 issues 標記的 span；同句其他層級病灶（如跑 L2 時的「進行了」）絕對禁止修改，並以反例說明。
- [ ] 每份明載最小手術防呆：禁止替換 `must_keep_content_words` 中的作者原詞；`frozen_whitelist_hits` 禁止拆改；禁止 AI 腔增飾。
- [ ] 改寫輸出固定為 §6.4 雙版本 Diff 格式：📍 行號與 sentence_id、命中規則、理論依據、保護錨點（🔒/⚓）、【原句】、【版本 A 微調版】、【版本 B 竹節重構版】。
- [ ] 各 Skill 將 Part I 對應層級案例庫濃縮為 Few-Shot Examples（L1 六類病灶、L2 三類、L3 三類、L4 四類，含 ❌→✅ 對照）。
- [ ] 各 Skill 的改寫指引與引擎 instruction 欄位一致（如 L1 弱動詞還原強動詞、L2 前飾改後飾、L3 以「而」代「及」、L4 零形回指與四字格收束）。
- [ ] 作者裁決權：Diff 僅供選擇，未經作者確認不得直接寫回原文檔。

## Design Reference
- `zh_polish_skill_spec_v2.md` §6.2（正交隔離）、§6.4（雙版本 Diff 與防呆）、Part I §2.1~§2.4（各層案例庫）、§5.2（各層轉換指令）。

## References
- `engine/ast_scanner.py`（#006）— lint payload 實際欄位。
- #007~#010 規則實作 — instruction 與 theoretical_basis 內容來源。

## Implementation Notes
- Required constraints: 四份 Skill 的 Diff 格式與防呆條款必須完全一致（共用同一段規範文字），僅層級、案例與 CLI 參數不同。
- Suggested approach: 先寫一份共用規範（可放各 SKILL.md 內重複或引用共用檔），再填入各層 Few-Shot；Few-Shot 直接節錄 Part I 案例，不得自創與理論矛盾的改寫。

## Testing
- 人工 dogfood 每層：以含多層病灶的句子（如 Golden Case 1）分別跑四層 Skill，驗證只改該層 span、其他層病灶原樣保留。
- 驗證 Diff 輸出格式與 §6.4 範例一致；must_keep 詞在 A/B 兩版皆保留。