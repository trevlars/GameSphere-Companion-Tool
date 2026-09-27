"""library_sync state helpers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from host_tuning import library_sync


class LibrarySyncTests(unittest.TestCase):
    def test_record_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(library_sync, "config_dir", return_value=tmp):
                written = library_sync.record(
                    ok=True,
                    message="No changes needed",
                    added=0,
                    removed=0,
                    changed=False,
                )
                self.assertTrue(written["ok"])
                path = os.path.join(tmp, "library_sync.json")
                self.assertTrue(os.path.isfile(path))
                with open(path, encoding="utf-8") as fh:
                    raw = json.load(fh)
                self.assertEqual(raw["message"], "No changes needed")
                state = library_sync.read_state()
                self.assertTrue(state.get("ever_run"))
                self.assertEqual(state.get("added"), 0)


if __name__ == "__main__":
    unittest.main()
