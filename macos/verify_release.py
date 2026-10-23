"""Verify a relocated standalone app without Python on its executable PATH."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request


def verify_app(app: Path):
    app = app.resolve()
    for entry in app.rglob("*"):
        if entry.is_symlink() and not entry.resolve(strict=True).is_relative_to(app):
            raise RuntimeError(f"External symlink in app: {entry}")
        if entry.is_file() and not entry.is_symlink():
            with entry.open("rb") as source:
                magic = source.read(4)
            if magic in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'):
                linked = subprocess.check_output(["otool", "-L", str(entry)], text=True)
                for line in linked.splitlines()[1:]:
                    dependency = line.strip().split(" (", 1)[0]
                    if not dependency.startswith(("@", "/usr/lib/", "/System/Library/")):
                        raise RuntimeError(f"External dependency in {entry}: {dependency}")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    launcher = app / "Contents" / "MacOS" / "FM Season Hub"
    with tempfile.TemporaryDirectory(prefix="fmsh-release-check-") as folder:
        root = Path(folder)
        env = {
            "HOME": str(root),
            "PATH": "",
            "FMSH_PASTA_DADOS": str(root / "data"),
            "FMSH_PASTA_LOCAL": str(root / "local"),
        }
        subprocess.run([str(launcher), "--check-bundle"], cwd=root, env=env,
                       check=True, timeout=45)
        with (root / "server.log").open("w+") as log:
            process = subprocess.Popen([str(launcher), "--server-only"], cwd=root,
                                       env=env, stdout=log, stderr=log)
            try:
                port_file = root / "data" / "porta_do_app"
                deadline = time.monotonic() + 45
                while not port_file.exists():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise RuntimeError("Packaged server failed to start:\n" + log.read())
                    time.sleep(0.2)
                base = f"http://127.0.0.1:{int(port_file.read_text())}"
                for route in ("/api/live", "/api/settings"):
                    with urllib.request.urlopen(base + route, timeout=5) as response:
                        if not isinstance(json.load(response), dict):
                            raise RuntimeError(f"Invalid packaged response: {route}")
                with urllib.request.urlopen(base, timeout=5) as response:
                    html = response.read().decode()
                script = re.search(r'src="(/assets/[^\"]+\.js)"', html)
                if not script:
                    raise RuntimeError("Packaged UI did not serve its JavaScript entry point")
                with urllib.request.urlopen(base + script.group(1), timeout=5) as response:
                    if len(response.read()) < 1000:
                        raise RuntimeError("Packaged JavaScript is incomplete")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print("Standalone dependencies, runtime, Cocoa, native bridge, API and frontend passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    verify_app(parser.parse_args().app)
