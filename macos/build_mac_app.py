#!/usr/bin/env python3
"""
FM Season Hub - macOS Application Bundle Builder
Packages the Python 3.14 FastAPI backend, web assets, and runtime
into a local 'FM Season Hub.app' bundle (requires the source Python installation).
"""

import argparse
import shutil
import plistlib
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SRC_DIR = SCRIPT_DIR / "src"
FMSH_DIR = SCRIPT_DIR / "fmsh"
DIST_APP_DIR = SCRIPT_DIR / "dist" / "FM Season Hub.app"

INFO_PLIST_DATA = {
    "CFBundleName": "FM Season Hub",
    "CFBundleDisplayName": "FM Season Hub",
    "CFBundleIdentifier": "com.fmseasonhub.app",
    "CFBundleVersion": "1.0.0",
    "CFBundleShortVersionString": "1.0.0",
    "CFBundlePackageType": "APPL",
    "CFBundleSignature": "????",
    "CFBundleExecutable": "FM Season Hub",
    "CFBundleIconFile": "AppIcon",
    "LSMinimumSystemVersion": "11.0",
    "NSHighResolutionCapable": True,
    "NSSupportsAutomaticGraphicsSwitching": True,
    "LSUIElement": False,
    "NSRequiresAquaSystemAppearance": False,
}

LAUNCHER_SCRIPT = """#!/usr/bin/env bash
# macOS Application Bundle Entrypoint
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCES="$DIR/Resources"

# Use only the validated dependency environment packaged by the builder.
PYTHON_BIN="$RESOURCES/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    echo "FM Season Hub: bundled Python is unavailable. Restore its Python installation or rebuild the app." >&2
    exit 1
fi

unset PYTHONHOME
export PYTHONNOUSERSITE=1
export PYTHONPATH="$RESOURCES/src"
export PYTHONUNBUFFERED=1

ENTRYPOINT="$RESOURCES/src/app_main.py"
if [ ! -f "$ENTRYPOINT" ]; then
    ENTRYPOINT="$RESOURCES/src/server.py"
fi

exec "$PYTHON_BIN" "$ENTRYPOINT" "$@"
"""

def create_icns(source_png: Path, dest_icns: Path):
    """Convert PNG to Apple ICNS using sips and iconutil if available."""
    if not source_png.exists():
        return
    iconset_dir = dest_icns.parent / "AppIcon.iconset"
    iconset_dir.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 64, 128, 256, 512]
    try:
        for s in sizes:
            subprocess.run(
                ["sips", "-z", str(s), str(s), str(source_png), "--out", str(iconset_dir / f"icon_{s}x{s}.png")],
                capture_output=True,
            )
            subprocess.run(
                ["sips", "-z", str(s * 2), str(s * 2), str(source_png), "--out", str(iconset_dir / f"icon_{s}x{s}@2x.png")],
                capture_output=True,
            )
        subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(dest_icns)], capture_output=True)
    except Exception as e:
        print(f"Warning: Could not generate .icns: {e}")
    finally:
        if iconset_dir.exists():
            shutil.rmtree(iconset_dir)

RUNTIME_IMPORTS = "import uvicorn, fastapi, webview, psutil; import webview.platforms.cocoa"


def validate_runtime(runtime: Path):
    """Check the native window backend, not just the top-level webview package."""
    try:
        subprocess.run(
            [str(runtime / "bin" / "python"), "-I", "-c", RUNTIME_IMPORTS],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise RuntimeError(f"Incomplete macOS runtime at {runtime}:\n{detail}") from exc


def build_app(include_venv: bool = True, output: Path = DIST_APP_DIR):
    print("=== Building FM Season Hub.app ===")
    if not include_venv:
        raise ValueError("A dependency environment is required for a working app bundle")
    output = output.absolute()
    if output.suffix != ".app":
        raise ValueError("Output must be a new .app bundle directory")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Output already exists; choose a new build path: {output}")
    source_runtime = SCRIPT_DIR / ".venv"
    validate_runtime(source_runtime)
    # Reserve a new destination exclusively. Never remove an existing output.
    output.mkdir(parents=True, exist_ok=False)

    contents_dir = output / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"

    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Preserve interpreter links; this local bundle still needs the source Python.
    bundled_runtime = resources_dir / ".venv"
    shutil.copytree(source_runtime, bundled_runtime, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    validate_runtime(bundled_runtime)

    # 1. Write Info.plist
    plist_path = contents_dir / "Info.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(INFO_PLIST_DATA, f)
    print(f"[1/5] Created Info.plist at {plist_path}")

    # 2. Write executable launcher
    launcher_path = macos_dir / "FM Season Hub"
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write(LAUNCHER_SCRIPT)
    launcher_path.chmod(0o755)
    print(f"[2/5] Created launcher executable at {launcher_path}")

    # 3. Copy python sources
    res_src = resources_dir / "src"
    shutil.copytree(SRC_DIR, res_src, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"[3/5] Bundled Python sources to {res_src}")

    # 4. Copy fmsh assets & frontend
    res_fmsh = resources_dir / "fmsh"
    shutil.copytree(FMSH_DIR, res_fmsh, ignore=shutil.ignore_patterns(".git*", "*.tmp"))
    print(f"[4/5] Bundled assets and frontend to {res_fmsh}")

    # 5. Icons and metadata
    icon_src = FMSH_DIR / "frontend" / "dist" / "logo.png"
    icon_dst = resources_dir / "AppIcon.icns"
    if icon_src.exists():
        create_icns(icon_src, icon_dst)

    # 6. Copy native bridge dylib
    res_native = resources_dir / "native"
    if (SCRIPT_DIR / "native").exists():
        shutil.copytree(SCRIPT_DIR / "native", res_native, ignore=shutil.ignore_patterns("*.o", "*.c"))
        print(f"[6/6] Bundled native bridge dylib to {res_native}")

    print(f"[Done] App bundle created successfully at:\n  -> {output}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-venv", action="store_true",
                        help="Compatibility option; the dependency environment is always included")
    parser.add_argument("--output", type=Path, default=DIST_APP_DIR)
    args = parser.parse_args()
    build_app(output=args.output)
