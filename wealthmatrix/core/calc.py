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


# ── 分期貸款 ──────────────────────────────────────────────────────────
#
# data["liabilities"] 的項目有兩種：
#   一般負債（信用卡等）：{name, amount}，餘額就是 amount，自己手動更新。
#   分期貸款：{name, type:"loan", principal, rate, term, grace, start, method, paid_override?, id, amount}
#     principal 貸款總額；rate 年利率 %；term 總期數（月，含寬限期）；grace 寬限期（只繳利息的月數）；
#     start 首期繳款日 YYYY-MM-DD（之後每月同一天，31 日在小月落在月底）；
#     method "annuity" 本息平均攤還 / "equal_principal" 本金平均攤還；
#     paid_override 已繳期數手動覆寫（選填，預設依日期自動算）；
#     amount = 目前本金餘額（由程式同步，給舊版程式讀；計算一律用 liability_balance）。
# 不處理提前還款；與實際不符時用 paid_override 校正已繳期數。
# PWA 有同一套邏輯（loanSchedule / loanStatus / liabBalance），修改時兩邊要一起改。
LOAN_METHODS = ("annuity", "equal_principal")


def _rnd(x: float) -> int:
    return math.floor(x + 0.5)            # 與 JS 的 Math.floor(x + 0.5) 一致（正數四捨五入）


def _parse_date(s):
    from datetime import date
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        return None


