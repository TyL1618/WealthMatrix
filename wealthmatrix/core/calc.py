"""
calc.py - 資產 / 負債 / 淨值計算（純函式，不依賴 Qt，桌面各處共用）

淨值 = 銀行 + 現金 + 股票市值 - 負債
股票沒有即時報價時以成本價估算（與 PWA 的 stockTotal 行為一致）。

預算與目標預測也在這裡；PWA（docs/index.html）有同一套邏輯的 JS 版，修改時兩邊要一起改。
"""
import math
import re


# ── 股票代號 ──────────────────────────────────────────────────────────
_TW_BARE_TICKER = re.compile(r"^\d{4,6}[A-Z]?$")


def normalize_ticker(ticker: str) -> str:
    """去空白、轉大寫；純數字的台股代號（2330、0050、00981A）補上 .TW。

    Yahoo Finance 的台股代號一定要有後綴，沒有後綴會一直抓不到報價。
    上櫃股票是 .TWO，無法由代號判斷，需自行輸入 .TWO（有後綴的一律不動）。
    PWA 有同樣邏輯（normalizeTicker），修改時兩邊要一起改。
    """
    t = (ticker or "").strip().upper()
    return t + ".TW" if _TW_BARE_TICKER.match(t) else t


def bank_total(data: dict) -> float:
    return sum(b.get("amount", 0) for b in data.get("banks", []))


def liabilities_total(data: dict) -> float:
    return sum(x.get("amount", 0) for x in data.get("liabilities", []))


def stocks_total(data: dict, prices: dict) -> float:
    return sum(
        prices.get(s["ticker"], s.get("cost", 0)) * s["shares"]
        for s in data.get("stocks", [])
    )


def assets_total(data: dict, prices: dict) -> float:
    return bank_total(data) + data.get("cash", 0) + stocks_total(data, prices)


def net_worth(data: dict, prices: dict) -> float:
    return assets_total(data, prices) - liabilities_total(data)


# ── 投資：交易記錄 / 股利 / 損益摘要 ──────────────────────────────────
#
# data["transactions"]：{id, date, ticker, side: "buy"|"sell", shares, price, fee, note, realized?}
# data["dividends"]   ：{id, date, ticker, amount, note}
#
# 買賣會依「平均成本法」同步更新 data["stocks"]（shares / cost / holding_cost）；賣出時把
# 已實現損益存在該筆交易的 realized。不會動銀行或現金餘額（請自行維護，避免重複計算）。
# 刪除交易紀錄只移除紀錄，不會回頭調整持股。
# PWA 有同一套邏輯（applyTrade / portfolioSummary），修改時兩邊要一起改。
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def find_stock(data: dict, ticker: str):
    t = normalize_ticker(ticker)
    for s in data.get("stocks", []):
        if normalize_ticker(s.get("ticker", "")) == t:
            return s
    return None


