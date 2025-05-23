resource "aws_security_group" "ecs_service" {
  name        = "novaura-acs-ecs-service"
  description = "Security group for Novaura ACS ECS services"
  vpc_id      = data.aws_vpc.existing.id

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "Novaura ACS ECS Service Security Group"
    Environment = var.environment
  }
}

# Allow all outbound traffic from ECS tasks
resource "aws_security_group_rule" "ecs_allow_all_egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ecs_service.id
  description       = "Allow all outbound traffic from ECS tasks"
}

# Security group rule to allow ECS to access RDS
resource "aws_security_group_rule" "ecs_to_rds" {
  type                     = "ingress"
  from_port                = 3306
  to_port                  = 3306
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_service.id
  security_group_id        = var.rds_security_group_id
  description             = "Allow ECS to access RDS"
} 