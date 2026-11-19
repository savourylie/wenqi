# [TICKET-006] Scanner CLI 與 Diagnostic Payload 契約 (ast_scanner.py)

## Status
`pending`

## Dependencies
- Requires: #002 ✅, #004 ✅, #005 ✅

## Description
實作 `engine/ast_scanner.py` CLI 主入口：串接 state_manager、tokenizer、L0 與 L5 預檢，定義分句與 Diagnostic Payload 組裝邏輯，支援 §7 的完整參數介面。lint 模式先以可插拔的規則註冊機制回傳（此時 L1~L4 規則尚未實作，diagnostics 可為空但契約必須完整），使後續四層規則與六個 Skills 有穩定的輸出契約可依。

## Acceptance Criteria
- [ ] CLI 參數與 §7 一致：`--mode {preflight,lint,update-state}`、`--layer {L1,L2,L3,L4,ALL}`、`--file | --stdin`、`--profile {tech,social,essay}`、`--ephemeral-whitelist`、`--add-global-whitelist TERM:POS,...`、`--add-local-whitelist TERM:POS,...`。
- [ ] `--mode preflight` 輸出 §4.2 模式一 JSON（串接 #005）。
- [ ] `--mode update-state` 依參數寫入 global/local 白名單（串接 #002），輸出變更結果。
- [ ] `--mode lint` 輸出 §4.2 模式二 JSON 骨架：`mode`、`requested_layer`、`effective_profile`、`thresholds_applied`、`summary`（total_sentences/flagged_sentences/issue_counts）、`diagnostics` 陣列。
- [ ] 每筆 diagnostic 含完整欄位：`sentence_id`（如 `L14_S1`）、`line_number`、`context_before`、`target_sentence`、`context_after`、`frozen_whitelist_hits`、`must_keep_content_words`、`de_normalization_map`、`issues`。
- [ ] `must_keep_content_words` 正確抽取句中的實詞（名詞/動詞/形容詞核心）， frozen 白名單詞一律列入保護。
- [ ] 依 §4.2 以 `。！？` 和段落邊界斷句。診斷、前後文、`total_sentences` 和 `flagged_sentences` 都以整句為單位。每句的命中合併成一筆診斷，以原文的句首行定位。
- [ ] 需要分句的規則可在整句內依 `[，。！？；：]` 細分。整句與分句的切分及計數只取未遮罩正文（#004）。
- [ ] profile 解析優先序：CLI `--profile` > document 設定 > repo_defaults > global default_profile；`thresholds_applied` 反映生效 profile 的 `max_pre_modifier_len`／`max_clause_len`，`disabled_rules` 正確傳入規則層。
- [ ] 規則以註冊機制掛載（`--layer` 過濾），L1~L4 規則模組就緒後無需改動 CLI 即可生效。

## Design Reference
- `zh_polish_skill_spec_v2.md` §4.2（兩種 payload schema）、§7（CLI 介面）、§6.4（must_keep_content_words 防呆由來）。

## References
- `engine/state_manager.py`（#002）、`engine/l0_normalizer.py`（#004）、`engine/rules/l5_preflight.py`（#005）。

## Implementation Notes
- Required constraints: JSON 輸出必須機器可解析（stdout 純 JSON，日誌走 stderr）；`sentence_id` 與 `line_number` 必須可回溯原文，供 Diff 輸出定位。
- Suggested approach: 規則介面定義為 `scan(tokens, sentence_ctx, profile) -> List[Issue]`，Issue 含 layer/rule_id/priority/span/pos_pattern/theoretical_basis/instruction；CLI 負責組裝 payload 與 summary 計數。

## Testing
- CLI 整合測試：三種 mode 各跑一次，驗證 JSON schema 欄位齊全；`--stdin` 與 `--file` 行為一致（除 workspace 寫入）；`--profile` 覆寫生效；`--layer L1` 只回傳 L1 issues（規則掛載後）。
- 以 §4.2 模式二範例驗證 `sentence_id`、前後文與 `de_normalization_map` 對齊原文。單獨輸入含逗號的 `target_sentence` 時，`total_sentences` 為 1。掛載規則後驗證逗號兩側的命中共用一筆診斷。

## As-Built Notes

### 2026-11-19

- 檔案與 stdin 使用 UTF-8 原文，stdout 回傳 JSON。Preflight 以明確指定的語體優先，其餘情況沿用 005 的推測並以已解析設定備援。Lint 的語體優先序沿用 002，停用規則取生效語體與單篇設定的聯集。
- `update-state` 回傳 `UPDATE_STATE`、`target_id` 和各作用域已寫入的詞條。單篇寫入按原文指紋承接改名設定。CLI 以狀態目錄的鎖序列化讀取遷移與寫入，多作用域請求可重試，第二步失敗時會說明已寫入的作用域。
- 各層模組匯出的 `scan(tokens, sentence_ctx, profile)` 由 Scanner 按請求層級載入。規則取得整句、句內分句座標與段末標記。掃描與診斷使用同一組句內字元座標，`ALL` 可帶入 L0 補語用字診斷。
- 預檢與分詞共用詞組比對，作者確認的「進行 A/B testing」可完整冷凍。必留詞依核心名詞、動詞與形容詞提取，排除詞庫標記的弱動詞與偽術語，也排除「的過程當中」等句框的空殼詞。白名單命中一律列入必留詞。
- 全套 pytest 共 143 項通過。新增測試覆蓋三種模式、CRLF 與遮罩座標、規則掛載及停用、並行更新與改名持久化。另透過 CLI 核對 Golden Case 2 的 L0 標記及術語寫入後的預檢豁免。007～010 接續提供正式規則。
