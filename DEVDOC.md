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
│   │   ├── data_manager.py  # 資料讀寫、網路抓取、雲端同步
│   │   ├── calc.py          # 淨值/貸款/交易/預算/年化報酬等純函式（不依賴 Qt）
│   │   ├── recurring.py     # 固定收支（含貸款還款規則）
│   │   └── secret.py        # Windows DPAPI（保護 wm_cloud.json 的密碼）
│   └── ui/
│       ├── __init__.py
│       ├── dashboard.py     # Dashboard 頁籤
│       ├── cashflow.py      # Cashflow 頁籤
│       ├── charts.py        # Charts 頁籤
│       ├── holdings.py      # Holdings 頁籤（即時持股走勢）
│       └── dialogs.py       # 新增/編輯對話框
├── tests/
│   ├── test_*.py            # Python 單元測試
│   ├── gen_vectors.py       # 產生 vectors.json（Python 與 PWA 共用的標準答案）
│   ├── vectors.json
│   └── js/                  # Node 測試：logic.js、共用向量、Worker
├── worker/                  # 股價代理（Cloudflare Worker，需自行部署，見 worker/README.md）
├── docs/
│   ├── index.html           # 網頁版（GitHub Pages）：版面與畫面程式
│   ├── app.css              # 網頁版樣式
│   ├── logic.js             # 網頁版純邏輯（與 core/calc.py 同一套規則，共用測試向量）
│   ├── manifest.json        # PWA Web App Manifest
│   ├── sw.js                # PWA Service Worker
│   ├── icon-192.png         # PWA 圖示 192×192
│   └── icon-512.png         # PWA 圖示 512×512
└── .gitignore
```

**不在 git 中的檔案**（存放於 `%APPDATA%\WealthMatrix\`）：

| 檔案 | 說明 |
|---|---|
| `wm_cloud.json` | Supabase 連線設定（密碼以 Windows DPAPI 加密） |
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
  "schema_version": 5,           // 2: liabilities / recurring；3: budgets / goal.deadline；4: transactions / dividends；5: budgets_by_month / settings；舊資料載入時由兩端各自補齊
  "budgets_by_month": { "2026-12": { "餐飲": 8000, "購物": 0 } },   // 按月覆寫：只存和每個月預設不同的項目；0 = 這個月不設預算
  "settings": { "price_proxy": "https://wealthmatrix-quotes.xxx.workers.dev" },   // PWA 設定（股價代理網址），電腦版不使用
  "transactions": [              // 買賣紀錄（賣出多一個 realized = 已實現損益）
    { "id": "t_1a2b3c4d", "date": "2026-03-05", "ticker": "0050.TW", "side": "sell",
      "shares": 40, "price": 150, "fee": 10, "note": "", "realized": 1990 }
  ],
  "dividends": [                 // 股利（實收金額）
    { "id": "d_5e6f7a8b", "date": "2026-07-20", "ticker": "0050.TW", "amount": 250, "note": "Q2" }
  ],
  "budgets": { "餐飲": 6000, "娛樂": 2000 },   // 分類 → 每月預算（>0 才存；「投資買入」不列入預算）
  "banks": [
    { "name": "台灣銀行", "amount": 100000 }
  ],
  "liabilities": [               // 負債；淨值 = 銀行 + 現金 + 股票 − 負債（貸款用 liability_balance 算目前餘額）
    { "name": "信用卡", "amount": 12000 },                       // 一般負債：amount 就是餘額，自己手動更新
    { "id": "l_1a2b3c4d", "name": "車貸", "type": "loan",       // 分期貸款
      "principal": 600000, "rate": 2.5,                         // 貸款總額、年利率（%）
      "term": 60, "grace": 0,                                    // 總期數（月，含寬限期）、寬限期（只繳利息的月數）
      "start": "2026-11-05",                                     // 首期繳款日，之後每月同一天（31 日在小月落在月底）
      "method": "annuity",                                       // "annuity" 本息平均攤還 | "equal_principal" 本金平均攤還
      "paid_override": 12,                                       // 選填：已繳期數手動覆寫（預設依日期自動算）
      "amount": 480000 }                                         // 目前本金餘額（程式同步，給舊版程式讀；計算用 liability_balance）
  ],
  "recurring": [                 // 固定收支規則，見 core/recurring.py
    {
      "id": "r_1a2b3c4d", "type": "支出", "category": "房租", "amount": 12000,
      "day": 5,                  // 每月幾號；31 在小月落在月底
      "note": "", "active": true,
      "start": "2026-10",        // 從這個月開始產生
      "end": "2031-10",          // 選填：最後一個要產生的月份（貸款還完就停）
      "loan": "l_1a2b3c4d",      // 選填：與哪筆貸款綁定（貸款自動還款規則）
      "generated": ["2026-10"]   // 已產生過的月份（刪除當月記錄後不會重新產生）
    }
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
    { "name": "緊急備用金", "target": 300000, "deadline": "2027-06" }   // deadline 選填，'YYYY-MM'
  ],
  "goals_visible": true,
  "cashflow_monthly": {
    "2026-05": [
      {
        "date": "2026-05-10",
        "category": "薪資",
        "type": "收入",        // "收入" | "支出"（amount 一律存正數；PWA 讀取時容忍舊資料沒有 type，改看正負號）
        "amount": 65000,
        "note": "",
        "rec": "r_1a2b3c4d"      // 選填：由固定收支規則自動產生時帶規則 id
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

> **淨值與目標進度的計算基礎**：銀行存款 + 現金 + 股票市值 − 負債（桌面版 `core/calc.py` 的 `net_worth()`、PWA 的 `grandTotal()`，兩邊公式一致）。`history[].total` 從加入負債功能起記的是淨值；**第一次填入負債的那天，走勢會出現一次性的下降**（舊紀錄是沒扣負債的資產總額）。淨值為負時目標進度顯示 0%。
>
> **交易記錄與股利**：桌面「DASHBOARD → 股票面板 → 📒 交易」、PWA「總覽 → 股票 → 📒 交易」。可記買進、賣出、股利，並顯示未實現／已實現（今年與累計）／股利／總報酬（＝三者相加）。
> - 買賣依**平均成本法**更新 `stocks`：買進時 `holding_cost += 股數×價格 + 費用`、`cost = holding_cost / shares`（手續費計入成本）；賣出時已實現損益 `= 股數×價格 − 費用 − 均價×股數`（費用請填手續費＋證交稅），均價不變；賣光時該檔從 `stocks` 移除，損益留在交易記錄。賣出股數超過持股會被拒絕，資料不變。
> - **不會動銀行或現金餘額**（避免和你自己維護的餘額重複計算）；股利也只記在投資摘要，不會自動寫進收支。
> - 刪除紀錄只移除紀錄，**不會回頭調整持股**；沒有「編輯」，改錯請刪掉重記。
> - 既有的「新增持股」「+倉」也會補一筆買進紀錄（持股本身照舊更新），所以帳本會包含這些操作；在這功能之前建立的持股沒有紀錄，視為期初持股。
> - 未實現損益：桌面用即時報價（沒有再用 `last_price`），PWA 沒有報價來源，只用桌面版寫入的 `last_price`；兩者都沒有的持股不計入。**這不是年化報酬**（沒有期初買進日期就無法算 XIRR），只是損益合計。
> - 邏輯在 `core/calc.py`（`apply_trade` / `add_dividend` / `portfolio_summary`），PWA 是 JS 版（`applyTrade` / `addDividend` / `portfolioSummary`），兩邊要一起改。
>
> **分期貸款**：桌面「負債面板 → + ADD → 分期貸款」、PWA「總覽 → 負債與貸款 → ＋新增 → 分期貸款」。填貸款名稱、貸款總額、年利率、總期數、寬限期、首期繳款日、攤還方式，即時預覽每月應繳、總利息與結清月份；卡片顯示剩餘本金、**還款進度條**（已還本金 %）、第 n / 總期數期、每月應繳、下次繳款日、預計結清、總利息。
> - 每期明細由 `loan_schedule()` 算出（四捨五入到整數元，最後一期補尾數使餘額歸零）：本息平均 `pmt = P·r·(1+r)^m / ((1+r)^m − 1)`（`r` 為月利率、`m` = 期數 − 寬限期）；本金平均每月還 `P/m` 加遞減利息；寬限期只繳利息。
> - **已繳期數依繳款日自動計算**（繳款日當天算已繳），負債餘額與淨值隨時間自動下降，不需要手動更新。與銀行實際不符時（提前還款、延後繳）用「已繳期數」欄位覆寫。**不處理提前還款**。
> - 勾選「每月自動記一筆『貸款還款』支出」（只在本息平均且沒有寬限期時提供，因為金額才固定）會建立一條綁定貸款的固定收支規則（`rule.loan` = 貸款 id、`rule.end` = 最後一期月份）。編輯貸款時沿用舊規則的 `generated`，不會把已入帳的月份重複入帳；刪除貸款會一併移除規則，已入帳的記錄保留。
> - 還款支出是整筆（本金＋利息）都算支出，所以「存錢速度」與預備金天數會比實際保守；銀行餘額不會自動扣，請自行維護。
> - 邏輯在 `core/calc.py`（`validate_loan` / `loan_schedule` / `loan_status` / `liability_balance`）與 `core/recurring.py`（`set_loan_rule`）；PWA 是 JS 版（`loanSchedule` / `loanStatus` / `liabBalance` / `setLoanRule`），兩邊要一起改。
>
> **預算**：`budgets` 是「分類 → 每月上限」。桌面版在「CASHFLOW → 預算設定」，本月/所選月份各分類顯示進度條（<80% 綠、80–100% 橘、超過粉紅）；PWA 在總覽「本月」卡的「預算」鈕，有設預算的分類顯示進度條，沒設的才出現在下方「支出分類」。PWA 記一筆支出後，若該分類已用到 80% 以上會在提示裡帶出進度，超過 100% 以紅字提示。計算在 `core/calc.py`（`expense_by_category` / `budget_status`），PWA 是 JS 版（`budgetStatus`）。
>
> **目標預測**：每個目標下方一行說明——還差多少、（有設期限）剩幾個月與每月需存多少、依近況約幾月達成；預估速度是「最近 3 個完整月份（不含本月、且有記錄）的平均每月存下」＝收入 − 支出，**「投資買入」不算支出**（它變成資產，淨值沒減少）；沒有完整月份的記錄時顯示「記帳滿一個月後可預估」。設了期限且預估會晚於期限（或根本存不到）時整行變橘色並加「⚠ 會晚於期限」。桌面版 `goal_projection` / `monthly_saving`，PWA `goalProjection` / `monthlySaving`，兩邊要一起改。桌面版目標新增 ✎ 編輯（改名稱/金額/期限，取消勾選「設定期限」就會移除期限）。
>
> **固定收支**：到期時由桌面版（`app._apply_recurring_now`，啟動與每次價格更新時檢查）或 PWA（`applyRecurring`，開啟、回前景、解鎖、每 5 分鐘檢查）自動寫入 `cashflow_monthly`。兩端都以 `rule.generated` 判斷是否已產生，同一份資料被兩端各處理一次也不會重複。規則重新啟用時 `start` 重設為本月，不回補停用期間；最多回補 12 個月。管理入口：桌面「CASHFLOW → ⟳ 固定收支」、PWA「記帳 → ⟳ 固定收支」。

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

上面是**第一次建立**時的寫法（明文 `password`）。程式第一次讀到明文密碼時，會自動用 **Windows DPAPI**（`core/secret.py`，不需額外套件）加密，把檔案改寫成：

```json
{
  "supabase_url": "...", "supabase_key": "...", "email": "your@email.com",
  "password_dpapi": "AQAAANCMnd8BFdERjHoAwE/Cl+s..."
}
```

- 明文 `password` 會從檔案移除；加密結果只有**同一個 Windows 使用者、同一台電腦**解得開，檔案被複製走、不小心 commit 或上傳雲端硬碟都沒用。
- **把 `wm_cloud.json` 複製到別台電腦**：加密的密碼在新電腦解不開，第一次啟動（`app._ask_cloud_password_if_needed`）會彈出視窗請你輸入一次密碼，驗證通過後存成那台電腦自己的加密版；也可以直接把檔案改回明文 `password` 欄位，下次啟動會自動重新加密。
- 取消、或連續輸入錯誤 3 次：程式照常啟動，只是雲端同步暫停（`_cloud_push_allowed = False`，不會用空資料覆蓋雲端）。連不上網時無法驗證密碼，會先存起來。
- 非 Windows（沒有 DPAPI）維持明文存法。
- 密碼只在記憶體裡以明文存在（`_load_cloud_cfg()` 每次呼叫時解密）。`scripts/bake_config.py` 只讀 URL / anon key，不碰密碼。

> **注意**：用記事本或 VS Code 儲存，避免使用 PowerShell `Set-Content`（會產生 UTF-8 BOM，導致 Python `json.load()` 解析失敗；程式讀取時有容忍 BOM，寫回時不帶 BOM）。

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

### `core/calc.py`、`core/recurring.py`、`core/secret.py`
不依賴 Qt 的純函式，可直接單元測試。`secret.py`：`protect()` / `unprotect()`（Windows DPAPI，見「設定檔：wm_cloud.json」）。`calc.py` 另有 `normalize_ticker()`（純數字台股代號補 `.TW`，上櫃請自行輸入 `.TWO`；PWA 為 `normalizeTicker`）與 `is_income()` / `rec_type()`（沒有 `type` 的舊記錄看金額正負）。`calc.py`：`bank_total` / `liabilities_total` / `stocks_total` / `assets_total` / `net_worth`（原本散在 `app.py` 與 `dashboard.py` 三處的合計邏輯）。`recurring.py`：`apply_recurring(data, today)`、`new_rule_id()`。新增模組要同步加進 `WealthMatrix.spec` 的 `hiddenimports`。

### 桌面版介面
沉穩配色（與手機版一致）、系統字體、中文標籤；`CpPanel` 的樣式只套用在面板本身（`QFrame#cppanel`），不再讓每個 QLabel 外面多一個框（QLabel 也是 QFrame）。總覽的銀行/目標清單依內容長高、股票清單只保留水平捲動並依內容設定高度，**只剩最外層一個垂直捲軸**（不再是固定高度加內層捲軸）。股票摘要與交易記錄視窗會顯示年化報酬；預算視窗可選「每個月 / 只有這個月」。

