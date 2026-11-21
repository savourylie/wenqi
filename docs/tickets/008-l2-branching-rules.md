# [TICKET-008] L2 規則引擎：修飾與包孕結構 (l2_branching.py)

## Status
`done`

## Dependencies
- Requires: #006 ✅

## Description
實作 `engine/rules/l2_branching.py`：依 §5.2 第二層規則矩陣偵測左分支定語過載（前飾關閉句）、「的」字連環套、長狀語黏著與「成功地」重言。核心是 DDM（依存距離最小化）：讓核心名詞提早落地、長修飾改後飾流水展開。閾值隨語體 profile 動態調整，且完全依賴 L0 的 DE 消歧義結果。

## Acceptance Criteria
- [ ] 實作三條規則，依 §5.2 L2 表格：
  - `L2_LEFT_BRANCH_OVERLOAD`：以動詞/數量詞為左錨點、`DE_ATTR+Head_Noun` 為右錨點，中間修飾語字數 > `max_pre_modifier_len` 且內部含至少一個 v/vn 時觸發；閾值 tech>18、social/essay>12；指令為前飾改後飾（核心名詞先落地＋逗號流水補充）。
  - `L2_DE_CHAIN_NOISE`：單一分句 DE_ATTR ≥3，或雙形容詞並列（a1+的+a2+的+n）、單音節/材質冗餘（白/黑/紅/木頭/都市+的+n）、隱含動詞被壓扁（a1+的+n1+的+a2+的+n2）；專有名詞內部的「的」不計入；指令分別為「而」連接、直接黏合（白鴨）、補回動態動詞（投下）。
  - `L2_ADVERB_DI_OVERUSE`：成語（pos=i）或 span≥4 字片語＋DE_ADV＋v（即便作者寫「的」，靠 L0 標記捕捉）；「成功/順利＋地＋達成動詞(推翻/發明/泳渡/解決/完成/突破)+了」結果重言；雙音節純副詞（漸漸地、悄悄地）不強制拆句；指令為去「地/的」改逗號、刪「成功地」。
- [ ] 每條 Issue 含完整欄位（rule_id/span/pos_pattern/theoretical_basis/instruction），thresholds 取自生效 profile。
- [ ] Part I §2.2.2 案例庫病態句命中、道地句不誤報（含司馬遷後飾句「籍長八尺餘，力能扛鼎，才氣過人」不觸發）。
- [ ] Golden Case 2 斷言：「苦口婆心的勸」觸發 L2_ADVERB_DI_OVERUSE；「長得像你兄弟說話也有點像他的陌生男人」（16 字含動詞，essay/social 閾值 12）觸發 L2_LEFT_BRANCH_OVERLOAD。
- [ ] Golden Case 4 斷言：「灰暗的淒冷的天空」觸發 L2_DE_CHAIN_NOISE。

## Design Reference
- `zh_polish_skill_spec_v2.md` §2.2（L2 理論：DDM、的字連環套、去地求活）、§5.2 L2 規則矩陣、§4.1A（profile 閾值）、§8.1 Cases 2/4。

## References
- `engine/l0_normalizer.py`（#004）— DE_ATTR/DE_ADV 標記是偵測前提。
- `engine/ast_scanner.py`（#006）— thresholds_applied 與規則介面。

## Implementation Notes
- Required constraints: 字數計算以中文字元為準（扣除英文與遮罩佔位符的口徑與 L4 一致）；左分支偵測不得把 frozen 專有名詞內部的「的」計入修飾跨度。
- Suggested approach: 左分支以錨點間 span 字數＋內部動詞存在性雙條件判定，避免短定語誤報。

## Testing
- 每條規則正反例單元測試，含 profile 閾值切換（同一句在 tech 不觸發、essay 觸發）。
- 執行 Golden Cases 2/4 的 L2 斷言。

## As-Built Notes

### 2026-11-20

- `--layer L2` 與 `--layer ALL` 透過既有掃描器回報三條 L2 規則的命中片段、句內位置、理由和調整方式。L0 補齊規格案例中的助詞切分與語法標記，保留 L1 的名物化診斷。
- 長前飾以生效語體的漢字門檻判定。修飾語指向同一核心名詞時可跨逗號，各節不超過四字的短並列放行，末尾的「的」不列入該節。凍結詞內的「的」從門檻計數扣除。
- 「成功地／順利地」接達成動詞時，「了」為可選。明確否定與未然的結果放行。改寫建議沿用掃描器按原文位置管理必留詞的介面。
- 全套 pytest 為 394 通過、3 項既有 `xfail`。CLI 驗證 Golden Cases 2／4 在 `L2` 與 `ALL` 的命中與計數。
