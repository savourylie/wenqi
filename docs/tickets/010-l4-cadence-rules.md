# [TICKET-010] L4 規則引擎：篇章呼吸與音律節奏 (l4_cadence.py)

## Status
`pending`

## Dependencies
- Requires: #006 ✅

## Description
實作 `engine/rules/l4_cadence.py`：依 §5.2 第四層規則矩陣偵測憋氣長分句、冗餘代名詞（含無生命「它們」）、冗餘存在句與繫詞過剩、口水套語與段落句尾軟弱。目標是還原中文「竹節流水句」呼吸（7~15 字舒適區）與話題鏈零形回指，並以四字格收束段落。

## Acceptance Criteria
- [ ] 實作四條規則，依 §5.2 L4 表格：
  - `L4_CLAUSE_BREATH_OVERLOAD`：以 `[，。！？；：]` 切分，扣除英文單字與遮罩佔位符後中文字數 > `max_clause_len`（tech>24、essay>20、social>16）。用詞性辨識第二個動作或承接詞，定位可信斷點。
  - `L4_REDUNDANT_PRONOUNS`：句中出現「它們」（無生命複數）、同句相同代詞（他/他的/它/它的/我們/我們的）≥2 次，或連續分句句首重複同一主語代詞。明確切換話題時豁免。指涉有歧義時仍提示，指令要求先確認指涉相同，再視文意省略。
  - `L4_EXISTENTIAL_COPULA_BLOAT`：`有+NP+(存在|發生|出現)`；`基於(這個|這樣|上述)的?(原因|理由)`；非對比強調之 `是+[很/非常/相當]?+Adj+的。`（social profile 豁免口語強調，對應 `L4_COPULA_SHI_DE` disabled_rules）；指令為坍縮存在句（問題很多）、「因此/為此」、剝除「是…的」。
  - `L4_WEAK_ENDING_VERBOSE_IDIOM`：口水套語表（不是一句話就能說清楚的、總的來說、在很大程度上）；段落末句結尾 `…是(我們)?(需要|必須|值得)(去)?(注意|思考|關注)的(一個)?(地方|問題|事情)。`；tech profile 降低古雅成語替換強度（`idiom_replacement_aggressiveness`）；指令為四字格替換（一言難盡、總而言之）與砍句尾空殼鏗鏘收束。
- [ ] 每條 Issue 含完整欄位與 theoretical_basis（竹節句、話題鏈、四字格韻律）。
- [ ] 找到可信斷點時，`suggested_breakpoint` 回傳相對於原文整句的字元索引。找不到時仍回報長分句，省略此欄位並請改寫時另找斷法。
- [ ] Part I §2.4.2 案例庫病態句命中、道地句不誤報。
- [ ] Golden Case 3 斷言：「他的…他的…」重複觸發 L4_REDUNDANT_PRONOUNS。

## Design Reference
- `zh_polish_skill_spec_v2.md` §2.4（L4 理論：竹節句、零形回指、四字格）、§5.2 L4 規則矩陣、§4.1A（profile 閾值與 aggressiveness）、§8.1 Case 3。

## References
- `engine/ast_scanner.py`（#006）— thresholds/disabled_rules 與規則介面。
- `config/default_lexicons.json`（#001）— 四字格映射表。

## Implementation Notes
- Required constraints: 字數統計口徑（扣除英文與遮罩）須與 L2 一致；代詞豁免必須偵測話題切換，避免把合法換主語的代詞誤刪。
- Suggested approach: 段落邊界以空行判定，句尾軟弱規則只作用於段落最後一句。

## Testing
- 每條規則正反例單元測試，含三種 profile 閾值與 social「是…的」豁免、tech 成語強度降級。
- 執行 Golden Case 3 的 L4 斷言；長句測試驗證 suggested_breakpoint 位置合理。

## As-Built Notes

### 2026-11-25

- 四條 L4 規則接上既有 Scanner。長分句沿用 L2 的漢字計數，優先採用明確承接詞，再找可信的第二個動作。斷點與診斷範圍使用原文整句座標，找不到可信位置時仍回報過長。
- 明確切換主語時保留代詞。其餘重複代詞由作者確認同指後再決定是否省略。白名單凍結及必留詞沿用掃描器契約。社群語體的繫詞豁免只影響「是……的」。
- 63 項 L4 規則測試和 1 項 CLI 驗收通過，涵蓋三種語體、遮罩、白名單、原文索引及 Golden Case 3 的 L4／ALL 一致性。全套回歸為舊測項逐份補跑 L5 預檢後，796 項通過，1 項既有預期失敗（016 的 R-33）。
- 外部 AI 題庫逐題經 L5 預檢後以題面設定掃描 L4，首輪符合 30／32 題。修正「同步／更新」的動詞辨識及「常有」等合併詞的存在句偵測後，原題的命中、範圍與斷點符合 32／32 題。這兩項修正已加入回歸測試，L4 與 L5 預檢後的 CLI 驗收共 71 項通過。
- 第二批外部題庫首輪符合 26／32 題。修正時間短語後的斷點、使役動詞的必要代詞、數量詞後可作名詞的動詞，以及「好用」的形容詞用法後，兩批共 64 題的命中、範圍與斷點皆符合。新增對照測試涵蓋「後三天」等完整時間短語。L4 與 L5 預檢後的 CLI 驗收共 79 項通過。
