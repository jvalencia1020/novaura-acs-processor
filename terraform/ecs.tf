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

# Bulk Campaign Scheduler Task
resource "aws_ecs_task_definition" "bulk_campaign_scheduler_task" {
  family                   = "novaura-acs-bulk-campaign-scheduler"
  cpu                      = var.scheduler_cpu
  memory                   = var.scheduler_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn
  
  container_definitions = jsonencode([
    {
      name      = "bulk-campaign-scheduler"
      image     = "${data.aws_ecr_repository.processor_repository.repository_url}:latest"
      essential = true
      command   = ["python", "manage.py", "run_bulk_campaign_processor"]
      
      environment = [
        { name = "SERVICE_TYPE", value = "bulk_campaign_scheduler" },
        { name = "JOURNEY_EVENTS_QUEUE_URL", value = aws_sqs_queue.journey_events.url },
        { name = "DB_NAME", value = var.db_name },
        { name = "DB_USER", value = var.db_user },
        { name = "DB_HOST", value = var.db_host },
        { name = "DB_PORT", value = "3306" },
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
          "awslogs-stream-prefix" = "bulk-campaign-scheduler"
        }
      }
    }
  ])
  
  tags = {
    Name        = "Novaura ACS Bulk Campaign Scheduler Task"
    Environment = var.environment
  }
}

# Journey Scheduler Task
resource "aws_ecs_task_definition" "journey_scheduler_task" {
  family                   = "novaura-acs-journey-scheduler"
  cpu                      = var.scheduler_cpu
  memory                   = var.scheduler_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn
  
  container_definitions = jsonencode([
    {
      name      = "journey-scheduler"
      image     = "${data.aws_ecr_repository.processor_repository.repository_url}:latest"
      essential = true
      command   = ["python", "manage.py", "run_scheduler"]
      
      environment = [
        { name = "SERVICE_TYPE", value = "journey_scheduler" },
        { name = "JOURNEY_EVENTS_QUEUE_URL", value = aws_sqs_queue.journey_events.url },
        { name = "DB_NAME", value = var.db_name },
        { name = "DB_USER", value = var.db_user },
        { name = "DB_HOST", value = var.db_host },
        { name = "DB_PORT", value = "3306" },
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
          "awslogs-stream-prefix" = "journey-scheduler"
        }
      }
    }
  ])
  
  tags = {
    Name        = "Novaura ACS Journey Scheduler Task"
    Environment = var.environment
  }
}

# Journey Worker Task
resource "aws_ecs_task_definition" "journey_worker_task" {
  family                   = "novaura-acs-journey-worker"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn
  
  container_definitions = jsonencode([
    {
      name      = "journey-worker"
      image     = "${data.aws_ecr_repository.processor_repository.repository_url}:latest"
      essential = true
      command   = ["python", "manage.py", "run_worker"]
      
      environment = [
        { name = "SERVICE_TYPE", value = "journey_worker" },
        { name = "JOURNEY_EVENTS_QUEUE_URL", value = aws_sqs_queue.journey_events.url },
        { name = "DB_NAME", value = var.db_name },
        { name = "DB_USER", value = var.db_user },
        { name = "DB_HOST", value = var.db_host },
        { name = "DB_PORT", value = "3306" },
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
          "awslogs-stream-prefix" = "journey-worker"
        }
      }
    }
  ])
  
  tags = {
    Name        = "Novaura ACS Journey Worker Task"
    Environment = var.environment
  }
}

# Bulk Campaign Worker Task
resource "aws_ecs_task_definition" "bulk_campaign_worker_task" {
  family                   = "novaura-acs-bulk-campaign-worker"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn
  
  container_definitions = jsonencode([
    {
      name      = "bulk-campaign-worker"
      image     = "${data.aws_ecr_repository.processor_repository.repository_url}:latest"
      essential = true
      command   = ["python", "manage.py", "process_due_messages"]
      
      environment = [
        { name = "SERVICE_TYPE", value = "bulk_campaign_worker" },
        { name = "JOURNEY_EVENTS_QUEUE_URL", value = aws_sqs_queue.journey_events.url },
        { name = "DB_NAME", value = var.db_name },
        { name = "DB_USER", value = var.db_user },
        { name = "DB_HOST", value = var.db_host },
        { name = "DB_PORT", value = "3306" },
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
          "awslogs-stream-prefix" = "bulk-campaign-worker"
        }
      }
    }
  ])
  
  tags = {
    Name        = "Novaura ACS Bulk Campaign Worker Task"
    Environment = var.environment
  }
}

# Services
resource "aws_ecs_service" "bulk_campaign_scheduler_service" {
  name            = "novaura-acs-bulk-campaign-scheduler"
  cluster         = aws_ecs_cluster.processor_cluster.id
  task_definition = aws_ecs_task_definition.bulk_campaign_scheduler_task.arn
  desired_count   = 0
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets          = local.private_subnet_ids
    security_groups = [aws_security_group.ecs_service.id]
  }
  
  tags = {
    Name        = "Novaura ACS Bulk Campaign Scheduler Service"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "journey_scheduler_service" {
  name            = "novaura-acs-journey-scheduler"
  cluster         = aws_ecs_cluster.processor_cluster.id
  task_definition = aws_ecs_task_definition.journey_scheduler_task.arn
  desired_count   = 0
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets          = local.private_subnet_ids
    security_groups = [aws_security_group.ecs_service.id]
  }
  
  tags = {
    Name        = "Novaura ACS Journey Scheduler Service"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "journey_worker_service" {
  name            = "novaura-acs-journey-worker"
  cluster         = aws_ecs_cluster.processor_cluster.id
  task_definition = aws_ecs_task_definition.journey_worker_task.arn
  desired_count   = var.worker_count
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets          = local.private_subnet_ids
    security_groups = [aws_security_group.ecs_service.id]
  }
  
  tags = {
    Name        = "Novaura ACS Journey Worker Service"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "bulk_campaign_worker_service" {
  name            = "novaura-acs-bulk-campaign-worker"
  cluster         = aws_ecs_cluster.processor_cluster.id
  task_definition = aws_ecs_task_definition.bulk_campaign_worker_task.arn
  desired_count   = var.worker_count
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets          = local.private_subnet_ids
    security_groups = [aws_security_group.ecs_service.id]
  }
  
  tags = {
    Name        = "Novaura ACS Bulk Campaign Worker Service"
    Environment = var.environment
  }
} 