# macOS app

## Install a release

Download from [GitHub Releases](https://github.com/chilliesdev/fmseasonhub-re/releases).
Requires macOS 15 or later.

- Apple Silicon (M-series): `FMSeasonHub-macos-arm64.dmg`.
- Intel: `FMSeasonHub-macos-x86_64.dmg`.

Open the DMG and quit any older copy of the app. Drag **FM Season Hub.app** to the
**Applications** shortcut in the disk image. Eject the DMG, then open the app from
Applications. Python and all app dependencies are included. Keep your existing
`~/Documents/FM Season Hub` data folder.

The app has an ad-hoc signature, but no Apple Developer ID signature or notarization.
The DMG does not remove Apple's security warning. If macOS says **Apple could not
verify the app**, click **Done**. Then use **System Settings → Privacy & Security →
Open Anyway** to approve this app, and confirm **Open**. See [Apple's
instructions](https://support.apple.com/102445). A Developer ID and Apple
notarization credentials are needed to remove this first-open step.

Each DMG has a matching `.dmg.sha256` file and `.json` build record. To verify a
download, place the DMG and checksum in the same folder, then run:

```sh
shasum -a 256 -c FMSeasonHub-macos-arm64.dmg.sha256
```

Use the `x86_64` filename for Intel.

## Connect to Football Manager

Open Football Manager and load a save before you select **Connect**. The app
checks the running process, memory access, and loaded save before it reports ready.
If the game is closed, access is denied, or no save is loaded, follow the error
message and try again. Capture stays disabled until the connection is ready.

Save ID and game date come from the loaded save. Fields that cannot be verified
stay empty. Disconnect, game exit, or a changed save clears the live connection;
select **Connect** again after you load the required save.

## Build a standalone release

On macOS 15 or later, use Python 3.14 for the target architecture:

```sh
python3.14 -m venv macos/.venv
macos/.venv/bin/python -m pip install -r macos/requirements-build.txt
macos/.venv/bin/python macos/build_release.py --output .tmp/release-build --build-number 1
```

Choose a new output directory for each build. The builder compiles the native
bridge, freezes Python and dependencies with PyInstaller, moves the app, verifies
its signature and internal links, imports Cocoa, and checks the packaged API and
frontend with no Python on PATH. It creates a compressed DMG with an Applications
shortcut and install instructions, mounts it read-only, copies the app to a new
test Applications folder, ejects the image, and repeats the app checks. It then
writes the checksum and build record. To verify a downloaded DMG with the same checks:

```sh
macos/.venv/bin/python macos/verify_release.py /path/to/FMSeasonHub-macos-arm64.dmg
```

Build each architecture on its matching Mac; CI checks both before publishing.

## Local development bundle

The tracked `fmsh/frontend/dist` files are the existing prebuilt runtime assets.
This repository has no frontend build source. CI uses these files for the web UI
and app icon; keep them available in a fresh checkout.

From the repository root on macOS, prepare Python 3.14 and the pinned dependencies:

```sh
python3.14 -m venv macos/.venv
macos/.venv/bin/python -m pip install -r macos/requirements.txt
macos/.venv/bin/python -m pip check
clang -arch arm64 -arch x86_64 -shared -O3 macos/native/libfmsh_bridge.c -o macos/native/libfmsh_bridge.dylib
```

Build with the prepared `macos/.venv` environment:

```sh
macos/.venv/bin/python macos/build_mac_app.py
```

Output: `macos/dist/FM Season Hub.app`. Use `--output '/path/FM Season Hub.app'`
for a separate test build. The destination must be a new `.app` directory. Existing
outputs and symlinks are refused; the builder never deletes an existing app. `--include-venv` remains accepted; all builds now include
that environment. The build checks FastAPI, Uvicorn, psutil, pywebview and its Cocoa backend
in both the source and copied environment. Missing dependencies stop the build.
Run the builder in a macOS desktop session where Cocoa can load.

This is a local bundle, not a standalone distribution. The copied environment
retains interpreter links to the source Python installation (currently Homebrew
Python 3.14 on this Mac). Keep that Python installation available. A different
Mac, architecture or removed Python installation requires a new environment and
rebuild. Do not use this bundle as a portable release.

The launcher uses only the packaged environment. It does not fall back to a global
Python installation with unknown dependencies. After validation, quit the old app,
keep a backup of it, and copy the new app to Applications. Keep the existing
`~/Documents/FM Season Hub` data folder intact.

Run macOS tests with isolated data:

```sh
FMSH_PASTA_DADOS=/private/tmp/fmsh-tests-data \
FMSH_PASTA_LOCAL=/private/tmp/fmsh-tests-local \
macos/.venv/bin/python -m unittest discover -s macos/tests -v
```

These tests need local socket and Cocoa access. The packaging test moves a bundle
and checks its real launcher with a minimal PATH, including native window imports.
