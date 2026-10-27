"""產生 tests/vectors.json — Python 與 PWA(JS) 共用的「標準答案」。

   python tests/gen_vectors.py          重新產生（改了 calc.py / recurring.py 的規則之後）
   python -m unittest discover tests    Python 端驗證仍符合向量
   node --test tests/js                 JS 端（docs/logic.js）驗證符合同一份向量

向量的輸入是純資料，輸出由 Python 實作計算；JS 實作必須得到相同的結果。
"""
import copy
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wealthmatrix.core.calc import (  # noqa: E402
    normalize_ticker, is_income, loan_schedule, loan_status, liability_balance, validate_loan,
    apply_trade, add_dividend, portfolio_summary, xirr, portfolio_xirr,
    budget_limits, budget_status, monthly_saving, goal_projection, month_budget_override,
)
from wealthmatrix.core.recurring import apply_recurring, set_loan_rule  # noqa: E402

VECTOR_FILE = os.path.join(ROOT, "tests", "vectors.json")


def D(s):
    return date.fromisoformat(s)


def strip_ids(rules):
    return [{k: v for k, v in r.items() if k != "id"} for r in rules]


def _loan(**kw):
    base = {"id": "l_t", "name": "車貸", "type": "loan", "principal": 600000, "rate": 2.5, "term": 60,
            "grace": 0, "start": "2026-11-05", "method": "annuity"}
    base.update(kw)
    return base


