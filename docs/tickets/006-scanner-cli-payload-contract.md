# [TICKET-006] Scanner CLI 與 Diagnostic Payload 契約 (ast_scanner.py)

## Status
`blocked`

## Dependencies
- Requires: #002 ✅, #004, #005

## Description
實作 `engine/ast_scanner.py` CLI 主入口：串接 state_manager、tokenizer、L0 與 L5 預檢，定義分句與 Diagnostic Payload 組裝邏輯，支援 §7 的完整參數介面。lint 模式先以可插拔的規則註冊機制回傳（此時 L1~L4 規則尚未實作，diagnostics 可為空但契約必須完整），使後續四層規則與六個 Skills 有穩定的輸出契約可依。

## Acceptance Criteria
- [ ] CLI 參數與 §7 一致：`--mode {preflight,lint,update-state}`、`--layer {L1,L2,L3,L4,ALL}`、`--file | --stdin`、`--profile {tech,social,essay}`、`--ephemeral-whitelist`、`--add-global-whitelist TERM:POS,...`、`--add-local-whitelist TERM:POS,...`。
- [ ] `--mode preflight` 輸出 §4.2 模式一 JSON（串接 #005）。
- [ ] `--mode update-state` 依參數寫入 global/local 白名單（串接 #002），輸出變更結果。
- [ ] `--mode lint` 輸出 §4.2 模式二 JSON 骨架：`mode`、`requested_layer`、`effective_profile`、`thresholds_applied`、`summary`（total_sentences/flagged_sentences/issue_counts）、`diagnostics` 陣列。
- [ ] 每筆 diagnostic 含完整欄位：`sentence_id`（如 `L14_S1`）、`line_number`、`context_before`、`target_sentence`、`context_after`、`frozen_whitelist_hits`、`must_keep_content_words`、`de_normalization_map`、`issues`。
- [ ] `must_keep_content_words` 正確抽取句中的實詞（名詞/動詞/形容詞核心）， frozen 白名單詞一律列入保護。
- [ ] 分句以 `[，。！？；：]` 等標點切分並保留行號對應；遮罩區（#004）不參與分句計數。
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
- 以 §4.2 模式二範例句驗證 sentence_id、context、de_normalization_map 欄位格式。