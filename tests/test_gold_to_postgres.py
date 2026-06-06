from __future__ import annotations

import contextlib
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
LOADER_SRC = os.path.join(HERE, "..", "lambda", "gold_to_postgres")
sys.path.insert(0, LOADER_SRC)

import handler  # noqa: E402


@contextlib.contextmanager
def env(**overrides):
    saved = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_missing_env_returns_400():
    with env(DATA_LAKE_BUCKET=None, GOLD_PREFIX=None, POSTGRES_PASSWORD_SECRET_ARN=None):
        result = handler.lambda_handler({}, None)

    assert result["statusCode"] == 400
    assert result["body"]["loaded"] is False
    assert "DATA_LAKE_BUCKET" in result["body"]["missing"]


def test_build_load_plan_uses_event_and_env():
    with env(
        DATA_LAKE_BUCKET="bucket",
        GOLD_PREFIX="gold",
        POSTGRES_PASSWORD_SECRET_ARN="secret-arn",
        POSTGRES_HOST="postgres.internal",
        POSTGRES_DB="metrics",
        POSTGRES_USER="loader",
        TARGET_DATE="2026-05-31",
    ):
        result = handler.lambda_handler(
            {"metric_tables": ["daily_users_metric", "data_quality_score"]},
            None,
        )

    body = result["body"]
    assert result["statusCode"] == 200
    assert body["mode"] == "dry_run"
    assert body["plan"]["bucket"] == "bucket"
    assert body["plan"]["metric_tables"] == ["daily_users_metric", "data_quality_score"]
    assert body["plan"]["target_date"] == "2026-05-31"


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print("ok  - {0}".format(test.__name__))
    print("\n{0} passed".format(len(tests)))


if __name__ == "__main__":
    _run_all()
