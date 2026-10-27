"""固定收支與淨值計算的測試：python -m unittest discover tests"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wealthmatrix.core.calc import (  # noqa: E402
    assets_total, liabilities_total, net_worth,
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


if __name__ == "__main__":
    unittest.main()
