# Milos Infrastructure Notes

This folder contains Terraform for the bronze control point plus Milos's full-project slice.

Milos's scope:

- Shared S3 data lake bucket.
- Shared bronze Lambda IAM role and S3 write policy.
- Hacker News Lambda resource.
- Daily EventBridge schedule for Hacker News ingestion.
- Outputs used by Vukan and Marko during integration.
- VPC, public subnets, route tables, and security groups for Lambda, PostgreSQL, and Superset.
- Secrets Manager placeholders for PostgreSQL credentials and notification webhooks.
- Step Functions state machine that runs bronze ingestion, placeholder silver/gold steps, and the gold-to-PostgreSQL loader.
- Gold-to-PostgreSQL Lambda skeleton for the final export step.

## Shared Environment Variables

| Name | Description |
| --- | --- |
| `BRONZE_BUCKET` | S3 bucket where bronze data is written |
| `BRONZE_PREFIX` | S3 prefix for bronze data, defaults to `bronze` |
| `INGESTION_DATE` | Optional test override for the ingestion date |
| `TARGET_DATE` | Optional test override for the source data date |
| `DATA_LAKE_BUCKET` | S3 bucket used by the gold loader |
| `GOLD_PREFIX` | S3 prefix for gold metric outputs, defaults to `gold` |
| `POSTGRES_PASSWORD_SECRET_ARN` | Secrets Manager ARN for the PostgreSQL password |

## Expected Hacker News Output Layout

```text
s3://<data-lake-bucket>/bronze/hacker_news/
└── ingestion_date=YYYY-MM-DD/
    ├── metadata.json
    └── raw_items.jsonl
```

## Terraform Commands

```bash
terraform -chdir=infra init
terraform -chdir=infra fmt
terraform -chdir=infra validate
AWS_PROFILE=social-ingestor terraform -chdir=infra plan
```

Deploy when ready:

```bash
AWS_PROFILE=social-ingestor terraform -chdir=infra apply
```

Invoke the loader wiring check:

```bash
AWS_PROFILE=social-ingestor aws lambda invoke \
  --function-name "$(terraform -chdir=infra output -raw gold_to_postgres_lambda_name)" \
  --payload '{}' \
  gold-loader-response.json
cat gold-loader-response.json
```

Run the Step Functions pipeline:

```bash
EXECUTION_ARN="$(AWS_PROFILE=social-ingestor aws stepfunctions start-execution \
  --state-machine-arn "$(terraform -chdir=infra output -raw pipeline_state_machine_arn)" \
  --input '{}' \
  --query executionArn \
  --output text)"

AWS_PROFILE=social-ingestor aws stepfunctions describe-execution \
  --execution-arn "$EXECUTION_ARN"
```

List the bucket after ingestion:

```bash
AWS_PROFILE=social-ingestor aws s3 ls "s3://$(terraform -chdir=infra output -raw data_lake_bucket)/$(terraform -chdir=infra output -raw bronze_prefix)/" --recursive
```
