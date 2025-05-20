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