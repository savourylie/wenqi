# [TICKET-013] Skills：zh-l1～zh-l4 單層正交技能（含雙版本 Diff 規範）

## Status
`pending`

## Dependencies
- Requires: #011 ✅

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

## As-Built Notes

### 2026-11-22

- 依已確認決策建立四份單層正交技能：`skills/zh-l1-vitality/SKILL.md`、`skills/zh-l2-branching/SKILL.md`、`skills/zh-l3-logic/SKILL.md`、`skills/zh-l4-cadence/SKILL.md`，維持純 `SKILL.md` 範圍（符合規格 §3.2 拓撲，不更動 `engine/`）。
- **L5 預檢前置與握手銜接（Q1 選項 A）**：對齊 `AGENTS.md` 與 `#012`（`zh-l5-guard`）握手契約，各單層 Skill 執行 `--mode lint --layer <L1|L2|L3|L4>` 前先檢查同對話是否已對相同 `target_id`＋`content_hash` 完成 L5 握手；已握手則直接帶入 `--profile <tech|social|essay>`（與必要時的 `--ephemeral-whitelist`），未握手則先跑 `--mode preflight` 完成單輪確認後再執行單層 `lint`。同時沿用 `WENQI_ROOT`／`WENQI_PYTHON`（優先 `.venv/bin/python`）解析與只讀 `stdout` JSON 規範。
- **自包含內聯共用規範區塊（Q2 選項 A）**：四份 `SKILL.md` 以 `<!-- SHARED_SPEC_START -->` 至 `<!-- SHARED_SPEC_END -->` 內聯完全一字不差的共用規範文字（共 4,457 字元，SHA-256 前綴 `9447cb0234bc`），涵蓋步驟 0～1、嚴格正交隔離約束、最小手術防呆（`must_keep_content_words`、`frozen_whitelist_hits`、零 AI 腔增飾、零命中空狀態）、§6.4 雙版本 Diff 固定輸出模板與作者最終裁決權。
- **單層 A/B 改寫邊界與引擎實作欄位對齊（Q3 選項 A）**：
  - 【版本 A：微調版】僅針對本層 `issues` 的 `span` 依 `instruction` 做最小字面手術；【版本 B：竹節重構版】在僅限本層命中 `span` 及其直接依存範圍內強化動詞張力／後飾展開／意合銜接／竹節韻律；同句他層病灶（含單層模式下未進 `issues` 的 L0 `DE_COMP` 補語錯字如 Golden Case 2「跑的很快」）在 A/B 兩版皆 100% 原字保留。
  - 各層規則表與 Few-Shot 案例（L1 六類、L2 三類、L3 三類、L4 四類，直接節錄規格 Part I §2.1.2～§2.4.2）完整對齊 `#007`～`#010` 引擎實際輸出：含 L1 `severity: "info"`（弱動詞接英文動作）、L3 `L3_CAUSAL_MALFORMED`（主語湮沒 `priority: 0` 與 `L3_SHORT_CAUSAL_DROP` 停用開關）、L4 `suggested_breakpoint` 可選斷點與 `L4_REDUNDANT_PRONOUNS` 同指確認提示，以及同句必留詞衝突時 Scanner 覆寫為「保留…的原字，可調整…的語序」的保護指令。
- **驗收與 dogfood 驗證**（於隔離臨時 `HOME` 依 `AGENTS.md` 先 L5 `preflight` 再單層 `lint`）：
  - 自動化結構與契約檢查：四份 `SKILL.md` YAML frontmatter、CLI 簽章、Few-Shot 類別數（6/3/3/4）與共用規範區塊 100% 一致性檢查通過。
  - 四層單層正交 dogfood：對 Golden Cases 1～4 先跑 `preflight` 再分別跑 `--layer L1`、`L2`、`L3`、`L4`，驗證每層僅回傳該層 `issues`、雙版本 Diff 只改該層 `span` 而 100% 保留他層病灶與全數 `must_keep_content_words`／`frozen_whitelist_hits`（如 `高可用性`），且 `--file` 原稿 SHA-256（`2daa8765a61a`）零變動。
  - 全套回歸測試 `.venv/bin/python -m pytest -q` 通過（820 passed, 1 xfailed 既有 `#016` R-33），無引入回歸。
