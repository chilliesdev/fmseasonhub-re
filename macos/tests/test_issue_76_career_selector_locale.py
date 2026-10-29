"""Issue #76: Career selector displays properly translated season count and never raw key."""

from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import db
import idiomas
import server
import settings


class CareerSelectorLocaleTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="fmsh-issue-76-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / "local" / "fm26_snapshots.db"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        db.init_db(str(self.database))

        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.executemany("""
                INSERT INTO snapshots(id, name, game_date, scope, carreira_id, club_uid, fm_version)
                VALUES(?,?,?,?,?,?,?)
            """, [
                (1, "Old Hull", "2026-02-01", "full", "career_default", 5, "26.3.2"),
                (2, "Latest Hull", "2026-02-07", "full", "career_default", 5, "26.3.2"),
                (3, "Leeds Squad", "2026-07-01", "squad", "qa_test", 12, "26.3.2"),
            ])

    def test_ui_contract_and_locale_dictionaries(self):
        script = Path(__file__).with_name("career_selector_locale_ui.mjs")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Career selector locale UI contract passed", result.stdout)

    def test_api_carreiras_returns_temporadas_and_metadata(self):
        settings_path = self.root / "data" / "fmsh_settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        from unittest.mock import patch
        with patch.object(settings, "SETTINGS_PATH", str(settings_path)), patch.object(
            server, "get_db_path", return_value=self.database
        ):
            settings.save(carreira_ativa="career_default")
            response = server.get_carreiras()
            self.assertEqual(response["ativa"], "career_default")
            career_map = {c["id"]: c for c in response["carreiras"]}

            # Both 'n_temporadas' and 'temporadas' must be integer counts
            self.assertEqual(career_map["career_default"]["temporadas"], 2)
            self.assertEqual(career_map["career_default"]["n_temporadas"], 2)
            self.assertEqual(career_map["qa_test"]["temporadas"], 1)
            self.assertEqual(career_map["qa_test"]["n_temporadas"], 1)

            # Metadata from most recent snapshot
            self.assertEqual(career_map["career_default"]["ultima"], "2026-02-07")
            self.assertEqual(career_map["career_default"]["club_uid"], 5)
            self.assertEqual(career_map["career_default"]["fm_version"], "26.3.2")

    def test_idiomas_resolver_carreira_seasons_keys(self):
        for codigo in ["en", "pt", "de", "es", "fr", "tr"]:
            res = idiomas.resolver(codigo)
            self.assertIn("carreira.seasons", res, f"{codigo} must include carreira.seasons")
            self.assertIn("carreira.seasons_one", res, f"{codigo} must include carreira.seasons_one")
            self.assertIn("carreira.seasons_other", res, f"{codigo} must include carreira.seasons_other")
            self.assertNotIn("carreira.seasons", res["carreira.seasons"])


if __name__ == "__main__":
    unittest.main()
