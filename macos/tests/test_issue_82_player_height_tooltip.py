"""Issue #82: Player height tooltip must not expose [object Object] serialization."""

from pathlib import Path
import subprocess
import unittest


class PlayerHeightTooltipTests(unittest.TestCase):
    def test_player_height_tooltip_formatting_contract(self):
        script = Path(__file__).with_name("player_height_tooltip_ui.mjs")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Player height tooltip formatting contract passed", result.stdout)

    def test_shipped_bundle_static_contract(self):
        assets_dir = Path(__file__).resolve().parents[1] / "fmsh" / "frontend" / "dist" / "assets"
        js_file = assets_dir / "index-Cvmv7E2F.js"
        js_content = js_file.read_text(encoding="utf-8")

        # Must declare human-readable text fallback for height tooltip title
        self.assertIn("Xe?`${Xe} cm`:`—`", js_content)

        # Must use fallback parameter in title interpolation
        self.assertIn("et.map(([e,t,n,r])=>(0,z.jsxs)(`div`,{title:`${e}: ${n||r||t}`", js_content)

        # Legacy interpolation pattern must not be present
        self.assertNotIn("et.map(([e,t,n])=>(0,z.jsxs)(`div`,{title:`${e}: ${n||t}`", js_content)


if __name__ == "__main__":
    unittest.main()
