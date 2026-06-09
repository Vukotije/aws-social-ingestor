CREATE TABLE IF NOT EXISTS daily_users_metric (
    metric_date DATE NOT NULL,
    source VARCHAR(32) NOT NULL,
    active_users INTEGER NOT NULL,
    post_count INTEGER NOT NULL,
    comment_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (metric_date, source)
);

CREATE TABLE IF NOT EXISTS data_quality_score (
    metric_date DATE NOT NULL,
    source VARCHAR(32) NOT NULL,
    total_records INTEGER NOT NULL,
    valid_records INTEGER NOT NULL,
    invalid_records INTEGER NOT NULL,
    quality_score NUMERIC(5, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (metric_date, source)
);
