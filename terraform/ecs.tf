resource "aws_ecs_cluster" "processor_cluster" {
  name = "novaura-acs-processor-cluster"
  
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  
  tags = {
    Name        = "Novaura ACS Processor Cluster"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "processor_logs" {
  name              = "/ecs/novaura-acs-processor"
  retention_in_days = 30
  
  tags = {
    Name        = "Novaura ACS Processor Logs"
    Environment = var.environment
  }
}

resource "aws_ecs_task_definition" "scheduler_task" {
  family                   = "novaura-acs-processor-scheduler"
  cpu                      = var.scheduler_cpu
  memory                   = var.scheduler_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn
  
  container_definitions = jsonencode([
    {
      name      = "scheduler"
      image     = "${var.ecr_repository_url}:latest"
      essential = true
      
      environment = [
        { name = "SERVICE_TYPE", value = "scheduler" },
        { name = "JOURNEY_EVENTS_QUEUE_URL", value = aws_sqs_queue.journey_events.url },
        { name = "DB_NAME", value = var.db_name },
        { name = "DB_USER", value = var.db_user },
        { name = "DB_HOST", value = var.db_host },
        { name = "DB_PORT", value = "5432" },
        { name = "DJANGO_SETTINGS_MODULE", value = "acs_personalization.settings.prod" }
      ]
      
      secrets = [
        { name = "DB_PASSWORD", valueFrom = var.db_password_arn },
        { name = "DJANGO_SECRET_KEY", valueFrom = var.django_secret_key_arn }
      ]
      
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.processor_logs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "scheduler"
        }
      }
    }
  ])
  
  tags = {
    Name        = "Novaura ACS Processor Scheduler Task"
    Environment = var.environment
  }
}

resource "aws_ecs_task_definition" "worker_task" {
  family                   = "novaura-acs-processor-worker"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn
  
  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = "${var.ecr_repository_url}:latest"
      essential = true
      
      environment = [
        { name = "SERVICE_TYPE", value = "worker" },
        { name = "JOURNEY_EVENTS_QUEUE_URL", value = aws_sqs_queue.journey_events.url },
        { name = "DB_NAME", value = var.db_name },
        { name = "DB_USER", value = var.db_user },
        { name = "DB_HOST", value = var.db_host },
        { name = "DB_PORT", value = "5432" },
        { name = "DJANGO_SETTINGS_MODULE", value = "acs_personalization.settings.prod" }
      ]
      
      secrets = [
        { name = "DB_PASSWORD", valueFrom = var.db_password_arn },
        { name = "DJANGO_SECRET_KEY", valueFrom = var.django_secret_key_arn }
      ]
      
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.processor_logs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])
  
  tags = {
    Name        = "Novaura ACS Processor Worker Task"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "scheduler_service" {
  name            = "novaura-acs-processor-scheduler"
  cluster         = aws_ecs_cluster.processor_cluster.id
  task_definition = aws_ecs_task_definition.scheduler_task.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.ecs_service.id]
  }
  
  tags = {
    Name        = "Novaura ACS Processor Scheduler Service"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "worker_service" {
  name            = "novaura-acs-processor-worker"
  cluster         = aws_ecs_cluster.processor_cluster.id
  task_definition = aws_ecs_task_definition.worker_task.arn
  desired_count   = var.worker_count
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.ecs_service.id]
  }
  
  tags = {
    Name        = "Novaura ACS Processor Worker Service"
    Environment = var.environment
  }
} 