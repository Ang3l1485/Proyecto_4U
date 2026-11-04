#!/usr/bin/env bash
# Prints the current public IP of the running ECS task + test command.
REGION="us-east-2"
CLUSTER="${CLUSTER:-my-first-cluster}"
SERVICE_NAME="locations-export-api"

TASK_ARN=$(aws ecs list-tasks \
  --cluster "${CLUSTER}" \
  --service-name "${SERVICE_NAME}" \
  --region "${REGION}" \
  --query "taskArns[0]" \
  --output text)

if [ -z "${TASK_ARN}" ] || [ "${TASK_ARN}" = "None" ]; then
  echo "No running task found. Start the service with: bash ecs/start.sh"
  exit 1
fi

ENI_ID=$(aws ecs describe-tasks \
  --cluster "${CLUSTER}" \
  --tasks "${TASK_ARN}" \
  --region "${REGION}" \
  --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" \
  --output text)

PUBLIC_IP=$(aws ec2 describe-network-interfaces \
  --network-interface-ids "${ENI_ID}" \
  --region "${REGION}" \
  --query "NetworkInterfaces[0].Association.PublicIp" \
  --output text)

echo ""
echo "=========================================="
echo "  API endpoint: http://${PUBLIC_IP}:8080"
echo "=========================================="
echo ""
echo "Health check:"
echo "  curl http://${PUBLIC_IP}:8080/health"
echo ""
echo "Predict (replace image.png with your file):"
echo "  curl -X POST http://${PUBLIC_IP}:8080/predict -F image=@image.png"
echo ""