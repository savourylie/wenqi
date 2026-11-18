# [TICKET-002] 非侵入式狀態管理與 Content Hash 對齊 (State Manager)

## Status
`blocked`

## Dependencies
- Requires: #001

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