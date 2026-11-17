# WealthMatrix

個人財富管理工具：桌面版（PyQt6）+ 網頁版 PWA（`docs/`，純 HTML/JS，GitHub Pages），資料經 Supabase 雲端同步，含股價報價（Yahoo，經 `worker/` Cloudflare Worker）、貸款、固定收支、持股損益。**財務資料敏感。**

## 怎麼跑
- 一律用專案 `.venv`（`setup_env.bat` 以 `py -3.14` 建立，照釘死的 `requirements.txt` 安裝）。
- 桌面版：`.venv\Scripts\python.exe main.py`（雲端設定檔 `wm_cloud.json` 放在 `%APPDATA%\WealthMatrix\`，不在 repo）。
- 網頁版：`docs/index.html`（`app.css`、`logic.js`、`sw.js`），無 build 工具。
- 在這個環境執行 bat 要寫 `.\xxx.bat`。

## 怎麼測 / 打包
- Python 單元測試（已驗證，89 項全過、不碰真實資料）：`.venv\Scripts\python.exe -m unittest discover tests -v`。
- JS 測試（已驗證，41 項全過）：`node --test "tests/js/*.test.mjs"`（`logic.js` 對照同一份向量 + 三方合併 + Worker）。
- 改了 Python 的計算規則要先 `python tests\gen_vectors.py` 重產標準答案（向量過期測試會失敗），Python 與 JS 兩邊都要綠。
- 打包：`.\build_exe.bat`（`setup_env` → `pyinstaller WealthMatrix.spec --noconfirm --clean`）→ `dist\WealthMatrix.exe`（onefile、`console=False`）。
- 圖示：`python scripts\make_icon.py`（只用 PyQt6），一次產生 `icon.ico` 與 `docs/` 的 PNG。

## 地雷 / 刻意不做
- **絕不讀取、貼出、提交**：`%AppData%\WealthMatrix\` 底下的 `wm_cloud.json`、`wm_config.json`、本地資料與備份、任何 Supabase 連線資訊 / 密碼 / token。測試用假資料與暫存目錄。
- 同步安全旗標：`_cloud_push_allowed=False` 時禁止推送、本地筆數 < 雲端 50% 拒絕推送（防舊電腦/空資料覆蓋雲端）；衝突檢測看 `_updated` 與筆數。不要繞過。
- `self.data` 是被 Dashboard / Cashflow / Holdings 共同持有的同一個 dict：替換整份資料一律 `WealthMatrix._replace_data(new)`（就地 clear + update），**不可寫 `self.data = new`**。
- 貸款/交易/報酬等標準答案**Python 與 PWA（`logic.js`）要保持一致**，共用 `tests/vectors.json`；改一邊就要同步另一邊與向量。
- 密碼在本機以 Windows DPAPI 保存（`core/secret.py`），換電腦要重新輸入；別改成明文或把密碼寫進 repo。
- DPI 縮放用 `S()`；用環境變數 `QT_AUTO_SCREEN_SCALE_FACTOR=0` / `QT_SCALE_FACTOR=1` 避免雙重縮放。
- 網頁版字體刻意不載入 Google Fonts（離線一致、避免 Orbitron 把 D 畫得像 0）。
- 新 `import` 第三方套件要同步補進 `requirements.txt`（`==` 釘死）。

## DEVDOC 索引（`DEVDOC.md`，目錄 12 節）
- 專案概述｜目錄結構｜依賴套件｜架構說明（資料流、參照規則、安全旗標、DPI）｜資料結構｜本地儲存（每日輪替備份、舊版遷移）｜雲端同步（資料表、RLS、認證、衝突檢測）
- 桌面版模組說明（含測試清單）｜網頁版（含 PWA、Worker）｜打包｜開發環境設定｜設定檔說明｜打包環境（setup_env）｜圖示