def build():
    v = {}

    # ── 股票代號 / 收支類型 ──
    tickers = ["2330", " 0050 ", "00981a", "006208", "2330.TW", "6488.TWO", "aapl", "BRK-B", "123", "1234567", "", None]
    v["normalize_ticker"] = [{"in": t, "out": normalize_ticker(t)} for t in tickers]
    recs = [{"amount": 100}, {"amount": -100}, {"type": "收入", "amount": -5}, {"type": "支出", "amount": 5}, {"amount": 0}, {"type": "其他", "amount": -1}]
    v["is_income"] = [{"in": r, "out": is_income(r)} for r in recs]

    # ── 貸款 ──
    loans = [
        _loan(), _loan(principal=100000, rate=12, term=12), _loan(principal=120000, rate=0, term=12),
        _loan(principal=120000, rate=12, term=12, method="equal_principal"),
        _loan(principal=100000, rate=6, term=12, grace=3), _loan(start="2026-01-31", term=4),
        _loan(principal=5000, rate=5, term=1), _loan(principal=987654, rate=7.9, term=84, grace=3, method="equal_principal"),
        _loan(principal=987654, rate=1.88, term=84), _loan(principal=333333, rate=3.33, term=37),
        _loan(start="2024-02-29", term=26, principal=450000, rate=2.2),
    ]
    todays = ["2026-10-27", "2026-11-05", "2027-01-04", "2027-01-05", "2031-10-05", "2040-01-01"]
    v["loans"] = []
    for ln in loans:
        item = {"loan": ln, "schedule": loan_schedule(ln), "status": {t: loan_status(ln, D(t)) for t in todays},
                "balance": {t: liability_balance(ln, D(t)) for t in todays}}
        v["loans"].append(item)
    overrides = [_loan(paid_override=10), _loan(paid_override=0), _loan(paid_override=60)]
    v["loan_overrides"] = [{"loan": ln, "today": "2026-10-27", "status": loan_status(ln, D("2026-10-27"))} for ln in overrides]
    bad = [_loan(principal=0), _loan(principal=-1), _loan(rate=-1), _loan(rate=101), _loan(term=0), _loan(term=601),
           _loan(grace=60), _loan(grace=-1), _loan(method="x"), _loan(start="2026-13-01"), _loan(start=""),
           _loan(start="2026/11/05"), _loan(principal="abc"), _loan(paid_override=61), _loan(paid_override=-1),
           _loan(principal=""), _loan(rate=None), _loan(term=""), _loan(rate=0), _loan()]
    v["loan_validation"] = [{"loan": ln, "error": validate_loan(ln)} for ln in bad]

    # ── 交易 / 股利 / 摘要 ──
    def scenario(name, start, ops):
        data = copy.deepcopy(start)
        results = []
        for op in ops:
            if op["kind"] == "div":
                results.append(add_dividend(data, op["div"]))
            else:
                results.append(apply_trade(data, op["trade"]))
        return {"name": name, "start": start, "ops": ops, "errors": results, "final": data}

    def buy(i, **kw):
        t = {"id": f"t{i}", "ticker": "0050", "side": "buy", "shares": 100, "price": 150, "fee": 0, "date": "2026-01-10"}
        t.update(kw)
        return {"kind": "trade", "trade": t}

    def sell(i, **kw):
        t = {"id": f"t{i}", "ticker": "0050", "side": "sell", "shares": 50, "price": 180, "fee": 0, "date": "2026-06-10"}
        t.update(kw)
        return {"kind": "trade", "trade": t}

    v["trades"] = [
        scenario("首買含費用", {}, [buy(1, fee=20)]),
        scenario("二次買進平均成本", {}, [buy(1, price=100), buy(2, price=200, date="2026-02-01")]),
        scenario("沿用舊持股", {"stocks": [{"ticker": "0050.TW", "shares": 100, "cost": 100}]}, [buy(1, price=200)]),
        scenario("部分賣出", {}, [buy(1), sell(2, shares=40, fee=30)]),
        scenario("賠錢賣光", {}, [buy(1, shares=10, price=100), sell(2, shares=10, price=80)]),
        scenario("賣光保留損益", {}, [buy(1, price=100), sell(2, shares=100, price=110)]),
        scenario("賣太多被拒", {}, [buy(1, shares=10, price=100), sell(2, shares=11)]),
        scenario("沒持股賣出", {}, [sell(1)]),
        scenario("無效輸入", {}, [buy(1, ticker=""), buy(2, shares=0), buy(3, shares=-5), buy(4, price=-1), buy(5, fee=-1),
                                  buy(6, date="2026/01/01"), buy(7, date=""), buy(8, side="hold"), buy(9, shares="abc")]),
        scenario("小數股", {}, [buy(1, ticker="AAPL", shares=0.5, price=200), sell(2, ticker="AAPL", shares=0.5, price=300)]),
        scenario("股利", {}, [{"kind": "div", "div": {"id": "d1", "ticker": "0056", "date": "2026-07-20", "amount": 1500, "note": " Q2 "}},
                              {"kind": "div", "div": {"id": "d2", "ticker": "", "date": "2026-07-20", "amount": 1}},
                              {"kind": "div", "div": {"id": "d3", "ticker": "0056", "date": "bad", "amount": 1}},
                              {"kind": "div", "div": {"id": "d4", "ticker": "0056", "date": "2026-07-20", "amount": 0}}]),
        scenario("多檔多次", {}, [buy(1, ticker="0050", date="2026-01-05"), buy(2, ticker="2330", shares=10, price=900, date="2026-02-01"),
                                  sell(3, ticker="0050", shares=30, price=170, fee=25, date="2026-04-01"),
                                  buy(4, ticker="0050", shares=70, price=160, fee=15, date="2026-05-02"),
                                  {"kind": "div", "div": {"id": "d1", "ticker": "0050", "date": "2026-07-20", "amount": 420}}]),
    ]

    sdata = {"stocks": [{"ticker": "0050.TW", "shares": 100, "cost": 100, "holding_cost": 10000},
                        {"ticker": "AAPL", "shares": 2, "cost": 5000, "holding_cost": 10000, "last_price": 6000},
                        {"ticker": "NOPRICE", "shares": 1, "cost": 10, "holding_cost": 10}],
             "transactions": [{"side": "sell", "date": "2026-03-01", "realized": 500}, {"side": "sell", "date": "2025-12-31", "realized": -200},
                              {"side": "buy", "date": "2026-01-01"}],
             "dividends": [{"date": "2026-07-01", "amount": 300}, {"date": "2025-07-01", "amount": 100}]}
    v["summary"] = [
        {"data": sdata, "prices": {"0050.TW": 120}, "year": 2026, "out": portfolio_summary(sdata, {"0050.TW": 120}, 2026)},
        {"data": sdata, "prices": {"0050.TW": 100, "AAPL": 5000}, "year": 2026, "out": portfolio_summary(sdata, {"0050.TW": 100, "AAPL": 5000}, 2026)},
        {"data": {}, "prices": {}, "year": 2026, "out": portfolio_summary({}, {}, 2026)},
    ]

    # ── XIRR ──
    flow_sets = [
        [{"date": "2026-01-01", "amount": -1000}, {"date": "2027-01-01", "amount": 1100}],
        [{"date": "2026-01-01", "amount": -1000}, {"date": "2026-07-01", "amount": -500}, {"date": "2027-01-01", "amount": 1700}],
        [{"date": "2026-01-01", "amount": -1000}, {"date": "2026-12-31", "amount": 900}],
        [{"date": "2026-01-01", "amount": -1000}],
        [{"date": "2026-01-01", "amount": 1000}, {"date": "2026-06-01", "amount": 500}],
        [{"date": "2026-01-01", "amount": -100000}, {"date": "2026-03-15", "amount": 2500}, {"date": "2026-09-30", "amount": 3100}, {"date": "2027-04-01", "amount": 99000}],
        [],
    ]
    v["xirr"] = [{"flows": f, "out": xirr(f)} for f in flow_sets]

    def ledger(name, data, prices, today):
        return {"name": name, "data": data, "prices": prices, "today": today, "out": portfolio_xirr(data, prices, today)}

    full = {}
    apply_trade(full, {"id": "t1", "ticker": "0050", "side": "buy", "shares": 100, "price": 100, "fee": 10, "date": "2026-01-05"})
    apply_trade(full, {"id": "t2", "ticker": "0050", "side": "sell", "shares": 40, "price": 130, "fee": 20, "date": "2026-06-05"})
    add_dividend(full, {"id": "d1", "ticker": "0050", "date": "2026-07-20", "amount": 250})
    partial = copy.deepcopy(full)
    partial["stocks"].append({"ticker": "2330.TW", "shares": 10, "cost": 500, "holding_cost": 5000})   # 沒有買進紀錄
    sold_out = {}
    apply_trade(sold_out, {"id": "t1", "ticker": "AAPL", "side": "buy", "shares": 2, "price": 5000, "fee": 0, "date": "2026-01-01"})
    apply_trade(sold_out, {"id": "t2", "ticker": "AAPL", "side": "sell", "shares": 2, "price": 6000, "fee": 0, "date": "2026-10-01"})
    v["portfolio_xirr"] = [
        ledger("完整帳本", full, {"0050.TW": 125}, "2026-10-27"),
        ledger("缺買進紀錄的股票被排除", partial, {"0050.TW": 125, "2330.TW": 600}, "2026-10-27"),
        ledger("沒報價被排除", full, {}, "2026-10-27"),
        ledger("期間太短不算年化", full, {"0050.TW": 125}, "2026-01-20"),
        ledger("已全部賣出", sold_out, {}, "2026-10-27"),
        ledger("空資料", {}, {}, "2026-10-27"),
    ]

    # ── 預算（含按月覆寫）──
    bdata = {
        "budgets": {"餐飲": 5000, "交通": 0, "娛樂": 1000, "壞值": "abc"},
        "budgets_by_month": {"2026-12": {"餐飲": 8000, "娛樂": 0, "購物": 3000}, "2027-01": {"交通": 1500}},
        "cashflow_monthly": {
            "2026-10": [{"type": "支出", "category": "餐飲", "amount": 4000}, {"type": "支出", "category": "餐飲", "amount": 500},
                        {"type": "支出", "category": "娛樂", "amount": 1500}, {"type": "支出", "category": "交通", "amount": 900},
                        {"type": "收入", "category": "薪資", "amount": 65000}, {"category": "舊資料", "amount": -300}],
            "2026-12": [{"type": "支出", "category": "餐飲", "amount": 6000}, {"type": "支出", "category": "購物", "amount": 3500},
                        {"type": "支出", "category": "娛樂", "amount": 100}],
        },
    }
    v["budgets"] = [{"data": bdata, "key": k, "limits": budget_limits(bdata, k), "status": budget_status(bdata, k)}
                    for k in ["2026-10", "2026-11", "2026-12", "2027-01"]]
    v["budgets"].append({"data": {}, "key": "2026-10", "limits": budget_limits({}, "2026-10"), "status": budget_status({}, "2026-10")})

    ov_cases = [({"餐飲": 5000, "購物": 3000}, {"餐飲": 8000, "購物": 0}), ({"餐飲": 5000}, {"餐飲": 5000}),
                ({"餐飲": 5000}, {"餐飲": ""}), ({"餐飲": 5000}, {"餐飲": 0, "交通": 1500}), ({}, {"餐飲": 100}),
                ({"餐飲": 5000}, {"餐飲": "abc"}), ({"餐飲": "5000"}, {"餐飲": 5000.0}), ({}, {}), (None, {"a": 1})]
    v["budget_override"] = [{"base": b, "values": vals, "out": month_budget_override(b, vals)} for b, vals in ov_cases]

    # ── 存錢速度 / 目標 ──
    sv = {"cashflow_monthly": {
        "2026-10": [{"type": "收入", "amount": 999999}],
        "2026-09": [{"type": "收入", "amount": 60000, "category": "薪資"}, {"type": "支出", "amount": 20000, "category": "生活費"},
                    {"type": "支出", "amount": 10000, "category": "投資買入"}],
        "2026-08": [{"type": "收入", "amount": 60000, "category": "薪資"}, {"type": "支出", "amount": 30000, "category": "生活費"}]}}
    v["saving"] = [{"data": sv, "today": "2026-10-27", "out": monthly_saving(sv, D("2026-10-27"))},
                   {"data": {"cashflow_monthly": {"2026-10": [{"type": "收入", "amount": 1}]}}, "today": "2026-10-27",
                    "out": monthly_saving({"cashflow_monthly": {"2026-10": [{"type": "收入", "amount": 1}]}}, D("2026-10-27"))},
                   {"data": {}, "today": "2026-10-27", "out": monthly_saving({}, D("2026-10-27"))}]
    goals = [({"target": 100}, 150, 10), ({"target": 1000000, "deadline": "2027-06"}, 700000, 50000),
             ({"target": 1000000, "deadline": "2027-06"}, 700000, 20000), ({"target": 1000000, "deadline": "2027-06"}, 700000, None),
             ({"target": 1000000, "deadline": "2027-06"}, 700000, 0), ({"target": 1000000, "deadline": "2027-06"}, 700000, -500),
             ({"target": 1000000}, 700000, 100000), ({"target": 100, "deadline": "2026-01"}, 40, 5),
             ({"target": 100, "deadline": "abc"}, 40, 5), ({"target": 100, "deadline": "2026-13"}, 40, 5),
             ({"target": 100.5}, 0, 50), ({"target": 100.5}, 0, 0.5)]
    v["goals"] = [{"goal": g, "net_worth": nw, "saving": sv_, "today": "2026-10-27",
                   "out": goal_projection(g, nw, sv_, D("2026-10-27"))} for g, nw, sv_ in goals]

    # ── 固定收支 / 貸款還款規則 ──
    def rule(**kw):
        base = {"id": "r_test", "type": "支出", "category": "房租", "amount": 12000, "day": 5, "note": "", "active": True, "start": "2026-10"}
        base.update(kw)
        return base

    rec_cases = [
        ("到期產生", [rule()], ["2026-10-27"]), ("未到期再到期", [rule(day=28)], ["2026-10-27", "2026-10-28"]),
        ("冪等", [rule()], ["2026-10-27", "2026-10-28"]), ("回補 4 個月", [rule(start="2026-07")], ["2026-10-27"]),
        ("回補上限 12", [rule(start="2020-01")], ["2026-10-27"]), ("31 日落月底", [rule(day=31, start="2026-02")], ["2026-03-01"]),
        ("停用與無效", [rule(id="a", active=False), rule(id="b", amount=0), rule(id="c", type="其他"), rule(id="d", day=0), {"id": "e"}], ["2026-10-27"]),
        ("跨年", [rule(start="2025-11", day=1)], ["2026-01-15"]),
        ("end 停止", [rule(start="2026-11", end="2027-01", day=5)], ["2027-01-10", "2027-06-01", "2028-01-01"]),
    ]
    v["recurring"] = []
    for name, rules, days in rec_cases:
        data = {"recurring": copy.deepcopy(rules), "cashflow_monthly": {}}
        counts = [apply_recurring(data, D(d)) for d in days]
        v["recurring"].append({"name": name, "start": {"recurring": rules, "cashflow_monthly": {}}, "days": days, "counts": counts,
                               "final": data})

    v["loan_rules"] = []
    for name, ln, steps in [
        ("建立並入帳", _loan(), [("set", True), ("apply", "2027-01-10")]),
        ("還完就停", _loan(term=3), [("set", True), ("apply", "2027-01-10"), ("apply", "2027-06-01"), ("apply", "2028-01-01")]),
        ("更新保留 generated", _loan(), [("set", True), ("apply", "2026-12-10"), ("edit", {"rate": 3.0}), ("set", True), ("apply", "2026-12-20")]),
        ("停用保留記錄", _loan(), [("set", True), ("apply", "2026-12-10"), ("set", False)]),
        ("本金平均不建規則", _loan(method="equal_principal"), [("set", True)]),
        ("有寬限期不建規則", _loan(grace=3), [("set", True)]),
    ]:
        data = {"liabilities": [copy.deepcopy(ln)], "recurring": [], "cashflow_monthly": {}}
        log = []
        for op, arg in steps:
            if op == "set":
                r = set_loan_rule(data, data["liabilities"][0], arg)
                log.append(None if r is None else {k: x for k, x in r.items() if k != "id"})
            elif op == "apply":
                log.append(apply_recurring(data, D(arg)))
            elif op == "edit":
                data["liabilities"][0].update(arg)
                log.append(None)
        data["recurring"] = strip_ids(data["recurring"])
        for recs in data["cashflow_monthly"].values():           # rec 是隨機的規則 id，比對時不看
            for r in recs:
                r.pop("rec", None)
        v["loan_rules"].append({"name": name, "loan": ln, "steps": steps, "log": log, "final": data})
    return v


def main():
    v = build()
    with open(VECTOR_FILE, "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"wrote {VECTOR_FILE}: " + ", ".join(f"{k}={len(x)}" for k, x in v.items()))


if __name__ == "__main__":
    main()
