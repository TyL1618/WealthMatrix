# 股價代理（Cloudflare Worker）

手機瀏覽器直接抓 Yahoo Finance 會被 CORS 擋下，所以 PWA 需要一個「代理」幫它抓股價。這個 Worker 就是那個代理：
**只轉發公開股價，不碰你的任何財務資料**；只接受來自你的 GitHub Pages 的呼叫；結果快取 60 秒。

> 這個資料夾**不會自動部署**。部署要用你自己的 Cloudflare 帳號，由你執行下面的指令。

## 部署（約 3 分鐘，免費方案就夠）

```bash
cd worker
npx wrangler login          # 第一次會開瀏覽器登入 Cloudflare
npx wrangler deploy
```

完成後會印出網址，例如 `https://wealthmatrix-quotes.<你的帳號>.workers.dev`。

## 在 PWA 設定

手機開 WealthMatrix → 右上角「設定」→ 把網址貼到「股價代理網址」→「測試連線」→ 儲存。
設定會存在雲端資料裡，電腦版不受影響。之後「持股」頁會顯示即時報價與今日漲跌，總資產與損益也會用最新價格計算。

## 允許其他來源（例如本機測試）

`wrangler.jsonc` 的 `ALLOWED_ORIGINS`（逗號分隔）。改完重新 `npx wrangler deploy`。

## 本機測試

```bash
cd worker
npx wrangler dev            # http://localhost:8787
curl "http://localhost:8787/quote?symbols=0050.TW,AAPL"
```

## API

`GET /quote?symbols=0050.TW,2330.TW,AAPL`

```json
{ "fx": 31.5,
  "quotes": { "0050.TW": { "price": 185.2, "prevClose": 184.1, "currency": "TWD", "state": "REGULAR", "time": 1761552000 } },
  "at": 1761552012345 }
```

- 台股代號要有後綴：上市 `.TW`、上櫃 `.TWO`（PWA 新增持股時數字代號會自動補 `.TW`）。
- `fx`（USD/TWD）只有在查詢到美元計價的股票時才會附上。
- 查不到的代號不會出現在 `quotes` 裡。

## 限制

- Yahoo Finance 是非官方來源，偶爾會限流或改格式；失敗時 PWA 會沿用最後一次的價格。
- 免費方案每天 10 萬次請求，PWA 每 60 秒更新一次，用不完。
