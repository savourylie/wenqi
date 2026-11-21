---
name: zh-l5-guard
description: "改文前的語體定調與白名單守門員（L5）。在執行 L1～L4 或 wenqi-all 改寫前，呼叫 scanner preflight 推測語體並抽取未登錄的疑似專有名詞，透過單輪互動取得作者裁決，再將確認的白名單寫入全域／本地狀態或帶入暫用白名單。由使用者呼叫 /zh-l5-guard 或由 wenqi-all Stage 1 觸發；僅做預檢、確認與狀態更新，不改寫文章。"
---

# zh-l5-guard：語體定調與白名單守門員

改文前先定調語體與保護專有名詞，避免 L1 規則把領域術語（如「局部性」）誤當成空洞偽術語拆解，或破壞「進行 Fine-tuning」這類中英夾雜的語法黏著結構。

## 觸發時機

- 使用者直接呼叫 `/zh-l5-guard`（或 `$zh-l5-guard`）對檔案或貼上文字做預檢。
- 由總調度器 `wenqi-all` 在 Stage 1 自動呼叫，作為全層掃描前的握手關卡。

## 核心鐵律（Guardrails）

1. **禁止自動豁免**：所有全域（Global）、單篇（Local）與暫用（Ephemeral）白名單條目都必須由作者明確選擇，Agent 不得擅自寫入或靜默放行任何疑似詞。
2. **禁止提前改寫**：在作者確認語體與疑似詞處置之前，不得呼叫 `--mode lint` 或開始任何改寫；單獨呼叫 `zh-l5-guard` 時，完成狀態更新並輸出握手摘要即停止，不得擅自改文。
3. **單輪互動原則**：一次呈現語體建議與所有待確認疑似詞供作者批次回覆，避免來回打斷；僅在作者回覆遺漏部分條目時，針對漏答項追問一次。
4. **原稿零侵入**：絕不修改作者的文章檔案或 Markdown Frontmatter；所有持久化狀態統一寫入 `~/.config/wenqi/`。

---

## 執行步驟

### 步驟 0：解析引擎路徑與 Python 直譯器

在呼叫掃描器前先定位 `WENQI_ROOT` 與 `WENQI_PYTHON`（本機在任一工作目錄執行絕對路徑的 `ast_scanner.py` 皆可正常偵測文章所屬的 Git Repo）：

1. **`WENQI_ROOT` 解析順序**（取第一個包含 `engine/ast_scanner.py` 的路徑）：
   - 本 `SKILL.md` 所在位置往上兩層（即 `skills/zh-l5-guard/SKILL.md` 對應的專案根目錄）。
   - 目前工作目錄。
   - 環境變數 `$WENQI_ROOT`。
   - 若以上皆找不到，先向使用者詢問 `wenqi` 安裝路徑再繼續。
2. **`WENQI_PYTHON` 解析順序**：
   - 若 `"$WENQI_ROOT/.venv/bin/python"` 存在，優先使用它（避免系統 `python3` 缺少 `jieba` 依賴）。
   - 否則使用 `python3`（若在 `WENQI_ROOT` 內且已啟用含 `jieba` 的環境，即等同 `python3 engine/ast_scanner.py ...`）。
3. **輸出解析提醒**：`ast_scanner.py` 的 `stdout` 為純 JSON，`jieba` 詞典載入訊息走 `stderr`。執行與解析時只讀取 `stdout`，切勿將 `stderr` 混入 JSON 解析。

### 步驟 1：執行 Preflight 並解析 `L5_PREFLIGHT` JSON

依輸入來源選擇對應指令執行預檢：

- **檔案模式**（使用者提供檔案路徑 `<target_path>`）：
  ```bash
  "$WENQI_PYTHON" "$WENQI_ROOT/engine/ast_scanner.py" --mode preflight --file "<target_path>"
  ```
- **對話貼文模式**（使用者直接在對話貼入文章內容，無對應檔案）：
  ```bash
  "$WENQI_PYTHON" "$WENQI_ROOT/engine/ast_scanner.py" --mode preflight --stdin
  ```

> 若使用者已在本次指令明示語體（例如「用 essay 語體」），可於上述指令附加 `--profile <tech|social|essay>`。