### 測試

```powershell
python -m unittest discover tests -v
```

- `tests/test_backup.py`：備份輪替（每日一份、保留 30、pre-restore 標籤、原子寫入）。測試用暫存目錄，不會碰真實資料。
- `tests/test_loans.py`：貸款攤還表（已知值、168 組設定的不變量：本金合計＝總額/餘額歸零/餘額單調遞減、零利率、本金平均、寬限期、月底截斷、單期、無效輸入含空白欄位的提示）、依日期算已繳期數與進度、已繳期數覆寫、結清、利息統計、混合負債餘額與淨值、貸款還款規則（建立、到期入帳、`end` 停止、更新不重複入帳、停用保留記錄、不適用的貸款不建規則）。PWA 版逐案在瀏覽器對照驗證過。
- `tests/test_vectors.py` + `tests/js/*.test.mjs`：Python 與 PWA 共用的標準答案（貸款、交易、年化報酬、預算、固定收支、目標預測…）、三方合併、搜尋、報價解析、定期定額提醒、Worker。
- `tests/test_trades.py`：買進（首買、平均成本、費用計入、沿用舊持股）、賣出（部分、賠錢、賣光、賣太多被拒且資料不變）、輸入驗證、小數股、股利、損益摘要與端到端。PWA 版的同一批案例在瀏覽器逐項對照驗證過。
- `tests/test_secret.py`：DPAPI 加解密（含中文、毀損/他機 blob）、明文密碼自動升級、換電腦需重新輸入密碼、股票代號正規化、舊資料（沒有 `type`、沒有 `.TW`）載入補齊。DPAPI 相關測試只在 Windows 執行。
- `tests/test_recurring.py`：固定收支（到期、未到期、冪等、刪除不重生、回補與上限、31 日、跨年、兩端不重複）、淨值計算、預算統計、存錢速度與目標預測。PWA 的 `applyRecurring` / `budgetStatus` / `goalProjection` 是同一套規則的 JS 版，修改時兩邊要一起改。

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
| 字型 | 系統字體（`system-ui` + Noto Sans TC / PingFang TC / 微軟正黑體），數字用 `tabular-nums`。**不再載入 Google Fonts**（離線也一致）。先前的 Orbitron 把「D」畫得像「0」，「7D」被看成「70」 |
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
| `docs/sw.js` | Service Worker（app shell network-first、CDN/字型 cache-first；快取版本 `wm-v4`） |
| `docs/icon-192.png` | PWA 圖示 192×192 |
| `docs/icon-512.png` | PWA 圖示 512×512 |

