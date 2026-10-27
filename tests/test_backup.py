"""每日輪替備份的測試：python -m unittest discover tests"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wealthmatrix.core import data_manager as dm  # noqa: E402


class BackupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self._patches = [
            mock.patch.object(dm, "DATA_FILE", os.path.join(root, "wealth_matrix_data.json")),
            mock.patch.object(dm, "BACKUP_DIR", os.path.join(root, "backups")),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _write_main(self, data):
        with open(dm.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_no_backup_when_no_main_file(self):
        dm._save_local_raw(json.dumps({"banks": []}))
        self.assertEqual(dm.list_backups(), [])

    def test_first_write_of_day_backs_up_previous_state(self):
        self._write_main({"cash": 1})
        dm._save_local_raw(json.dumps({"cash": 2}))
        dm._save_local_raw(json.dumps({"cash": 3}))   # 同一天第二次不再備份

        backups = dm.list_backups()
        self.assertEqual([b[0] for b in backups], [date.today().isoformat()])
        self.assertEqual(dm.load_backup(backups[0][1]), {"cash": 1})
        with open(dm.DATA_FILE, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"cash": 3})

    def test_keeps_only_latest_30(self):
        os.makedirs(dm.BACKUP_DIR)
        for i in range(1, 41):
            day = (date.today() - timedelta(days=i)).isoformat()
            with open(os.path.join(dm.BACKUP_DIR, f"wealth_matrix_data_{day}.json"), "w") as f:
                f.write("{}")
        self._write_main({"cash": 1})
        dm._save_local_raw(json.dumps({"cash": 2}))

        labels = [b[0] for b in dm.list_backups()]
        self.assertEqual(len(labels), 30)
        self.assertEqual(labels[0], date.today().isoformat())       # 新的在前
        oldest_kept = (date.today() - timedelta(days=29)).isoformat()
        self.assertEqual(labels[-1], oldest_kept)

    def test_backup_now_tag_does_not_overwrite_daily(self):
        self._write_main({"cash": 1})
        dm._save_local_raw(json.dumps({"cash": 2}))
        dm.backup_now("pre-restore")

        labels = [b[0] for b in dm.list_backups()]
        today = date.today().isoformat()
        self.assertIn(today, labels)
        self.assertIn(f"{today}_pre-restore", labels)
        pre = dict(dm.list_backups())[f"{today}_pre-restore"]
        self.assertEqual(dm.load_backup(pre), {"cash": 2})

    def test_atomic_write_leaves_no_tmp(self):
        dm._save_local_raw(json.dumps({"cash": 1}))
        self.assertFalse(os.path.exists(dm.DATA_FILE + ".tmp"))

    def test_load_backup_bad_file_returns_none(self):
        os.makedirs(dm.BACKUP_DIR)
        bad = os.path.join(dm.BACKUP_DIR, "wealth_matrix_data_2020-01-01.json")
        with open(bad, "w") as f:
            f.write("{not json")
        self.assertIsNone(dm.load_backup(bad))


if __name__ == "__main__":
    unittest.main()