解析回傳的 `L5_PREFLIGHT` JSON，擷取以下欄位：
- `source_type`（`"file"` 或 `"stdin"`）與 `target_id`（檔案相對路徑／絕對路徑，或 `"stdin"`）
- `content_hash`（8 碼文章內容指紋）
- `suggested_profile`（系統推測語體：`tech` / `social` / `essay`）與 `profile_reason`（推測依據）
- `active_whitelist_terms`（目前正文已命中並受保護的白名單詞清單）
- `suspect_terms_for_review`（待確認疑似詞陣列；每項含 `term`、`count`、`sample_sentence`、`reason`）

`reason` 分為兩類：
- `SUFFIX_XING_UNREGISTERED`：帶有「~性／~度／~化」後綴但尚未登錄於白名單的詞。
- `CODE_SWITCH_WEAK_VERB`：弱動詞（進行／做／作出等）後接英文專有動作（如「進行 Fine-tuning」）。

### 步驟 2：判斷是否需要互動並發起單輪確認

#### 分流判斷
- **免互動直接進入步驟 4（輸出握手摘要）**：僅當 `suspect_terms_for_review` 為空陣列 `[]`，**且**符合下列任一條件時適用：
  1. 作者已在本次指令明確指定語體（如 `--profile essay` 或明確說「用隨筆語體」）；或
  2. 同對話先前已對相同 `target_id` 與 `content_hash` 完成過一次 L5 確認（例如寫入白名單後的覆驗）。
- **必須發起單輪互動**：只要 `suspect_terms_for_review` 非空，或屬於本對話對該稿件的首次執行且作者未明示語體，一律暫停進入下一步，向作者發起單輪確認。

#### 單輪互動呈現規範
在同一次回覆中完整列出以下項目並停止等待作者裁決：

1. **語體定調確認**：
   - 呈現 `suggested_profile` 與 `profile_reason`。
   - 簡列三種語體供確認或改選：
     - `tech`（技術架構文）：邏輯精確優先；左分支上限 18 字、分句上限 24 字，保留必要短因果（停用 `L3_SHORT_CAUSAL_DROP`）。
     - `social`（社群短文）：強調快速推進；左分支上限 12 字、分句上限 16 字，容許「是…的」強調句（停用 `L4_COPULA_SHI_DE`）。
     - `essay`（人文隨筆）：全開余光中標準；左分支上限 12 字、分句上限 20 字，無停用規則。
2. **目前已生效保護詞**：若 `active_whitelist_terms` 非空，簡列這些詞讓作者確認已受保護。
3. **疑似專有名詞確認表**（當 `suspect_terms_for_review` 非空時）：
   - 以編號表格呈現每個疑似詞的 `reason` 與 `sample_sentence`：
     `| 編號 | 詞彙 | 次數 | 檢出原因 (reason) | 原文例句 (sample_sentence) |`
   - 明確說明三個作用域選項：
     - **`[G]` 全域永久豁免（Global）**：寫入 `~/.config/wenqi/global_config.json`，日後所有文章永久凍結保護。
     - **`[L]` 僅限本文／本專案豁免（Local / Ephemeral）**：Git Repo 內檔案寫入 `~/.config/wenqi/workspaces/<repo_hash>.json`；`--stdin` 或 Repo 外檔案不建立 workspace 檔，改在本次會話透過 `--ephemeral-whitelist` 帶入。
     - **`[X]` 非專有名詞（Reject）**：不豁免，交由後續 L1～L4 規則當作病灶偵測與改寫。
   - 提示作者以簡潔格式一次回覆（例如：`語體 tech；1G 2L 3X` 或「接受建議語體，全部 G」）。
4. **漏答處理**：若作者回覆遺漏部分編號，不得自行猜測或預設 `[G]`/`[L]`/`[X]`，僅針對漏答編號追問一次。

### 步驟 3：依作者裁決執行 `update-state` 或記錄暫用白名單

收到作者明確回覆後，將每個詞依作用域分類執行：

#### 1. `TERM:POS` 詞性標籤慣例
`--add-global-whitelist` 與 `--add-local-whitelist` 要求 `TERM:POS` 格式。若作者未另外指定詞性，依預設規則賦值（寫入前同一作用域先去重）：
- `SUFFIX_XING_UNREGISTERED`：以 `性`、`度` 結尾者填 `nz`；以 `化` 結尾者填 `vn`。
- `CODE_SWITCH_WEAK_VERB`：整體詞組（如 `"進行 Fine-tuning"`）填 `v`。

> 所有包含空白或英文詞組的參數**必須以雙引號包覆**，避免 shell 拆字導致格式錯誤。

