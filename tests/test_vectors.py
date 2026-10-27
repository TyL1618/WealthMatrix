"""Python 端對照共用向量（tests/vectors.json）。向量過期（有人改了規則卻沒重新產生）會在這裡失敗。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gen_vectors  # noqa: E402


class VectorsUpToDate(unittest.TestCase):
    def test_vectors_match_current_python_implementation(self):
        with open(gen_vectors.VECTOR_FILE, encoding="utf-8") as f:
            on_disk = json.load(f)
        fresh = json.loads(json.dumps(gen_vectors.build(), ensure_ascii=False, sort_keys=True))
        for group in fresh:
            self.assertEqual(fresh[group], on_disk.get(group), f"向量 {group} 過期：請執行 python tests/gen_vectors.py")
        self.assertEqual(set(fresh), set(on_disk))


class SanityOfVectors(unittest.TestCase):
    """向量本身的幾個關鍵數字（避免『兩邊一起錯』）。"""

    @classmethod
    def setUpClass(cls):
        with open(gen_vectors.VECTOR_FILE, encoding="utf-8") as f:
            cls.v = json.load(f)

    def test_known_loan_values(self):
        by_loan = {(x["loan"]["principal"], x["loan"]["rate"], x["loan"]["term"], x["loan"]["method"], x["loan"]["grace"]): x
                   for x in self.v["loans"]}
        a = by_loan[(100000, 12, 12, "annuity", 0)]
        self.assertEqual(a["schedule"][0]["payment"], 8885)
        b = by_loan[(600000, 2.5, 60, "annuity", 0)]
        self.assertEqual((b["schedule"][0]["payment"], sum(r["interest"] for r in b["schedule"])), (10648, 38905))

    def test_xirr_known(self):
        out = {json.dumps(x["flows"], sort_keys=True): x["out"] for x in self.v["xirr"]}
        one_year = out[json.dumps([{"amount": -1000, "date": "2026-01-01"}, {"amount": 1100, "date": "2027-01-01"}], sort_keys=True)]
        self.assertAlmostEqual(one_year, 0.1, places=6)          # 一年賺 10%
        self.assertIsNone(out[json.dumps([], sort_keys=True)])

    def test_every_group_non_empty(self):
        for k, x in self.v.items():
            self.assertTrue(x, k)


if __name__ == "__main__":
    unittest.main()
