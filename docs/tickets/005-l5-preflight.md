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

## As-Built Notes

- 2026-11-19（TICKET-005）
  - Q1 採原文詞組比對。「進行 Fine-tuning」確認後，以完整的原文範圍豁免，並列入當篇命中的 `active_whitelist_terms`。每次預檢使用當次合併的白名單，暫用詞的豁免沿用同一套比對。
  - Q2 將 `profile_reason` 納入 §4.2，供 012 向作者呈現。語體先採用明確的 `--profile`，其次依技術詞密度、中英比例、弱動詞接英文及中文句長推測。線索不足時採用設定值。
  - `preflight()` 接收原文、來源識別與 #002 合併後的白名單。#006 傳入顯式語體覆寫，並把狀態管理解析出的語體作為備援。使用 #004 的 Markdown 遮罩及原文座標，原文用於內容指紋及例句。
  - 英文候選涵蓋弱動詞後第一個英文詞及連字形式，並接受常見時態助詞及次數。中文候選沿用 Jieba 的分詞邊界，另支援分詞器獨立切出後綴的情況。
  - `.venv/bin/python -m pytest -q` 共 118 項通過，涵蓋三層白名單、作者確認詞組後重新預檢、`stdin` 暫用詞、Markdown 遮罩、語體推測及覆寫。

- 2026-11-19（實句驗收修正）
  - 排除「一度」「十度」等數字加度數的量詞形式。「複雜度」和「滿意度」仍列為術語候選。
  - 弱動詞後擷取連續的英文詞，支援斜線縮寫與連字形式，遇到中文、標點、換行或遮罩即停止。以「進行 A/B testing」和「做一次 load testing」驗證完整詞組與白名單比對。
  - 重跑原句與新增兩項回歸測試後，`.venv/bin/python -m pytest -q` 共 120 項通過。

- 2026-11-19（詞界與計數再驗）
  - 以同篇已辨認的完整詞形比對原文。候選在相同後綴位置完整吻合時，補回較長的詞形再計數。「局部性」可合計兩次，「速度」和「加速度」各自計數。
  - 獨立的 `before` 與 `after` 可在英文詞組後標記時間說明。「進行 A/B testing before release」以「進行 A/B testing」送審，保留完整原句作例句。像 `before and after testing` 的比較用語保留在詞組內。
  - 原句與白名單重測均符合預期，`.venv/bin/python -m pytest -q` 共 122 項通過。

- 2026-11-19（獨立案例修正）
  - 遇到原文相鄰的「可＋單一動詞＋性」，以完整詞形參與候選計數與白名單比對。「可觀察性」可合計兩次，「可彈性調整」仍擷取「彈性」。
  - 語體判斷增加中文技術詞與口語線索。技術線索可由不同類別的詞互相佐證。口語線索採兩種獨立成詞的語氣詞，或表情符號搭配一個語氣詞。兩種語體都有明確線索時採備援設定，並在 `profile_reason` 列出雙方線索。明確的 `--profile` 優先。
  - `.venv/bin/python -m pytest -q` 共 130 項通過。獨立模型提供的原始案例 18/20 符合預期，將 L5-14、L5-15 換成補齊 Markdown 標記的對照後為 20/20。
