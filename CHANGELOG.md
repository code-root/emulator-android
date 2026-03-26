# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
