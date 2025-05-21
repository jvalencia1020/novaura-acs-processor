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
    values = ["*novaura-crm-lambda-private*"]
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