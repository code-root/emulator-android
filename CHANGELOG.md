# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Fingerprint hub (`/api/fingerprint/*`), `extended_json`, revision snapshots / revert / compare, consistency checks on apply.
- Samsung-oriented AVD `config.ini` overlay (`medium_phone` + Samsung manufacturer/LCD); sync on fingerprint updates and on start.
- SAMFW Odin folder merge (e.g. XSG) with product-segment tweak; `backend/tests/test_firmware_xsg.py`.
- Device create: optional `firmware_package`; UI firmware dropdown; default Samsung G996B preset.
- Auto fingerprint + anti-detect apply after emulator boot; anti-detect CPU/characteristics improvements; Frida templates under `scripts/frida/`.
- Optional H.264 WebSocket path (where enabled); touch **auto** mode on device screen; App Store install UX tweaks.
- **README:** “Recent updates (March 2026)” (EN + AR) documenting the above.

## [1.0.1] — 2026-03-26

### Added

- Root **`pyproject.toml`**: Python package **`emulator-android-farm`** (`pip install .`).
- **`VERSION`** file and **`CHANGELOG.md`**.
- **GitHub Actions `release.yml`**: on tag `v*`, attach source tarball (`package_release.sh`) + wheel to GitHub Release.
- CI job **packaging**: validates `python -m build --wheel` on every push/PR.

[1.0.1]: https://github.com/code-root/emulator-android/releases/tag/v1.0.1

## [1.0.0] — 2026-03-26

### Added

- FastAPI backend: devices, AVD/emulator control, ADB tools, fingerprints, APK store, proxy, WebSocket live screen (JPEG), operation logs.
- React (Vite) frontend: dashboard, devices, device detail, App Store, auth (JWT).
- Docker Compose stack (Postgres, Redis, Nginx, backend, frontend).
- SAMFW firmware discovery and fingerprint alignment presets.
- GitHub Actions CI (backend, frontend, compose validate).
- GitHub Actions **Release** workflow: source tarball with built frontend (`dist/emulator-android-<version>.tar.gz`).
- Root **`pyproject.toml`**: install backend as Python distribution `emulator-android-farm` (`pip install .` from repo root).
- **`VERSION`** file as single source for release tarball naming when no git tag override.

[1.0.0]: https://github.com/code-root/emulator-android/releases/tag/v1.0.0
