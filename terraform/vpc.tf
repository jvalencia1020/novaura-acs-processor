# Get the existing VPC where RDS is hosted
data "aws_vpc" "existing" {
  tags = {
    Name = "Lambda VPC"
  }
}

# Get the existing private subnets
data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.existing.id]
  }

  filter {
    name   = "tag:Name"
    values = ["*novaura-crm-lambda-public*"]
  }
}

# Get the existing public subnets
data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.existing.id]
  }

  filter {
    name   = "tag:Name"
    values = ["*novaura-crm-private-nat-*"]
  }
}

# Get subnet details
data "aws_subnet" "private" {
  for_each = toset(data.aws_subnets.private.ids)
  id       = each.value
}

data "aws_subnet" "public" {
  for_each = toset(data.aws_subnets.public.ids)
  id       = each.value
}

# Get the existing route table for private subnets
data "aws_route_table" "private" {
  vpc_id = data.aws_vpc.existing.id
  filter {
    name   = "tag:Name"
    values = ["novaura-crm-private-nat-rt"]
  }
}

# Get existing routes in the route table
data "aws_route" "existing_nat" {
  route_table_id = data.aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
}

# Create Elastic IP for NAT Gateway
resource "aws_eip" "nat" {
  tags = {
    Name = "novaura-acs-nat-eip"
  }
}

# Create NAT Gateway in the first public subnet
resource "aws_nat_gateway" "nat" {
  allocation_id = aws_eip.nat.id
  subnet_id     = tolist(data.aws_subnets.public.ids)[0]

  tags = {
    Name = "novaura-acs-nat-gateway"
  }

  depends_on = [aws_eip.nat]
}

# Add NAT Gateway route to existing route table only if it doesn't exist
resource "aws_route" "nat_gateway" {
  count                  = data.aws_route.existing_nat.id == null ? 1 : 0
  route_table_id         = data.aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.nat.id
}

# Create VPC Endpoints for AWS Services
resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id             = data.aws_vpc.existing.id
  service_name       = "com.amazonaws.us-east-1.secretsmanager"
  vpc_endpoint_type  = "Interface"
  subnet_ids         = data.aws_subnets.private.ids
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  private_dns_enabled = true

  tags = {
    Name = "novaura-acs-secretsmanager-endpoint"
  }
}

resource "aws_vpc_endpoint" "rds" {
  vpc_id             = data.aws_vpc.existing.id
  service_name       = "com.amazonaws.us-east-1.rds"
  vpc_endpoint_type  = "Interface"
  subnet_ids         = data.aws_subnets.private.ids
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  private_dns_enabled = true

  tags = {
    Name = "novaura-acs-rds-endpoint"
  }
}

resource "aws_vpc_endpoint" "logs" {
  vpc_id             = data.aws_vpc.existing.id
  service_name       = "com.amazonaws.us-east-1.logs"
  vpc_endpoint_type  = "Interface"
  subnet_ids         = data.aws_subnets.private.ids
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  private_dns_enabled = true

  tags = {
    Name = "novaura-acs-logs-endpoint"
  }
}

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id             = data.aws_vpc.existing.id
  service_name       = "com.amazonaws.us-east-1.ecr.api"
  vpc_endpoint_type  = "Interface"
  subnet_ids         = data.aws_subnets.private.ids
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  private_dns_enabled = true

  tags = {
    Name = "novaura-acs-ecr-api-endpoint"
  }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id             = data.aws_vpc.existing.id
  service_name       = "com.amazonaws.us-east-1.ecr.dkr"
  vpc_endpoint_type  = "Interface"
  subnet_ids         = data.aws_subnets.private.ids
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  private_dns_enabled = true

  tags = {
    Name = "novaura-acs-ecr-dkr-endpoint"
  }
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = data.aws_vpc.existing.id
  service_name      = "com.amazonaws.us-east-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [data.aws_route_table.private.id]

  tags = {
    Name = "novaura-acs-s3-endpoint"
  }
}

# Security group for VPC endpoints
resource "aws_security_group" "vpc_endpoints" {
  name        = "novaura-acs-vpc-endpoints"
  description = "Security group for VPC endpoints"
  vpc_id      = data.aws_vpc.existing.id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_service.id]
  }

  tags = {
    Name = "novaura-acs-vpc-endpoints-sg"
  }
}

# Allow link-runtime ECS tasks to reach shared VPC endpoints (ECR, Secrets Manager).
# Link-runtime adds this via its own Terraform; if this project owns the SG, we must
# include the rule here or our apply will remove it and break link-runtime.
resource "aws_security_group_rule" "vpc_endpoints_from_link_runtime" {
  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  source_security_group_id = "sg-0487a1fcba60f06e2" # link-runtime ECS tasks (confirm in link-runtime terraform output)
  security_group_id        = aws_security_group.vpc_endpoints.id
  description              = "Allow HTTPS from link-runtime ECS tasks to VPC endpoint"
}

# Update the private_subnet_ids variable to use the existing subnets
locals {
  private_subnet_ids = data.aws_subnets.private.ids
}

# Outputs for reference
output "vpc_id" {
  value       = data.aws_vpc.existing.id
  description = "The ID of the VPC where RDS is hosted"
}

output "private_subnet_ids" {
  value       = local.private_subnet_ids
  description = "List of private subnet IDs in the VPC"
}

output "vpc_cidr" {
  value       = data.aws_vpc.existing.cidr_block
  description = "The CIDR block of the VPC"
}

output "nat_gateway_ip" {
  value       = aws_eip.nat.public_ip
  description = "The public IP address of the NAT Gateway"
} 