手機瀏覽器可將網頁版「加入主畫面」作為 PWA 安裝，支援離線讀取快取內容。

**檔案組成與測試**：網頁版拆成 `index.html`（版面與畫面程式）、`app.css`（樣式）、`logic.js`（純邏輯：貸款、交易、年化報酬、預算、固定收支、三方合併、搜尋、報價解析…，全部以參數傳入、不碰 DOM）。`logic.js` 與桌面版 `core/calc.py`、`core/recurring.py` 是**同一套規則的兩份實作**，用同一份 `tests/vectors.json` 保證一致：

```powershell
python tests/gen_vectors.py              # 改了 Python 規則後重新產生標準答案（只有這時需要）
python -m unittest discover tests -v     # Python：單元測試 + 對照向量（向量過期會失敗）
node --test "tests/js/*.test.mjs"        # JS：logic.js 對照同一份向量 + 三方合併 + Worker
```

修改規則的流程：先改 Python → `gen_vectors.py` → 讓 JS 測試通過。之前「兩邊各寫一份、只能靠手動對照」的問題現在由測試擋住（開發過程中向量就抓到過平手排序不一致）。

**自動合併（三方合併）**：存檔時發現雲端已被其他裝置更新，不再直接二選一，而是用「上次同步的資料（`_baseData`）／這裡的修改／雲端最新」做三方合併（`WMLogic.threeWayMerge`）：
- 記帳按月份合併：兩邊各自新增的都保留、一邊刪除的不會復活；兩邊各新增一筆完全相同的記錄兩筆都留（可能真的買了兩杯咖啡）。
- 交易與股利依 `id` 取聯集；自動產生的固定收支依 `rec`（規則 id）＋日期去重，規則的 `generated` 取聯集（兩邊同一天各自開一次不會重複入帳）；淨值走勢依日期取聯集。
- 其他欄位逐欄位比較：只有一邊改就採用那邊；物件（例如預算）逐項合併；**兩邊改了同一個欄位成不同值才算衝突**，這時才跳確認並列出衝突的欄位名稱（沿用「覆蓋雲端／載入雲端」二選一）。
- 合併後復原快照會清空（舊快照會把別台新增的東西刪掉）。桌面版沒有做合併：桌面版每次存檔立即推送、5 分鐘拉一次，衝突機率低，維持原本的啟動衝突對話框。

