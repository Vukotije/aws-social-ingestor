# Milos Control-Point Infrastructure

This folder contains the initial Terraform foundation for the bronze control point.

Milos's scope:

- Shared S3 data lake bucket.
- Shared bronze Lambda IAM role and S3 write policy.
- Hacker News Lambda resource.
- Daily EventBridge schedule for Hacker News ingestion.
- Outputs used by Vukan and Marko during integration.

The Hacker News Lambda currently contains only a minimal handler skeleton in `../lambda/hacker_news/handler.py`. Vukan should replace the skeleton body with the real Hacker News API ingestion logic while keeping the same handler name and environment variable contract.

## Shared Environment Variables

| Name | Description |
| --- | --- |
| `BRONZE_BUCKET` | S3 bucket where bronze data is written |
| `BRONZE_PREFIX` | S3 prefix for bronze data, defaults to `bronze` |
| `INGESTION_DATE` | Optional test override for the ingestion date |
| `TARGET_DATE` | Optional test override for the source data date |

## Expected Hacker News Output Layout

```text
s3://<data-lake-bucket>/bronze/hacker_news/
└── ingestion_date=YYYY-MM-DD/
    ├── metadata.json
    └── raw_items.jsonl
```

## Terraform Commands

```bash
cd infra
terraform init
terraform fmt
terraform validate
terraform plan
```

Deploy when ready:

```bash
terraform apply
```

Manually invoke the skeleton Lambda:

```bash
aws lambda invoke \
  --function-name "$(terraform output -raw hacker_news_lambda_name)" \
  --payload '{}' \
  hn-response.json
```

List the bucket after real ingestion is implemented:

```bash
aws s3 ls "s3://$(terraform output -raw data_lake_bucket)/$(terraform output -raw bronze_prefix)/hacker_news/" --recursive
```
