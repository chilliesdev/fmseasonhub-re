"""Regression checks for the Python runtime selected by an installed app."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MACOS_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_mac_app", MACOS_DIR / "build_mac_app.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class MacPackagingTests(unittest.TestCase):
    def test_existing_destinations_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("user-data", "Existing.app"):
                with self.subTest(name=name):
                    output = root / name
                    output.mkdir()
                    sentinel = output / "keep.txt"
                    sentinel.write_text("preserve me")
                    with self.assertRaises((ValueError, FileExistsError)):
                        builder.build_app(output=output)
                    self.assertEqual(sentinel.read_text(), "preserve me")
            link = root / "Linked.app"
            link.symlink_to(root / "Existing.app", target_is_directory=True)
            with self.assertRaises(FileExistsError):
                builder.build_app(output=link)
            self.assertTrue(link.is_symlink())

    def test_missing_runtime_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "New.app"
            with patch.object(builder, "SCRIPT_DIR", root):
                with self.assertRaisesRegex(RuntimeError, "Incomplete macOS runtime"):
                    builder.build_app(output=output)
            self.assertFalse(output.exists())

    @unittest.skipUnless(sys.platform == "darwin", "Requires macOS Cocoa runtime")
    def test_relocated_launcher_uses_packaged_window_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "src"
            source.mkdir()
            (source / "app_main.py").write_text(
                builder.RUNTIME_IMPORTS + "\nimport sys\nprint(sys.prefix)\n"
            )
            assets = root / "assets"
            assets.mkdir()
            output = root / "Build.app"
            with patch.object(builder, "SRC_DIR", source), patch.object(builder, "FMSH_DIR", assets):
                builder.build_app(output=output)
            installed = root / "Installed App.app"
            shutil.move(output, installed)
            launcher = installed / "Contents/MacOS/FM Season Hub"
            env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
            result = subprocess.run([str(launcher)], env=env, check=True, capture_output=True, text=True)
            self.assertEqual(Path(result.stdout.strip()).resolve(), (installed / "Contents/Resources/.venv").resolve())
            # A missing packaged runtime must never select a global Python.
            shutil.rmtree(installed / "Contents/Resources/.venv")
            result = subprocess.run([str(launcher)], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("bundled Python is unavailable", result.stderr)
