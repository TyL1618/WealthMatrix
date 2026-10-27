# WEALTH MATRIX v4.1 — 技術文件

## 目錄

1. [專案概述](#專案概述)
2. [目錄結構](#目錄結構)
3. [依賴套件](#依賴套件)
4. [架構說明](#架構說明)
5. [資料結構](#資料結構)
6. [本地儲存](#本地儲存)
7. [雲端同步（Supabase）](#雲端同步supabase)
8. [桌面版模組說明](#桌面版模組說明)
9. [網頁版](#網頁版)
10. [打包（PyInstaller）](#打包pyinstaller)
11. [開發環境設定](#開發環境設定)
12. [設定檔說明](#設定檔說明)

---

## 專案概述

WealthMatrix 是一個個人財富管理工具，提供桌面版（PyQt6）與網頁版（純 HTML/JS）兩種介面，資料透過 Supabase 雲端同步，支援多裝置使用。

| 項目 | 說明 |
|---|---|
| 桌面版 | PyQt6 GUI，即時股價（Yahoo Finance）、本地 JSON 備份 |
| 網頁版 | 純 HTML 單檔，行動裝置友善，無需安裝 |
| 雲端 | Supabase PostgreSQL，Auth 模式（email/password） |
| 同步邏輯 | 時間戳比較，較新者優先，斷線時用本地備份 |

---

## 目錄結構

```
WealthMatrix/
├── main.py                  # 程式入口
├── requirements.txt         # Python 依賴
├── WealthMatrix.spec        # PyInstaller 打包設定
├── icon.ico                 # 應用程式圖示（7 尺寸：16/24/32/48/64/128/256）
├── DEVDOC.md                # 本技術文件
├── wealthmatrix/            # 主套件
│   ├── __init__.py
│   ├── app.py               # QMainWindow、Toast、run()
│   ├── theme.py             # 色盤、樣式表、縮放工具函式
│   ├── core/
│   │   ├── __init__.py
│   │   └── data_manager.py  # 資料讀寫、網路抓取、雲端同步
│   └── ui/
│       ├── __init__.py
│       ├── dashboard.py     # Dashboard 頁籤
│       ├── cashflow.py      # Cashflow 頁籤
│       ├── charts.py        # Charts 頁籤
│       ├── holdings.py      # Holdings 頁籤（即時持股走勢）
│       └── dialogs.py       # 新增/編輯對話框
├── tests/
│   └── test_backup.py       # 每日備份單元測試
├── docs/
│   ├── index.html           # 網頁版（GitHub Pages）
│   ├── manifest.json        # PWA Web App Manifest
│   ├── sw.js                # PWA Service Worker
│   ├── icon-192.png         # PWA 圖示 192×192
│   └── icon-512.png         # PWA 圖示 512×512
└── .gitignore
```

**不在 git 中的檔案**（存放於 `%APPDATA%\WealthMatrix\`）：

| 檔案 | 說明 |
|---|---|
| `wm_cloud.json` | Supabase 連線設定（含帳密） |
| `wealth_matrix_data.json` | 本地資料備份（明文 JSON） |
| `wm_config.json` | 本機設定（UI 縮放比例，不同步至雲端） |

---

## 依賴套件

```
PyQt6 >= 6.4.0          # GUI 框架
requests >= 2.28.0      # HTTP 請求（股價、雲端）
certifi >= 2023.0.0     # SSL 憑證（PyInstaller onefile 必要）
```

> `cryptography` 已不再是必要依賴。若本機安裝了 `cryptography`，啟動時會自動嘗試將舊版 `.enc` 加密備份遷移為明文 JSON；沒有安裝則跳過（不影響正常運作）。

---

## 架構說明

### 資料流

```
啟動
 ├─ _try_migrate_enc()  若存在舊版 .enc 加密備份，嘗試遷移為明文 JSON（需 cryptography）
 ├─ _load_local()       讀本地 wealth_matrix_data.json（明文 JSON）
 ├─ _cloud_pull()       讀 Supabase（Auth 模式：明文 JSON）
 ├─ 衝突檢測            local_ts > cloud_ts AND local_count < cloud_count × 70%
 │                      → 可能是舊電腦覆蓋，回傳 conflict_info 給 UI 顯示警告
 ├─ _pick_newer()       比較 _updated 時間戳，取較新者
 └─ load_data() return  (data, conflict_info)  — conflict_info 為 None 表示無衝突

資料變更
 └─ save_data()
      ├─ 寫本地 wealth_matrix_data.json（立即，同步）
      └─ _cloud_push()（背景執行緒，非同步）
           └─ upsert → Supabase wealthmatrix 表（id = user UUID）
```

### 資料 dict 的參照規則

`self.data` 是同一個 dict 物件，同時被 Dashboard / Cashflow / Holdings 持有。**要替換整份資料時一律用 `WealthMatrix._replace_data(new)`（就地 clear + update），不可寫 `self.data = new`**，否則各分頁還握著舊 dict，之後操作會把舊資料存回去。衝突處理、背景同步、備份還原都走這個方法。

### 安全旗標

| 旗標 | 說明 |
|---|---|
| `_cloud_push_allowed` | `False` 時禁止推送（完全 fallback 情境，防止空資料蓋掉雲端） |
| `_cloud_record_count` | 推送前若本地筆數 < 雲端 50%，呼叫 warning callback 並拒絕推送 |

### DPI 縮放

`theme.py` 中 `SCALE` 係數由 `app.run()` 在 `QApplication` 建立後根據螢幕 DPI 自動設定（`dpi / 96.0`）。若 `wm_config.json` 有 `ui_scale` 欄位則以其覆蓋自動值。所有像素值透過 `S(n)` 函式乘上係數，支援 `FORCE_SCALE` 環境變數手動覆蓋。

### 捲動與 Layout

Dashboard、Charts、Holdings 三個頁籤均有外層 `QScrollArea` 承接垂直溢出，確保小螢幕也可用滾輪瀏覽完整內容。各 section（銀行、股票、目標）使用 `setFixedHeight(S(n))` 固定高度，多於顯示行數時顯示內部捲軸。

---

## 資料結構

```jsonc
{
  "banks": [
    { "name": "台灣銀行", "amount": 100000 }
  ],
  "cash": 5000,
  "stocks": [
    {
      "ticker": "0050.TW",
      "shares": 100,
      "cost": 150.0,           // 每股平均成本
      "holding_cost": 15000,   // 總持倉成本（cost × shares，可因加碼而調整）
      "last_price": 185.2,     // 最後一次抓到的股價（快取）
      "last_updated": "2026-05-26"
    }
  ],
  "goals": [
    { "name": "緊急備用金", "target": 300000 }
  ],
  "goals_visible": true,
  "cashflow_monthly": {
    "2026-05": [
      {
        "date": "2026-05-10",
        "category": "薪資",
        "type": "收入",        // "收入" | "支出"（amount 一律存正數；PWA 讀取時容忍舊資料沒有 type，改看正負號）
        "amount": 65000,
        "note": ""
      }
    ]
  },
  "history":       [{ "date": "2026-05-26", "total": 245000 }],
  "history_bank":  [{ "date": "2026-05-26", "bank":  200000 }],
  "history_cash":  [{ "date": "2026-05-26", "cash":  5000   }],
  "history_stock": [{ "date": "2026-05-26", "stock": 40000  }],
  "dca_reminder": { "enabled": false, "day": 5, "last_reminded": "" },
  "usd_rate": 31.5,
  "usd_rate_date": "2026-05-26",
  "undo_stack": [],
  "_updated": "2026-05-26T06:00:00.000000"  // UTC ISO 8601
}
```

> **目標進度的計算基礎**：銀行存款 + 現金 + 股票市值（三者合計）。

---

## 本地儲存

| 路徑 | 格式 | 說明 |
|---|---|---|
| `%APPDATA%\WealthMatrix\wealth_matrix_data.json` | 明文 JSON | 主要本地備份 |
| `%APPDATA%\WealthMatrix\wm_config.json` | 明文 JSON | 本機設定（UI 縮放，不同步） |
| `%APPDATA%\WealthMatrix\wm_cloud.json` | 明文 JSON | Supabase 連線設定（不在 git） |
| `%APPDATA%\WealthMatrix\backups\wealth_matrix_data_YYYY-MM-DD.json` | 明文 JSON | 每日輪替備份（見下） |

### 每日輪替備份

- `_save_local_raw()` 每次寫本地檔前呼叫 `_backup_daily()`：**當天第一次寫入前**，把現有的 `wealth_matrix_data.json` 複製到 `backups/`，所以備份的是「當天第一次修改之前」的狀態（可還原到前一天的樣子）。
- 只保留最近 30 份（`_BACKUP_KEEP`），超過的由舊到新刪除。
- 本地檔改為「先寫 `.tmp` 再 `os.replace`」，寫到一半當機不會留下半截檔案。
- 設定視窗（⚙）有「開啟備份資料夾」與「從備份還原…」：
  還原前會先把現況另存為 `…_YYYY-MM-DD_pre-restore.json`，再 `_replace_data()` 套用備份、`set_cloud_sync_state(True, 0)` 解除筆數鎖、`save_data()` 蓋上新時間戳推送雲端。
  **不要手動把備份檔複製回 `wealth_matrix_data.json`**：雲端的 `_updated` 比較新，下次啟動 `_pick_newer` 會選雲端，備份會被蓋掉；請用 App 內的還原。
- 備份只涵蓋桌面本地檔；PWA 端沒有獨立備份，資料以雲端那一列為準。

### 舊版遷移（`wealth_matrix_data.enc`）

若 `%APPDATA%\WealthMatrix\` 下存有舊版 `.enc` 加密備份，啟動時 `_try_migrate_enc()` 會嘗試用 `cryptography` 套件解密並轉存為 `.json`。成功後刪除 `.enc` 和 `wm.key`，之後不再需要 `cryptography`。

---

## 雲端同步（Supabase）

### 資料表結構

```sql
CREATE TABLE wealthmatrix (
  id      text PRIMARY KEY,   -- Auth 模式: user UUID；舊版: "singleton"
  payload text,               -- JSON 字串（Auth 模式明文；舊版 Fernet 密文）
  updated text                -- UTC ISO 8601 時間戳
);
```

### RLS（建議啟用）

```sql
ALTER TABLE wealthmatrix ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Own data only" ON wealthmatrix
  FOR ALL USING (auth.uid()::text = id);
```

### 認證模式

| 模式 | 條件 | row id | payload 格式 |
|---|---|---|---|
| Auth 模式 | `wm_cloud.json` 有 email/password | user UUID | 明文 JSON |
| Legacy 模式 | 只有 url/key，無 email/password | `singleton` | Fernet 密文 |

### Token 快取

登入 token 快取於 `_auth_cache`（module-level dict），到期前 60 秒自動重新登入，避免每次 save 都呼叫 Auth API。

### 設定檔：`wm_cloud.json`

```json
{
  "supabase_url": "https://xxxx.supabase.co",
  "supabase_key": "sb_publishable_...",
  "email": "your@email.com",
  "password": "yourpassword"
}
```

> **注意**：用記事本或 VS Code 儲存，避免使用 PowerShell `Set-Content`（會產生 UTF-8 BOM，導致 Python `json.load()` 解析失敗）。

### 衝突檢測

`load_data()` 回傳 `(data, conflict_info)`。當本地時間戳較新但筆數明顯少於雲端（< 70%）時，`conflict_info` 為包含雙方資訊的 dict，啟動後 400ms 顯示警告對話框讓使用者選擇保留哪份資料。`conflict_info` 為 `None` 表示無衝突。

---

## 桌面版模組說明

### `app.py`
- `WealthMatrix`：主視窗，整合所有頁籤與計時器
- `Toast`：右下角淡出通知元件
- `run()`：建立 `QApplication`、設定 DPI 縮放與 Fusion 主題、啟動視窗
- `_show_settings()`：UI 縮放設定對話框（80% / 100% / 125% / 150% / 175%）
- `_handle_startup_conflict()`：啟動時資料衝突處理

### `theme.py`
- `CP`：色盤 dict（`bg`, `cyan`, `green`, `panel` 等 15 色）
- `S(n)` / `Sf(n)`：像素/字型縮放函式
- `STYLESHEET` / `DIALOG_STYLE`：全域 QSS 樣式表（lazy object，確保 SCALE 設定後才生成）
- `CpPanel`：帶頂部色條的面板元件（`QFrame` 子類）
- `fmt_ntd()` / `fmt_pnl()` / `fmt_pct()`：數值格式化
- 捲軸樣式：垂直（粉紅→青色漸層）/ 水平（青色→粉紅漸層），10px 寬，neon 邊框

### `core/data_manager.py`
- `load_data()` → `(data, conflict_info)`：載入資料並回傳衝突資訊
- `save_data()`：寫本地 JSON + 背景推送雲端
- `load_config()` / `save_config()`：讀寫 `wm_config.json`（本機設定）
- `_cloud_pull()` / `_cloud_push()`：Supabase 讀寫
- `DataFetcher`（QThread）：Yahoo Finance 股價抓取、匯率抓取
- `add_month_record()` / `del_month_record()` / `edit_month_record()`：現金流 CRUD
- `push_undo()` / `pop_undo()`：復原機制（最多 20 筆）
- `register_push_warning_callback()` / `set_cloud_sync_state()`：推送安全控制
- `list_backups()` / `load_backup()` / `backup_now()` / `count_records()`：每日備份與還原（見「每日輪替備份」）

### 測試

```powershell
python -m unittest discover tests -v
```

`tests/test_backup.py` 涵蓋備份輪替（每日一份、保留 30、pre-restore 標籤、原子寫入）。測試用暫存目錄，不會碰真實資料。

### `ui/dashboard.py`
- 銀行帳戶（全寬，`setFixedHeight(S(155))`，可滾動）
- 現金（緊湊橫條）
- 股票（`setFixedHeight(S(210))`，支援水平捲軸）
- 目標進度（`setFixedHeight(S(265))`）：計算基礎包含股票市值
- DCA 提醒功能

### `ui/cashflow.py`
- 年月選擇器、月度收支記錄
- 使用 `enumerate` 保存原始 index 解決重複記錄刪除問題

### `ui/charts.py`
- 總資產、銀行、現金、股票歷史走勢圖（自繪 `QPainter`）
- 圓餅圖：資產配置比例

### `ui/holdings.py`
- 每支持股一張 card，由上到下排列
- **即時走勢圖**：Yahoo Finance v8 chart API（5 分鐘 K 棒），`IntradayChart`（自繪 `QPainter`）
- **今日損益**：`(chart_price − 昨收) × shares`（chart API 資料）
- **總損益**：`(dashboard_price × shares) − holding_cost`（與 Dashboard 同一份 `stock_prices`，數字一致）
- `FetchThread`（QThread）：背景抓取，不阻塞 UI
- 自動刷新：每 2 分鐘，倒數計時顯示於 header
- 快取機制：chart 資料快取於 `_last_results`，Dashboard 每 60 秒更新 price 時觸發 `_apply_results()` 刷新總損益，不重複打 chart API
- 市場狀態 badge：OPEN / PRE / POST / CLOSED（依 `marketState` 欄位）

### `ui/dialogs.py`
- 銀行、股票、目標、現金流記錄的新增/編輯對話框

---

## 網頁版

**位置**：`docs/index.html`（GitHub Pages：`https://tyl1618.github.io/WealthMatrix/`）

| 項目 | 說明 |
|---|---|
| 框架 | 純 HTML + CSS + JS，無 build 工具 |
| 字型 | `Orbitron`（數字/標題）+ `Rajdhani`（介面）— Google Fonts |
| Supabase SDK | `@supabase/supabase-js@2`（CDN） |
| 圖表 | `chart.js@4`（CDN）— Cashflow tab 含資產配置圓餅圖 |
| 認證 | Supabase Auth email/password |
| Session | 瀏覽器 localStorage，自動重用（約 60 天） |
| 連線設定 | URL / anon key **內建於 index.html**（見下方「內建連線設定」）；email 存 localStorage、密碼不存 |

**畫面流程（boot）**：

```
boot() → boot-splash（啟動中，不閃登入頁）
  ├─ 無 session         → login-screen（只需 email + 密碼）
  └─ 有 session
       ├─ 已設指紋/PIN   → lock-screen（指紋優先，可切 PIN）→ enterApp
       ├─ 未設且可用鎖   → lock-screen enroll（啟用指紋 / 設 PIN / 略過）
       └─ 已略過(optOut) → enterApp
```

**應用程式鎖（本機隱私鎖）**：
- 指紋 / Face ID：WebAuthn platform authenticator（`navigator.credentials`）。無後端驗章，
  僅作為擋在「已登入 session」前的本機鎖，防止旁人在此裝置開啟 PWA 看到個資。
- PIN 備援：4–6 位，SHA-256 + 隨機 salt 雜湊存 localStorage（`wm_lock`，不存明碼）。
  指紋失敗/取消或裝置不支援 WebAuthn 時自動切換到 PIN。
- Header 🔒 可手動上鎖；鎖定畫面「用密碼重新登入」會登出改走密碼。
- `wm_lock` 結構：`{ credId?, pinSalt?, pinHash?, optOut? }`。

**內建連線設定（bake）**：
- `index.html` 內 `BAKED_URL` / `BAKED_KEY` 兩個常數，由 `scripts/bake_config.py`
  從 `%APPDATA%\WealthMatrix\wm_cloud.json` 自動填入，手機端不再需要手動輸入 URL / anon key
  （清快取也不遺失，因為值隨 index.html 由 GitHub Pages 送出）。
- **安全性**：URL 與 anon key 是公開金鑰，由 Supabase RLS（`auth.uid()::text = id`）保護，
  沒有帳密登入讀不到資料。**前提：RLS 必須維持開啟、關閉匿名註冊。** email / 密碼絕不寫入程式碼。
- 重寫 index.html 後需重跑 `python scripts/bake_config.py` 再 commit。

**PWA 支援**：

| 檔案 | 說明 |
|---|---|
| `docs/manifest.json` | Web App Manifest（名稱、主題色、icon 路徑） |
| `docs/sw.js` | Service Worker（app shell network-first、CDN/字型 cache-first；快取版本 `wm-v2`） |
| `docs/icon-192.png` | PWA 圖示 192×192 |
| `docs/icon-512.png` | PWA 圖示 512×512 |

手機瀏覽器可將網頁版「加入主畫面」作為 PWA 安裝，支援離線讀取快取內容。

**介面結構（底部導覽）**：

| 位置 | 內容 |
|---|---|
| 🏠 總覽 | 總資產＋淨值變化（7D / 30D / YTD，取自 `history`）→ 本月收支卡（收入/支出/淨額、上月支出對照、緊急預備金可撐月數、支出分類前 5 名長條）→ 銀行 → 現金 → 股票 → 目標 |
| 🧾 記帳 | 月收支 / 年總覽、CSV 匯出（與先前相同） |
| ＋（中間浮動鈕） | 快速記帳：支出/收入切換 → 金額（數字鍵盤）→ 分類 chips → 日期 → 備註 |
| 📊 圖表 | 淨值走勢（30D/90D/1Y/ALL）、資產配置圓餅、近 6 月收支長條（Chart.js，切到分頁時才繪製，避免隱藏狀態量不到尺寸） |

- **分類 chips**：預設清單與桌面版 `dialogs.py` 的 `INCOME_CATS` / `EXPENSE_CATS` 相同；資料裡實際用過的分類依次數排在前面，最多 12 個，也可自行輸入。兩端資料格式沒變，桌面版看得到手機新增的分類。
- **走勢資料**：桌面版每天記 `history`；PWA 在每天第一次存檔時 `recordHistoryToday()` 補上當天（`history` / `history_bank` / `history_cash` / `history_stock`），當天已有就不動，所以不會蓋掉桌面版較準的即時股價結果。
- 編輯記錄時把日期改到別的月份，會從舊月份移除並放進新月份（先前會留在舊月份 key 下，日期卻對不上）。
- Service Worker 快取版本 `wm-v3`。

**Cashflow 檢視**：月收支（明細清單）/ 年總覽（12 個月收入/支出/淨額表格 + 全年合計，與桌面版對齊）可切換。

**股票顯示**：僅顯示成本計算（`cost × shares`），不抓即時股價（瀏覽器 CORS 限制）。

**資料格式**：與桌面版完全相同 JSON，seamless 雙向同步。

**同步安全（防止蓋掉雲端資料）**：

| 防線 | 行為 |
|---|---|
| 讀取失敗 → 唯讀 | `cloudLoad()` 回傳 `{state: 'ok' \| 'empty' \| 'error'}`。`error`（斷線、解析失敗）時進入 `_readOnly`：顯示紅色橫幅＋重試鈕、禁止編輯、`scheduleSave()`/`cloudSave()` 直接擋下，不會拿 `defaultData()` 去覆蓋雲端。`empty`（雲端確實沒有這個帳號的列）才視為新帳號可編輯。 |
| 存檔前比對 | 每次 `cloudSave()` 先查雲端 `updated`；若比 `_baseUpdated`（上次讀到/寫入的值）新，代表其他裝置改過 → `confirm()` 讓使用者選「覆蓋雲端」或「放棄本機修改、載入雲端」。背景緊急存檔遇衝突不彈窗，保留 `_dirty` 等回到前景再處理。 |
| 重新拉取 | 回到前景（`visibilitychange`）、恢復連線（`online`）、解鎖回來、每 5 分鐘 → `syncNow()`：有未存修改就存，否則 `pullLatest()` 載入較新的雲端資料。編輯 modal 開啟中、存檔中、有未存修改時不會替換資料。 |

其他細節：`_dirty` 在存檔失敗時保留（恢復連線自動重試）；`_editSeq` 處理「存檔期間又有新修改」；切到背景時立即存檔（行動瀏覽器可能凍結 1.5 秒 debounce 計時器）；時間戳比較用 `tsMs()` 統一成毫秒（桌面版寫的是無時區微秒、PWA 寫的是 ISO Z 毫秒）。

---

## 打包（PyInstaller）

```powershell
cd C:\Users\...\WealthMatrix
build_exe.bat   # 內部跑 pyinstaller WealthMatrix.spec --noconfirm --clean
# 輸出: dist\WealthMatrix.exe
```

**spec 重點**：
- `onefile` 模式：所有依賴打包成單一 EXE
- `console=False`：無黑色終端視窗
- `certifi` data 打包：確保 HTTPS 正常（`os.environ['REQUESTS_CA_BUNDLE']` 在 frozen 模式自動設定）
- `cryptography` 若在 hiddenimports 中：僅用於遷移舊版 `.enc` 備份，新安裝可移除

---

## 開發環境設定

```powershell
# 1. Clone
git clone https://github.com/TyL1618/WealthMatrix.git
cd WealthMatrix

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 設定雲端（複製或建立）
# 將 wm_cloud.json 放到 %APPDATA%\WealthMatrix\

# 4. 執行
python main.py
```

---

## 設定檔說明

### `%APPDATA%\WealthMatrix\wm_cloud.json`

必要欄位：`supabase_url`、`supabase_key`
選用欄位（Auth 模式）：`email`、`password`

缺少 email/password → 自動降級為 Legacy 模式（singleton row + Fernet）。

### `%APPDATA%\WealthMatrix\wm_config.json`

本機專屬設定，**不同步至雲端**，不同裝置可有不同值。

```json
{
  "ui_scale": 1.5
}
```

| 欄位 | 說明 | 預設 |
|---|---|---|
| `ui_scale` | UI 縮放比例（0.8 / 1.0 / 1.25 / 1.5 / 1.75） | 依螢幕 DPI 自動計算 |

### 環境變數

| 變數 | 說明 |
|---|---|
| `FORCE_SCALE` | 強制指定 DPI 縮放係數（如 `1.5`），優先級低於 `wm_config.json` |
| `QT_AUTO_SCREEN_SCALE_FACTOR` | 設為 `0` 避免 Qt 自動縮放與 `S()` 雙重縮放 |
| `QT_SCALE_FACTOR` | 設為 `1` 同上 |

## 打包環境（build_exe.bat / setup_env.bat）
`build_exe.bat` 開頭會呼叫 `setup_env.bat`：用 `py -3.14` 在專案資料夾建 `.venv`，照 `requirements.txt`（版本全部 `==` 釘死）安裝，再把 `.venv\Scripts` 放到 PATH 最前面，後面的 `python` / `pyinstaller` 都是 `.venv` 裡的那份。
所以**換電腦 git clone 後直接雙擊 `build_exe.bat` 就能打包**，不依賴那台電腦原本裝了什麼版本的 Python 或套件。第一次要連網（約 1-3 分鐘），之後只有 `requirements.txt` 變動才會重新安裝。
- 要換 Python 版本：改 `setup_env.bat` 的 `PYVER`、刪掉 `.venv` 後重跑。
- 新增或升級套件：改 `requirements.txt`（用 `==`），下次執行 bat 會自動重裝；程式 import 了新套件卻沒寫進 `requirements.txt` 的話，別台電腦打包會缺模組。
- `.venv/` 不進版控。
