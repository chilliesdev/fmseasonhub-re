"""Build, relocate and verify a standalone macOS app in a DMG installer."""

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
from verify_release import verify_app, verify_dmg

ROOT = Path(__file__).resolve().parent


def create_dmg(app: Path, output: Path, architecture: str) -> Path:
    staging = output / "dmg-content"
    staging.mkdir()
    subprocess.run(["ditto", str(app), str(staging / app.name)], check=True)
    (staging / "Applications").symlink_to("/Applications", target_is_directory=True)
    shutil.copyfile(ROOT / "INSTALL.txt", staging / "INSTALL.txt")
    image = output / f"FMSeasonHub-macos-{architecture}.dmg"
    subprocess.run([
        "hdiutil", "create", "-volname", "FM Season Hub", "-srcfolder", str(staging),
        "-fs", "HFS+", "-format", "UDZO", str(image),
    ], check=True)
    verify_dmg(image)
    return image


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
    archive = create_dmg(installed, output, architecture)
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    archive.with_suffix(".dmg.sha256").write_text(f"{digest}  {archive.name}\n")
    metadata = {
        "architecture": architecture,
        "format": "dmg",
        "minimum_macos": "15.0",
        "build_number": build_number,
        "commit": os.environ.get("GITHUB_SHA") or subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "signing": "ad-hoc (not notarized)",
    }
    (output / f"FMSeasonHub-macos-{architecture}.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Release installer: {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--build-number", default="1")
    args = parser.parse_args()
    build_release(args.output, args.build_number)