**股價與持股頁（手機）**：瀏覽器直接抓 Yahoo 會被 CORS 擋下，所以要自己部署一個 Cloudflare Worker 當代理（`worker/`，只轉發公開股價、只接受你的 GitHub Pages 呼叫、快取 60 秒）。**這個 Worker 還沒部署，需要你用自己的 Cloudflare 帳號部署**（步驟見 `worker/README.md`），再到 PWA「設定」貼上網址並「測試連線」。設好之後：
- 每分鐘（前景時）更新報價；價格只存在記憶體，**存檔時才寫進 `last_price`**，所以更新報價本身不會觸發同步、也不會和電腦版互相覆蓋。總資產、損益、淨值走勢都會用最新價。
- 「持股」分頁：績效摘要（未實現／已實現／股利／總報酬／年化報酬）＋每檔持股卡（現價、今日漲跌、損益、均價、佔比）。沒設代理時顯示電腦版最後更新的價格並提示去設定。失敗時沿用最後一次的價格。
- 沒有盤中走勢圖（需要 intraday K 棒，代理沒做）。

**年化報酬（XIRR）**：以交易與股利為現金流、目前市值為期末價值，二分法解 `Σ金額/(1+r)^(天數/365)=0`。**只計入「帳本能完整解釋目前持股」的股票**（買進 − 賣出 = 目前股數）：在交易功能之前建立的期初持股沒有買進日期，算出來會誤導，所以排除並註明；沒有報價的也排除；投資期間不到 30 天不顯示年化。桌面版 `calc.portfolio_xirr`、PWA `portfolioXirr`。

