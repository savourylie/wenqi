# [TICKET-010] L4 規則引擎：篇章呼吸與音律節奏 (l4_cadence.py)

## Status
`blocked`

## Dependencies
- Requires: #006

## Description
實作 `engine/rules/l4_cadence.py`：依 §5.2 第四層規則矩陣偵測憋氣長分句、冗餘代名詞（含無生命「它們」）、冗餘存在句與繫詞過剩、口水套語與段落句尾軟弱。目標是還原中文「竹節流水句」呼吸（7~15 字舒適區）與話題鏈零形回指，並以四字格收束段落。

## Acceptance Criteria
- [ ] 實作四條規則，依 §5.2 L4 表格：
  - `L4_CLAUSE_BREATH_OVERLOAD`：以 `[，。！？；：]` 切分，扣除英文單字與遮罩佔位符後中文字數 > `max_clause_len`（tech>24、essay>20、social>16）；以 POS 標出分句內第 2 個動詞或承接詞位置作為 `suggested_breakpoint`。
  - `L4_REDUNDANT_PRONOUNS`：句中出現「它們」（無生命複數）；同一句號內相同代詞（他/他的/它/它的/我們/我們的）≥2 次，或連續分句句首重複同一主語代詞；前後分句已切換話題（新實體名詞）時豁免；指令為提取公因式、零形回指。
  - `L4_EXISTENTIAL_COPULA_BLOAT`：`有+NP+(存在|發生|出現)`；`基於(這個|這樣|上述)的?(原因|理由)`；非對比強調之 `是+[很/非常/相當]?+Adj+的。`（social profile 豁免口語強調，對應 `L4_COPULA_SHI_DE` disabled_rules）；指令為坍縮存在句（問題很多）、「因此/為此」、剝除「是…的」。
  - `L4_WEAK_ENDING_VERBOSE_IDIOM`：口水套語表（不是一句話就能說清楚的、總的來說、在很大程度上）；段落末句結尾 `…是(我們)?(需要|必須|值得)(去)?(注意|思考|關注)的(一個)?(地方|問題|事情)。`；tech profile 降低古雅成語替換強度（`idiom_replacement_aggressiveness`）；指令為四字格替換（一言難盡、總而言之）與砍句尾空殼鏗鏘收束。
- [ ] 每條 Issue 含完整欄位與 theoretical_basis（竹節句、話題鏈、四字格韻律）。
- [ ] `suggested_breakpoint` 以字元索引輸出且落在合理斷點（第二動作/轉折處）。
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