"""
recurring.py - 固定收支（每月自動入帳），純函式，不依賴 Qt

規則存在 data["recurring"]：
    {
      "id": "r_1a2b3c4d",
      "type": "收入" | "支出",
      "category": "房租",
      "amount": 12000,
      "day": 5,                  # 每月幾號；31 在小月自動落在月底
      "note": "",
      "active": true,
      "start": "2026-10",        # 從這個月開始產生
      "generated": ["2026-10"]   # 已產生過的月份，刪除當月記錄後不會被重新產生
    }

產生的記錄是一般的 cashflow 記錄，多一個 "rec": <規則 id> 欄位。
桌面版與 PWA 各自實作同一套邏輯（PWA 在 docs/index.html 的 applyRecurring）；
兩邊都用 generated 判斷，所以同一份資料被兩端各開一次也不會重複入帳。
"""
import calendar
import uuid
from datetime import date

MAX_BACKFILL_MONTHS = 12   # 太久沒開（或規則重新啟用）時最多往前補幾個月


def new_rule_id() -> str:
    return "r_" + uuid.uuid4().hex[:8]


def _month_index(y: int, m: int) -> int:
    return y * 12 + (m - 1)


def _valid(rule: dict) -> bool:
    try:
        return (
            rule.get("type") in ("收入", "支出")
            and float(rule.get("amount", 0)) > 0
            and 1 <= int(rule.get("day", 0)) <= 31
            and bool(rule.get("id"))
        )
    except (TypeError, ValueError):
        return False


LOAN_CATEGORY = "貸款還款"


def loan_rule_eligible(loan: dict) -> bool:
    """每月還款金額固定才適合自動記帳：本息平均攤還且沒有寬限期。"""
    return loan.get("method", "annuity") == "annuity" and int(loan.get("grace", 0) or 0) == 0


def set_loan_rule(data: dict, loan: dict, enabled: bool):
    """建立 / 更新 / 移除與貸款綁定的固定收支規則（規則的 loan 欄位 = 貸款 id）。

    更新時沿用舊規則的 generated，避免把已入帳的月份重複入帳。
    """
    from wealthmatrix.core.calc import loan_schedule     # 避免循環 import
    rules = data.setdefault("recurring", [])
    old = next((r for r in rules if r.get("loan") == loan.get("id")), None)
    if old is not None:
        rules.remove(old)
    rows = loan_schedule(loan)
    if not (enabled and rows and loan_rule_eligible(loan)):
        return None
    rule = {
        "id": (old or {}).get("id") or new_rule_id(),
        "type": "支出", "category": LOAN_CATEGORY, "amount": rows[0]["payment"],
        "day": int(loan["start"][8:10]), "note": loan.get("name", ""), "active": True,
        "start": loan["start"][:7], "end": rows[-1]["date"][:7],
        "generated": list((old or {}).get("generated", [])), "loan": loan["id"],
    }
    rules.append(rule)
    return rule


def apply_recurring(data: dict, today: date = None) -> int:
    """把到期的固定收支寫進 cashflow_monthly，回傳新增筆數。"""
    today = today or date.today()
    now_idx = _month_index(today.year, today.month)
    added = 0

    for rule in data.get("recurring", []):
        if not rule.get("active", True) or not _valid(rule):
            continue
        try:
            sy, sm = int(rule["start"][:4]), int(rule["start"][5:7])
        except (KeyError, TypeError, ValueError):
            sy, sm = today.year, today.month
        first = max(_month_index(sy, sm), now_idx - (MAX_BACKFILL_MONTHS - 1))
        last = now_idx
        try:                                          # 選填 end（YYYY-MM）：最後一個要產生的月份，貸款還完就停
            last = min(last, _month_index(int(rule["end"][:4]), int(rule["end"][5:7])))
        except (KeyError, TypeError, ValueError):
            pass
        generated = rule.setdefault("generated", [])

        for idx in range(first, last + 1):
            y, m = divmod(idx, 12)
            m += 1
            key = f"{y:04d}-{m:02d}"
            day = min(int(rule["day"]), calendar.monthrange(y, m)[1])
            due = date(y, m, day)
            if due > today or key in generated:
                continue
            data.setdefault("cashflow_monthly", {}).setdefault(key, []).append({
                "date":     due.isoformat(),
                "type":     rule["type"],
                "category": rule.get("category", ""),
                "amount":   float(rule["amount"]),
                "note":     rule.get("note", ""),
                "rec":      rule["id"],
            })
            generated.append(key)
            added += 1
    return added