def apply_trade(data: dict, trade: dict):
    """套用一筆買賣：更新持股、寫入交易記錄。成功回傳 None，失敗回傳錯誤訊息（資料不變）。"""
    ticker = normalize_ticker(trade.get("ticker", ""))
    side   = trade.get("side")
    try:
        shares = float(trade.get("shares", 0))
        price  = float(trade.get("price", 0))
        fee    = float(trade.get("fee", 0) or 0)
    except (TypeError, ValueError):
        return "數字格式錯誤"
    if not ticker:
        return "請輸入股票代號"
    if side not in ("buy", "sell"):
        return "類型必須是買進或賣出"
    if not _DATE_RE.match(trade.get("date", "")):
        return "日期格式必須是 YYYY-MM-DD"
    if shares <= 0:
        return "股數必須大於 0"
    if price < 0 or fee < 0:
        return "價格與費用不可為負"

    stocks = data.setdefault("stocks", [])
    stock  = find_stock(data, ticker)
    rec = {
        "id": trade.get("id") or new_id("t"), "date": trade["date"], "ticker": ticker,
        "side": side, "shares": shares, "price": price, "fee": fee,
        "note": (trade.get("note") or "").strip(),
    }

    if side == "buy":
        cost_now = shares * price + fee
        if stock is None:
            stock = {"ticker": ticker, "shares": 0, "cost": 0, "holding_cost": 0}
            stocks.append(stock)
        holding = stock.get("holding_cost")
        if holding is None:
            holding = stock.get("cost", 0) * stock.get("shares", 0)
        new_shares = stock.get("shares", 0) + shares
        new_holding = holding + cost_now
        stock["shares"]       = new_shares
        stock["holding_cost"] = round(new_holding, 2)
        stock["cost"]         = round(new_holding / new_shares, 4)
    else:
        if stock is None or stock.get("shares", 0) + 1e-9 < shares:
            have = stock.get("shares", 0) if stock else 0
            return f"持股不足：{ticker} 目前只有 {have:g} 股"
        holding = stock.get("holding_cost")
        if holding is None:
            holding = stock.get("cost", 0) * stock.get("shares", 0)
        avg = holding / stock["shares"] if stock["shares"] else 0
        rec["realized"] = round(shares * price - fee - avg * shares, 2)
        remain = stock["shares"] - shares
        if remain <= 1e-9:
            stocks.remove(stock)                         # 全部賣光：從持股移除，損益留在交易記錄
        else:
            stock["shares"]       = remain
            stock["holding_cost"] = round(holding - avg * shares, 2)
            stock["cost"]         = round(avg, 4)        # 賣出不改變均價

    data.setdefault("transactions", []).append(rec)
    return None


def add_dividend(data: dict, div: dict):
    ticker = normalize_ticker(div.get("ticker", ""))
    try:
        amount = float(div.get("amount", 0))
    except (TypeError, ValueError):
        return "金額格式錯誤"
    if not ticker:
        return "請輸入股票代號"
    if not _DATE_RE.match(div.get("date", "")):
        return "日期格式必須是 YYYY-MM-DD"
    if amount <= 0:
        return "股利金額必須大於 0"
    data.setdefault("dividends", []).append({
        "id": div.get("id") or new_id("d"), "date": div["date"], "ticker": ticker,
        "amount": amount, "note": (div.get("note") or "").strip(),
    })
    return None


def portfolio_summary(data: dict, prices: dict, year: int) -> dict:
    """未實現損益（有報價的持股）、已實現損益、股利，以及三者合計的總報酬。

    報價優先用 prices（即時），沒有就用 stock["last_price"]；兩者都沒有的持股不計入未實現。
    """
    unrealized, priced = 0.0, 0
    for s in data.get("stocks", []):
        price = prices.get(s.get("ticker"), s.get("last_price"))
        if price is None:
            continue
        holding = s.get("holding_cost")
        if holding is None:
            holding = s.get("cost", 0) * s.get("shares", 0)
        unrealized += price * s.get("shares", 0) - holding
        priced += 1

    y = str(year)
    realized = [t for t in data.get("transactions", []) if t.get("side") == "sell"]
    r_total = sum(t.get("realized", 0) for t in realized)
    r_year  = sum(t.get("realized", 0) for t in realized if t.get("date", "").startswith(y))
    d_all   = data.get("dividends", [])
    d_total = sum(d.get("amount", 0) for d in d_all)
    d_year  = sum(d.get("amount", 0) for d in d_all if d.get("date", "").startswith(y))
    return {
        "unrealized": unrealized, "priced": priced,
        "realized_total": r_total, "realized_year": r_year,
        "dividends_total": d_total, "dividends_year": d_year,
        "total_return": unrealized + r_total + d_total,
    }


# ── 預算 ──────────────────────────────────────────────────────────────
# 這些支出分類是「把錢轉成資產」，不算花掉：不列入存錢速度的支出，也不適合設預算。
SAVING_CATEGORIES = ("投資買入",)


