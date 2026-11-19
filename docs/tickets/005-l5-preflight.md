# [TICKET-005] L5 預檢：疑似術語抽取與語體推測 (L5 Preflight)

## Status
`pending`

## Dependencies
- Requires: #002 ✅, #003 ✅

## Description
實作 `engine/rules/l5_preflight.py`：改文前的守門員預檢。掃描文章中未登錄的疑似專有名詞（`~性/~度/~化` 後綴詞與中英夾雜弱動詞結構），推測本文語體（tech/social/essay），輸出 §4.2 模式一的 `L5_PREFLIGHT` payload，供 `zh-l5-guard` Skill 與作者互動建立白名單。沒有這層，L1 規則會把「高可用性」「冪等性」等精確技術定義誤當偽術語拆解。

## Acceptance Criteria
- [ ] 疑似術語抽取兩類 reason：
  - `SUFFIX_XING_UNREGISTERED`：帶「~性/~度/~化」後綴但未登錄於三級合併白名單的詞（附 count 與 sample_sentence）。
  - `CODE_SWITCH_WEAK_VERB`：弱動詞（進行/做/作出等）後接英文專有動作詞（如「進行 Fine-tuning」）。
- [ ] 已登錄白名單詞（global/repo/local 合併後）不出現在 `suspect_terms_for_review`，並列入 `active_whitelist_terms`。
- [ ] `suggested_profile` 依文本特徵自動推測（技術詞密度、中英夾雜比例、句長等），可被 CLI `--profile` 覆寫。
- [ ] 輸出 JSON 與 §4.2 模式一 schema 一致：`mode: "L5_PREFLIGHT"`、`source_type`、`target_id`、`content_hash`、`suggested_profile`、`active_whitelist_terms`、`suspect_terms_for_review`。
- [ ] `--stdin` 模式同樣可預檢（無 workspace，僅 global＋ephemeral 白名單）。

## Design Reference
- `zh_polish_skill_spec_v2.md` §2.5（L5 原理與領域誤傷）、§3.1（L5 守門員優先）、§4.2 模式一（payload schema）、§6.1（guard 互動流程）。

## References
- `engine/state_manager.py`（#002）— 三級白名單合併與 content_hash。
- `engine/tokenizer_adapter.py`（#003）— 分詞與 is_frozen 標記。

## Implementation Notes
- Required constraints: 預檢只抽取與建議，不自動寫入白名單（寫入由 guard Skill 經作者確認後呼叫 update-state）；「~性」詞若已 frozen 一律豁免。
- Suggested approach: 語體推測用簡單可解釋的啟發式計分（技術白名單命中數、英文詞比例、平均句長），保留推測理由便於 guard 向作者說明。

## Testing
- 單元測試：含「高可用性」（已登錄）與「局部性」（未登錄）的技術文本 → 前者不在 suspect、後者以 SUFFIX_XING_UNREGISTERED 出現；「對小模型進行 Fine-tuning」→ CODE_SWITCH_WEAK_VERB。
- 以 §4.2 模式一範例文本比對輸出欄位齊全且型別正確。