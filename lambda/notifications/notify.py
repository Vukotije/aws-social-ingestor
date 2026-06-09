"""Failure-notification logic for the medallion pipeline (Marko's slice).

Pure, AWS-free helpers that turn a job-failure event into a chat-platform
message payload. The Lambda handler in ``handler.py`` is the thin wrapper that
resolves the webhook secret and performs the HTTP POST.

Primary trigger: an EventBridge "Step Functions Execution Status Change" event
for the pipeline state machine, fired when an execution ends in
``FAILED`` / ``TIMED_OUT`` / ``ABORTED``. The same helpers also accept a generic
``{"status": ..., "message": ...}`` event so the notifier can be reused for
direct Lambda/alarm failures.

No boto3 and no network here, so every helper is unit testable in isolation.
"""

from __future__ import annotations

# Step Functions execution statuses that represent a failed job.
FAILURE_STATUSES = ("FAILED", "TIMED_OUT", "ABORTED")

# Discord embed colour for a failure (red), as the decimal int Discord expects.
COLOR_FAILURE = 15158332


def _short_arn(arn):
    """Return the trailing name of an ARN (after the last ``:`` or ``/``)."""
    if not arn:
        return None
    tail = arn.rsplit(":", 1)[-1]
    return tail.rsplit("/", 1)[-1]


def parse_event(event):
    """Normalize a failure event into a flat dict.

    Handles three shapes:
      * EventBridge Step Functions Execution Status Change (``detail`` present).
      * A generic ``{"status"/"state", "message"/"cause", ...}`` payload.
      * Anything else: best-effort passthrough.
    """
    event = event or {}
    detail = event.get("detail")

    if isinstance(detail, dict) and ("executionArn" in detail or "stateMachineArn" in detail):
        return {
            "kind": "step_functions",
            "status": detail.get("status"),
            "state_machine": _short_arn(detail.get("stateMachineArn")),
            "state_machine_arn": detail.get("stateMachineArn"),
            "execution": detail.get("name") or _short_arn(detail.get("executionArn")),
            "execution_arn": detail.get("executionArn"),
            "error": detail.get("error"),
            "cause": detail.get("cause"),
            "region": event.get("region"),
            "account": event.get("account"),
            "time": event.get("time") or detail.get("stopDate"),
        }

    # Generic / direct-invocation shape.
    status = event.get("status") or event.get("state")
    return {
        "kind": "generic",
        "status": status,
        "state_machine": event.get("state_machine") or event.get("job") or event.get("source"),
        "state_machine_arn": None,
        "execution": event.get("execution") or event.get("name"),
        "execution_arn": None,
        "error": event.get("error") or event.get("errorType"),
        "cause": event.get("cause") or event.get("message") or event.get("errorMessage"),
        "region": event.get("region"),
        "account": event.get("account"),
        "time": event.get("time"),
    }


def is_failure(normalized):
    """True if the normalized event represents a failed job.

    Step Functions events are failures only for the terminal failure statuses.
    Generic events count as failures unless they explicitly carry a
    success/ok/running status, so a bare ``{"message": ...}`` alert still fires.
    """
    status = (normalized.get("status") or "").upper()
    if normalized.get("kind") == "step_functions":
        return status in FAILURE_STATUSES
    if status in ("SUCCEEDED", "SUCCESS", "OK", "RUNNING"):
        return False
    return True


def build_discord_payload(normalized):
    """Build a Discord webhook JSON payload from a normalized failure event."""
    sm = normalized.get("state_machine")
    title = "❌ {0} failed".format(sm) if sm else "❌ Pipeline failure"

    fields = []

    def _field(name, value, inline=True):
        if value:
            fields.append({"name": name, "value": str(value)[:1000], "inline": inline})

    _field("Status", normalized.get("status"))
    _field("Execution", normalized.get("execution"))
    _field("Error", normalized.get("error"))
    _field("Region", normalized.get("region"))
    _field("Account", normalized.get("account"))

    cause = normalized.get("cause")
    if cause:
        fields.append({"name": "Cause", "value": str(cause)[:1500], "inline": False})

    embed = {
        "title": title,
        "color": COLOR_FAILURE,
        "fields": fields,
    }
    time = normalized.get("time")
    if time:
        embed["footer"] = {"text": "Pipeline time: {0}".format(time)}

    return {"username": "Pipeline Monitor", "embeds": [embed]}


def build_message(event, platform="discord"):
    """Convenience: parse -> decide -> build payload.

    Returns ``(should_send, payload, normalized)``. ``payload`` is ``None`` when
    the event is not a failure (nothing to send). Only Discord is implemented;
    other platforms reuse the Discord payload, which is also valid generic JSON
    that most webhook receivers accept.
    """
    normalized = parse_event(event)
    if not is_failure(normalized):
        return False, None, normalized
    return True, build_discord_payload(normalized), normalized
