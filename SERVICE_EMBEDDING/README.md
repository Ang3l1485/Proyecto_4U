# locations-info export service

One-shot AWS Fargate task that:
1. Connects to **Aurora PostgreSQL** using **IAM token auth** (no stored passwords).
2. `SELECT * FROM locations_info`
3. Uploads the result as a timestamped CSV to **S3**.

---

## Project structure

```
.
├── app/
│   ├── config.py       # Env-var configuration
│   ├── db.py           # IAM token auth + psycopg2 helpers
│   ├── exporter.py     # CSV → S3
│   └── main.py         # Entry point
├── ecs/
│   ├── task_definition.json   # ECS Fargate task definition template
│   ├── task_role_policy.json  # IAM policy for the task role
│   ├── iam_setup.sh           # One-time IAM role creation
│   └── deploy.sh              # Build → ECR push → register → run
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Prerequisites

| Tool | Purpose |
|------|---------|
| AWS CLI v2 | ECR login, ECS commands |
| Docker | Build the image |
| Python 3.11+ | Local testing |

Your AWS identity must have permissions to:
- `ecr:*` on the `locations-export` repository
- `ecs:RegisterTaskDefinition`, `ecs:RunTask`
- `iam:CreateRole`, `iam:PutRolePolicy` (for `iam_setup.sh`)

---

## First-time setup

```bash
# 1. Configure env vars (fill in your real values)
export ACCOUNT_ID=123456789012
export CLUSTER=your-ecs-cluster
export SUBNET_ID=subnet-xxxxxxxx          # PUBLIC subnet (Fargate needs a public IP to reach RDS)
export SECURITY_GROUP_ID=sg-xxxxxxxx      # must allow outbound TCP/5432 to 0.0.0.0/0
export S3_BUCKET=your-export-bucket-name

# 2. Create the IAM task role (once)
bash ecs/iam_setup.sh

# 3. Build, push, and run the Fargate task
bash ecs/deploy.sh
```

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_HOST` | ✅ | — | RDS cluster endpoint |
| `S3_BUCKET` | ✅ | — | Target S3 bucket |
| `DB_PORT` | | `5432` | PostgreSQL port |
| `DB_USER` | | `postgres` | DB username |
| `DB_NAME` | | `postgres` | Database name |
| `DB_REGION` | | `us-east-2` | AWS region for IAM token |
| `DB_TABLE` | | `locations_info` | Table to export |
| `S3_KEY_PREFIX` | | `exports/` | S3 key prefix |

---

## IAM auth — how it works

The Fargate task role has `rds-db:connect` permission.  
At runtime, `boto3.client("rds").generate_db_auth_token(...)` returns a short-lived  
(15-min) signed token that is used as the PostgreSQL password.  
SSL is enforced (`sslmode=require`).

The RDS cluster must have **IAM Database Authentication enabled** and the  
`postgres` user must be granted the `rds_iam` role:

```sql
GRANT rds_iam TO postgres;
```

---

## Output

CSV files are written to:
```
s3://<S3_BUCKET>/exports/locations_info_<YYYYMMDDTHHMMSSZ>.csv
```

Each run produces a distinct timestamped file.

---

## Monitoring

```bash
# Tail live logs
aws logs tail /ecs/locations-info-export --follow --region us-east-2
```
