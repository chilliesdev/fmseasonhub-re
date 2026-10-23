"""Build one native-architecture app with an embedded Python runtime."""

import os
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH)
build_root = Path(os.environ["FMSH_BUILD_ROOT"])
analysis = Analysis(
    [str(root / "release_entry.py")],
    pathex=[str(root / "src")],
    binaries=[(str(build_root / "libfmsh_bridge.dylib"), "native")],
    datas=[(str(root / "fmsh"), "fmsh")] + copy_metadata("pywebview"),
    hiddenimports=[path.stem for path in (root / "src").glob("*.py")]
    + ["webview.platforms.cocoa"] + collect_submodules("uvicorn"),
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="FM Season Hub",
    console=False,
    target_arch=platform.machine(),
)
collection = COLLECT(
    executable, analysis.binaries, analysis.datas, name="FM Season Hub"
)
app = BUNDLE(
    collection,
    name="FM Season Hub.app",
    icon=str(build_root / "AppIcon.icns"),
    bundle_identifier="com.fmseasonhub.app",
    version="0.8.2",
    info_plist={
        "CFBundleVersion": os.environ.get("FMSH_BUILD_NUMBER", "1"),
        "LSMinimumSystemVersion": "15.0",
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
    },
)
