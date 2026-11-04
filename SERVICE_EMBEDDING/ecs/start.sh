#!/usr/bin/env bash
# Start the service back up (desired_count=1).
# The task will be ready in ~2 min (model already baked in image).
REGION="us-east-2"
CLUSTER="${CLUSTER:-my-first-cluster}"
SERVICE_NAME="locations-export-api"

echo "Scaling service to 1..."
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "${SERVICE_NAME}" \
  --desired-count 1 \
  --region "${REGION}" \
  --query "service.{desired:desiredCount,status:status}" \
  --output table

echo "Service starting. Wait ~2 min then run get_ip.sh to get the endpoint."