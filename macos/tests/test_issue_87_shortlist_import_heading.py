"""Issue #87: Shortlist import heading duplicates the FM prefix."""

from pathlib import Path
import subprocess
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import idiomas


class ShortlistImportHeadingLocaleTests(unittest.TestCase):
    def test_ui_contract_and_locale_dictionaries(self):
        script = Path(__file__).with_name("shortlist_import_heading_ui.mjs")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Shortlist import heading UI contract passed", result.stdout)

    def test_idiomas_resolver_lista_na_pasta_across_all_locales(self):
        expected_interpolations = {
            "en": "In the Football Manager 26 folder",
            "pt": "Na pasta do Football Manager 26",
            "de": "Im Football Manager 26-Ordner",
            "fr": "Dans le dossier du Football Manager 26",
            "es": "En la carpeta de Football Manager 26",
            "tr": "Football Manager 26 klasöründe",
        }
        for codigo, expected in expected_interpolations.items():
            res = idiomas.resolver(codigo)
            self.assertIn("lista.naPasta", res, f"{codigo} must include lista.naPasta")
            template = res["lista.naPasta"]
            self.assertNotIn("FM{{jogo}}", template, f"{codigo} template must not contain FM{{jogo}}")
            interpolated = template.replace("{{jogo}}", "Football Manager 26")
            self.assertEqual(
                interpolated,
                expected,
                f"{codigo} interpolation mismatch: expected {expected!r}, got {interpolated!r}",
            )
            self.assertNotIn("FMFootball", interpolated, f"{codigo} must not contain duplicate FMFootball prefix")


if __name__ == "__main__":
    unittest.main()
