# ==============================================================
# infrastructure/variables.tf
# ==============================================================

variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "us-east-2"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    Project   = "locations-info-export"
    ManagedBy = "terraform"
  }
}

variable "vpc_id" {
  description = "VPC ID. Leave null to use the account default VPC."
  type        = string
  default     = null
}

# ------ S3 legacy export bucket --------------------------------

variable "s3_bucket_name" {
  description = "Legacy S3 bucket (kept for backward-compat)."
  type        = string
}

variable "s3_key_prefix" {
  description = "Key prefix inside the legacy export bucket."
  type        = string
  default     = "exports/"
}

# ------ S3 input / output (new CLIP pipeline) ------------------

variable "input_bucket" {
  description = "S3 bucket that holds query PNG images."
  type        = string
  default     = "4uproject-eafit"
}

variable "input_prefix" {
  description = "S3 prefix (folder) for query images."
  type        = string
  default     = "testing/"
}

variable "output_bucket" {
  description = "S3 bucket where the results CSV is written."
  type        = string
  default     = "4uproject-eafit"
}

variable "output_prefix" {
  description = "S3 prefix (folder) for the results CSV."
  type        = string
  default     = "output/"
}

# ------ Database -----------------------------------------------

variable "db_host" {
  description = "Aurora PostgreSQL cluster endpoint."
  type        = string
}

variable "db_port" {
  description = "PostgreSQL port."
  type        = number
  default     = 5432
}

variable "db_user" {
  description = "DB user for IAM auth."
  type        = string
  default     = "postgres"
}

variable "db_name" {
  description = "Database name."
  type        = string
  default     = "postgres"
}

variable "embeddings_table" {
  description = "Table with pre-computed reference embeddings."
  type        = string
  default     = "train_embeddings"
}

variable "locations_table" {
  description = "Table mapping point IDs to location names."
  type        = string
  default     = "locations_info"
}

# ------ CLIP model ---------------------------------------------

variable "clip_model_id" {
  description = "HuggingFace model ID for CLIP (must match what was used to generate stored embeddings)."
  type        = string
  default     = "openai/clip-vit-base-patch32"
}

# ------ ECS ----------------------------------------------------

variable "cluster_name" {
  description = "ECS cluster name."
  type        = string
  default     = "my-first-cluster"
}

# ------ CloudWatch ---------------------------------------------

variable "log_retention_days" {
  description = "Days to retain ECS task logs."
  type        = number
  default     = 30
}
