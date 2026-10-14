#!/usr/bin/env bash
# ============================================================
# deploy.sh -- Build, push to ECR, update ECS service.
#              Auto-stops the service after 1 hour.
# ============================================================

set -euo pipefail

REGION="us-east-2"
REPO_NAME="locations-export"
IMAGE_TAG="latest"
TASK_FAMILY="locations-info-export"
SERVICE_NAME="locations-export-api"

: "${ACCOUNT_ID:?Set ACCOUNT_ID}"
: "${CLUSTER:?Set CLUSTER}"

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}"
SCRIPT_DIR="$(dirname "$0")"

echo "=== 1. Authenticate Docker to ECR ==="
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${ECR_URI}"

echo "=== 2. Create ECR repo if it does not exist ==="
aws ecr describe-repositories --repository-names "${REPO_NAME}" \
  --region "${REGION}" 2>/dev/null \
  || aws ecr create-repository --repository-name "${REPO_NAME}" \
       --region "${REGION}"

echo "=== 3. Build Docker image ==="
docker build -t "${REPO_NAME}:${IMAGE_TAG}" "${SCRIPT_DIR}/.."

echo "=== 4. Tag and push ==="
docker tag "${REPO_NAME}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"

echo "=== 5. Register task definition ==="
TMP_TASK_DEF="task_definition.patched.json"
sed \
  -e "s/ACCOUNT_ID/${ACCOUNT_ID}/g" \
  -e "s/YOUR_EXPORT_BUCKET_NAME/${S3_BUCKET:-my-locations-export-2026}/g" \
  "${SCRIPT_DIR}/task_definition.json" > "${TMP_TASK_DEF}"

TASK_DEF_ARN=$(MSYS2_ARG_CONV_EXCL="*" aws ecs register-task-definition \
  --cli-input-json "file://${TMP_TASK_DEF}" \
  --region "${REGION}" \
  --query "taskDefinition.taskDefinitionArn" \
  --output text)
rm -f "${TMP_TASK_DEF}"
echo "Registered: ${TASK_DEF_ARN}"

echo "=== 6. Update ECS service ==="
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "${SERVICE_NAME}" \
  --task-definition "${TASK_FAMILY}" \
  --desired-count 1 \
  --force-new-deployment \
  --region "${REGION}" \
  --query "service.{status:status,running:runningCount,desired:desiredCount}" \
  --output table

echo ""
echo "=== 7. Auto-stop timer: 1 hour ==="
# Schedules stop.sh to run in the background after 3600 seconds.
# If you close this terminal, run stop.sh manually when done.
(
  sleep 3600
  export CLUSTER="${CLUSTER}"
  bash "${SCRIPT_DIR}/stop.sh"
  echo "[auto-stop] Service stopped after 1 hour."
) &
AUTO_STOP_PID=$!
echo "Auto-stop scheduled (PID ${AUTO_STOP_PID})."
echo "To cancel auto-stop: kill ${AUTO_STOP_PID}"
echo "To stop manually now: bash ecs/stop.sh"

echo ""
echo "=== Deployment started! ==="
echo "Wait ~2 min for startup, then get the endpoint:"
echo "  bash ecs/get_ip.sh"
echo ""
echo "Tail logs:"
echo "  MSYS_NO_PATHCONV=1 aws logs tail /ecs/locations-info-export --follow --region ${REGION}"