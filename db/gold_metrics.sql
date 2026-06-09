-- Gold metric tables for Apache Superset (Marko's slice).
-- Applied to PostgreSQL by the Superset/PostgreSQL EC2 user-data (viz_ec2.tf).
-- These mirror the gold Parquet datasets produced by lambda/gold/metrics.py and
-- are the schema Superset dashboards read.
--
-- INTEGRATION NOTE: db/gold_schema.sql (Milos's loader slice) also declares
-- daily_users_metric and data_quality_score. data_quality_score matches here.
-- daily_users_metric here is the spec-aligned dashboard shape (platform / new /
-- total / active / post / comment). Reconcile to a single definition with Milos
-- before the gold->PostgreSQL loader writes real rows.

CREATE TABLE IF NOT EXISTS daily_hn_item_counts (
    metric_date DATE NOT NULL,
    post_type   VARCHAR(16) NOT NULL,
    item_count  INTEGER NOT NULL,
    PRIMARY KEY (metric_date, post_type)
);

CREATE TABLE IF NOT EXISTS daily_users_metric (
    metric_date   DATE NOT NULL,
    platform      VARCHAR(32) NOT NULL,
    new_users     INTEGER NOT NULL,
    total_users   INTEGER NOT NULL,
    active_users  INTEGER NOT NULL,
    post_count    INTEGER NOT NULL,
    comment_count INTEGER NOT NULL,
    PRIMARY KEY (metric_date, platform)
);

CREATE TABLE IF NOT EXISTS top_x_users_by_followers (
    metric_date     DATE NOT NULL,
    rank            INTEGER NOT NULL,
    username        VARCHAR(255) NOT NULL,
    followers_count BIGINT,
    is_verified     BOOLEAN,
    PRIMARY KEY (metric_date, rank)
);

CREATE TABLE IF NOT EXISTS top_hn_users_by_karma_high (
    metric_date DATE NOT NULL,
    rank        INTEGER NOT NULL,
    username    VARCHAR(255) NOT NULL,
    karma_score INTEGER,
    PRIMARY KEY (metric_date, rank)
);

CREATE TABLE IF NOT EXISTS top_hn_users_by_karma_low (
    metric_date DATE NOT NULL,
    rank        INTEGER NOT NULL,
    username    VARCHAR(255) NOT NULL,
    karma_score INTEGER,
    PRIMARY KEY (metric_date, rank)
);

CREATE TABLE IF NOT EXISTS top_hn_jobs_by_score (
    metric_date     DATE NOT NULL,
    rank            INTEGER NOT NULL,
    post_id         VARCHAR(64) NOT NULL,
    score           INTEGER,
    author_username VARCHAR(255),
    content_text    TEXT,
    PRIMARY KEY (metric_date, rank)
);

CREATE TABLE IF NOT EXISTS top_hn_stories_by_score (
    metric_date     DATE NOT NULL,
    rank            INTEGER NOT NULL,
    post_id         VARCHAR(64) NOT NULL,
    score           INTEGER,
    author_username VARCHAR(255),
    content_text    TEXT,
    PRIMARY KEY (metric_date, rank)
);

CREATE TABLE IF NOT EXISTS data_quality_score (
    metric_date     DATE NOT NULL,
    source          VARCHAR(32) NOT NULL,
    total_records   INTEGER NOT NULL,
    valid_records   INTEGER NOT NULL,
    invalid_records INTEGER NOT NULL,
    quality_score   NUMERIC(5, 2) NOT NULL,
    PRIMARY KEY (metric_date, source)
);
