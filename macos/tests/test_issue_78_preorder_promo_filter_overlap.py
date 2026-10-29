"""Issue #78: Floating pre-order promotion must not cover filter dialog Apply button."""

from pathlib import Path
import subprocess
import unittest


class PreorderPromoFilterOverlapTests(unittest.TestCase):
    def test_filter_dialog_stacks_above_promo_badge_contract(self):
        script = Path(__file__).with_name("preorder_promo_filter_overlap_ui.mjs")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Pre-order promo and filter modal stacking contract passed", result.stdout)

    def test_shipped_assets_z_index_hierarchy(self):
        assets_dir = Path(__file__).resolve().parents[1] / "fmsh" / "frontend" / "dist" / "assets"
        js_file = assets_dir / "index-Cvmv7E2F.js"
        css_file = assets_dir / "index-iL5Te9Ln.css"

        js_content = js_file.read_text(encoding="utf-8")
        css_content = css_file.read_text(encoding="utf-8")

        # Promo badge must use z-30, not z-40
        self.assertIn("badge-oferta fixed right-3.5 z-30", js_content)
        self.assertNotIn("badge-oferta fixed right-3.5 z-40", js_content)

        # Advanced filter dialog modal must use z-50
        self.assertIn("fixed inset-0 z-50 flex items-center justify-center veu-modal p-4", js_content)

        # CSS must define z-index:30 for .badge-oferta
        self.assertIn(".badge-oferta{z-index:30;", css_content)


if __name__ == "__main__":
    unittest.main()
