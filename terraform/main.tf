terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
    }
  }
  backend "s3" {
    bucket         = "novaura-terraform-state"
    key            = "ecs/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

# Variables
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "scheduler_cpu" {
  description = "CPU units for scheduler task"
  type        = number
  default     = 256
}

variable "scheduler_memory" {
  description = "Memory for scheduler task"
  type        = number
  default     = 512
}

variable "worker_cpu" {
  description = "CPU units for worker task"
  type        = number
  default     = 256
}

variable "worker_memory" {
  description = "Memory for worker task"
  type        = number
  default     = 512
}

variable "worker_count" {
  description = "Number of worker tasks"
  type        = number
  default     = 2
}

variable "ecr_repository_url" {
  description = "ECR repository URL"
  type        = string
}

variable "db_name" {
  description = "Database name"
  type        = string
}

variable "db_user" {
  description = "Database user"
  type        = string
}

variable "db_host" {
  description = "Database host"
  type        = string
}

variable "db_password_arn" {
  description = "ARN of the database password in Secrets Manager"
  type        = string
}

variable "django_secret_key_arn" {
  description = "ARN of the Django secret key in Secrets Manager"
  type        = string
} 