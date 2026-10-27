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
