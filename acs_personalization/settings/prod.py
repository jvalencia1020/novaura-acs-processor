"""
Production settings for acs_personalization project.
"""

from .base import *
import os

# No DEBUG in production
DEBUG = False

# Define allowed hosts for production
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')  # Get from environment variable or default to '*'

# SQS Queue URLs for communication processor
SMS_QUEUE_URL = os.getenv('SMS_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/054037109114/novaura-acs-sms-events')
EMAIL_QUEUE_URL = os.getenv('EMAIL_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/054037109114/novaura-acs-email-events')

# Additional production-specific settings
# AWS-specific settings would go here if needed