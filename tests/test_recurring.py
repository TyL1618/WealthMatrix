"""固定收支與淨值計算的測試：python -m unittest discover tests"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wealthmatrix.core.calc import (  # noqa: E402
    assets_total, liabilities_total, net_worth,
    expense_by_category, budget_status, monthly_saving, goal_projection,
)
from wealthmatrix.core.recurring import apply_recurring, new_rule_id  # noqa: E402


def _rule(**kw):
    base = {"id": "r_test", "type": "支出", "category": "房租", "amount": 12000,
            "day": 5, "note": "", "active": True, "start": "2026-10"}
    base.update(kw)
    return base


class RecurringTests(unittest.TestCase):
    def test_generates_when_due(self):
        d = {"recurring": [_rule()], "cashflow_monthly": {}}
        n = apply_recurring(d, date(2026, 10, 27))
        self.assertEqual(n, 1)
        rec = d["cashflow_monthly"]["2026-10"][0]
        self.assertEqual(rec["date"], "2026-10-05")
        self.assertEqual((rec["type"], rec["category"], rec["amount"], rec["rec"]),
                         ("支出", "房租", 12000.0, "r_test"))

    def test_not_due_yet(self):
        d = {"recurring": [_rule(day=28)], "cashflow_monthly": {}}
        self.assertEqual(apply_recurring(d, date(2026, 10, 27)), 0)
        self.assertEqual(apply_recurring(d, date(2026, 10, 28)), 1)

    def test_idempotent(self):
        d = {"recurring": [_rule()], "cashflow_monthly": {}}
        apply_recurring(d, date(2026, 10, 27))
        self.assertEqual(apply_recurring(d, date(2026, 10, 28)), 0)
        self.assertEqual(len(d["cashflow_monthly"]["2026-10"]), 1)

    def test_deleted_record_is_not_regenerated(self):
        d = {"recurring": [_rule()], "cashflow_monthly": {}}
        apply_recurring(d, date(2026, 10, 27))
        d["cashflow_monthly"]["2026-10"].clear()          # 使用者刪掉當月那筆
        self.assertEqual(apply_recurring(d, date(2026, 10, 30)), 0)

    def test_backfills_missed_months(self):
        d = {"recurring": [_rule(start="2026-07")], "cashflow_monthly": {}}
        self.assertEqual(apply_recurring(d, date(2026, 10, 27)), 4)
        self.assertEqual(sorted(d["cashflow_monthly"]), ["2026-07", "2026-08", "2026-09", "2026-10"])

    def test_backfill_is_capped(self):
        d = {"recurring": [_rule(start="2020-01")], "cashflow_monthly": {}}
        self.assertEqual(apply_recurring(d, date(2026, 10, 27)), 12)

    def test_day_31_clamped_to_month_end(self):
        d = {"recurring": [_rule(day=31, start="2026-02")], "cashflow_monthly": {}}
        apply_recurring(d, date(2026, 3, 1))
        self.assertEqual(d["cashflow_monthly"]["2026-02"][0]["date"], "2026-02-28")

    def test_inactive_and_invalid_rules_skipped(self):
        d = {"recurring": [
            _rule(id="a", active=False),
            _rule(id="b", amount=0),
            _rule(id="c", type="其他"),
            _rule(id="d", day=0),
            {"id": "e"},
        ], "cashflow_monthly": {}}
        self.assertEqual(apply_recurring(d, date(2026, 10, 27)), 0)

    def test_year_boundary(self):
        d = {"recurring": [_rule(start="2025-11", day=1)], "cashflow_monthly": {}}
        apply_recurring(d, date(2026, 1, 15))
        self.assertEqual(sorted(d["cashflow_monthly"]), ["2025-11", "2025-12", "2026-01"])

    def test_two_devices_do_not_duplicate(self):
        """同一份資料經兩端各自執行一次，每月仍只有一筆。"""
        d = {"recurring": [_rule()], "cashflow_monthly": {}}
        apply_recurring(d, date(2026, 10, 27))
        import copy
        other = copy.deepcopy(d)
        apply_recurring(other, date(2026, 10, 28))
        self.assertEqual(len(other["cashflow_monthly"]["2026-10"]), 1)

    def test_rule_ids_unique(self):
        self.assertNotEqual(new_rule_id(), new_rule_id())


class CalcTests(unittest.TestCase):
    DATA = {
        "banks": [{"amount": 100000}, {"amount": 50000}],
        "cash": 2000,
        "stocks": [{"ticker": "0050.TW", "shares": 100, "cost": 150},
                   {"ticker": "AAPL", "shares": 2, "cost": 6000}],
        "liabilities": [{"name": "信用卡", "amount": 7000}, {"name": "學貸", "amount": 3000}],
    }

    def test_assets_use_price_or_fall_back_to_cost(self):
        # 0050 有報價 200 → 20000；AAPL 無報價 → 成本 6000*2
        self.assertEqual(assets_total(self.DATA, {"0050.TW": 200}), 150000 + 2000 + 20000 + 12000)

    def test_net_worth_subtracts_liabilities(self):
        prices = {"0050.TW": 200, "AAPL": 6000}
        self.assertEqual(liabilities_total(self.DATA), 10000)
        self.assertEqual(net_worth(self.DATA, prices), assets_total(self.DATA, prices) - 10000)

    def test_missing_liabilities_key(self):
        d = {k: v for k, v in self.DATA.items() if k != "liabilities"}
        self.assertEqual(liabilities_total(d), 0)


class BudgetTests(unittest.TestCase):
    DATA = {
        "budgets": {"餐飲": 5000, "交通": 0, "娛樂": 1000, "壞值": "abc"},
        "cashflow_monthly": {"2026-10": [
            {"type": "支出", "category": "餐飲", "amount": 4000},
            {"type": "支出", "category": "餐飲", "amount": 500},
            {"type": "支出", "category": "娛樂", "amount": 1500},
            {"type": "支出", "category": "交通", "amount": 900},
            {"type": "收入", "category": "薪資", "amount": 65000},
            {"category": "舊資料", "amount": -300},          # 沒有 type：負數視為支出
        ]},
    }

    def test_expense_by_category(self):
        s = expense_by_category(self.DATA, "2026-10")
        self.assertEqual(s, {"餐飲": 4500, "娛樂": 1500, "交通": 900, "舊資料": 300})
        self.assertEqual(expense_by_category(self.DATA, "2026-09"), {})

    def test_budget_status_sorted_and_filtered(self):
        rows = budget_status(self.DATA, "2026-10")
        self.assertEqual([r["category"] for r in rows], ["娛樂", "餐飲"])   # 0 與壞值被略過
        self.assertAlmostEqual(rows[0]["ratio"], 1.5)
        self.assertAlmostEqual(rows[1]["ratio"], 0.9)

    def test_no_budgets(self):
        self.assertEqual(budget_status({}, "2026-10"), [])


class GoalTests(unittest.TestCase):
    TODAY = date(2026, 10, 27)

    def _data(self, months):
        return {"cashflow_monthly": months}

    def test_monthly_saving_excludes_current_month_and_investments(self):
        d = self._data({
            "2026-10": [{"type": "收入", "amount": 999999}],            # 本月不算
            "2026-09": [{"type": "收入", "amount": 60000, "category": "薪資"},
                        {"type": "支出", "amount": 20000, "category": "生活費"},
                        {"type": "支出", "amount": 10000, "category": "投資買入"}],   # 不算支出
            "2026-08": [{"type": "收入", "amount": 60000, "category": "薪資"},
                        {"type": "支出", "amount": 30000, "category": "生活費"}],
        })
        self.assertEqual(monthly_saving(d, self.TODAY), (40000 + 30000) / 2)

    def test_monthly_saving_none_without_history(self):
        self.assertIsNone(monthly_saving(self._data({"2026-10": [{"type": "收入", "amount": 1}]}), self.TODAY))

    def test_done(self):
        p = goal_projection({"target": 100}, 150, 10, self.TODAY)
        self.assertTrue(p["done"] and p["remaining"] == 0)

    def test_deadline_and_eta(self):
        g = {"target": 1_000_000, "deadline": "2027-06"}
        p = goal_projection(g, 700_000, 50_000, self.TODAY)
        self.assertEqual(p["months_left"], 8)
        self.assertEqual(p["need_per_month"], 300_000 / 8)
        self.assertEqual((p["eta_months"], p["eta"]), (6, "2027-04"))
        self.assertFalse(p["late"])

    def test_late_when_too_slow(self):
        g = {"target": 1_000_000, "deadline": "2027-06"}
        p = goal_projection(g, 700_000, 20_000, self.TODAY)       # 需 15 個月，期限只剩 8
        self.assertEqual(p["eta_months"], 15)
        self.assertTrue(p["late"])

    def test_late_when_no_saving(self):
        g = {"target": 1_000_000, "deadline": "2027-06"}
        for saving in (None, 0, -500):
            p = goal_projection(g, 700_000, saving, self.TODAY)
            self.assertIsNone(p["eta"])
            self.assertTrue(p["late"])

    def test_no_deadline(self):
        p = goal_projection({"target": 1_000_000}, 700_000, 100_000, self.TODAY)
        self.assertIsNone(p["months_left"])
        self.assertIsNone(p["need_per_month"])
        self.assertFalse(p["late"])
        self.assertEqual(p["eta"], "2027-01")

    def test_overdue_deadline(self):
        p = goal_projection({"target": 100, "deadline": "2026-01"}, 40, 5, self.TODAY)
        self.assertEqual(p["months_left"], 0)
        self.assertEqual(p["need_per_month"], 60)
        self.assertTrue(p["late"])

    def test_bad_deadline_ignored(self):
        for bad in ("abc", "2026-13", "", None):
            p = goal_projection({"target": 100, "deadline": bad}, 40, 5, self.TODAY)
            self.assertIsNone(p["months_left"])

    def test_fractional_remaining_rounds_up(self):
        p = goal_projection({"target": 100.5}, 0, 50, self.TODAY)
        self.assertEqual(p["eta_months"], 3)


if __name__ == "__main__":
    unittest.main()
