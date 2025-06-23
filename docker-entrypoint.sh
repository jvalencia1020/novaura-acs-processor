#!/bin/bash
set -e

echo "docker-entrypoint.sh started..."

# Print all environment variables (masking sensitive ones)
echo "Environment variables:"
echo "====================="
env | while read -r line; do
    if [[ $line == *"PASSWORD"* ]] || [[ $line == *"SECRET"* ]]; then
        echo "${line%%=*}=[MASKED]"
    else
        echo "$line"
    fi
done
echo "====================="

# Check if DB_PASSWORD is set
if [ -z "$DB_PASSWORD" ]; then
    echo "ERROR: DB_PASSWORD is not set!"
    echo "This could be because:"
    echo "1. The secret ARN is incorrect"
    echo "2. The ECS task doesn't have permission to access the secret"
    echo "3. The secret doesn't exist in AWS Secrets Manager"
    exit 1
fi

# Wait for the database to be ready
echo "Waiting for database..."

python -c "
import sys
import time
import pymysql
import os
import socket

def get_connection_info():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        return f'Could not determine IP: {str(e)}'

max_retries = 30
retry_count = 0

while retry_count < max_retries:
    try:
        conn = pymysql.connect(
            host=os.environ.get('DB_HOST'),
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASSWORD'),
            database=os.environ.get('DB_NAME'),
            port=int(os.environ.get('DB_PORT', 3306)),
            connect_timeout=10
        )
        print('Successfully connected to database!')
        conn.close()
        break
    except pymysql.OperationalError as e:
        retry_count += 1
        if retry_count == max_retries:
            print('Max retries reached. Exiting...')
            sys.exit(1)
        time.sleep(2)
"

echo "Database is ready!"

# Start the specified service
case "$SERVICE_TYPE" in
  "bulk_campaign_scheduler")
    echo "Starting bulk campaign processor scheduler..."
    exec python manage.py process_bulk_campaigns
    ;;
  "bulk_campaign_worker")
    echo "Starting bulk campaign processor worker..."
    exec python manage.py process_due_messages
    ;;
  "journey_scheduler")
    echo "Starting journey processor scheduler..."
    exec python manage.py run_scheduler
    ;;
  "journey_worker")
    echo "Starting journey processor worker..."
    exec python manage.py run_worker
    ;;
  "communication_processor_worker")
    echo "Starting communication processor worker..."
    exec python communication_processor/worker.py
    ;;
  *)
    echo "Unknown service type: $SERVICE_TYPE"
    exit 1
    ;;
esac