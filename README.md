# aws-social-ingestor
AWS data lake for real-time social analytics, engineered with a serverless Medallion pipeline and IaC provisioning

## Project Docs

- [Project specification](PROJECT_SPECIFICATION.md)
- [Agent guide](AGENTS.md)
- [KT bronze control point plan](KT%20plan.md)
- [Milos control-point infrastructure notes](infra/README.md)
- [Vukan Hacker News bronze ingestion notes](lambda/hacker_news/README.md)
- [Marko X/Twitter bronze ingestion notes](lambda/x/README.md)

## Demo Commands

Run local checks without AWS:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  lambda/hacker_news/handler.py \
  lambda/hacker_news/hn_ingest.py \
  lambda/x/handler.py \
  lambda/x/x_ingest.py \
  lambda/x/validate.py

PYTHONDONTWRITEBYTECODE=1 python3 tests/test_x_bronze.py
PYTHONDONTWRITEBYTECODE=1 python3 tests/test_hacker_news_bronze.py
PYTHONDONTWRITEBYTECODE=1 python3 lambda/x/validate.py
```

Check deployed infrastructure:

```bash
AWS_PROFILE=social-ingestor aws sts get-caller-identity
terraform -chdir=infra init
terraform -chdir=infra fmt -check
terraform -chdir=infra validate
AWS_PROFILE=social-ingestor terraform -chdir=infra plan
```

Invoke both deployed bronze Lambdas:

```bash
AWS_PROFILE=social-ingestor aws lambda invoke \
  --function-name "$(terraform -chdir=infra output -raw x_lambda_name)" \
  --payload '{}' \
  x-response.json
cat x-response.json

AWS_PROFILE=social-ingestor aws lambda invoke \
  --function-name "$(terraform -chdir=infra output -raw hacker_news_lambda_name)" \
  --payload '{}' \
  hn-response.json
cat hn-response.json
```

Show the bronze objects in S3:

```bash
AWS_PROFILE=social-ingestor aws s3api list-objects-v2 \
  --bucket "$(terraform -chdir=infra output -raw data_lake_bucket)" \
  --prefix "$(terraform -chdir=infra output -raw bronze_prefix)/" \
  --query 'Contents[].{Key:Key,Size:Size,LastModified:LastModified}' \
  --output table
```