**按月預算**：`budgets_by_month[月份]` 覆寫該月的預算（`budget_limits`）。預算視窗選「每個月」改預設、選「只有這個月」只存差異（`month_budget_override`，兩邊共用向量）；改回和預設相同就會移除覆寫。

**其他 PWA 功能**：
- **設定**（標題列「設定」）：股價代理網址（含測試連線）、每月定期定額提醒、匯出備份（完整 JSON 下載）、匯入備份（覆蓋資料，可復原）、復原上一步。
- **定期定額提醒**：到提醒日起、本月還沒提醒過就跳（`dcaDue`；比桌面版「只有提醒日當天」不易漏，桌面版提醒後會寫 `last_reminded`，兩邊不會重複提醒）。
- **復原**：刪除銀行/股票/目標/負債/貸款/記帳/固定收支/交易前先留快照，toast 上有「復原」鈕（10 步）。
- **搜尋/篩選記帳**：搜尋分類、備註、金額、日期（空白分隔多個關鍵字都要符合），跨所有月份；可只看收入或支出。
- **交易日期/備註可編輯**（股數、價格、費用不可改，會影響持股與損益；記錯請刪除重記）。
- **圖表**：新增「本月支出分類」圓餅與「近 12 個月已實現損益與股利」長條。
- **開啟時補快照**：每天第一次開啟若還沒有今天的走勢紀錄就補一筆（沒開電腦的日子也有資料）。**仍然做不到「電腦和手機都沒開的日子」自動記錄**——那需要雲端排程（要你的帳號），這次沒做。