#### 2. 依模式執行更新

- **Git Repo 內的 `--file` 模式**：
  - 同時有 `[G]` 與 `[L]` 時，可單次併傳兩個作用域：
    ```bash
    "$WENQI_PYTHON" "$WENQI_ROOT/engine/ast_scanner.py" \
      --mode update-state \
      --file "<target_path>" \
      --add-global-whitelist "詞1:nz,詞2:vn" \
      --add-local-whitelist "詞3:v"
    ```
  - 僅有 `[G]` 時可省略 `--file`；僅有 `[L]` 時必須帶 `--file "<target_path>"`。
- **`--stdin` 模式，或位於 Git Repo 以外的檔案**：
  - **`[G]` 條目**：呼叫 `update-state` 寫入全域白名單，**切勿加上 `--stdin`**（CLI 會直接拒絕）：
    ```bash
    "$WENQI_PYTHON" "$WENQI_ROOT/engine/ast_scanner.py" \
      --mode update-state \
      --add-global-whitelist "詞1:nz"
    ```
  - **`[L]` 條目**：**不可呼叫** `--add-local-whitelist`。改將純詞面（**不帶 `:POS`**）收進 `ephemeral_whitelist` 清單，留待後續 `--mode lint` 時以 `--ephemeral-whitelist "詞3,詞4"` 傳入。
    - 若對原本以為在 Repo 內的 `--file` 執行 `--add-local-whitelist` 時收到「`--add-local-whitelist 須搭配 Git Repo 內的 --file`」錯誤，自動改收入 `ephemeral_whitelist`，並告知作者「因檔案不在 Git Repo 內，此單篇豁免僅限本次會話生效」。
- **`[X]` 條目**：不執行任何寫入或暫存，交由後續 lint 處理。

#### 3. 常見錯誤處置與已知限制
- **部分成功錯誤**：若雙作用域寫入遇到「`單篇白名單已更新。全域白名單更新失敗`」，向作者明確回報「單篇白名單已更新」，只針對失敗的 `--add-global-whitelist` 重試，避免重複嘗試已成功的寫入。
- **語體不會經 `update-state` 寫入磁碟**：現行 `--mode update-state` 僅支援白名單寫入，不接受 `--profile`。因此作者確認的語體不寫入狀態檔，而是透過步驟 4 的握手摘要強制帶入後續所有 `--mode lint --profile <確認值>` 呼叫。

### 步驟 4：輸出握手摘要（Handoff Contract）

完成狀態處理後，輸出固定結構的握手摘要供作者確認或交棒給後續技能（`zh-l1`～`zh-l4` 或 `wenqi-all` Stage 2）：

```markdown
### L5 守門員握手摘要
- **目標來源**：`<source_type>` / `<target_id>`（`content_hash: <hash>`）
- **確認語體**：`<tech|social|essay>`
- **本次新增 Global 白名單**：`<詞:POS, ...>`（或「無」）
- **本次新增 Local 白名單**：`<詞:POS, ...>`（或「無」）
- **後續 Lint 必帶參數**：`--profile <tech|social|essay>`（若有暫用詞則併帶 `--ephemeral-whitelist "<詞1,詞2>"`）
- **交由 L1～L4 檢查（Reject `[X]`）**：`<詞1, 詞2>`（或「無」）
```

- **單獨執行 `/zh-l5-guard`**：輸出握手摘要後即結束工作流程，不開始掃描或改寫正文。
- **由 `/wenqi-all` Stage 1 觸發**：將此摘要中的 `--profile` 與（若有）`--ephemeral-whitelist` 直接傳入 Stage 2 的 `--mode lint --layer ALL` 指令，不可遺漏 `--profile`。

---

## Few-Shot 互動範例

### 情境：技術文章（含已登錄白名單詞「高可用性」與未登錄詞「局部性」）

**輸入檔案**：Git Repo 內 `posts/2026-11-agent-memory.md`

```markdown
系統重構時，我們確保了檢索模組的高可用性，透過快取提升資料存取的局部性，並對小模型進行 Fine-tuning。這份架構說明具有很高的可讀性。
```

**步驟 1 執行 preflight 取得之關鍵 JSON**：

