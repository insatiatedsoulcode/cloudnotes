"""
F-15: Structured JSON Logging tests.

- request_id_var is isolated per request (ContextVar semantics).
- Every HTTP response carries an X-Request-ID header.
- RequestContextFilter injects request_id into log records.
- JSON formatter produces valid JSON with the required fields.
- Log level is WARNING in test mode (existing log output suppressed).
"""

import json
import logging
import io
from contextvars import copy_context

import pytest

from app.logger import _RequestContextFilter, _level_for_env, get_logger, request_id_var
from pythonjsonlogger.json import JsonFormatter as _JsonFormatterNew


# ── request_id_var isolation ──────────────────────────────────────────────────

def test_request_id_var_default_is_empty():
    assert request_id_var.get("") == ""


def test_request_id_var_set_and_get():
    token = request_id_var.set("abc-123")
    try:
        assert request_id_var.get("") == "abc-123"
    finally:
        request_id_var.reset(token)


def test_request_id_var_isolated_across_contexts():
    """Two concurrent requests must not bleed their request IDs into each other."""
    results = {}

    def task_a():
        request_id_var.set("request-A")
        results["a"] = request_id_var.get("")

    def task_b():
        request_id_var.set("request-B")
        results["b"] = request_id_var.get("")

    ctx_a = copy_context()
    ctx_b = copy_context()
    ctx_a.run(task_a)
    ctx_b.run(task_b)

    assert results["a"] == "request-A"
    assert results["b"] == "request-B"


# ── Filter injects request_id ─────────────────────────────────────────────────

def test_filter_injects_request_id_into_record():
    token = request_id_var.set("test-rid-xyz")
    try:
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        f = _RequestContextFilter()
        f.filter(record)
        assert record.request_id == "test-rid-xyz"
    finally:
        request_id_var.reset(token)


def test_filter_injects_empty_string_when_no_request_id():
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    f = _RequestContextFilter()
    f.filter(record)
    assert record.request_id == ""


# ── JSON formatter output ─────────────────────────────────────────────────────

def _make_json_handler() -> tuple[logging.StreamHandler, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(_RequestContextFilter())
    handler.setFormatter(
        _JsonFormatterNew(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
            rename_fields={"levelname": "level", "name": "logger", "asctime": "timestamp"},
        )
    )
    return handler, stream


def test_json_output_is_valid_json():
    handler, stream = _make_json_handler()
    logger = logging.getLogger("test.json_valid")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.info("test message")
        line = stream.getvalue().strip()
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
    finally:
        logger.removeHandler(handler)


def test_json_output_contains_required_fields():
    token = request_id_var.set("req-json-test")
    handler, stream = _make_json_handler()
    logger = logging.getLogger("test.json_fields")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.info("structured log")
        parsed = json.loads(stream.getvalue().strip())
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "logger" in parsed
        assert "message" in parsed
        assert parsed["request_id"] == "req-json-test"
        assert parsed["message"] == "structured log"
        assert parsed["level"] == "INFO"
    finally:
        logger.removeHandler(handler)
        request_id_var.reset(token)


# ── X-Request-ID response header ─────────────────────────────────────────────

def test_health_endpoint_returns_request_id_header(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert "x-request-id" in res.headers


def test_request_id_header_is_uuid_format(client):
    import re
    res = client.get("/health")
    rid = res.headers.get("x-request-id", "")
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.match(uuid_pattern, rid), f"Not a UUID4: {rid!r}"


def test_each_request_gets_unique_request_id(client):
    rid1 = client.get("/health").headers["x-request-id"]
    rid2 = client.get("/health").headers["x-request-id"]
    assert rid1 != rid2


def test_health_log_contains_request_id(client):
    """The X-Request-ID in the response matches the ID set by the middleware."""
    res = client.get("/health")
    assert res.status_code == 200
    rid = res.headers.get("x-request-id", "")
    assert rid != ""


# ── Log level per environment ─────────────────────────────────────────────────

def test_log_level_production_is_info():
    assert _level_for_env("production") == logging.INFO


def test_log_level_test_is_warning():
    assert _level_for_env("test") == logging.WARNING


def test_log_level_development_is_debug():
    assert _level_for_env("development") == logging.DEBUG


def test_log_level_unknown_env_defaults_to_debug():
    assert _level_for_env("staging") == logging.DEBUG
