"""Build, relocate, verify and archive a standalone macOS application."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from build_mac_app import create_icns
from verify_release import verify_app

ROOT = Path(__file__).resolve().parent


def build_release(output: Path, build_number: str):
    if sys.platform != "darwin":
        raise RuntimeError("Build the app on macOS")
    if not build_number.isdecimal() or int(build_number) < 1:
        raise ValueError("Build number must be a positive integer")
    architecture = platform.machine()
    if architecture not in ("arm64", "x86_64"):
        raise RuntimeError(f"Unsupported architecture: {architecture}")
    output = output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    subprocess.run([
        "clang", "-arch", architecture, "-mmacosx-version-min=15.0", "-shared", "-O3",
        str(ROOT / "native" / "libfmsh_bridge.c"),
        "-o", str(output / "libfmsh_bridge.dylib"),
    ], check=True)
    create_icns(ROOT / "fmsh" / "frontend" / "dist" / "logo.png", output / "AppIcon.icns")
    if not (output / "AppIcon.icns").is_file():
        raise RuntimeError("App icon generation failed")
    env = dict(os.environ, FMSH_BUILD_ROOT=str(output), FMSH_BUILD_NUMBER=build_number)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
        "--distpath", str(output / "dist"), "--workpath", str(output / "work"),
        str(ROOT / "FMSeasonHub.spec"),
    ], env=env, check=True)
    installed = output / "relocated" / "FM Season Hub.app"
    installed.parent.mkdir()
    shutil.move(output / "dist" / "FM Season Hub.app", installed)
    verify_app(installed)
    archive = output / f"FMSeasonHub-macos-{architecture}.zip"
    subprocess.run([
        "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(installed), str(archive),
    ], check=True)
    unpacked = output / "unpacked"
    subprocess.run(["ditto", "-x", "-k", str(archive), str(unpacked)], check=True)
    verify_app(unpacked / "FM Season Hub.app")
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
    metadata = {
        "architecture": architecture,
        "minimum_macos": "15.0",
        "build_number": build_number,
        "commit": os.environ.get("GITHUB_SHA") or subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "signing": "ad-hoc (not notarized)",
    }
    (output / f"FMSeasonHub-macos-{architecture}.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Release archive: {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--build-number", default="1")
    args = parser.parse_args()
    build_release(args.output, args.build_number)
