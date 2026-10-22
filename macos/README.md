# Local macOS app

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
