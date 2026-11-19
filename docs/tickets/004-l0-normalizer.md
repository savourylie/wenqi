# [TICKET-004] L0 預處理：Markdown 遮罩與「的／地／得」消歧義 (L0 Normalizer)

## Status
`done`

## Dependencies
- Requires: #003 ✅

## Description
實作 `engine/l0_normalizer.py`：在進入 L1~L4 之前的預處理層。包含 Markdown AST 遮罩（保護 code block、連結、公式、引用不被改寫），以及「的／地／得」左右詞性窗口消歧義狀態機——台灣作者慣以「的」通代三角色，若只從字面匹配「地」會漏失 70% 以上狀語病灶。此層同時產出 `de_normalization_map` 與 `L0_TYPO_DE_COMP` 錯別字診斷，是 L2 規則與 Diagnostic Payload 的必要輸入。

## Acceptance Criteria
- [x] Markdown 遮罩：fenced code blocks、YAML Frontmatter、inline code、連結 URL `](url)`、LaTeX `$...$`、blockquote（`^>\s+.*`）在分句分詞前替換為定長佔位符 `__MASK_i__`，掃描結果不命中遮罩區內容，且輸出可還原對應原文位置。
- [x] DE-Normalizer 對每個「的／地／得」token 依 §5.1C 的 Left/Right/Right2 窗口判定 `true_de_role`：
  - `DE_COMP`：左鄰 v/a（排除能/會/可以），右鄰程度副詞＋形容詞或結果狀態詞；排除雙音節詞內部「得」（獲得/得到/覺得/值得/記得）與「我得去」的 děi。
  - `DE_ADV`：條件 A（左鄰成語 i 或雙音節以上 d/a/ad，右鄰 v，或右鄰 去/來/把/被/將 且 Right2 為 v/vn）；條件 B（vn 兼類詞消歧義：右後接 了/過/著 或受詞 → 真動詞 DE_ADV；左前為量詞/指示代詞/弱動詞 → 真名詞 DE_ATTR）。
  - `DE_ATTR`：其餘右鄰名詞性結構或句尾助詞。
- [x] `true_de_role == DE_COMP` 且字面非「得」時，發出 `L0_TYPO_DE_COMP` 診斷（提示修正為「得」）。
- [x] 產出 `de_normalization_map`（char_idx、surface、true_role），索引與原文對齊，供 §4.2 LINT payload 使用。
- [x] Golden Case 2 的 L0 斷言通過：「苦口婆心的勸」的「的」→ `DE_ADV`；「跑的很快」的「的」→ `DE_COMP` 並觸發 `L0_TYPO_DE_COMP`。

## Design Reference
- `zh_polish_skill_spec_v2.md` §2.6（L0 原理）、§5.1B（遮罩清單）、§5.1C（消歧義狀態機完整條件）、§8.1 Case 2（L0 斷言）。

## References
- `engine/tokenizer_adapter.py`（#003）— Token 結構與 `true_de_role` 欄位。

## Implementation Notes
- Required constraints: 消歧義必須在語法（POS 窗口）層級而非字面層級；遮罩不得破壞未遮罩文字的字元索引對應。
- Suggested approach: 遮罩以 regex 前處理產生佔位符並保存還原映射；狀態機以規則優先序 DE_COMP → DE_ADV → DE_ATTR 實作，邊界案例以單元測試固化。

## Testing
- 單元測試覆蓋 §5.1C 各條件與排除項（含「獲得」「我得去」「一份詳細的評估」vn 名詞化 vs「詳細地評估了」vn 動詞化）。
- 遮罩測試：code block 內的「進行研究」不產生診斷；blockquote 不套用規則。
- 以 Golden Case 2 輸入驗證兩個 L0 斷言。

## As-Built Notes

### 2026-11-19

- PR #5 已合併至 `main`（`d8b707b`）。
- `normalize(text, tokenizer=None)` 接受 #003 的分詞器，複用既有的白名單冷凍標記。先隔離 Frontmatter、圍欄程式碼和整行引文，再辨識行內程式碼、連結目的地及單行 `$…$`。連結文字仍參與掃描。
- 每個 `__MASK_i__` 對應一個 POS `x` token。`mask_regions` 以半開區間記錄原文和遮罩後的座標，可區分佔位符與正文中的同名字串。可見 token 的 `start_char`／`end_char` 對齊原文。
- 補語採左鄰詞性加右鄰程度詞、結果詞、形容詞或句尾程度詞四種證據。右鄰後接名詞時加上防誤判條件，涵蓋「好話」、「很多書」與「更新內容」。狀語左鄰接受雙字以上的 `b`，`vn` 的量詞、指示詞與既有弱動詞表優先判為名詞結構。量詞後的名詞「地」及主語後的助動詞「得」排除於助詞標記。
- `de_normalization_map` 與 `L0_TYPO_DE_COMP` 的 `char_idx` 均為文件絕對座標。錯字診斷帶有 `suggestion` 和 `theoretical_basis`，由 #006 組裝句級 payload 時換算座標。
- 判定受 jieba 併詞與詞性限制，例如「跑得快」、「悄悄的」併成一詞，或「走」被標為名詞。缺少分句標點時，相鄰名詞也可能影響補語判定。`.venv/bin/python -m pytest -q` 共 108 項通過，包含 Golden Case 2 的兩項 L0 斷言和遮罩位移回歸。
