"""帳密保護（DPAPI）、舊資料補齊、股票代號正規化的測試：python -m unittest discover tests"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wealthmatrix.core import data_manager as dm  # noqa: E402
from wealthmatrix.core import secret  # noqa: E402
from wealthmatrix.core.calc import normalize_ticker, is_income, rec_type  # noqa: E402

WIN = sys.platform == "win32"


@unittest.skipUnless(WIN, "DPAPI 只在 Windows")
class SecretTests(unittest.TestCase):
    def test_roundtrip_unicode(self):
        for pw in ("p@ssw0rd", "密碼-測試-🔒", "a" * 500):
            enc = secret.protect(pw)
            self.assertIsNotNone(enc)
            self.assertNotIn(pw, enc)
            self.assertEqual(secret.unprotect(enc), pw)

    def test_same_text_gives_different_blobs_or_at_least_decrypts(self):
        self.assertEqual(secret.unprotect(secret.protect("x")), "x")

    def test_bad_input_returns_none(self):
        self.assertIsNone(secret.unprotect(""))
        self.assertIsNone(secret.unprotect("not base64!!"))
        self.assertIsNone(secret.unprotect("AAAA"))                 # 合法 base64 但不是 DPAPI blob
        enc = secret.protect("hello")
        tampered = enc[:-8] + ("AAAAAAAA" if enc[-8:] != "AAAAAAAA" else "BBBBBBBB")
        self.assertIsNone(secret.unprotect(tampered))


class CloudCfgTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "wm_cloud.json")
        self._p = mock.patch.object(dm, "CLOUD_CFG", self.path)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def _write(self, cfg, bom=False):
        with open(self.path, "w", encoding="utf-8-sig" if bom else "utf-8") as f:
            json.dump(cfg, f)

    def _read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _raw(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    BASE = {"supabase_url": "https://x.supabase.co/", "supabase_key": "k", "email": "a@b.c"}

    def test_missing_file(self):
        self.assertEqual(dm._load_cloud_cfg(), (None, None, None, None))
        self.assertFalse(dm.cloud_password_needed())

    @unittest.skipUnless(WIN, "DPAPI 只在 Windows")
    def test_plaintext_password_is_upgraded_and_removed(self):
        self._write({**self.BASE, "password": "secret-pw"}, bom=True)     # 舊檔可能帶 BOM
        self.assertEqual(dm._load_cloud_cfg(), ("https://x.supabase.co", "k", "a@b.c", "secret-pw"))
        on_disk = self._read()
        self.assertNotIn("password", on_disk)
        self.assertIn("password_dpapi", on_disk)
        self.assertNotIn("secret-pw", json.dumps(on_disk))
        self.assertEqual(on_disk["email"], "a@b.c")
        # 第二次讀取：從加密欄位解回來，檔案不再變動
        before = self._raw()
        self.assertEqual(dm._load_cloud_cfg()[3], "secret-pw")
        self.assertEqual(self._raw(), before)
        self.assertFalse(dm.cloud_password_needed())

    @unittest.skipUnless(WIN, "DPAPI 只在 Windows")
    def test_foreign_blob_needs_password_then_set(self):
        self._write({**self.BASE, "password_dpapi": "AAAA"})              # 別台電腦加密的（這裡解不開）
        self.assertEqual(dm._load_cloud_cfg()[3], "")
        self.assertTrue(dm.cloud_password_needed())
        self.assertEqual(dm.cloud_email(), "a@b.c")
        self.assertTrue(dm.set_cloud_password("new-pw"))
        self.assertEqual(dm._load_cloud_cfg()[3], "new-pw")
        self.assertFalse(dm.cloud_password_needed())
        self.assertNotIn("new-pw", self._raw())

    def test_no_email_never_needs_password(self):
        self._write({"supabase_url": "https://x", "supabase_key": "k"})
        self.assertFalse(dm.cloud_password_needed())

    def test_set_password_without_dpapi_falls_back_to_plaintext(self):
        self._write(dict(self.BASE))
        with mock.patch.object(secret, "protect", lambda t: None):
            self.assertTrue(dm.set_cloud_password("pw"))
        self.assertEqual(self._read()["password"], "pw")

    def test_upgrade_failure_keeps_plaintext_working(self):
        self._write({**self.BASE, "password": "pw"})
        with mock.patch.object(secret, "protect", lambda t: None):
            self.assertEqual(dm._load_cloud_cfg()[3], "pw")
        self.assertEqual(self._read()["password"], "pw")

    def test_set_password_clears_auth_cache(self):
        self._write(dict(self.BASE))
        dm._auth_cache.update({"token": "t", "user_id": "u", "expires_at": 9e12})
        dm.set_cloud_password("pw")
        self.assertIsNone(dm._auth_cache["token"])


class NormalizeTests(unittest.TestCase):
    def test_ticker(self):
        cases = {"2330": "2330.TW", " 0050 ": "0050.TW", "00981a": "00981A.TW", "006208": "006208.TW",
                 "2330.TW": "2330.TW", "6488.TWO": "6488.TWO", "aapl": "AAPL", "BRK-B": "BRK-B",
                 "123": "123", "1234567": "1234567", "": "", None: ""}
        for raw, want in cases.items():
            self.assertEqual(normalize_ticker(raw), want, raw)

    def test_legacy_type_by_sign(self):
        self.assertTrue(is_income({"amount": 100}))
        self.assertFalse(is_income({"amount": -100}))
        self.assertTrue(is_income({"type": "收入", "amount": -5}))
        self.assertFalse(is_income({"type": "支出", "amount": 5}))
        self.assertEqual(rec_type({"amount": -1}), "支出")

    def test_migration_fills_type_ticker_and_keeps_good_data(self):
        raw = {
            "cashflow_monthly": {"2026-10": [
                {"date": "2026-10-01", "category": "薪資", "amount": 50000},
                {"date": "2026-10-02", "category": "餐飲", "amount": -300},
                {"date": "2026-10-03", "type": "支出", "category": "交通", "amount": 80},
            ]},
            "stocks": [{"ticker": "2330", "shares": 1, "cost": 1}, {"ticker": "AAPL", "shares": 1, "cost": 1},
                       {"ticker": "0050.TW", "shares": 1, "cost": 1}],
        }
        d = dm._apply_migrations(raw, dm._default_data())
        recs = d["cashflow_monthly"]["2026-10"]
        self.assertEqual([(r["type"], r["amount"]) for r in recs], [("收入", 50000), ("支出", 300), ("支出", 80)])
        self.assertEqual([s["ticker"] for s in d["stocks"]], ["2330.TW", "AAPL", "0050.TW"])
        s = dm.get_year_summary(d, 2026)[10]
        self.assertEqual((s["income"], s["expense"], s["net"]), (50000, 380, 50000 - 380))

    def test_year_summary_tolerates_missing_type_without_migration(self):
        d = {"cashflow_monthly": {"2026-01": [{"amount": 100}, {"amount": -40}]}}
        s = dm.get_year_summary(d, 2026)[1]
        self.assertEqual((s["income"], s["expense"]), (100, 40))


if __name__ == "__main__":
    unittest.main()