def _add_months(d, k: int):
    import calendar
    from datetime import date
    idx = d.year * 12 + (d.month - 1) + k
    y, m = divmod(idx, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def validate_loan(loan: dict):
    """合法回傳 None，否則回傳錯誤訊息。"""
    for key, msg in (("principal", "請輸入貸款總額"), ("rate", "請輸入年利率"), ("term", "請輸入總期數")):
        if loan.get(key) in (None, ""):
            return msg
    try:
        principal, rate = float(loan.get("principal", 0)), float(loan.get("rate", 0))
        term, grace = int(loan.get("term", 0)), int(loan.get("grace", 0) or 0)
    except (TypeError, ValueError):
        return "數字格式錯誤"
    if principal <= 0:
        return "貸款總額必須大於 0"
    if not 0 <= rate <= 100:
        return "年利率必須在 0～100 之間"
    if not 1 <= term <= 600:
        return "期數必須在 1～600 之間"
    if not 0 <= grace < term:
        return "寬限期必須小於總期數"
    if loan.get("method", "annuity") not in LOAN_METHODS:
        return "攤還方式不正確"
    if _parse_date(loan.get("start", "")) is None:
        return "首期繳款日格式必須是 YYYY-MM-DD"
    po = loan.get("paid_override")
    if po not in (None, ""):
        try:
            if not 0 <= int(po) <= term:
                return "已繳期數必須在 0～總期數 之間"
        except (TypeError, ValueError):
            return "已繳期數格式錯誤"
    return None


def loan_schedule(loan: dict) -> list:
    """每期明細：[{n, date, payment, interest, principal, balance}]。無效的貸款回傳 []。"""
    if validate_loan(loan):
        return []
    P, r = float(loan["principal"]), float(loan["rate"]) / 1200
    n, g = int(loan["term"]), int(loan.get("grace", 0) or 0)
    m = n - g
    method = loan.get("method", "annuity")
    start = _parse_date(loan["start"])
    if method == "annuity":
        pmt = _rnd(P / m) if r == 0 else _rnd(P * r * (1 + r) ** m / ((1 + r) ** m - 1))
    else:
        base = _rnd(P / m)

    rows, bal = [], _rnd(P)
    for i in range(1, n + 1):
        interest = _rnd(bal * r)
        if i <= g:
            prin = 0
        else:
            k = i - g
            if k == m:
                prin = bal                                     # 最後一期把尾數補齊
            elif method == "annuity":
                prin = min(bal, max(0, pmt - interest))
            else:
                prin = min(bal, base)
        bal -= prin
        rows.append({"n": i, "date": _add_months(start, i - 1).isoformat(),
                     "payment": interest + prin, "interest": interest, "principal": prin, "balance": bal})
    return rows


def loan_status(loan: dict, today=None):
    """貸款目前狀態；無效的貸款回傳 None。"""
    from datetime import date
    rows = loan_schedule(loan)
    if not rows:
        return None
    today = today or date.today()
    n, P = len(rows), _rnd(float(loan["principal"]))
    po = loan.get("paid_override")
    if po not in (None, ""):
        paid = int(po)
    else:
        paid = sum(1 for x in rows if x["date"] <= today.isoformat())
    balance = rows[paid - 1]["balance"] if paid > 0 else P
    nxt = rows[paid] if paid < n else None
    return {
        "paid": paid, "term": n, "remaining_terms": n - paid, "done": paid >= n,
        "balance": balance, "principal_paid": P - balance,
        "progress": (P - balance) / P if P else 0,
        "next_date": nxt["date"] if nxt else None,
        "next_payment": nxt["payment"] if nxt else 0,
        "monthly_payment": (nxt or rows[-1])["payment"],
        "total_interest": sum(x["interest"] for x in rows),
        "interest_paid": sum(x["interest"] for x in rows[:paid]),
        "end_date": rows[-1]["date"],
    }


def liability_balance(item: dict, today=None) -> float:
    """負債目前餘額：貸款依期數表計算，一般負債就是 amount。"""
    if item.get("type") == "loan":
        st = loan_status(item, today)
        if st is not None:
            return st["balance"]
    return item.get("amount", 0)


def refresh_loan_amounts(data: dict, today=None):
    """把貸款的 amount 同步成目前本金餘額（舊版程式只讀 amount）。"""
    for x in data.get("liabilities", []):
        if x.get("type") == "loan":
            st = loan_status(x, today)
            if st is not None:
                x["amount"] = st["balance"]


def bank_total(data: dict) -> float:
    return sum(b.get("amount", 0) for b in data.get("banks", []))


def liabilities_total(data: dict, today=None) -> float:
    return sum(liability_balance(x, today) for x in data.get("liabilities", []))


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


# ── 年化報酬（XIRR）───────────────────────────────────────────────────
def xirr(flows: list):
    """flows: [{"date": "YYYY-MM-DD", "amount": 數字}]，投入為負、收回為正。無解或資料不足回傳 None。

    用二分法解 Σ amount / (1+r)^(天數/365) = 0，結果與 PWA 的 xirr 一致。
    """
    from datetime import date as _d
    fl = [f for f in flows if f.get("amount") and _DATE_RE.match(f.get("date", ""))]
    if not any(f["amount"] < 0 for f in fl) or not any(f["amount"] > 0 for f in fl):
        return None
    ords = [_d.fromisoformat(f["date"]).toordinal() for f in fl]
    t0 = min(ords)
    yrs = [(o - t0) / 365 for o in ords]

    def npv(r):
        return sum(f["amount"] / (1 + r) ** y for f, y in zip(fl, yrs))

    try:
        lo, hi = -0.9999, 100.0
        flo, fhi = npv(lo), npv(hi)
        if flo * fhi > 0:
            return None
        for _ in range(200):
            mid = (lo + hi) / 2
            fm = npv(mid)
            if flo * fm <= 0:
                hi, fhi = mid, fm
            else:
                lo, flo = mid, fm
    except (OverflowError, ZeroDivisionError):
        return None
    return (lo + hi) / 2


def portfolio_xirr(data: dict, prices: dict, today: str, min_days: int = 30) -> dict:
    """持股的年化報酬。只計入「帳本能完整解釋目前持股」的股票（買進 − 賣出 = 目前股數）。

    回傳 {rate, included, excluded:[{ticker, reason}], start, days, flows}；rate 為 None 表示無法計算
    （沒有足夠紀錄、或投資期間不到 min_days 天——時間太短年化沒有意義）。
    """
    from datetime import date as _d
    net, holding = {}, {}
    for t in data.get("transactions", []):
        net[t["ticker"]] = net.get(t["ticker"], 0) + (t["shares"] if t["side"] == "buy" else -t["shares"])
    for s in data.get("stocks", []):
        holding[normalize_ticker(s["ticker"])] = s

    def price_of(s):
        return prices.get(s.get("ticker"), s.get("last_price"))

    included, excluded = [], []
    for tk in sorted(set(net) | set(holding)):
        s = holding.get(tk)
        have = s.get("shares", 0) if s else 0
        if abs(have - net.get(tk, 0)) > 1e-6:
            excluded.append({"ticker": tk, "reason": "缺少完整買進紀錄"})
        elif s and have > 0 and price_of(s) is None:
            excluded.append({"ticker": tk, "reason": "沒有報價"})
        else:
            included.append(tk)
    inc = set(included)
    flows = []
    for t in data.get("transactions", []):
        if t["ticker"] in inc:
            gross = t["shares"] * t["price"]
            flows.append({"date": t["date"], "amount": -(gross + t.get("fee", 0)) if t["side"] == "buy" else gross - t.get("fee", 0)})
    for d in data.get("dividends", []):
        if normalize_ticker(d["ticker"]) in inc:
            flows.append({"date": d["date"], "amount": d["amount"]})
    terminal = sum(price_of(holding[tk]) * holding[tk]["shares"] for tk in included if tk in holding and holding[tk].get("shares", 0) > 0)
    if terminal > 0:
        flows.append({"date": today, "amount": terminal})
    flows.sort(key=lambda f: f["date"])
    start = flows[0]["date"] if flows else None
    days = (_d.fromisoformat(today) - _d.fromisoformat(start)).days if start else 0
    rate = xirr(flows) if days >= min_days else None
    return {"rate": rate, "included": included, "excluded": excluded, "start": start, "days": days, "flows": len(flows)}


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


def budget_limits(data: dict, key: str) -> dict:
    """某月（'YYYY-MM'）實際生效的預算：基本預算 + 該月覆寫（budgets_by_month[key]；覆寫值 <= 0 代表該月不設預算）。"""
    out = dict(data.get("budgets") or {})
    for cat, v in ((data.get("budgets_by_month") or {}).get(key) or {}).items():
        try:
            positive = float(v) > 0
        except (TypeError, ValueError):
            positive = False
        if positive:
            out[cat] = v
        else:
            out.pop(cat, None)
    return out


def month_budget_override(base: dict, values: dict) -> dict:
    """使用者在「只有這個月」模式下輸入的各分類預算 → 要存進 budgets_by_month[月份] 的差異。

    只存和每個月預設不同的項目；填 0 / 留空而預設有預算 = 這個月不設預算（存 0）。
    """
    base = base or {}
    out = {}
    for cat, v in (values or {}).items():
        try:
            v = float(v or 0)
        except (TypeError, ValueError):
            v = 0
        try:
            b = float(base.get(cat) or 0)
        except (TypeError, ValueError):
            b = 0
        if v > 0 and v != b:
            out[cat] = v
        elif not v > 0 and b > 0:
            out[cat] = 0
    return out


def budget_status(data: dict, key: str) -> list:
    """有設預算的分類：[{category, limit, spent, ratio}]，用掉比例高的在前。"""
    spent = expense_by_category(data, key)
    rows = []
    for cat, limit in budget_limits(data, key).items():
        try:
            limit = float(limit)
        except (TypeError, ValueError):
            continue
        if limit <= 0:
            continue
        s = spent.get(cat, 0)
        rows.append({"category": cat, "limit": limit, "spent": s, "ratio": s / limit})
    return sorted(rows, key=lambda x: (-x["ratio"], x["category"]))      # 平手時依分類名稱，兩端順序一致


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
