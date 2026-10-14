#!/usr/bin/env bash
# Stop the service (desired_count=0). Costs nothing while stopped.
# Run again with start.sh to bring it back.
REGION="us-east-2"
CLUSTER="${CLUSTER:-my-first-cluster}"
SERVICE_NAME="locations-export-api"

echo "Scaling service to 0..."
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "${SERVICE_NAME}" \
  --desired-count 0 \
  --region "${REGION}" \
  --query "service.{desired:desiredCount,status:status}" \
  --output table

echo "Service stopped. No Fargate charges accruing."