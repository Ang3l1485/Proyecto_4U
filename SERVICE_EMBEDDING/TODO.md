# Deploy locations-info export job → ECS Fargate + ECR
### Goal: query Aurora PostgreSQL → write `locations_info.csv` to S3

Track every step. Mark as you go: `[ ]` → `[/]` (in progress) → `[x]` (done).

> **Shell used throughout**: **Command Prompt (cmd.exe)**.
> The `.sh` scripts in `ecs/` require **Git Bash** or **WSL** — noted at each step.

---

## What this job actually does

```
Fargate task starts
  → connects to Aurora PostgreSQL using a temporary IAM token (no password!)
  → SELECT * FROM locations_info
  → writes locations_info_<timestamp>.csv to your S3 bucket
  → exits
```

The code lives in `app/`:
- `main.py` — orchestrates the flow
- `db.py` — generates IAM token, opens psycopg2 connection, fetches rows
- `exporter.py` — serialises rows to CSV, uploads with `boto3`
- `config.py` — reads everything from env vars (no hardcoded secrets)

---

## 0 · AWS account basics (do once)

- [ ] Create an AWS account at https://aws.amazon.com if you don't have one
- [ ] Sign in to the **AWS Console** → go to **IAM → Users → your user**
- [ ] Make sure your user has these managed policies (or ask an admin):
  - `AmazonECS_FullAccess`
  - `AmazonEC2ContainerRegistryFullAccess`
  - `IAMFullAccess`
  - `AmazonS3FullAccess`
  - `CloudWatchLogsFullAccess`
- [ ] Install **AWS CLI v2**: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html
  - Download the `.msi` installer for Windows and run it
- [ ] Configure it with your credentials (open Command Prompt):
  ```cmd
  aws configure
  REM AWS Access Key ID:     <from IAM -> your user -> Security credentials>
  REM AWS Secret Access Key: <same place>
  REM Default region:        us-east-2
  REM Default output format: json
  ```
- [ ] Verify it works:
  ```cmd
  aws sts get-caller-identity
  REM Should print your Account ID, UserId, and ARN
  ```
