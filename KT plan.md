# KT Plan: Bronze Layer Control Point

For the control point, implement only **Requirement 1: Prikupljanje podataka (bronze layer)**. This requirement is worth 10 points.

The team should deliver raw data collection for two sources:

- Hacker News
- X/Twitter-style dataset

Bronze-layer rule: data must be saved to S3 in its original/raw form. Do not normalize, clean, deduplicate, transform timestamps, or write Parquet in this phase.

## Shared Contract

Use one shared S3 layout so everyone can work independently:

```text
s3://<data-lake-bucket>/bronze/
├── hacker_news/
│   └── ingestion_date=YYYY-MM-DD/
│       ├── metadata.json
│       └── raw_items.jsonl
└── x/
    └── ingestion_date=YYYY-MM-DD/
        ├── metadata.json
        └── raw_dataset.<json|jsonl|csv>
```

Shared environment variables:

- `BRONZE_BUCKET`: target S3 bucket.
- `BRONZE_PREFIX`: default `bronze`.
- `INGESTION_DATE`: optional override for testing.
- `TARGET_DATE`: optional source-data date override.

## Collaboration Model

Each person should touch all core technologies:

- Terraform/IaC
- Python Lambda code
- S3 bronze layout
- Local tests or validation
- Documentation

To avoid blocking each other, split the work into vertical slices. Each person owns one small module end to end, while the shared contract stays fixed.

## Milos: Shared Foundation and Hacker News Lambda Wiring

Milos owns the shared project foundation and the Terraform wiring for the Hacker News ingestion path.

Tasks:

- Create the initial Terraform structure for the control point.
- Define the shared S3 data lake bucket and bronze prefix layout.
- Define the shared Lambda IAM role or reusable IAM policy pattern.
- Add the Terraform resource for the Hacker News Lambda.
- Add EventBridge schedule for daily Hacker News ingestion.
- Implement or co-implement the small Lambda packaging pattern used by all team members.
- Add a minimal Python handler skeleton for Hacker News so Vukan can fill in the API logic without waiting on infrastructure.
- Document shared environment variables and deploy commands.

Deliverables:

- `infra/` Terraform setup.
- S3 bucket resource.
- Shared IAM role or IAM policy pattern.
- Hacker News Lambda Terraform resource.
- EventBridge schedule for Hacker News ingestion.
- Hacker News handler skeleton.
- Shared deployment notes.

Verification:

- `terraform fmt`
- `terraform validate`
- `terraform plan`
- Local handler import check for the Hacker News Lambda skeleton.

## Vukan: Hacker News API Logic and X Lambda Wiring

Vukan owns the Hacker News API collection logic and the Terraform wiring for the X/Twitter dataset Lambda. This gives Vukan both Python/data work and IaC work.

Tasks:

- Implement Hacker News API client.
- Collect previous-day items of types `story`, `ask`, `comment`, `job`, and `poll`.
- Save raw Hacker News item JSON to S3 as `raw_items.jsonl`.
- Write `metadata.json` with target date, ingestion date, record count, and counts by type.
- Keep the data raw: no HTML cleaning, timestamp normalization, deduplication, or schema mapping.
- Add tests for date filtering and item type filtering with mocked API responses.
- Add the Terraform resource for the X/Twitter dataset ingestion Lambda.
- Wire the X Lambda to the shared S3 bucket, IAM role/policy, and environment variables.

Deliverables:

- Hacker News Lambda handler.
- HN API helper/client.
- Tests for filtering logic.
- X/Twitter Lambda Terraform resource.
- Local run notes for the Hacker News ingestion path.

Verification:

- Unit tests pass.
- A sample run writes `raw_items.jsonl` and `metadata.json` in the agreed S3 layout.
- Raw records still match the Hacker News API shape.
- `terraform validate` still passes after adding the X Lambda resource.

## Marko: X/Twitter Dataset Logic and IAM/S3 Validation

Marko owns the X/Twitter-style dataset ingestion logic and helps verify the Terraform/IAM/S3 integration from the data producer side. This gives Marko Python/data work plus IaC review and validation work.

Tasks:

- Choose, manually create, or generate a small X/Twitter-style dataset.
- Preserve the raw dataset format as JSON, JSONL, or CSV.
- Implement upload path using a Lambda or repeatable script.
- Save the dataset to S3 as `raw_dataset.<json|jsonl|csv>`.
- Write `metadata.json` with dataset name, provenance, format, ingestion date, and row/file count.
- Add lightweight validation for file existence, readable format, and row count.
- Review the Terraform IAM policy to confirm the X ingestion path can only write to the bronze prefix.
- Add or update Terraform variables/outputs needed to manually invoke and verify the X ingestion Lambda.
- Document the dataset provenance and exact S3 output path.

Deliverables:

- Dataset file or documented dataset generation/download step.
- X ingestion Lambda or script.
- Metadata writer.
- Validation/test for upload shape.
- Dataset provenance notes.
- Terraform output or documentation for invoking/verifying the X ingestion path.

Verification:

- Sample run writes `raw_dataset.<json|jsonl|csv>` and `metadata.json`.
- Dataset remains raw and unnormalized.
- Metadata contains row/file count and provenance.
- Terraform outputs are sufficient to find the bucket and X Lambda.

## Integration Steps

1. Agree on handler names and environment variables before coding.
2. Milos creates the base Terraform module, shared S3 bucket, shared IAM pattern, and Hacker News Lambda skeleton.
3. Vukan implements Hacker News logic and adds the X Lambda Terraform resource.
4. Marko implements the X dataset ingestion logic and validates IAM/S3 outputs.
5. Everyone runs `terraform validate` after their Terraform changes.
6. Everyone runs the relevant local Python tests for their Lambda code.
7. Run one manual test ingestion for Hacker News.
8. Run one manual test ingestion for X/Twitter dataset.
9. Capture S3 output paths or screenshots for the control-point demo.

## Done Criteria

The control point is ready when:

- Terraform defines the bronze infrastructure.
- Hacker News raw previous-day data can be collected into S3.
- X/Twitter-style raw dataset can be placed into S3.
- Both sources produce `metadata.json`.
- The S3 bronze layout can be demonstrated.
- No silver/gold processing is included in the bronze implementation.