```json
{
  "mode": "L5_PREFLIGHT",
  "source_type": "file",
  "target_id": "posts/2026-11-agent-memory.md",
  "content_hash": "87f232bf",
  "suggested_profile": "tech",
  "profile_reason": "正文有 1 處弱動詞接英文詞。",
  "active_whitelist_terms": ["高可用性"],
  "suspect_terms_for_review": [
    {
      "term": "局部性",
      "count": 1,
      "sample_sentence": "系統重構時，我們確保了檢索模組的高可用性，透過快取提升資料存取的局部性，並對小模型進行 Fine-tuning。",
      "reason": "SUFFIX_XING_UNREGISTERED (帶有『~性/~度/~化』後綴但未登錄於白名單)"
    },
    {
      "term": "進行 Fine-tuning",
      "count": 1,
      "sample_sentence": "系統重構時，我們確保了檢索模組的高可用性，透過快取提升資料存取的局部性，並對小模型進行 Fine-tuning。",
      "reason": "CODE_SWITCH_WEAK_VERB (弱動詞後接英文專有動作)"
    },
    {
      "term": "可讀性",
      "count": 1,
      "sample_sentence": "這份架構說明具有很高的可讀性。",
      "reason": "SUFFIX_XING_UNREGISTERED (帶有『~性/~度/~化』後綴但未登錄於白名單)"
    }
  ]
}
```

**步驟 2 Agent 發起單輪互動**：

> 在開始檢查與潤飾前，請先確認以下語體與未登錄詞的處理方式（確認前不會改動文章）：
>
> **1. 本文語體確認**
> - 系統建議：**`tech`**（技術架構與工程深度文：左分支上限 18 字／分句 24 字，保留必要短因果）
> - 推測依據：正文有 1 處弱動詞接英文詞。
> - 若要改用其他語體，請回覆 `social`（社群短文）或 `essay`（人文隨筆）。
>
> **2. 目前已生效的保護詞**：`高可用性`
>
> **3. 待確認疑似專有名詞**
> | 編號 | 詞彙 | 次數 | 檢出原因 | 原文例句 |
> | --- | --- | --- | --- | --- |
> | 1 | 局部性 | 1 | `SUFFIX_XING_UNREGISTERED`（帶「~性／~度／~化」後綴但未登錄） | 系統重構時，我們確保了檢索模組的高可用性，透過快取提升資料存取的局部性，並對小模型進行 Fine-tuning。 |
> | 2 | 進行 Fine-tuning | 1 | `CODE_SWITCH_WEAK_VERB`（弱動詞後接英文專有動作） | 系統重構時，我們確保了檢索模組的高可用性，透過快取提升資料存取的局部性，並對小模型進行 Fine-tuning。 |
> | 3 | 可讀性 | 1 | `SUFFIX_XING_UNREGISTERED`（帶「~性／~度／~化」後綴但未登錄） | 這份架構說明具有很高的可讀性。 |
>
> 請為每個詞擇一：
> - **`[G]` 全域永久豁免**：寫入全域設定，所有文章永久保護
> - **`[L]` 僅限本文／本專案豁免**：僅寫入本篇／本專案白名單（無檔案或 Repo 外則限本次會話）
> - **`[X]` 非專有名詞**：不豁免，交由 L1～L4 規則檢查改寫
>
> 回覆範例：`語體 tech；1G 2L 3X`

**作者回覆**：

> `語體 tech；1G 2L 3X`

**步驟 3 Agent 依決策呼叫 `update-state`**：

```bash
"$WENQI_PYTHON" "$WENQI_ROOT/engine/ast_scanner.py" \
  --mode update-state \
  --file "posts/2026-11-agent-memory.md" \
  --add-global-whitelist "局部性:nz" \
  --add-local-whitelist "進行 Fine-tuning:v"
```

> 若此對話是以 `--stdin` 貼入相同文章，則 `[G]` 只執行 `--mode update-state --add-global-whitelist "局部性:nz"`（不帶 `--stdin`），而 `2L` 不寫入 workspace，改於下方握手摘要列為 `--ephemeral-whitelist "進行 Fine-tuning"`。

**步驟 4 輸出握手摘要（完成）**：

```markdown
### L5 守門員握手摘要
- **目標來源**：`file` / `posts/2026-11-agent-memory.md`（`content_hash: 87f232bf`）
- **確認語體**：`tech`
- **本次新增 Global 白名單**：`局部性:nz`
- **本次新增 Local 白名單**：`進行 Fine-tuning:v`
- **後續 Lint 必帶參數**：`--profile tech`
- **交由 L1～L4 檢查（Reject `[X]`）**：`可讀性`
```