- [ ] Save your Account ID to an environment variable (you'll reuse this all session):
  ```cmd
  for /f "delims=" %i in ('aws sts get-caller-identity --query Account --output text') do set ACCOUNT_ID=%i
  echo Account ID: %ACCOUNT_ID%
  ```
  > Note: if you put this in a `.bat` script instead of typing it directly, double the percent signs: `%%i` instead of `%i`.
- [ ] Install **Docker Desktop**: https://www.docker.com/products/docker-desktop/
  - Start Docker and confirm it's running:
  ```cmd
  docker info
  ```

---

## 1 · Verify the ECS script contents (no edits needed)

> The files in `ecs/` already have the correct names for this job. Just confirm them.

- [ ] Open `ecs/task_definition.json` and confirm:
  - `"family": "locations-info-export"` ✅
  - `"name": "locations-export"` ✅
  - `"image": "ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/locations-export:latest"` ✅ (placeholder filled by deploy script)
  - `"awslogs-group": "/ecs/locations-info-export"` ✅

- [ ] Open `ecs/deploy.sh` and confirm the top says:
  ```
  REPO_NAME="locations-export"
  TASK_FAMILY="locations-info-export"
  ```
  ✅ Already correct.

- [ ] Open `ecs/iam_setup.sh` and confirm:
  ```
  ROLE_NAME="locations-export-task-role"
  ```
  ✅ Already correct.

---

## 2 · Create an S3 bucket (where the CSV will land)

- [ ] Go to AWS Console → **S3** → **Create bucket**
  - Bucket name: e.g. `my-locations-export-2026` (must be globally unique)
  - Region: `us-east-2`
  - Leave all other settings as default (Block Public Access = ON)
  - Click **Create bucket**
- [ ] Or create it via Command Prompt:
  ```cmd
  aws s3 mb s3://my-locations-export-2026 --region us-east-2
  ```
- [ ] Save to a variable:
  ```cmd
  set S3_BUCKET=my-locations-export-2026
  ```

---

## 3 · IAM — create the two roles the task needs

The task needs **two** IAM roles:

| Role | Purpose |
|---|---|
| `ecsTaskExecutionRole` | Lets ECS pull the image from ECR and write logs to CloudWatch |
| `locations-export-task-role` | Lets the task code connect to RDS and write to S3 |

### 3a — `ecsTaskExecutionRole` (may already exist)

- [ ] Check if it exists:
  ```cmd
  aws iam get-role --role-name ecsTaskExecutionRole
  ```
- [ ] If **not found** (error `NoSuchEntity`), create it. Command Prompt can't hold multi-line strings, so write the trust policy to a file first:
  ```cmd
  echo {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]} > trust-policy.json

  aws iam create-role ^
    --role-name ecsTaskExecutionRole ^
    --assume-role-policy-document file://trust-policy.json

  aws iam attach-role-policy ^
    --role-name ecsTaskExecutionRole ^
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
  ```
  > `^` is the Command Prompt line-continuation character (like `` ` `` in PowerShell or `\` in bash). Make sure there's no trailing space after each `^`.

### 3b — `locations-export-task-role` (the job's own permissions)

> ⚠️ This step runs a `.sh` script — you need **Git Bash** or **WSL**.

- [ ] Confirm your variables are set in Command Prompt:
  ```cmd
  for /f "delims=" %i in ('aws sts get-caller-identity --query Account --output text') do set ACCOUNT_ID=%i
  set S3_BUCKET=my-locations-export-2026
  echo ACCOUNT_ID=%ACCOUNT_ID%  S3_BUCKET=%S3_BUCKET%
  ```
- [ ] Open **Git Bash** (right-click the folder → "Git Bash Here") and run:
  ```bash
  # In Git Bash:
  export ACCOUNT_ID=<paste your account id>
  export S3_BUCKET=my-locations-export-2026
  bash ecs/iam_setup.sh
  ```
- [ ] Verify the role ARN was printed. It should look like:
  ```
  arn:aws:iam::123456789012:role/locations-export-task-role
  ```

---

## 4 · Create the CloudWatch log group

ECS will stream the task's stdout here — this is where you'll see logs.

- [ ] Run in Command Prompt:
  ```cmd
  aws logs create-log-group ^
    --log-group-name /ecs/locations-info-export ^
    --region us-east-2
  ```

---

## 5 · Create an ECS cluster

A cluster is just a logical container for tasks — with Fargate you don't manage any servers.

- [ ] Check if you already have a cluster:
  ```cmd
  aws ecs list-clusters --region us-east-2
  ```
- [ ] Create one if needed:
  ```cmd
  aws ecs create-cluster ^
    --cluster-name my-first-cluster ^
    --region us-east-2
  ```
- [ ] Save to a variable:
  ```cmd
  set CLUSTER=my-first-cluster
  ```

---

## 6 · Find your VPC subnet and security group

Fargate tasks run inside your VPC. You need to tell it which subnet and security group to use.

### 6a — Find a subnet

- [ ] List your subnets:
  ```cmd
  aws ec2 describe-subnets ^
    --query "Subnets[*].{ID:SubnetId,Public:MapPublicIpOnLaunch,VPC:VpcId,AZ:AvailabilityZone}" ^
    --output table --region us-east-2
  ```
- [ ] Pick a **public** subnet (where `Public = true`) that is in the same VPC as your RDS instance
- [ ] Save to a variable:
  ```cmd
  set SUBNET_ID=subnet-xxxxxxxxxx
  ```

### 6b — Find or create a security group

The task needs:
- Outbound **TCP 5432** → to reach Aurora RDS
- Outbound **TCP 443** → to reach S3 and ECR (over HTTPS)
- No inbound rules needed (the task calls out, nothing calls in)

- [ ] List existing security groups:
  ```cmd
  aws ec2 describe-security-groups ^
    --query "SecurityGroups[*].{ID:GroupId,Name:GroupName,VPC:VpcId}" ^
    --output table --region us-east-2
  ```
- [ ] If your RDS already has a security group that allows outbound 5432 + 443, you can reuse it
- [ ] Or create a new one (replace `vpc-xxxxxxxx` with your actual VPC ID):
  ```cmd
  for /f "delims=" %i in ('aws ec2 create-security-group --group-name locations-export-sg --description "Outbound to RDS and S3 for export task" --vpc-id vpc-xxxxxxxx --region us-east-2 --query GroupId --output text') do set SG_ID=%i

  REM Allow all outbound (simplest for a first test)
  aws ec2 authorize-security-group-egress ^
    --group-id %SG_ID% ^
    --protocol -1 ^
    --cidr 0.0.0.0/0 ^
    --region us-east-2

  echo Security Group: %SG_ID%
  ```
- [ ] Save to a variable:
  ```cmd
  set SECURITY_GROUP_ID=sg-xxxxxxxxxx
  ```

---

## 7 · Build the Docker image and push to ECR

> ⚠️ `deploy.sh` is a bash script — run it in **Git Bash** or **WSL**.

- [ ] First confirm all variables are set in Command Prompt:
  ```cmd
  echo ACCOUNT_ID        = %ACCOUNT_ID%
  echo S3_BUCKET         = %S3_BUCKET%
  echo CLUSTER           = %CLUSTER%
  echo SUBNET_ID         = %SUBNET_ID%
  echo SECURITY_GROUP_ID = %SECURITY_GROUP_ID%
  ```

- [ ] Open **Git Bash** in the `service_embedding_Dinov2/` folder and run:
  ```bash
  # In Git Bash:
  export ACCOUNT_ID=<your-account-id>
  export CLUSTER=my-first-cluster
  export SUBNET_ID=subnet-xxxxxxxxxx
  export SECURITY_GROUP_ID=sg-xxxxxxxxxx
  export S3_BUCKET=my-locations-export-2026

  bash ecs/deploy.sh
  ```

**What `deploy.sh` does step by step:**
1. `aws ecr get-login-password | docker login` — authenticates Docker to ECR
2. `aws ecr create-repository` — creates `locations-export` repo in ECR (safe to re-run)
3. `docker build` — builds the image from your `Dockerfile`
4. `docker tag` + `docker push` — uploads the image to ECR
5. Patches `task_definition.json` with your real `ACCOUNT_ID` and `S3_BUCKET`
6. `aws ecs register-task-definition` — registers the task with ECS
7. `aws ecs run-task` — starts the Fargate task

- [ ] The script should finish with:
  ```
  Task started: arn:aws:ecs:us-east-2:...
  ```
  Copy that task ARN — you'll use it in step 8.

---

## 8 · Monitor the task while it runs

Back in **Command Prompt**:

- [ ] Tail the CloudWatch logs (Ctrl+C to stop):
  ```cmd
  aws logs tail /ecs/locations-info-export ^
    --follow ^
    --region us-east-2
  ```
  Expected output:
  ```
  === locations_info export job starting ===
  Connected to database-2.cluster-xxx.us-east-2.rds.amazonaws.com:5432/postgres ...
  Executing: SELECT * FROM locations_info;
  Fetched N rows from locations_info.
  Exported N rows → s3://my-locations-export-2026/exports/locations_info_20260908T....csv
  === Job finished successfully. ===
  ```

- [ ] Check the task's exit status (paste the task ARN from step 7):
  ```cmd
  aws ecs describe-tasks ^
    --cluster %CLUSTER% ^
    --tasks <task-arn-from-step-7> ^
    --region us-east-2 ^
    --query "tasks[0].{status:lastStatus,exitCode:containers[0].exitCode,reason:stoppedReason}" ^
    --output table
  ```
  - `exitCode: 0` = success ✅
  - `exitCode: 1` = the Python script raised an exception → check logs above

---

## 9 · Verify the CSV in S3

- [ ] List the exports folder:
  ```cmd
  aws s3 ls "s3://%S3_BUCKET%/exports/" --region us-east-2
  ```
- [ ] Download and view the first few lines:
  ```cmd
  set FILENAME=<paste filename from listing above>
  aws s3 cp "s3://%S3_BUCKET%/exports/%FILENAME%" - > temp_export.csv
  more +0 temp_export.csv | findstr /n "^" | findstr "^[1-5]:"
  ```
  > Command Prompt has no built-in equivalent of `Select-Object -First 5`, so this downloads to a temp file and prints the first 5 lines using `more`/`findstr`. You should see a CSV header + data rows from `locations_info`. 🎉

---

## 10 · Troubleshooting — common first-time errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `CannotPullContainerError` | ECR auth issue or image not pushed | Re-run `deploy.sh` in Git Bash; check ECR repo exists |
| `ResourceInitializationError: unable to pull secrets` | `ecsTaskExecutionRole` missing ECR permissions | Attach `AmazonECSTaskExecutionRolePolicy` to the role |
| `exitCode: 1` + `FATAL: pg_hba.conf rejects connection` | RDS not accepting IAM auth | Enable IAM auth on the RDS cluster in the AWS Console |
| `exitCode: 1` + `SSL connection is required` | SSL not enabled | Check `sslmode="require"` in `db.py` ✅ already set |
| `exitCode: 1` + `rds-db:connect` access denied | Task role missing RDS permission | Check `task_role_policy.json` was applied correctly |
| `exitCode: 1` + `NoCredentialsError` | Task role not attached to task def | Confirm `taskRoleArn` in `task_definition.json` |
| `AccessDenied` on S3 put | Task role missing S3 write permission | Check S3 resource ARN in `task_role_policy.json` matches your bucket |
| Task stops immediately with no logs | Log group doesn't exist | Run step 4 to create `/ecs/locations-info-export` |

---

## Quick-reference — Command Prompt session variables

Run these at the start of each Command Prompt session before doing anything else. Save this as `set_vars.bat` and just run `set_vars.bat`:

```cmd
@echo off
for /f "delims=" %%i in ('aws sts get-caller-identity --query Account --output text') do set ACCOUNT_ID=%%i
set S3_BUCKET=my-locations-export-2026
set CLUSTER=my-first-cluster
set SUBNET_ID=subnet-xxxxxxxxxx
set SECURITY_GROUP_ID=sg-xxxxxxxxxx

echo Ready. Account: %ACCOUNT_ID%
```

> Note the doubled `%%i` in the `for` loop — that's required inside a `.bat` file (a single `%i` is only correct when typing the command directly at the Command Prompt).