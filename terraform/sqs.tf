resource "aws_sqs_queue" "journey_events_dlq" {
  name                      = "novaura-acs-events-dlq"
  message_retention_seconds = 1209600  # 14 days
  
  tags = {
    Name        = "Novaura ACS Events Dead Letter Queue"
    Environment = var.environment
  }
}

resource "aws_sqs_queue" "journey_events" {
  name                      = "novaura-acs-events"
  visibility_timeout_seconds = 300  # 5 minutes
  message_retention_seconds = 345600  # 4 days
  
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.journey_events_dlq.arn
    maxReceiveCount     = 5
  })
  
  tags = {
    Name        = "Novaura ACS Events Queue"
    Environment = var.environment
  }
}

# SMS Channel Queues
resource "aws_sqs_queue" "sms_events_dlq" {
  name                      = "novaura-acs-sms-events-dlq"
  message_retention_seconds = 1209600  # 14 days
  
  tags = {
    Name        = "Novaura ACS SMS Events Dead Letter Queue"
    Environment = var.environment
  }
}

resource "aws_sqs_queue" "sms_events" {
  name                      = "novaura-acs-sms-events"
  visibility_timeout_seconds = 300  # 5 minutes
  message_retention_seconds = 345600  # 4 days
  
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.sms_events_dlq.arn
    maxReceiveCount     = 5
  })
  
  tags = {
    Name        = "Novaura ACS SMS Events Queue"
    Environment = var.environment
  }
}

# Email Channel Queues
resource "aws_sqs_queue" "email_events_dlq" {
  name                      = "novaura-acs-email-events-dlq"
  message_retention_seconds = 1209600  # 14 days
  
  tags = {
    Name        = "Novaura ACS Email Events Dead Letter Queue"
    Environment = var.environment
  }
}

resource "aws_sqs_queue" "email_events" {
  name                      = "novaura-acs-email-events"
  visibility_timeout_seconds = 300  # 5 minutes
  message_retention_seconds = 345600  # 4 days
  
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.email_events_dlq.arn
    maxReceiveCount     = 5
  })
  
  tags = {
    Name        = "Novaura ACS Email Events Queue"
    Environment = var.environment
  }
}

# Push Notification Channel Queues
resource "aws_sqs_queue" "push_events_dlq" {
  name                      = "novaura-acs-push-events-dlq"
  message_retention_seconds = 1209600  # 14 days
  
  tags = {
    Name        = "Novaura ACS Push Events Dead Letter Queue"
    Environment = var.environment
  }
}

resource "aws_sqs_queue" "push_events" {
  name                      = "novaura-acs-push-events"
  visibility_timeout_seconds = 300  # 5 minutes
  message_retention_seconds = 345600  # 4 days
  
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.push_events_dlq.arn
    maxReceiveCount     = 5
  })
  
  tags = {
    Name        = "Novaura ACS Push Events Queue"
    Environment = var.environment
  }
} 