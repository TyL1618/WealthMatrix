"""交易記錄 / 股利 / 損益摘要的測試：python -m unittest discover tests"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wealthmatrix.core.calc import apply_trade, add_dividend, portfolio_summary, find_stock  # noqa: E402


def _buy(ticker="0050", shares=100, price=150, fee=0, date="2026-01-10", **kw):
    return {"ticker": ticker, "side": "buy", "shares": shares, "price": price, "fee": fee, "date": date, **kw}


def _sell(ticker="0050", shares=50, price=180, fee=0, date="2026-06-10", **kw):
    return {"ticker": ticker, "side": "sell", "shares": shares, "price": price, "fee": fee, "date": date, **kw}


class TradeTests(unittest.TestCase):
    def test_first_buy_creates_stock_with_normalized_ticker(self):
        d = {}
        self.assertIsNone(apply_trade(d, _buy(fee=20)))
        s = d["stocks"][0]
        self.assertEqual((s["ticker"], s["shares"], s["holding_cost"]), ("0050.TW", 100, 15020))
        self.assertAlmostEqual(s["cost"], 150.2)            # 手續費算進成本
        t = d["transactions"][0]
        self.assertEqual((t["side"], t["ticker"], t["shares"]), ("buy", "0050.TW", 100))
        self.assertTrue(t["id"].startswith("t_"))

    def test_second_buy_averages_cost(self):
        d = {}
        apply_trade(d, _buy(shares=100, price=100))
        apply_trade(d, _buy(shares=100, price=200, date="2026-02-01"))
        s = d["stocks"][0]
        self.assertEqual((s["shares"], s["holding_cost"], s["cost"]), (200, 30000, 150))

    def test_buy_into_legacy_stock_without_holding_cost(self):
        d = {"stocks": [{"ticker": "0050.TW", "shares": 100, "cost": 100}]}
        apply_trade(d, _buy(shares=100, price=200))
        s = d["stocks"][0]
        self.assertEqual((s["shares"], s["holding_cost"]), (200, 30000))
        self.assertEqual(len(d["stocks"]), 1)                # 沿用既有持股，沒有新增一筆

    def test_partial_sell_realized_and_average_unchanged(self):
        d = {}
        apply_trade(d, _buy(shares=100, price=150))
        self.assertIsNone(apply_trade(d, _sell(shares=40, price=180, fee=30)))
        s = d["stocks"][0]
        self.assertEqual((s["shares"], s["holding_cost"], s["cost"]), (60, 9000, 150))
        t = d["transactions"][-1]
        self.assertEqual(t["realized"], 40 * 180 - 30 - 150 * 40)   # 1170

    def test_sell_at_loss(self):
        d = {}
        apply_trade(d, _buy(shares=10, price=100))
        apply_trade(d, _sell(shares=10, price=80))
        self.assertEqual(d["transactions"][-1]["realized"], -200)

    def test_sell_all_removes_stock_but_keeps_realized(self):
        d = {}
        apply_trade(d, _buy(shares=100, price=100))
        apply_trade(d, _sell(shares=100, price=110))
        self.assertEqual(d["stocks"], [])
        self.assertEqual(d["transactions"][-1]["realized"], 1000)

    def test_sell_more_than_held_is_rejected_and_data_unchanged(self):
        d = {}
        apply_trade(d, _buy(shares=10, price=100))
        before = copy.deepcopy(d)
        err = apply_trade(d, _sell(shares=11))
        self.assertIn("持股不足", err)
        self.assertEqual(d, before)
        self.assertIn("持股不足", apply_trade({}, _sell()))      # 完全沒有持股

    def test_validation_errors_leave_data_untouched(self):
        for bad in (_buy(ticker=""), _buy(shares=0), _buy(shares=-5), _buy(price=-1), _buy(fee=-1),
                    _buy(date="2026/01/01"), _buy(date=""), {**_buy(), "side": "hold"},
                    {**_buy(), "shares": "abc"}):
            d = {}
            self.assertIsNotNone(apply_trade(d, bad), bad)
            self.assertEqual(d, {}, bad)

    def test_fractional_shares(self):
        d = {}
        apply_trade(d, _buy(ticker="AAPL", shares=0.5, price=200))
        apply_trade(d, _sell(ticker="AAPL", shares=0.5, price=300))
        self.assertEqual(d["stocks"], [])
        self.assertEqual(d["transactions"][-1]["realized"], 50)

    def test_find_stock_normalizes(self):
        d = {"stocks": [{"ticker": "0050.TW", "shares": 1}]}
        self.assertIs(find_stock(d, "0050"), d["stocks"][0])
        self.assertIsNone(find_stock(d, "2330"))


class DividendTests(unittest.TestCase):
    def test_add_and_validate(self):
        d = {}
        self.assertIsNone(add_dividend(d, {"ticker": "0056", "date": "2026-07-20", "amount": 1500, "note": " Q2 "}))
        self.assertEqual(d["dividends"][0]["ticker"], "0056.TW")
        self.assertEqual(d["dividends"][0]["note"], "Q2")
        for bad in ({"ticker": "", "date": "2026-07-20", "amount": 1}, {"ticker": "0056", "date": "bad", "amount": 1},
                    {"ticker": "0056", "date": "2026-07-20", "amount": 0}, {"ticker": "0056", "date": "2026-07-20", "amount": "x"}):
            self.assertIsNotNone(add_dividend({}, bad), bad)
        self.assertEqual(len(d["dividends"]), 1)


class SummaryTests(unittest.TestCase):
    def _data(self):
        d = {"stocks": [{"ticker": "0050.TW", "shares": 100, "cost": 100, "holding_cost": 10000},
                        {"ticker": "AAPL", "shares": 2, "cost": 5000, "holding_cost": 10000, "last_price": 6000},
                        {"ticker": "NOPRICE", "shares": 1, "cost": 10, "holding_cost": 10}]}
        d["transactions"] = [
            {"side": "sell", "date": "2026-03-01", "realized": 500},
            {"side": "sell", "date": "2025-12-31", "realized": -200},
            {"side": "buy", "date": "2026-01-01"},
        ]
        d["dividends"] = [{"date": "2026-07-01", "amount": 300}, {"date": "2025-07-01", "amount": 100}]
        return d

    def test_summary(self):
        s = portfolio_summary(self._data(), {"0050.TW": 120}, 2026)
        # 0050：120*100−10000 = 2000；AAPL 用 last_price：6000*2−10000 = 2000；NOPRICE 不計
        self.assertEqual((s["unrealized"], s["priced"]), (4000, 2))
        self.assertEqual((s["realized_total"], s["realized_year"]), (300, 500))
        self.assertEqual((s["dividends_total"], s["dividends_year"]), (400, 300))
        self.assertEqual(s["total_return"], 4000 + 300 + 400)

    def test_live_price_beats_last_price(self):
        s = portfolio_summary(self._data(), {"0050.TW": 100, "AAPL": 5000}, 2026)
        self.assertEqual(s["unrealized"], 0)

    def test_empty(self):
        s = portfolio_summary({}, {}, 2026)
        self.assertEqual((s["unrealized"], s["realized_total"], s["dividends_total"], s["total_return"]), (0, 0, 0, 0))

    def test_end_to_end(self):
        d = {}
        apply_trade(d, _buy(shares=100, price=100, date="2026-01-05"))
        apply_trade(d, _sell(shares=40, price=150, fee=10, date="2026-03-05"))
        add_dividend(d, {"ticker": "0050", "date": "2026-07-20", "amount": 250})
        s = portfolio_summary(d, {"0050.TW": 130}, 2026)
        self.assertEqual(s["realized_year"], 40 * 150 - 10 - 100 * 40)      # 1990
        self.assertEqual(s["unrealized"], 130 * 60 - 6000)                   # 1800
        self.assertEqual(s["total_return"], 1990 + 1800 + 250)


if __name__ == "__main__":
    unittest.main()
