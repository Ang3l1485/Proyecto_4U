#!/usr/bin/env bash
# ============================================================
# iam_setup.sh — Create the IAM role needed by the Fargate task
#
# Run once before your first deploy.
# Usage:
#   export ACCOUNT_ID=123456789012
#   export S3_BUCKET=your-export-bucket-name
#   ./ecs/iam_setup.sh
# ============================================================

set -euo pipefail

: "${ACCOUNT_ID:?Set ACCOUNT_ID}"
: "${S3_BUCKET:?Set S3_BUCKET}"

ROLE_NAME="locations-export-task-role"
REGION="us-east-2"

echo "=== Creating IAM task role: ${ROLE_NAME} ==="

# Trust policy — only ECS tasks can assume this role
TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ecs-tasks.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}'

aws iam create-role \
  --role-name "${ROLE_NAME}" \
  --assume-role-policy-document "${TRUST_POLICY}" \
  --description "Allows Fargate task to auth to RDS via IAM and write to S3" \
  2>/dev/null || echo "Role already exists, continuing."

echo "=== Attaching inline policy ==="

POLICY=$(
  sed \
    -e "s/ACCOUNT_ID/${ACCOUNT_ID}/g" \
    -e "s/YOUR_EXPORT_BUCKET_NAME/${S3_BUCKET}/g" \
    "$(dirname "$0")/task_role_policy.json"
)

aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "locations-export-policy" \
  --policy-document "${POLICY}"

echo ""
echo "=== Done. Role ARN: ==="
aws iam get-role --role-name "${ROLE_NAME}" \
  --query "Role.Arn" --output text
