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
| 桌面版 | PyQt6 GUI，即時股價（Yahoo Finance）、本地加密備份 |
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
├── icon.ico                 # 應用程式圖示
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
│       └── dialogs.py       # 新增/編輯對話框
├── docs/
│   └── index.html           # 網頁版（GitHub Pages）
└── .gitignore
```

**不在 git 中的檔案**（存放於 `%APPDATA%\WealthMatrix\`）：

| 檔案 | 說明 |
|---|---|
| `wm_cloud.json` | Supabase 連線設定（含帳密） |
| `wm.key` | 本地 Fernet 加密金鑰 |
| `wealth_matrix_data.enc` | 加密後的本地資料備份 |

---

## 依賴套件

```
PyQt6 >= 6.4.0          # GUI 框架（tested: 6.11.0）
requests >= 2.28.0      # HTTP 請求（股價、雲端）（tested: 2.34.0）
cryptography >= 40.0.0  # 本地 .enc 加密（tested: 48.0.0）
certifi >= 2023.0.0     # SSL 憑證（PyInstaller onefile 必要）
```

---

## 架構說明

### 資料流

```
啟動
 ├─ _load_local()       讀本地 .enc（Fernet 解密）
 ├─ _cloud_pull()       讀 Supabase（Auth 模式：明文 JSON）
 │    └─ Migration      若 UUID 列不存在，嘗試讀舊版 singleton 列（Fernet 解密）
 ├─ _pick_newer()       比較 _updated 時間戳，取較新者
 └─ load_data() return

資料變更
 └─ save_data()
      ├─ 寫本地 .enc（立即，同步）
      └─ _cloud_push()（背景執行緒，非同步）
           └─ upsert → Supabase wealthmatrix 表（id = user UUID）
```

### 安全旗標：`_cloud_push_allowed`

| 狀態 | 說明 |
|---|---|
| `True` | 資料來自雲端或本地備份，可安全推送 |
| `False` | 完全 fallback（斷線且無本地檔），禁止推送防止空資料蓋掉雲端 |

### DPI 縮放

`theme.py` 中 `SCALE` 係數由 `app.run()` 在 `QApplication` 建立後根據螢幕 DPI 自動設定（`dpi / 96.0`）。所有像素值透過 `S(n)` 函式乘上係數，支援 `FORCE_SCALE` 環境變數手動覆蓋。

---

## 資料結構

```jsonc
{
  "banks": [
    { "name": "台灣銀行", "amount": 100000 }
  ],
  "cash": 5000,
  "stocks": [
    { "ticker": "0050.TW", "shares": 100, "cost": 150.0 }
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
        "amount": 65000,       // 正數 = 收入，負數 = 支出
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

---

## 本地儲存

| 路徑 | 格式 | 說明 |
|---|---|---|
| `%APPDATA%\WealthMatrix\wealth_matrix_data.enc` | Fernet 加密二進位 | 主要本地備份 |
| `%APPDATA%\WealthMatrix\wm.key` | 原始 Fernet key bytes | 加密金鑰，請妥善保管 |

`wm.key` 首次啟動時自動產生。若金鑰遺失，本地 `.enc` 無法解密。**多台電腦需複製相同 `wm.key`** 才能互通本地備份（雲端同步不受影響）。

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

---

## 桌面版模組說明

### `app.py`
- `WealthMatrix`：主視窗，整合所有頁籤與計時器
- `Toast`：右下角淡出通知元件
- `run()`：建立 `QApplication`、設定 DPI 縮放與 Fusion 主題、啟動視窗

### `theme.py`
- `CP`：色盤 dict（`bg`, `cyan`, `green`, `panel` 等 15 色）
- `S(n)` / `Sf(n)`：像素/字型縮放函式
- `STYLESHEET`：全域 QSS 樣式表（lazy object）
- `fmt_ntd()` / `fmt_pnl()` / `fmt_pct()`：數值格式化

### `core/data_manager.py`
- `load_data()` / `save_data()`：公開 API
- `_cloud_pull()` / `_cloud_push()`：Supabase 讀寫
- `DataFetcher`（QThread）：Yahoo Finance 股價抓取、匯率抓取
- `add_month_record()` / `del_month_record()` / `edit_month_record()`：現金流 CRUD
- `push_undo()` / `pop_undo()`：復原機制（最多 20 筆）

### `ui/dashboard.py`
- 銀行帳戶、現金、股票（即時股價）、目標進度
- DCA 提醒功能

### `ui/cashflow.py`
- 年月選擇器、月度收支記錄
- 使用 `enumerate` 保存原始 index 解決重複記錄刪除問題

### `ui/charts.py`
- 總資產、銀行、現金、股票歷史走勢圖（自繪 QPainter）

### `ui/dialogs.py`
- 銀行、股票、目標、現金流記錄的新增/編輯對話框

---

## 網頁版

**位置**：`docs/index.html`（GitHub Pages：`https://tyl1618.github.io/WealthMatrix/`）

| 項目 | 說明 |
|---|---|
| 框架 | 純 HTML + CSS + JS，無 build 工具 |
| Supabase SDK | `@supabase/supabase-js@2`（CDN） |
| 圖表 | `chart.js@4`（CDN） |
| 認證 | Supabase Auth email/password |
| Session | 瀏覽器 localStorage，自動重用（約 60 天） |
| 設定儲存 | Supabase URL / anon key / email 存 localStorage（密碼不存） |

**股票顯示**：僅顯示成本計算（`cost × shares`），不抓即時股價（瀏覽器 CORS 限制）。

**資料格式**：與桌面版完全相同 JSON，seamless 雙向同步。

---

## 打包（PyInstaller）

```powershell
cd C:\Users\...\WealthMatrix
pyinstaller WealthMatrix.spec
# 輸出: dist\WealthMatrix.exe
```

**spec 重點**：
- `onefile` 模式：所有依賴打包成單一 EXE
- `console=False`：無黑色終端視窗
- `certifi` data 打包：確保 HTTPS 正常（`os.environ['REQUESTS_CA_BUNDLE']` 在 frozen 模式自動設定）
- `cryptography` 在 hiddenimports：因其在函式內 `try/except import`，靜態分析可能漏掉

---

## 開發環境設定

```powershell
# 1. Clone
git clone https://github.com/TyL1618/WealthMatrix.git
cd WealthMatrix

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 設定雲端（複製或建立）
# 將 wm_cloud.json 和 wm.key 放到 %APPDATA%\WealthMatrix\

# 4. 執行
python main.py
```

---

## 設定檔說明

### `%APPDATA%\WealthMatrix\wm_cloud.json`

必要欄位：`supabase_url`、`supabase_key`
選用欄位（Auth 模式）：`email`、`password`

缺少 email/password → 自動降級為 Legacy 模式（singleton row + Fernet）。

### 環境變數

| 變數 | 說明 |
|---|---|
| `FORCE_SCALE` | 強制指定 DPI 縮放係數（如 `1.5`） |
| `QT_AUTO_SCREEN_SCALE_FACTOR` | 設為 `0` 避免 Qt 自動縮放與 `S()` 雙重縮放 |
| `QT_SCALE_FACTOR` | 設為 `1` 同上 |
