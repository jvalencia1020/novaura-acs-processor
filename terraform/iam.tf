resource "aws_iam_role" "ecs_execution_role" {
  name = "novaura-acs-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_role_policy" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_role_secrets_policy" {
  name = "novaura-acs-ecs-execution-secrets-policy"
  role = aws_iam_role.ecs_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          var.db_password_arn,
          var.django_secret_key_arn,
          var.bland_ai_api_key_arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_execution_role_logs_policy" {
  name = "novaura-acs-ecs-execution-logs-policy"
  role = aws_iam_role.ecs_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:CreateLogGroup",
          "logs:DescribeLogStreams"
        ]
        Resource = [
          "${aws_cloudwatch_log_group.processor_logs.arn}:*",
          "${aws_cloudwatch_log_group.processor_logs.arn}:*:*"
        ]
      }
    ]
  })
}

resource "aws_iam_role" "ecs_task_role" {
  name = "novaura-acs-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_task_role_policy" {
  name = "novaura-acs-ecs-task-policy"
  role = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = [
          aws_sqs_queue.journey_events.arn,
          aws_sqs_queue.journey_events_dlq.arn,
          aws_sqs_queue.sms_events.arn,
          aws_sqs_queue.sms_events_dlq.arn,
          aws_sqs_queue.email_events.arn,
          aws_sqs_queue.email_events_dlq.arn,
          aws_sqs_queue.push_events.arn,
          aws_sqs_queue.push_events_dlq.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          var.db_password_arn,
          var.django_secret_key_arn,
          var.bland_ai_api_key_arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_execution_policy" {
  name = "novaura-acs-ecs-execution-policy"
  role = aws_iam_role.ecs_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          var.db_password_arn,
          var.django_secret_key_arn,
          var.twilio_credentials_arn,
          var.bland_ai_api_key_arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.processor_logs.arn}:*"
      }
    ]
  })
} 