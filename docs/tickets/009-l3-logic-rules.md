# [TICKET-009] L3 規則引擎：邏輯與銜接機制 (l3_logic.py)

## Status
`blocked`

## Dependencies
- Requires: #006

## Description
實作 `engine/rules/l3_logic.py`：依 §5.2 第三層規則矩陣偵測形合過剩病灶——冗餘介詞外框（In the process of 式包裝）、病態雙重因果（由於…使得…主語湮沒）、並列連詞西化（及/與誤連謂詞）。這是「由外而內」折疊重構的 Priority 1 層，先剝外殼才動核心。

## Acceptance Criteria
- [ ] 實作三條規則，依 §5.2 L3 表格：
  - `L3_PREPOSITIONAL_FRAME`：靶心型 `(有關|關於|針對|對於)+NP(2~15字)+的?(問題|種種|部分|方面|事項|故事)?`；情境型 `(在|於|從|當)+NP/VP(2~15字)+的(過程(當)?中|背景(之)?下|情況下|前提下|角度來看|層面上|基礎上)` 與「來到我們的中間」；後半句確實探討「問題本身」時保留「問題」僅刪「有關」；指令為剝外框（核心 NP 作主語/受詞，或改「[VP]時，」「就[NP]而言，」）。
  - `L3_CAUSAL_MALFORMED`：三型——主語湮沒 `(由於|因為|鑑於)…，…(使得|導致|造成|令)`；心理名詞驅使 `(由於|因為|受到)+心理名詞+的(驅使|影響|緣故)`；短句形合過剩 `由於/因為 [A≤8字]，所以/因此 [B≤8字]`（此型在 tech profile 預設關閉，對應 `L3_SHORT_CAUSAL_DROP` disabled_rules）；指令分別為刪由於/使得還原主語、「出於好奇」、意合並置。
  - `L3_CONJUNCTION_MISUSE`：及/以及/與/和 連接謂詞、形容詞片語或比較級（更…/越…）時觸發；同類名詞串列尾綴 `N1、N2、N3 及 N4`；嚴格集合定義之名詞並列豁免；指令為改用「而」（慢而可靠）、對稱四字比較級改逗號、名詞串列改頓號並置。
- [ ] 每條 Issue 含完整欄位與 theoretical_basis（意合 vs 形合、主語湮沒、「而」的詞性邊界）。
- [ ] `disabled_rules` 生效：tech profile 下短句因果型不觸發，essay/social 下觸發。
- [ ] Part I §2.3.2 案例庫病態句命中、道地句不誤報（「清風徐來，水波不興」不觸發）。
- [ ] Golden Case 1 斷言：「在系統遷移的過程當中」與「有關…的問題」觸發 L3_PREPOSITIONAL_FRAME。
- [ ] Golden Case 3 斷言：「由於…使得…」觸發 L3_CAUSAL_MALFORMED。
- [ ] Golden Case 4 斷言：「起步更早及邁步更快」觸發 L3_CONJUNCTION_MISUSE。

## Design Reference
- `zh_polish_skill_spec_v2.md` §2.3（L3 理論：意合/形合、介詞外框、And 意識）、§5.2 L3 規則矩陣、§4.1A（tech disabled_rules）、§8.1 Cases 1/3/4。

## References
- `engine/ast_scanner.py`（#006）— profile/disabled_rules 解析與規則介面。

## Implementation Notes
- Required constraints: 主語湮沒型是最高優先修復（整句無主詞屬語法崩壞，priority 應高於一般贅字）；連詞規則須檢查左右鄰居詞性，不可只看字面。
- Suggested approach: 介詞外框以環狀 regex 匹配框架詞＋跨度限制；因果套疊以句內共現匹配。

## Testing
- 每條規則正反例單元測試，含 tech profile 豁免短句因果、名詞集合並列豁免。
- 執行 Golden Cases 1/3/4 的 L3 斷言。