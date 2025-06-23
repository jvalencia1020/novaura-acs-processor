# Communication Processor SQS Worker Deployment Guide

This guide explains how to deploy and test the SQS worker for the communication processor in AWS.

## Overview

The SQS worker is a long-lived ECS container that continuously polls SQS queues and processes communication events using the appropriate channel processors (SMS, Email, etc.).

## Architecture

```
SQS Queues → ECS Worker → Channel Processors → Communication Events
     ↓              ↓              ↓                    ↓
  SMS Events   Worker Container  SMS Processor    Database Records
  Email Events                   Email Processor
  Push Events
```

## Prerequisites

1. **AWS Infrastructure**: VPC, ECS Cluster, ECR Repository
2. **SQS Queues**: Already configured in `terraform/sqs.tf`
3. **IAM Roles**: ECS execution and task roles with SQS permissions
4. **Secrets Manager**: Database and Twilio credentials
5. **Docker Image**: Built and pushed to ECR

## Deployment Steps

### 1. Build and Push Docker Image

```bash
# Build the Docker image
docker build -t novaura-acs-processor .

# Tag for ECR
docker tag novaura-acs-processor:latest 054037109114.dkr.ecr.us-east-1.amazonaws.com/novaura-acs-processor:latest

# Push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 054037109114.dkr.ecr.us-east-1.amazonaws.com
docker push 054037109114.dkr.ecr.us-east-1.amazonaws.com/novaura-acs-processor:latest
```

### 2. Deploy Terraform Infrastructure

```bash
cd terraform

# Plan the deployment
terraform plan -var-file=terraform.tfvars

# Apply the changes
terraform apply -var-file=terraform.tfvars
```

### 3. Verify Deployment

```bash
# Check ECS service status
aws ecs describe-services \
  --cluster novaura-acs-processor-cluster \
  --services novaura-acs-communication-processor-worker-service

# Check CloudWatch logs
aws logs describe-log-streams \
  --log-group-name /ecs/novaura-acs-processor \
  --log-stream-name-prefix communication-processor-worker
```

## Configuration

### Environment Variables

The worker uses the following environment variables:

- `WORKER_TYPE`: Type of worker (`all`, `sms`, `email`)
- `SMS_QUEUE_URL`: SMS events queue URL
- `EMAIL_QUEUE_URL`: Email events queue URL
- `DJANGO_SETTINGS_MODULE`: Django settings module
- Database credentials (from Secrets Manager)
- Twilio credentials (from Secrets Manager)

### Terraform Variables

Update `terraform/terraform.tfvars` with your values:

```hcl
environment = "production"
image_tag = "latest"
db_name = "your_database_name"
db_user = "your_database_user"
db_host = "your_database_host"
db_password_arn = "arn:aws:secretsmanager:us-east-1:054037109114:secret:db-password"
django_secret_key_arn = "arn:aws:secretsmanager:us-east-1:054037109114:secret:django-secret-key"
twilio_credentials_arn = "arn:aws:secretsmanager:us-east-1:054037109114:secret:twilio-credentials"
```

## Testing

### 1. Local Testing

Test the worker locally before deploying:

```bash
# Run all workers
python manage.py run_communication_worker

# Run SMS worker only
python manage.py run_communication_worker --worker-type sms

# Run with custom queue URLs
python manage.py run_communication_worker \
  --worker-type sms \
  --sms-queue-url https://sqs.us-east-1.amazonaws.com/054037109114/novaura-acs-sms-events
```

### 2. Send Test Messages

Use the existing management commands to send test messages:

```bash
# Send test SMS message
python manage.py build_sqs_message \
  --channel sms \
  --message-type message_received \
  --from-number +1234567890 \
  --to-number +0987654321 \
  --body "Hello, this is a test message"

# Send test email message
python manage.py build_sqs_message \
  --channel email \
  --message-type message_received \
  --from-email test@example.com \
  --to-email user@example.com \
  --subject "Test Email" \
  --body "This is a test email message"
```

### 3. Monitor Processing

Check CloudWatch logs for processing results:

```bash
# Get recent logs
aws logs filter-log-events \
  --log-group-name /ecs/novaura-acs-processor \
  --log-stream-name-prefix communication-processor-worker \
  --start-time $(date -d '1 hour ago' +%s)000
```

## Monitoring and Troubleshooting

### 1. CloudWatch Metrics

Monitor these key metrics:

- **ECS Service Metrics**:
  - CPU and Memory utilization
  - Running task count
  - Service health

- **SQS Metrics**:
  - Number of messages received
  - Number of messages deleted
  - Approximate age of oldest message
  - Number of messages in flight

### 2. Log Analysis

Common log patterns to monitor:

```bash
# Successful processing
grep "Successfully processed" /var/log/worker.log

# Processing errors
grep "Error processing" /var/log/worker.log

# Queue statistics
grep "Processed.*Failed.*Deleted" /var/log/worker.log
```

### 3. Common Issues

#### Worker Not Starting
- Check ECS task definition and service configuration
- Verify IAM roles have correct permissions
- Check CloudWatch logs for startup errors

#### Messages Not Processing
- Verify SQS queue URLs are correct
- Check IAM permissions for SQS access
- Ensure database connectivity
- Verify Django settings module

#### High Error Rate
- Check message format in SQS
- Verify processor validation logic
- Monitor database connection pool
- Check external service dependencies (Twilio, etc.)

### 4. Scaling

#### Horizontal Scaling
Increase the number of worker tasks:

```bash
# Update desired count
aws ecs update-service \
  --cluster novaura-acs-processor-cluster \
  --service novaura-acs-communication-processor-worker-service \
  --desired-count 3
```

#### Vertical Scaling
Increase CPU and memory allocation in the task definition.

## Security Considerations

### 1. IAM Permissions
- Use least privilege principle
- Regularly audit IAM roles and policies
- Rotate credentials regularly

### 2. Network Security
- Use private subnets for worker tasks
- Configure security groups to restrict access
- Use VPC endpoints for AWS services

### 3. Secrets Management
- Store sensitive data in AWS Secrets Manager
- Use IAM roles to access secrets
- Rotate secrets regularly

## Cost Optimization

### 1. Resource Allocation
- Monitor CPU and memory usage
- Right-size task definitions
- Use Spot instances for non-critical workloads

### 2. SQS Optimization
- Use long polling to reduce API calls
- Batch message processing
- Configure appropriate visibility timeout

### 3. Logging
- Set appropriate log retention periods
- Use log filtering to reduce storage costs
- Consider using CloudWatch Insights for analysis

## Maintenance

### 1. Regular Updates
- Keep Docker images updated
- Update dependencies regularly
- Apply security patches promptly

### 2. Backup and Recovery
- Backup database regularly
- Test recovery procedures
- Document rollback procedures

### 3. Performance Tuning
- Monitor and optimize database queries
- Tune SQS polling intervals
- Optimize message processing logic

## Support and Documentation

For issues and questions:

1. Check CloudWatch logs first
2. Review this deployment guide
3. Check the communication processor services documentation
4. Review Terraform configuration
5. Contact the development team

## Next Steps

After successful deployment:

1. **Set up monitoring alerts** for critical metrics
2. **Configure log aggregation** for better observability
3. **Implement automated testing** for the worker
4. **Plan for additional channels** (Voice, Chat, etc.)
5. **Consider implementing auto-scaling** based on queue depth 