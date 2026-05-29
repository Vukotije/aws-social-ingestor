# Agent Guide

This file describes how AI agents should work in this repository.

## Project Context

This repository implements an AWS-based social media data lake for the Cloud Computing course project. The system must collect, normalize, transform, store, analyze, and visualize data from Hacker News and X/Twitter-style datasets.

The project follows the Medallion architecture:

- **Bronze layer**: raw source data stored in S3 without transformation.
- **Silver layer**: cleaned, normalized, deduplicated, schema-based Parquet datasets.
- **Gold layer**: metrics, KPIs, and aggregate tables for analysis and visualization.

The full project requirements are in `PROJECT_SPECIFICATION.md`.

## Preferred Stack

- **Language**: Python
- **Data processing**: `pandas`, `awswrangler`, `pyarrow`
- **AWS compute**: Lambda
- **Storage**: S3
- **Orchestration**: Step Functions
- **Infrastructure as Code**: Terraform
- **Visualization database**: PostgreSQL on EC2
- **Dashboards**: Apache Superset on EC2
- **Notifications**: Discord webhook or equivalent notification integration

## Working Principles

- Read the relevant specification and nearby code before editing.
- Keep changes small, focused, and directly tied to the current task.
- Prefer simple Python functions for transformation logic so they can be unit tested locally.
- Keep bronze, silver, and gold responsibilities separate.
- Use Terraform for infrastructure instead of manual AWS setup as the long-term solution.
- Do not commit, push, deploy, or create real cloud resources unless explicitly asked.
- Do not store secrets, tokens, credentials, private keys, or webhook URLs in the repository.

## Project Boundaries

Agents should not silently change project requirements. If a requirement is unclear or expensive, explain the tradeoff and ask before changing direction.

Manual AWS console actions may be useful for exploration, but the final project infrastructure must be represented in IaC because IaC is an eliminatory requirement.

## Suggested Implementation Order

### 1. Foundation

- Set up Python package structure.
- Add local dependency management.
- Add test structure.
- Add Terraform project structure.
- Document local commands.

Expected verification:

- Unit tests can run locally.
- Terraform configuration validates.

### 2. Bronze Layer

- Implement Hacker News ingestion.
- Store raw Hacker News API responses in S3.
- Add a path for loading X/Twitter datasets into S3.

Expected verification:

- Raw files are written with a stable S3 key layout.
- Bronze code does not clean, normalize, or aggregate data.

### 3. Silver Layer

- Normalize Hacker News and X/Twitter records.
- Flatten nested fields where needed.
- Normalize timestamps to UTC.
- Clean HTML from text fields.
- Remove duplicates.
- Write Parquet datasets with partitions.

Expected verification:

- Unit tests cover timestamp normalization, HTML cleaning, deduplication, and schema mapping.
- Sample Parquet outputs can be read back.

### 4. Gold Layer

- Compute required metrics and top-10 reports.
- Compute Data Quality Score.
- Write partitioned Parquet datasets to the gold layer.

Expected verification:

- Unit tests cover each metric on small fixtures.
- Gold output schemas match expected dashboard tables.

### 5. PostgreSQL and Superset

- Load gold metrics from S3 into PostgreSQL.
- Run PostgreSQL and Apache Superset on EC2.
- Document dashboard setup.

Expected verification:

- PostgreSQL contains expected metric rows.
- Superset can connect to PostgreSQL and query the metric tables.

### 6. Notifications and Networking

- Add failure notifications for failed jobs.
- Wire job failures to the notification mechanism.
- Keep resources inside the VPC where required.
- Apply least-privilege networking with security groups.

Expected verification:

- A forced failure sends a notification.
- Security groups allow only required traffic.

## Code Guidelines

- Keep Lambda handlers thin. Put reusable logic in importable modules.
- Avoid AWS calls inside pure transformation functions so they can be tested locally.
- Prefer explicit schemas for silver and gold datasets.
- Use UTC timestamps consistently.
- Use Parquet for silver and gold outputs.
- Keep S3 key layouts predictable and partition-friendly.
- Avoid large, shared utility modules that mix unrelated responsibilities.

## Verification Checklist

Before considering a task complete, run the narrowest relevant checks:

- Python unit tests for transformation logic.
- Formatting or linting if configured.
- Terraform validation for infrastructure changes.
- Local sample-data runs for ETL code when possible.

If a check cannot be run, mention why in the final response.

## Communication Style

When finishing work, summarize:

- What changed.
- How it was verified.
- What remains or what should be done next.
