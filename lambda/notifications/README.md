# Failure Notifications (Marko)

Sends a chat message when a pipeline job fails (`PROJECT_SPECIFICATION.md`
section 5). An EventBridge rule watches the medallion pipeline state machine and
invokes this Lambda on a terminal failure (`FAILED` / `TIMED_OUT` / `ABORTED`),
which posts a Discord webhook message.

```text
Step Functions execution ends FAILED
        │  (EventBridge: Step Functions Execution Status Change)
        ▼
aws_cloudwatch_event_rule.pipeline_failed ──► notifications Lambda ──► Discord webhook
```

The state machine definition is **not** modified — the failure is observed via
its execution status event, so this slice stays decoupled from the orchestration
slice. The state machine's own `PipelineFailed` state delegates exactly this.

## Setup

The webhook URL lives in the Secrets Manager secret created in `secrets.tf`:

```bash
aws secretsmanager put-secret-value \
  --secret-id "$(cd infra && terraform output -raw notification_webhook_secret_arn)" \
  --secret-string 'https://discord.com/api/webhooks/XXXX/YYYY'
```

The secret may hold the raw URL or `{"webhook_url": "..."}`. The URL is never
logged.

## Run locally

```bash
# Dry run: prints the Discord payload it would send (no webhook configured):
python lambda/notifications/handler.py

# Point at a real/test webhook without touching Secrets Manager:
NOTIFICATION_WEBHOOK_URL='https://discord.com/api/webhooks/...' \
  python lambda/notifications/handler.py

# Tests (with or without pytest):
python tests/test_notifications.py
```

## Reuse for other failures

`notify.parse_event` also accepts a generic `{"status": "...", "message": "..."}`
payload, so the same Lambda can be invoked directly (or from a CloudWatch alarm)
to alert on non-Step-Functions failures. Anything not explicitly successful is
treated as a failure worth sending.
