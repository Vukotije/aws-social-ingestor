"""Integration test: the notifications Lambda performs a REAL HTTP POST.

Unlike test_notifications.py (which stubs ``handler._post``), this stands up a
local HTTP server, points the Lambda's webhook at it, and asserts the server
actually receives the Discord payload over the wire. Exercises the real urllib
send path end to end. Pure stdlib; runnable with or without pytest.

    pytest tests/test_integration_notifications_http.py
    python tests/test_integration_notifications_http.py
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "lambda", "notifications")
sys.path.insert(0, SRC)

import handler  # noqa: E402

SF_FAILED = {
    "detail-type": "Step Functions Execution Status Change",
    "source": "aws.states",
    "region": "eu-central-1",
    "account": "123456789012",
    "time": "2026-06-09T02:05:00Z",
    "detail": {
        "stateMachineArn": "arn:aws:states:eu-central-1:123456789012:stateMachine:aws-social-ingestor-dev-medallion-pipeline",
        "executionArn": "arn:aws:states:eu-central-1:123456789012:execution:aws-social-ingestor-dev-medallion-pipeline:run-42",
        "name": "run-42",
        "status": "FAILED",
        "error": "PipelineFailed",
        "cause": "A pipeline task failed.",
    },
}

_received = []


class _Capture(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _received.append({
            "path": self.path,
            "content_type": self.headers.get("Content-Type"),
            "body": body,
        })
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):  # keep test output quiet
        pass


@contextlib.contextmanager
def _server():
    httpd = HTTPServer(("127.0.0.1", 0), _Capture)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        yield "http://{0}:{1}/webhook/abc".format(host, port)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@contextlib.contextmanager
def env(**overrides):
    saved = {k: os.environ.get(k) for k in overrides}
    try:
        for k, v in overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_real_post_delivers_discord_payload():
    _received.clear()
    with _server() as url:
        with env(NOTIFICATION_WEBHOOK_URL=url, NOTIFICATION_WEBHOOK_SECRET_ARN=None):
            body = handler.lambda_handler(SF_FAILED, None)["body"]

    assert body["sent"] is True
    assert body["webhook_status"] == 204
    assert len(_received) == 1, "expected exactly one webhook POST"

    req = _received[0]
    assert req["path"] == "/webhook/abc"
    assert req["content_type"] == "application/json"
    payload = json.loads(req["body"])
    assert payload["username"] == "Pipeline Monitor"
    assert payload["embeds"][0]["color"] == 15158332
    assert "failed" in payload["embeds"][0]["title"]


def test_success_event_sends_nothing_over_the_wire():
    _received.clear()
    ok = {"detail": {"stateMachineArn": "x", "status": "SUCCEEDED"}}
    with _server() as url:
        with env(NOTIFICATION_WEBHOOK_URL=url, NOTIFICATION_WEBHOOK_SECRET_ARN=None):
            body = handler.lambda_handler(ok, None)["body"]

    assert body["sent"] is False
    assert _received == [], "no POST should be made for a successful execution"


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for func in funcs:
        func()
        passed += 1
        print("ok  - {0}".format(func.__name__))
    print("\n{0} passed".format(passed))


if __name__ == "__main__":
    _run_all()