**介面風格**：沉穩深色（藍灰底、單一藍色主色，綠＝收入/上漲、紅＝支出/下跌），不再有霓虹發光、漸層、紫粉色、表情符號圖示；所有標籤改為中文（近7天 / 近30天 / 今年、收入 / 支出 / 淨額、銀行帳戶、負債與貸款…）。底部導覽用單色線條圖示。

**原生感（`docs/index.html` 的「原生感」區塊；做法移植自 CyberMind / TaiexRider）**：
- **不彈出帳密自動填入**：Chrome 看到頁面上有 `type=password` 欄位時，會把同頁其他欄位（金額）當成帳號欄位而彈出「自動填入帳號密碼」。修法：PIN 欄位改成 `type=text inputmode=numeric` + CSS `-webkit-text-security: disc`（不是 password 型）；登入的 email / 密碼欄位只在登入畫面啟用（`showScreen` 切換 `disabled`）；其餘所有欄位 `autocomplete=off` 並加上 LastPass / 1Password / Bitwarden 的忽略屬性，動態產生的欄位在 `focusin` 時補上。
- **返回鍵「history 哨兵」**：進場放一個哨兵，第一次點擊後再補一個（Chrome 會略過沒有使用者互動時建立的項目）。返回鍵逐層處理：有開著的視窗 → 先關最上層；不在總覽 → 回總覽；總覽 → 提示「再按一次返回鍵離開」，2 秒內再按才真的離開。鎖定畫面/登入畫面同樣需要連按兩次。
- **沉浸式全螢幕**：`manifest.json` 的 `display: fullscreen`（`viewport-fit=cover` + safe-area padding 已有）。**manifest 的 `display` 在「安裝當下」就鎖定，之後修改不會套用到已安裝的 App——必須解除安裝再重新「加入主畫面」**（CyberMind 實測的結論）。另外在瀏覽器分頁或 standalone 模式下，每次點擊會嘗試 `requestFullscreen()` 作為備援。
- 其他：`overscroll-behavior: none`（不下拉重新整理）、不選取文字、不跳長按選單（輸入欄位除外）。