def is_income(rec: dict) -> bool:
    """有 type 看 type；舊資料沒有 type 時看金額正負（正 = 收入，負 = 支出）。"""
    t = rec.get("type")
    if t in ("收入", "支出"):
        return t == "收入"
    return rec.get("amount", 0) >= 0


def rec_type(rec: dict) -> str:
    return "收入" if is_income(rec) else "支出"


def expense_by_category(data: dict, key: str) -> dict:
    """某月（'YYYY-MM'）各分類的支出合計。"""
    sums = {}
    for r in data.get("cashflow_monthly", {}).get(key, []):
        if is_income(r):
            continue
        cat = r.get("category") or "其他"
        sums[cat] = sums.get(cat, 0) + abs(r.get("amount", 0))
    return sums


def budget_status(data: dict, key: str) -> list:
    """有設預算的分類：[{category, limit, spent, ratio}]，用掉比例高的在前。"""
    spent = expense_by_category(data, key)
    rows = []
    for cat, limit in (data.get("budgets") or {}).items():
        try:
            limit = float(limit)
        except (TypeError, ValueError):
            continue
        if limit <= 0:
            continue
        s = spent.get(cat, 0)
        rows.append({"category": cat, "limit": limit, "spent": s, "ratio": s / limit})
    return sorted(rows, key=lambda x: x["ratio"], reverse=True)


# ── 目標達成預測 ──────────────────────────────────────────────────────
def _month_idx(y: int, m: int) -> int:
    return y * 12 + (m - 1)


def _idx_to_ym(idx: int) -> str:
    y, m = divmod(idx, 12)
    return f"{y:04d}-{m + 1:02d}"


def monthly_saving(data: dict, today, n: int = 3):
    """最近 n 個「完整月份」（不含本月、且有記錄）的平均每月存下金額。

    存下 = 收入 − 支出，但「投資買入」不算支出（它變成資產，淨值沒有減少）。
    沒有任何完整月份的記錄時回傳 None。
    """
    cur = _month_idx(today.year, today.month)
    vals = []
    for off in range(1, n + 1):
        key = _idx_to_ym(cur - off)
        recs = data.get("cashflow_monthly", {}).get(key, [])
        if not recs:
            continue
        income = sum(abs(r.get("amount", 0)) for r in recs if is_income(r))
        spent = sum(abs(r.get("amount", 0)) for r in recs
                    if not is_income(r) and r.get("category") not in SAVING_CATEGORIES)
        vals.append(income - spent)
    return sum(vals) / len(vals) if vals else None


def goal_projection(goal: dict, net_worth_now: float, saving, today) -> dict:
    """目標進度預測。

    remaining       還差多少（>=0）
    done            已達成
    months_left     距離期限還有幾個月（沒設期限為 None；逾期為 0）
    need_per_month  期限內每月要存多少（沒設期限為 None）
    eta_months/eta  依 saving（平均每月存下）估計還要幾個月 / 約哪個月達成（saving<=0 或 None 為 None）
    late            設了期限，且依目前速度會晚於期限（或根本達不到）
    """
    remaining = max(0.0, float(goal.get("target", 0)) - net_worth_now)
    out = {"remaining": remaining, "done": remaining <= 0, "months_left": None,
           "need_per_month": None, "eta_months": None, "eta": None, "late": False}
    if out["done"]:
        return out

    cur = _month_idx(today.year, today.month)
    deadline = goal.get("deadline") or ""
    try:
        dl_idx = _month_idx(int(deadline[:4]), int(deadline[5:7]))
        if not 1 <= int(deadline[5:7]) <= 12:
            raise ValueError
    except (ValueError, TypeError):
        dl_idx = None

    if dl_idx is not None:
        out["months_left"] = max(0, dl_idx - cur)
        out["need_per_month"] = remaining / max(1, out["months_left"])

    if saving is not None and saving > 0:
        out["eta_months"] = math.ceil(remaining / saving)
        out["eta"] = _idx_to_ym(cur + out["eta_months"])

    if dl_idx is not None:
        out["late"] = out["eta_months"] is None or cur + out["eta_months"] > dl_idx
    return out
