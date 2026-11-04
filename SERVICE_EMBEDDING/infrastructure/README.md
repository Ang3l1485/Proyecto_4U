# Infrastructure — locations-info export job (Terraform)

> **Stack**: AWS ECS Fargate + ECR + S3 + IAM + CloudWatch  
> **Managed by**: Terraform >= 1.5 with AWS provider ~> 5.0

---

## What is provisioned

| Resource | Name / ID |
|---|---|
| ECR repository | `locations-export` |
| S3 bucket | `var.s3_bucket_name` (e.g. `my-locations-export-2026`) |
| IAM role — execution | `ecsTaskExecutionRole` |
| IAM role — task | `locations-export-task-role` |
| CloudWatch log group | `/ecs/locations-info-export` |
| ECS cluster | `var.cluster_name` (default `my-first-cluster`) |
| ECS task definition | `locations-info-export` (256 CPU / 512 MB, Fargate) |
| Security group | `locations-export-sg` (egress 5432 + 443 only) |

---

## Prerequisites

1. [Terraform >= 1.5](https://developer.hashicorp.com/terraform/downloads) installed
2. AWS CLI configured (`aws configure`) with a user that has the policies listed in `TODO.md § 0`
3. Your **VPC ID** (the one where your Aurora RDS cluster lives)

---

## First-time setup

### 1. Copy and fill in your variables

```cmd
cd infrastructure
copy terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` — the only **required** fields are:

| Variable | What to put |
|---|---|
| `vpc_id` | Your VPC ID, e.g. `vpc-0abc1234` |
| `s3_bucket_name` | Globally unique bucket name, e.g. `my-locations-export-2026` |
| `db_host` | Aurora cluster endpoint |

Everything else has sensible defaults.

### 2. Handle `ecsTaskExecutionRole` if it already exists

This role is often shared across projects. Check first:

```cmd
aws iam get-role --role-name ecsTaskExecutionRole
```

- **Not found** → Terraform will create it automatically.
- **Already exists** → Import it so Terraform manages it without trying to re-create it:

```cmd
terraform import aws_iam_role.ecs_task_execution ecsTaskExecutionRole
```

### 3. Initialise, plan, apply

```cmd
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

After apply you will see outputs like:

```
ecr_repository_url  = "123456789012.dkr.ecr.us-east-2.amazonaws.com/locations-export"
security_group_id   = "sg-0abc1234"
public_subnet_ids   = ["subnet-0aaa", "subnet-0bbb"]
ecs_cluster_name    = "my-first-cluster"
...
```

Copy those values — you will need them for `ecs/deploy.sh`.

---

## Deploying the Docker image (after `terraform apply`)

Once infrastructure is up, build and push the container image using the existing shell script (requires Git Bash or WSL):

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export CLUSTER=$(terraform output -raw ecs_cluster_name)
export SUBNET_ID=<pick one from terraform output public_subnet_ids>
export SECURITY_GROUP_ID=$(terraform output -raw security_group_id)
export S3_BUCKET=$(terraform output -raw s3_bucket_name)

bash ../ecs/deploy.sh
```

---

## Tearing down

```cmd
terraform destroy
```

> **Note**: The `ecsTaskExecutionRole` has `prevent_destroy = true` to avoid
> accidentally deleting a role that may be shared with other ECS workloads.
> Remove that lifecycle block from `main.tf` if you want Terraform to delete it.

---

## File layout

```
infrastructure/
├── main.tf                   # All resource definitions
├── variables.tf              # Input variables with descriptions
├── outputs.tf                # Values printed after apply
├── terraform.tfvars.example  # Template — copy to terraform.tfvars
├── .gitignore                # Excludes state, .terraform/, tfvars
└── README.md                 # This file
```
