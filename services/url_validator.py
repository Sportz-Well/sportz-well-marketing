"""URL reachability validator for the Researcher agent.

Uses HEAD first (no body download), falls back to GET with stream=True when
the server rejects HEAD (HTTP 405/501). Follows redirects automatically.

Public API
----------
validate_url(url, timeout=5) -> dict
    ok          bool         True if the final response is HTTP 2xx
    status_code int | None   Final HTTP status code
    final_url   str          URL after following redirects
    status      str          "ok" | "broken" | "redirected" | "timeout" | "unchecked"
    error       str | None   Error message when ok=False
"""

from __future__ import annotations

import requests
from requests.exceptions import ConnectionError as ReqConnectionError, Timeout

_HEADERS = {
    "User-Agent": "SportzWell-ResearchAgent/1.0 (link-validation; not scraping)"
}


def validate_url(url: str, timeout: int = 5) -> dict:
    """Check whether *url* resolves to a reachable page.

    HEAD is tried first; if the server rejects it (405/501), a streaming GET
    is made instead so no body is downloaded.
    """
    if not url or not url.startswith(("http://", "https://")):
        return {
            "ok": False,
            "status_code": None,
            "final_url": url or "",
            "status": "unchecked",
            "error": "No valid HTTP/HTTPS URL provided",
        }

    # Codes on HEAD that mean "try GET instead"
    _HEAD_RETRY_ON = {403, 405, 406, 429, 501}

    try:
        resp = requests.head(
            url, headers=_HEADERS, timeout=timeout, allow_redirects=True
        )

        if resp.status_code in _HEAD_RETRY_ON:
            resp = requests.get(
                url,
                headers=_HEADERS,
                timeout=timeout + 3,
                allow_redirects=True,
                stream=True,
            )
            resp.close()

        final_url      = resp.url
        was_redirected = final_url.rstrip("/") != url.rstrip("/")
        sc             = resp.status_code

        # 403 on GET = bot-blocked but server is alive (URL is real)
        if sc == 403:
            return {
                "ok": True,
                "status_code": 403,
                "final_url": final_url,
                "status": "redirected" if was_redirected else "ok",
                "error": None,
            }

        ok = 200 <= sc < 300
        if ok:
            status = "redirected" if was_redirected else "ok"
        else:
            status = "broken"

        return {
            "ok": ok,
            "status_code": sc,
            "final_url": final_url,
            "status": status,
            "error": None if ok else f"HTTP {sc}",
        }

    except Timeout:
        return {
            "ok": False,
            "status_code": None,
            "final_url": url,
            "status": "timeout",
            "error": "Request timed out",
        }
    except ReqConnectionError as exc:
        return {
            "ok": False,
            "status_code": None,
            "final_url": url,
            "status": "broken",
            "error": f"Connection error: {str(exc)[:120]}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "final_url": url,
            "status": "broken",
            "error": f"Unexpected error: {str(exc)[:120]}",
        }
