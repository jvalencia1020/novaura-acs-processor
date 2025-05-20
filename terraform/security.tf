resource "aws_security_group" "ecs_service" {
  name        = "novaura-acs-ecs-service"
  description = "Security group for Novaura ACS ECS services"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
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