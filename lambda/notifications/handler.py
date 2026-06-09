"""Failure-notification Lambda (Marko's slice).

Thin wrapper around ``notify.py``:

  1. Parse the incoming failure event.
  2. If it is a failure, resolve the chat webhook (from Secrets Manager, or a
     direct ``NOTIFICATION_WEBHOOK_URL`` override for local testing).
  3. POST the message to the webhook.

Triggered by an EventBridge "Step Functions Execution Status Change" rule for
the pipeline state machine (``FAILED`` / ``TIMED_OUT`` / ``ABORTED``). Can also
be invoked directly with a generic ``{"status": "...", "message": "..."}``
payload.

``boto3`` is imported lazily so the module imports (and unit tests run) without
boto3 or AWS credentials. The webhook URL is never logged.
"""

from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

import notify


def _resolve_webhook_url(env):
    """Return the webhook URL, or ``None`` when not configured (dry run).

    Precedence: an explicit ``NOTIFICATION_WEBHOOK_URL`` (handy for local tests),
    then the Secrets Manager secret named by ``NOTIFICATION_WEBHOOK_SECRET_ARN``.
    """
    direct = env.get("NOTIFICATION_WEBHOOK_URL")
    if direct:
        return direct.strip()

    secret_arn = env.get("NOTIFICATION_WEBHOOK_SECRET_ARN")
    if not secret_arn:
        return None

    import boto3  # lazy: only needed for the real send path

    client = boto3.client("secretsmanager")
    value = client.get_secret_value(SecretId=secret_arn).get("SecretString")
    if not value:
        return None
    value = value.strip()
    # The secret may hold either the raw URL or a small JSON object.
    if value.startswith("{"):
        try:
            data = json.loads(value)
            value = data.get("webhook_url") or data.get("url") or ""
        except json.JSONDecodeError:
            pass
    return value.strip() or None


def _post(url, payload, timeout=10):
    """POST ``payload`` as JSON to ``url`` and return the HTTP status code."""
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - trusted webhook host
        return response.getcode()


def lambda_handler(event, context=None):
    env = os.environ
    platform = env.get("NOTIFICATION_PLATFORM", "discord")

    should_send, payload, normalized = notify.build_message(event, platform=platform)

    if not should_send:
        return {
            "statusCode": 200,
            "body": {
                "sent": False,
                "reason": "event is not a failure",
                "status": normalized.get("status"),
            },
        }

    url = _resolve_webhook_url(env)
    if not url:
        # Dry run: nowhere configured to send, but report what *would* be sent.
        return {
            "statusCode": 200,
            "body": {
                "sent": False,
                "dry_run": True,
                "reason": "no webhook configured",
                "payload": payload,
            },
        }

    status_code = _post(url, payload)
    return {
        "statusCode": 200,
        "body": {
            "sent": True,
            "platform": platform,
            "webhook_status": status_code,
            "summary": payload["embeds"][0]["title"],
        },
    }


if __name__ == "__main__":
    sample = {
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
    print(json.dumps(lambda_handler(sample, None)["body"], indent=2, default=str))
