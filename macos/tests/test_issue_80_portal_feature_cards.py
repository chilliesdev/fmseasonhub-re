"""Issue #80: English portal feature cards show localized status labels."""

from pathlib import Path
import subprocess
import unittest


class PortalFeatureCardsTests(unittest.TestCase):
    def test_portal_feature_cards_ui_contract(self):
        script = Path(__file__).with_name("portal_feature_cards_ui.mjs")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Portal feature cards UI contract passed", result.stdout)

    def test_shipped_bundle_static_contract(self):
        assets_dir = Path(__file__).resolve().parents[1] / "fmsh" / "frontend" / "dist" / "assets"
        js_file = assets_dir / "index-Cvmv7E2F.js"
        js_content = js_file.read_text(encoding="utf-8")

        # Must not contain hardcoded Portuguese status label in card badge
        self.assertNotIn("children:[e,n?` · em breve`:``]", js_content)

        # Must interpolate localized portal.soon translation key
        self.assertIn("s(`portal.soon`)", js_content)

    def test_locale_dictionaries_portal_soon(self):
        idiomas_dir = Path(__file__).resolve().parents[1] / "fmsh" / "idiomas"

        def get_key(locale: str, key: str) -> str:
            path = idiomas_dir / locale / "interface.txt"
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip()
            return ""

        self.assertEqual(get_key("en", "portal.soon"), "Coming soon")
        self.assertEqual(get_key("pt", "portal.soon"), "em breve")
        self.assertEqual(get_key("de", "portal.soon"), "bald")
        self.assertEqual(get_key("fr", "portal.soon"), "bientôt")
        self.assertEqual(get_key("es", "portal.soon"), "pronto")
        self.assertEqual(get_key("tr", "portal.soon"), "yakında")


if __name__ == "__main__":
    unittest.main()
