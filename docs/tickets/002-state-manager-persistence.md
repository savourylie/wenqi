# [TICKET-002] 非侵入式狀態管理與 Content Hash 對齊 (State Manager)

## Status
`pending`

## Dependencies
- Requires: #001 ✅

## Description
實作 `engine/state_manager.py`：所有持久化狀態存放於 `~/.config/wenqi/`，100% 不污染使用者原始文章（不改 Markdown Frontmatter）。支援全域設定、單一 Repo 多篇文章的 workspace 設定、路徑＋內容指紋雙重綁定與改名自動遷移，以及 `--stdin` 隨手貼模式的無狀態運行。這是 L5 白名單寫入與所有 lint 呼叫讀取設定的基礎。

## Acceptance Criteria
- [ ] 能讀寫 `~/.config/wenqi/global_config.json`，schema 與 §4.1A 一致（`schema_version: "2.0.0"`、`default_profile`、三種 profiles 的閾值與 `disabled_rules`、`global_whitelist`）；檔案不存在時以內建預設初始化。
- [ ] 能讀寫 `~/.config/wenqi/workspaces/<repo_path_sha256_8>.json`，schema 與 §4.1B 一致（`repo_root`、`repo_defaults`、`documents` 以相對 Repo Root 路徑為 key）。
- [ ] `content_hash` = 文章前 300 字（去除空白）的 SHA-256 前 8 碼；檔案改名／搬移時，依 `content_hash` 比對自動遷移該篇的 profile、local_whitelist、disabled_rules 設定。
- [ ] 三級白名單合併順序正確：global → repo_defaults → document local_whitelist（後者可覆寫前者同詞條的 pos/note）。
- [ ] `--stdin` 模式不建立 workspace 檔，僅讀 global_config 並接受 `--ephemeral-whitelist` 於記憶體中合併。
- [ ] 提供 CLI 寫入入口所需的函式：新增 global whitelist、新增 local whitelist（對應 §7 的 `--mode update-state --add-global-whitelist / --add-local-whitelist`）。
- [ ] 全程不寫入、不改動使用者文章檔案本身。

## Design Reference
- `zh_polish_skill_spec_v2.md` §4.1（儲存結構與兩份 Schema）、§7（update-state CLI 參數）。

## References
- `config/default_lexicons.json`（#001）— 預設技術白名單作為 global_whitelist 初始化來源。

## Implementation Notes
- Required constraints: 狀態一律外部化於 `~/.config/wenqi/`；schema_version 欄位保留供未來遷移；repo hash 取 repo 絕對路徑 SHA-256 前 8 碼。
- Suggested approach: 讀取時做 schema 驗證與缺欄位補預設；content_hash 遷移以「同 hash 不同路徑」偵測，衝突時保留較新設定並記錄。

## Testing
- 單元測試（以暫存 HOME 隔離）：初始化預設、三級合併、白名單新增、改名遷移（同內容換路徑後設定仍在）、stdin 模式不落盤。
- 驗證測試前後目標文章檔案 bytes 完全不變。

## As-Built Notes
- 2026-11-19（TICKET-002 實作）：
  - 使用者決策（clarify 階段）：Q1 遷移衝突採確定性規則、不加時間戳（路徑優先；唯一 hash 匹配才遷移；歧義不覆寫＋log）——偏離 ticket「保留較新」之 Suggested approach，經使用者同意；Q2 repo root 以 `git rev-parse --show-toplevel` 偵測，無 repo／git 不可用則無狀態（只讀 global_config）；Q3 content_hash 輸入域為原始檔文字（含 Markdown/frontmatter）去空白後前 300 Unicode 字元。
  - 實作解讀：路徑 entry hash 不符且無遷移來源時，視為原文內容更新——保留設定並刷新指紋（避免作者改開頭即丟白名單）；過期佔位被遷移取代時，被取代 entry 的 hash 記入 log 供人工追溯。
  - profile 優先序：CLI `--profile` > 單篇 > repo_defaults > global `default_profile`；未設定的 repo／單篇 profile 以 `null` 儲存＝继承（skeleton 不得以 tech 覆寫全域預設）。`disabled_rules` 原樣暴露（profile 級＋單篇級），組合語義留給 TICKET-006+ 消費者。
  - Lazy 建立：純讀取不建 workspace 檔；首次持久化（add-local-whitelist、遷移）才寫。global_config 於首次讀取不存在時以內建預設初始化（stdin 亦同，惟絕不建 workspace）。`--ephemeral-whitelist` 於 file／stdin 皆僅記憶體合併、永不落盤，缺 pos 補 `nz`。
  - 工程慣例：`StateError(ValueError)` 沿用 `LexiconError` 模式；損壞 JSON 明確報錯不靜默重置；原子寫入（同目錄 tmp＋`os.replace`）；repo_root 先 `resolve()` 再哈希；documents key 為相對 POSIX 路徑（拒絕對路徑／`..`）；遷移／衝突記錄走 `logging`（stderr），stdout 保留給 TICKET-006 JSON payload；純 stdlib、py>=3.9 相容。
  - 已知限制（spec 設計本質）：指紋只覆蓋前 300 字，改開頭即失聯、同開頭撞號（以唯一匹配＋log 缓解）；不同 git worktree 的 toplevel 不同→各自一份 workspace；repo 資料夾改名→workspace 檔名改變，需手動遷移（`repo_root` 不符時明確報錯）。
  - 介面供下游：`merge_whitelists` 輸出 `List[dict]`（必含 pos）供 TICKET-003 `JiebaPosAdapter.register_whitelist`；`add_global_whitelist`／`add_local_whitelist` 供 TICKET-006 `--mode update-state`；stdin 下 `--add-local-whitelist` 之拒絕屬 CLI 層（TICKET-006），本模組 `add_local_whitelist` 必要 repo_root。
  - 驗證：`.venv/bin/python -m pytest` 41 passed（12 既有＋29 新增）；含改名遷移端到端、三級合併覆寫、stdin／無 repo 不落盤、ephemeral 不落盤、文章 bytes 全程不變、損壞 JSON／非 UTF-8／空檔／路徑逸出等錯誤路徑。