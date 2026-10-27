"""分期貸款（攤還表、進度、餘額、固定還款規則）的測試：python -m unittest discover tests"""
import copy
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wealthmatrix.core.calc import (  # noqa: E402
    validate_loan, loan_schedule, loan_status, liability_balance, liabilities_total,
    refresh_loan_amounts, net_worth,
)
from wealthmatrix.core.recurring import apply_recurring, set_loan_rule, LOAN_CATEGORY  # noqa: E402


def _loan(**kw):
    base = {"id": "l_test", "name": "車貸", "type": "loan", "principal": 600000, "rate": 2.5, "term": 60,
            "grace": 0, "start": "2026-11-05", "method": "annuity"}
    base.update(kw)
    return base


class ScheduleTests(unittest.TestCase):
    def test_known_annuity_value(self):
        rows = loan_schedule(_loan(principal=100000, rate=12, term=12))
        self.assertEqual(rows[0]["payment"], 8885)                  # 8884.88 四捨五入
        self.assertEqual(rows[0]["interest"], 1000)

    def test_invariants_for_many_configs(self):
        for P in (100000, 600000, 987654):
            for rate in (0, 1.88, 2.5, 7.9):
                for n in (1, 12, 60, 84):
                    for g in (0, 3):
                        if g >= n:
                            continue
                        for method in ("annuity", "equal_principal"):
                            rows = loan_schedule(_loan(principal=P, rate=rate, term=n, grace=g, method=method))
                            self.assertEqual(len(rows), n)
                            self.assertEqual(sum(r["principal"] for r in rows), P, (P, rate, n, g, method))
                            self.assertEqual(rows[-1]["balance"], 0)
                            self.assertTrue(all(r["balance"] >= 0 and r["principal"] >= 0 for r in rows))
                            balances = [r["balance"] for r in rows]
                            self.assertEqual(balances, sorted(balances, reverse=True))

    def test_annuity_payment_is_constant_except_last(self):
        rows = loan_schedule(_loan())
        self.assertEqual(len({r["payment"] for r in rows[:-1]}), 1)
        self.assertLessEqual(abs(rows[-1]["payment"] - rows[0]["payment"]), 60)   # 尾數調整

    def test_zero_rate(self):
        rows = loan_schedule(_loan(principal=120000, rate=0, term=12))
        self.assertTrue(all(r["payment"] == 10000 and r["interest"] == 0 for r in rows))

    def test_equal_principal(self):
        rows = loan_schedule(_loan(principal=120000, rate=12, term=12, method="equal_principal"))
        self.assertEqual((rows[0]["principal"], rows[0]["interest"], rows[0]["payment"]), (10000, 1200, 11200))
        self.assertGreater(rows[0]["payment"], rows[-1]["payment"])             # 本金平均：越繳越少

    def test_grace_period_interest_only(self):
        rows = loan_schedule(_loan(principal=100000, rate=6, term=12, grace=3))
        self.assertTrue(all(r["principal"] == 0 and r["payment"] == 500 for r in rows[:3]))
        self.assertEqual(rows[2]["balance"], 100000)
        self.assertGreater(rows[3]["principal"], 0)
        self.assertEqual(rows[-1]["balance"], 0)

    def test_due_dates_keep_day_and_clamp_month_end(self):
        rows = loan_schedule(_loan(start="2026-01-31", term=4))
        self.assertEqual([r["date"] for r in rows], ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"])
        rows = loan_schedule(_loan(start="2026-11-05", term=3))
        self.assertEqual([r["date"] for r in rows], ["2026-11-05", "2026-12-05", "2027-01-05"])

    def test_single_term(self):
        rows = loan_schedule(_loan(principal=5000, rate=5, term=1))
        self.assertEqual((len(rows), rows[0]["principal"], rows[0]["balance"]), (1, 5000, 0))

    def test_invalid_loans(self):
        bad = [_loan(principal=0), _loan(principal=-1), _loan(rate=-1), _loan(rate=101), _loan(term=0),
               _loan(term=601), _loan(grace=60), _loan(grace=-1), _loan(method="x"), _loan(start="2026-13-01"),
               _loan(start=""), _loan(principal="abc"), _loan(paid_override=61), _loan(paid_override=-1),
               _loan(paid_override="x")]
        for b in bad:
            self.assertIsNotNone(validate_loan(b), b)
            self.assertEqual(loan_schedule(b), [])
            self.assertIsNone(loan_status(b))
        # 空白欄位給明確提示（而不是「數字格式錯誤」）
        self.assertEqual(validate_loan(_loan(principal="")), "請輸入貸款總額")
        self.assertEqual(validate_loan(_loan(rate=None)), "請輸入年利率")
        self.assertEqual(validate_loan(_loan(term="")), "請輸入總期數")
        self.assertIsNone(validate_loan(_loan(rate=0)))                       # 利率 0 是合法的
        self.assertIsNone(validate_loan(_loan()))
        self.assertIsNone(validate_loan(_loan(paid_override=None)))
        self.assertIsNone(validate_loan(_loan(paid_override="")))


class StatusTests(unittest.TestCase):
    def test_before_first_payment(self):
        st = loan_status(_loan(), date(2026, 10, 27))
        self.assertEqual((st["paid"], st["balance"], st["progress"], st["done"]), (0, 600000, 0, False))
        self.assertEqual(st["next_date"], "2026-11-05")
        self.assertEqual(st["remaining_terms"], 60)

    def test_paid_counts_by_date_inclusive(self):
        loan = _loan()
        self.assertEqual(loan_status(loan, date(2026, 11, 4))["paid"], 0)
        self.assertEqual(loan_status(loan, date(2026, 11, 5))["paid"], 1)
        self.assertEqual(loan_status(loan, date(2027, 1, 4))["paid"], 2)
        st = loan_status(loan, date(2027, 1, 5))
        self.assertEqual(st["paid"], 3)
        self.assertEqual(st["next_date"], "2027-02-05")
        self.assertEqual(st["balance"], loan_schedule(loan)[2]["balance"])
        self.assertAlmostEqual(st["progress"], (600000 - st["balance"]) / 600000)

    def test_finished(self):
        st = loan_status(_loan(), date(2040, 1, 1))
        self.assertTrue(st["done"])
        self.assertEqual((st["paid"], st["balance"], st["remaining_terms"], st["next_payment"]), (60, 0, 0, 0))
        self.assertIsNone(st["next_date"])
        self.assertAlmostEqual(st["progress"], 1)

    def test_paid_override_beats_dates(self):
        st = loan_status(_loan(paid_override=10), date(2026, 10, 27))
        self.assertEqual((st["paid"], st["remaining_terms"]), (10, 50))
        self.assertEqual(st["balance"], loan_schedule(_loan())[9]["balance"])
        self.assertEqual(loan_status(_loan(paid_override=0), date(2030, 1, 1))["paid"], 0)

    def test_interest_totals(self):
        loan = _loan()
        rows = loan_schedule(loan)
        st = loan_status(loan, date(2027, 1, 5))
        self.assertEqual(st["total_interest"], sum(r["interest"] for r in rows))
        self.assertEqual(st["interest_paid"], sum(r["interest"] for r in rows[:3]))
        self.assertEqual(st["end_date"], rows[-1]["date"])
        self.assertEqual(st["monthly_payment"], st["next_payment"])


class BalanceTests(unittest.TestCase):
    def test_liability_balance_mixed(self):
        self.assertEqual(liability_balance({"name": "信用卡", "amount": 5000}), 5000)
        self.assertEqual(liability_balance(_loan(), date(2026, 10, 1)), 600000)
        self.assertEqual(liability_balance(_loan(), date(2027, 1, 5)), loan_schedule(_loan())[2]["balance"])
        self.assertEqual(liability_balance(_loan(principal=0, amount=777)), 777)       # 壞貸款退回 amount

    def test_totals_and_net_worth_use_balance(self):
        d = {"banks": [{"amount": 1_000_000}], "cash": 0, "stocks": [],
             "liabilities": [{"name": "卡", "amount": 3000}, _loan(amount=999)]}
        today = date(2026, 10, 1)
        self.assertEqual(liabilities_total(d, today), 3000 + 600000)
        self.assertEqual(net_worth(d, {}), 1_000_000 - liabilities_total(d))

    def test_refresh_loan_amounts(self):
        d = {"liabilities": [{"name": "卡", "amount": 3000}, _loan(amount=1)]}
        refresh_loan_amounts(d, date(2027, 1, 5))
        self.assertEqual(d["liabilities"][0]["amount"], 3000)
        self.assertEqual(d["liabilities"][1]["amount"], loan_schedule(_loan())[2]["balance"])


class LoanRuleTests(unittest.TestCase):
    def test_create_rule_and_generate_expenses(self):
        d = {"liabilities": [_loan()], "recurring": [], "cashflow_monthly": {}}
        rule = set_loan_rule(d, d["liabilities"][0], True)
        pmt = loan_schedule(_loan())[0]["payment"]
        self.assertEqual((rule["amount"], rule["day"], rule["start"], rule["loan"], rule["category"]),
                         (pmt, 5, "2026-11", "l_test", LOAN_CATEGORY))
        self.assertEqual(rule["end"], "2031-10")
        apply_recurring(d, date(2027, 1, 10))
        self.assertEqual(sorted(d["cashflow_monthly"]), ["2026-11", "2026-12", "2027-01"])
        self.assertEqual(d["cashflow_monthly"]["2026-11"][0]["amount"], pmt)

    def test_rule_stops_after_end(self):
        d = {"liabilities": [_loan(term=3)], "recurring": [], "cashflow_monthly": {}}
        set_loan_rule(d, d["liabilities"][0], True)
        apply_recurring(d, date(2027, 1, 10))
        apply_recurring(d, date(2027, 6, 1))        # 貸款已還完（3 期），之後不會再產生
        apply_recurring(d, date(2028, 1, 1))
        self.assertEqual(sorted(d["cashflow_monthly"]), ["2026-11", "2026-12", "2027-01"])

    def test_update_keeps_generated_no_duplicates(self):
        d = {"liabilities": [_loan()], "recurring": [], "cashflow_monthly": {}}
        set_loan_rule(d, d["liabilities"][0], True)
        apply_recurring(d, date(2026, 12, 10))
        first_id = d["recurring"][0]["id"]
        d["liabilities"][0]["rate"] = 3.0
        set_loan_rule(d, d["liabilities"][0], True)
        self.assertEqual(len(d["recurring"]), 1)
        self.assertEqual(d["recurring"][0]["id"], first_id)
        self.assertEqual(d["recurring"][0]["generated"], ["2026-11", "2026-12"])
        self.assertEqual(apply_recurring(d, date(2026, 12, 20)), 0)             # 已入帳的月份不重複

    def test_disable_removes_rule_but_keeps_records(self):
        d = {"liabilities": [_loan()], "recurring": [], "cashflow_monthly": {}}
        set_loan_rule(d, d["liabilities"][0], True)
        apply_recurring(d, date(2026, 12, 10))
        self.assertIsNone(set_loan_rule(d, d["liabilities"][0], False))
        self.assertEqual(d["recurring"], [])
        self.assertEqual(len(d["cashflow_monthly"]["2026-11"]), 1)

    def test_ineligible_loans_get_no_rule(self):
        for loan in (_loan(method="equal_principal"), _loan(grace=3)):
            d = {"liabilities": [loan], "recurring": [], "cashflow_monthly": {}}
            self.assertIsNone(set_loan_rule(d, loan, True))
            self.assertEqual(d["recurring"], [])

    def test_other_rules_untouched(self):
        other = {"id": "r_x", "type": "支出", "category": "房租", "amount": 1, "day": 1, "active": True}
        d = {"liabilities": [_loan()], "recurring": [copy.deepcopy(other)], "cashflow_monthly": {}}
        set_loan_rule(d, d["liabilities"][0], True)
        set_loan_rule(d, d["liabilities"][0], False)
        self.assertEqual(d["recurring"], [other])


if __name__ == "__main__":
    unittest.main()
