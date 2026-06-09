"""Unit tests for Marko's failure-notification slice.

No AWS / boto3 / network: the handler dry-runs when no webhook is configured,
and the pure helpers in ``notify`` are exercised directly. The one test that
covers the send path stubs ``handler._post`` so no real request is made.

    pytest tests/test_notifications.py
    python tests/test_notifications.py
"""

from __future__ import annotations

import contextlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "lambda", "notifications")
sys.path.insert(0, SRC)

import notify  # noqa: E402
import handler  # noqa: E402


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


def test_parse_step_functions_event():
    n = notify.parse_event(SF_FAILED)
    assert n["kind"] == "step_functions"
    assert n["status"] == "FAILED"
    assert n["state_machine"] == "aws-social-ingestor-dev-medallion-pipeline"
    assert n["execution"] == "run-42"


def test_sf_failure_statuses_detected():
    for status in ("FAILED", "TIMED_OUT", "ABORTED"):
        ev = {"detail": {"stateMachineArn": "x", "status": status}}
        assert notify.is_failure(notify.parse_event(ev)) is True


def test_sf_non_failure_ignored():
    for status in ("SUCCEEDED", "RUNNING"):
        ev = {"detail": {"stateMachineArn": "x", "status": status}}
        assert notify.is_failure(notify.parse_event(ev)) is False


def test_generic_failure_default_true():
    assert notify.is_failure(notify.parse_event({"message": "disk full"})) is True


def test_generic_success_false():
    assert notify.is_failure(notify.parse_event({"status": "OK"})) is False


def test_build_discord_payload_shape():
    _, payload, _ = notify.build_message(SF_FAILED)
    assert payload["embeds"]
    embed = payload["embeds"][0]
    assert embed["color"] == notify.COLOR_FAILURE
    names = [f["name"] for f in embed["fields"]]
    assert "Status" in names
    assert "medallion-pipeline" in embed["title"]


def test_build_message_skips_non_failure():
    should, payload, _ = notify.build_message(
        {"detail": {"stateMachineArn": "x", "status": "SUCCEEDED"}}
    )
    assert should is False
    assert payload is None


def test_handler_dry_run_when_no_webhook():
    with env(NOTIFICATION_WEBHOOK_URL=None, NOTIFICATION_WEBHOOK_SECRET_ARN=None):
        body = handler.lambda_handler(SF_FAILED, None)["body"]
    assert body["sent"] is False
    assert body["dry_run"] is True
    assert body["payload"]["embeds"][0]["title"]


def test_handler_skips_success_event():
    ok = {"detail": {"stateMachineArn": "x", "status": "SUCCEEDED"}}
    with env(NOTIFICATION_WEBHOOK_URL=None, NOTIFICATION_WEBHOOK_SECRET_ARN=None):
        body = handler.lambda_handler(ok, None)["body"]
    assert body["sent"] is False
    assert body["reason"] == "event is not a failure"


def test_handler_posts_when_webhook_set():
    sent = {}

    def fake_post(url, payload, timeout=10):
        sent["url"] = url
        sent["payload"] = payload
        return 204

    original = handler._post
    handler._post = fake_post
    try:
        with env(NOTIFICATION_WEBHOOK_URL="https://discord.test/webhook/abc"):
            body = handler.lambda_handler(SF_FAILED, None)["body"]
    finally:
        handler._post = original

    assert body["sent"] is True
    assert body["webhook_status"] == 204
    assert sent["url"] == "https://discord.test/webhook/abc"
    assert sent["payload"]["embeds"]


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
