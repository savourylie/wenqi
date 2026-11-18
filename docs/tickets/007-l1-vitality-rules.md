# [TICKET-007] L1 規則引擎：詞性與語態重心 (l1_vitality.py)

## Status
`blocked`

## Dependencies
- Requires: #006

## Description
實作 `engine/rules/l1_vitality.py`：依 §5.2 第一層規則矩陣偵測「化動為靜」病灶——弱動詞＋動名詞（文字義肢）、短句名物化、偽術語、冗餘複數與「之一」、無靈主語、生硬被動。每條 Issue 附帶 `theoretical_basis`（注入 Part I 語言學理據供 LLM 改寫）與具體轉換指令。白名單 frozen 詞在本層必須全程豁免。

## Acceptance Criteria
- [ ] 實作六條規則，偵測 pattern、豁免條件與轉換指令依 §5.2 L1 表格：
  - `L1_WEAK_VERB_NOMINALIZATION`：`[介詞+NP]? + 弱動詞(進行/作出/加以/予以/給予/展開/造成) + [了/過]? + [修飾]? + vn`；frozen vn 豁免；後接英文詞時改發 `info` 級微調建議（語法黏著劑豁免）。
  - `L1_EVENT_NOMINALIZATION`：主語/受詞位置 `NP + DE_ATTR + V/VN`；人稱代詞 NP（我的建議）豁免；區分主謂類（刪「的」解凍）與動賓類（反轉 V+N）。
  - `L1_PSEUDO_JARGON`：黑名單直抓（具有/頗具/更具/富於＋知名度/可讀性等）＋灰區（具有/具備/呈現出＋a＋~性/~度名詞）；frozen 技術術語（高可用性、冪等性、複雜度等）一律豁免。
  - `L1_REDUNDANT_PLURAL_ZHIYI`：「人們」與「民眾/聽眾/觀眾/讀者/球員/師生/同胞/顧客/乘客＋們」；「作為…之一的」「最…之一」與無明確數字集合之「之一」；明確封閉集合（竹林七賢之一、三大瓶頸之一）豁免。
  - `L1_INANIMATE_SUBJECT`：抽象 `NP+的+VN(減少/增加/…)` 主語＋使動謂語＋人稱受詞；tech profile 且主語為具體系統模組時豁免；指令為視角反轉（人提升為主詞）。
  - `L1_PASSIVE_BEI`：`(不)?被+[施事]?+V_target`；天然不幸/物理受事（被殺/被捕/被毀/被淘汰）豁免；指令區分有施事反轉、無施事泛指主動（有人/大家）與原生詞彙（未獲准/當選為）。
- [ ] 每條 Issue 輸出含 `layer`、`rule_id`、`priority`、`span`、`pos_pattern`、`theoretical_basis`、`instruction`，span 字元索引可定位原文。
- [ ] 偵測依賴 L0 的 `true_de_role`（而非字面「的/地」），名物化判定使用 DE_ATTR。
- [ ] Part I §2.1.2 案例庫的病態句全數命中對應規則，✅ 道地句不誤報（抽樣覆蓋六類病灶）。
- [ ] Golden Case 1 斷言：「高可用性」不觸發 L1_PSEUDO_JARGON；「對…進行了詳細的研究」觸發 L1_WEAK_VERB_NOMINALIZATION。
- [ ] Golden Case 3 斷言：「他的收入的減少」觸發 L1_INANIMATE_SUBJECT／L1_EVENT_NOMINALIZATION；「被徹底改變了」觸發 L1_PASSIVE_BEI。
- [ ] Golden Case 4 斷言：「具有很高的可讀性」觸發 L1_PSEUDO_JARGON。

## Design Reference
- `zh_polish_skill_spec_v2.md` §2.1（L1 理論與案例庫）、§5.2 L1 規則矩陣、§8.1 Cases 1/3/4。

## References
- `engine/ast_scanner.py`（#006）— 規則註冊介面與 Issue 欄位契約。
- `config/default_lexicons.json`（#001）— 弱動詞表與偽術語黑名單。

## Implementation Notes
- Required constraints: frozen 詞絕對不可出現在改寫 span 的拆解指令中；instruction 須具體到詞（如「詳加研究」「貢獻很大」），不得只寫抽象原則。
- Suggested approach: 以 POS 序列 regex 為主、詞表匹配為輔；每條規則的 theoretical_basis 直接節錄 Part I 對應理論句。

## Testing
- 每條規則一組正反例單元測試（病態句命中、道地句與豁免句不命中）。
- 執行 Golden Cases 1/3/4 的 L1 相關斷言（可先以規則層級測試，端到端由 Checkpoint 1 覆蓋）。