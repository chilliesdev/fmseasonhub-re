"""Standalone entry point, including a bounded packaging diagnostic."""

import multiprocessing
import sys


def check_bundle():
    import ctypes
    from pathlib import Path

    import moneyball
    import paths
    import webview.platforms.cocoa

    if not getattr(sys, "frozen", False):
        raise RuntimeError("This diagnostic requires the standalone app")
    bundle = Path(sys.executable).resolve().parents[2]
    runtime = Path(sys._MEIPASS).resolve()
    if not runtime.is_relative_to(bundle):
        raise RuntimeError("Python runtime is outside the app")
    if not Path(paths.resource_path("frontend", "dist", "index.html")).is_file():
        raise RuntimeError("Frontend assets are missing")
    if not moneyball.CATALOG:
        raise RuntimeError("Moneyball data is missing")
    bridge = ctypes.CDLL(str(runtime / "native" / "libfmsh_bridge.dylib"))
    bridge.fmsh_get_attached_pid.restype = ctypes.c_int
    if bridge.fmsh_get_attached_pid() != 0:
        raise RuntimeError("Native bridge is unexpectedly attached")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--check-bundle" in sys.argv[1:]:
        check_bundle()
    else:
        from app_main import main

        main()
