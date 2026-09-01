"""Unit tests for ``app._AccessLogFilter``.

The filter is attached to gunicorn's + werkzeug's access loggers to drop
zero-signal request lines (static assets, health pings, 304s) while keeping
every real API/page hit and all 4xx/5xx. Records are synthesized with the
final rendered access line as ``msg`` (args=None), since the filter matches on
``record.getMessage()``.
"""

from __future__ import annotations

import logging

from app import _AccessLogFilter

_FILTER = _AccessLogFilter()


def _rec(line: str) -> logging.LogRecord:
    return logging.LogRecord("gunicorn.access", logging.INFO, __file__, 0, line, None, None)


def _line(method: str, path: str, status: int) -> str:
    return (
        f'1.2.3.4 - - [23/Jun/2026:13:01:31 +0000] "{method} {path} HTTP/1.1" {status} 99 "-" "ua"'
    )


def test_drops_static_asset_success():
    assert not _FILTER.filter(_rec(_line("GET", "/assets/index-B7j78V_y.js", 200)))


def test_drops_health_check():
    assert not _FILTER.filter(_rec(_line("GET", "/healthz", 200)))


def test_drops_not_modified():
    assert not _FILTER.filter(_rec(_line("GET", "/index.html", 304)))


def test_drops_bare_favicon():
    assert not _FILTER.filter(_rec(_line("GET", "/favicon.ico", 200)))


def test_keeps_real_api_hit():
    assert _FILTER.filter(_rec(_line("GET", "/api/public/reciters?limit=500", 200)))


def test_keeps_mutation():
    assert _FILTER.filter(_rec(_line("POST", "/api/seg/save", 200)))


def test_keeps_error_even_on_noise_path():
    # A 404/500 always surfaces, even for an otherwise-suppressed asset path.
    assert _FILTER.filter(_rec(_line("GET", "/assets/missing.js", 404)))
    assert _FILTER.filter(_rec(_line("GET", "/healthz", 503)))


def test_keeps_non_access_record():
    # A werkzeug warning that isn't an access line passes through untouched.
    assert _FILTER.filter(_rec("WARNING: something happened"))
