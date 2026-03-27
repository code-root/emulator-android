"""
mitmproxy addon — captures HTTP/HTTPS flows as structured JSON.

Run with mitmdump:
    mitmdump --listen-port 8888 -s /path/to/mitm_addon.py \
             --set addon_store=/tmp/mitm_flows_<device_id>.jsonl

Each completed flow is appended as one JSON line to the store file.
The network inspector API reads this file to serve structured data.

Flow record schema
------------------
{
  "id":           str,          # unique flow ID
  "timestamp":    float,        # Unix timestamp of request
  "method":       str,
  "url":          str,
  "host":         str,
  "path":         str,
  "scheme":       str,
  "status_code":  int | null,
  "content_type": str | null,
  "req_headers":  {str: str},   # request headers (lowercase keys)
  "resp_headers": {str: str},   # response headers (lowercase keys)
  "req_cookies":  {str: str},   # cookies from Cookie: header
  "resp_cookies": [{name, value, domain, path, ...}],
  "req_body_b64": str | null,   # base64 of request body (<=16 KB)
  "resp_body_b64":str | null,   # base64 of response body (<=16 KB)
  "error":        str | null,
}
"""
from __future__ import annotations

import base64
import json
import os
import time
from http.cookies import SimpleCookie
from typing import Any, Dict, Optional

_MAX_BODY = 16 * 1024  # 16 KB


def _truncate_b64(data: Optional[bytes]) -> Optional[str]:
    if not data:
        return None
    chunk = data[:_MAX_BODY]
    return base64.b64encode(chunk).decode("ascii")


def _parse_cookie_header(header: str) -> Dict[str, str]:
    sc = SimpleCookie()
    try:
        sc.load(header)
        return {k: v.value for k, v in sc.items()}
    except Exception:
        return {}


def _headers_dict(headers) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in headers.items():
        out[k.lower()] = v
    return out


class FlowCapture:
    """mitmproxy addon — one instance per mitmdump process."""

    def __init__(self):
        self._store_path: Optional[str] = None
        self._fh = None

    def load(self, loader):
        loader.add_option("addon_store", str, "", "Path to JSONL store file for captured flows")

    def configure(self, updates):
        if "addon_store" in updates:
            path = self.addon_store  # type: ignore[attr-defined]
            if path and path != self._store_path:
                self._store_path = path
                if self._fh:
                    try:
                        self._fh.close()
                    except Exception:
                        pass
                self._fh = open(path, "a", encoding="utf-8", buffering=1)

    def _append(self, record: Dict[str, Any]) -> None:
        if self._fh:
            try:
                self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._fh.flush()
            except Exception:
                pass

    def response(self, flow):  # noqa: ANN001
        """Called after a complete request+response cycle."""
        try:
            req = flow.request
            resp = flow.response

            req_headers = _headers_dict(req.headers)
            resp_headers = _headers_dict(resp.headers) if resp else {}

            # Request cookies from Cookie header
            req_cookies = _parse_cookie_header(req_headers.get("cookie", ""))

            # Response Set-Cookie headers
            resp_cookies = []
            if resp:
                for sc_header in resp.headers.get_all("set-cookie"):
                    sc = SimpleCookie()
                    try:
                        sc.load(sc_header)
                        for name, morsel in sc.items():
                            resp_cookies.append({
                                "name": name,
                                "value": morsel.value,
                                "domain": morsel.get("domain", ""),
                                "path": morsel.get("path", "/"),
                                "secure": bool(morsel.get("secure")),
                                "httponly": bool(morsel.get("httponly")),
                                "expires": morsel.get("expires", ""),
                            })
                    except Exception:
                        pass

            record: Dict[str, Any] = {
                "id":            flow.id,
                "timestamp":     req.timestamp_start or time.time(),
                "method":        req.method,
                "url":           req.pretty_url,
                "host":          req.pretty_host,
                "path":          req.path,
                "scheme":        req.scheme,
                "status_code":   resp.status_code if resp else None,
                "content_type":  resp_headers.get("content-type") if resp else None,
                "req_headers":   req_headers,
                "resp_headers":  resp_headers,
                "req_cookies":   req_cookies,
                "resp_cookies":  resp_cookies,
                "req_body_b64":  _truncate_b64(req.content),
                "resp_body_b64": _truncate_b64(resp.content) if resp else None,
                "error":         None,
            }
            self._append(record)
        except Exception as exc:
            self._append({"error": str(exc), "timestamp": time.time()})

    def error(self, flow):  # noqa: ANN001
        try:
            req = flow.request
            self._append({
                "id":        flow.id,
                "timestamp": req.timestamp_start or time.time() if req else time.time(),
                "method":    req.method if req else "",
                "url":       req.pretty_url if req else "",
                "host":      req.pretty_host if req else "",
                "path":      req.path if req else "",
                "scheme":    req.scheme if req else "",
                "status_code": None,
                "content_type": None,
                "req_headers": {},
                "resp_headers": {},
                "req_cookies": {},
                "resp_cookies": [],
                "req_body_b64": None,
                "resp_body_b64": None,
                "error": str(flow.error) if flow.error else "unknown error",
            })
        except Exception:
            pass


addons = [FlowCapture()]
