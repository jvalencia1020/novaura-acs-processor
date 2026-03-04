# VPC and networking are provided by the shared Terraform repo (main repo).
# This app uses variables for vpc_id, private_subnet_ids, public_subnet_ids, and
# vpc_endpoints_security_group_id — set in terraform.tfvars or via SSM.

# Outputs for reference and for other modules
output "vpc_id" {
  value       = var.vpc_id
  description = "The ID of the VPC (from shared networking stack)"
}

output "private_subnet_ids" {
  value       = var.private_subnet_ids
  description = "Private subnet IDs in the VPC"
}

output "vpc_endpoints_security_group_id" {
  value       = var.vpc_endpoints_security_group_id
  description = "Security group ID for VPC endpoints (managed in shared repo)"
}