**介面結構（底部導覽）**：

| 位置 | 內容 |
|---|---|
| 🏠 總覽 | 淨值＋變化（7D / 30D / YTD，取自 `history`）→ 本月收支卡（收入/支出/淨額、上月支出對照、緊急預備金可撐月數、支出分類前 5 名長條）→ 銀行 → 現金 → 負債 → 股票 → 目標 |
| 🧾 記帳 | 月收支 / 年總覽、CSV 匯出、⟳ 固定收支（規則管理） |
| ＋（中間浮動鈕） | 快速記帳：支出/收入切換 → 金額（數字鍵盤）→ 分類 chips → 日期 → 備註 |
| 📊 圖表 | 淨值走勢（30D/90D/1Y/ALL）、資產配置圓餅、近 6 月收支長條（Chart.js，切到分頁時才繪製，避免隱藏狀態量不到尺寸） |

- **分類 chips**：預設清單與桌面版 `dialogs.py` 的 `INCOME_CATS` / `EXPENSE_CATS` 相同；資料裡實際用過的分類依次數排在前面，最多 12 個，也可自行輸入。兩端資料格式沒變，桌面版看得到手機新增的分類。
- **走勢資料**：桌面版每天記 `history`；PWA 在每天第一次存檔時 `recordHistoryToday()` 補上當天（`history` / `history_bank` / `history_cash` / `history_stock`），當天已有就不動，所以不會蓋掉桌面版較準的即時股價結果。
- 編輯記錄時把日期改到別的月份，會從舊月份移除並放進新月份（先前會留在舊月份 key 下，日期卻對不上）。
- Service Worker 快取版本 `wm-v4`。

**Cashflow 檢視**：月收支（明細清單）/ 年總覽（12 個月收入/支出/淨額表格 + 全年合計，與桌面版對齊）可切換。

**股票代號**：新增時純數字（`2330`、`0050`、`00981A`）自動補 `.TW`（Yahoo Finance 台股一定要有後綴），上櫃要自己輸入 `.TWO`；載入舊資料時兩端也會把沒有後綴的台股代號補齊（`_normalize_legacy` / `normalizeLegacy`），同時補上沒有 `type` 的舊現金流記錄（正負號決定收支、金額取絕對值）。

**股票顯示**：預設只用電腦版寫入的 `last_price`；設定股價代理後可在手機更新即時報價（見上方「股價與持股頁」）。

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
選用欄位（Auth 模式）：`email`，以及 `password`（明文，首次讀取後自動改成 `password_dpapi`，見上方「設定檔：wm_cloud.json」）

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
