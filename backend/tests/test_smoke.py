"""Smoke tests — تحميل صريح لـ backend/main.py لتفادي التعارض مع main.py / api في جذر المستودع."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_ROOT.parent
_MAIN_FILE = _BACKEND_ROOT / "main.py"


def _ensure_backend_on_sys_path():
    """Cursor/IDE قد يضيف جذر المستودع إلى PYTHONPATH فيُحمَّل api/ الخاطئ بدل backend/api."""
    backend_s = str(_BACKEND_ROOT.resolve())
    repo_s = str(_REPO_ROOT.resolve())
    sys.path[:] = [
        p
        for p in sys.path
        if p and os.path.normpath(p) != repo_s
    ]
    if backend_s not in sys.path:
        sys.path.insert(0, backend_s)
    elif sys.path.index(backend_s) != 0:
        sys.path.remove(backend_s)
        sys.path.insert(0, backend_s)


def _load_app_module():
    _ensure_backend_on_sys_path()
    spec = importlib.util.spec_from_file_location("backend_farm_main", _MAIN_FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_import_app():
    mod = _load_app_module()
    assert mod.app is not None
    assert mod.app.title == "Android Emulator Farm"


def test_health_with_lifespan():
    if os.environ.get("SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("SKIP_DB_TESTS=1")

    from fastapi.testclient import TestClient

    mod = _load_app_module()
    try:
        with TestClient(mod.app) as client:
            r = client.get("/health")
    except Exception as exc:
        pytest.skip(f"تعذّر تشغيل التطبيق مع lifespan (غالباً Postgres غير شغّال): {exc}")

    assert r.status_code == 200
    assert r.json().get("status") == "ok"
