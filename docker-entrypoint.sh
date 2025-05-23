#!/bin/bash
set -e

echo "docker-entrypoint.sh started..."

# Wait for the database to be ready
echo "Waiting for database..."
echo "📡 Attempting DB connection..."
echo "  DB_HOST: $DB_HOST"
echo "  DB_PORT: ${DB_PORT:-3306}"
echo "  DB_NAME: $DB_NAME"
echo "  DB_USER: $DB_USER"
echo "  DB_PASSWORD: [MASKED]"

python -c "
import sys
import time
import pymysql
import os

max_retries = 30
retry_count = 0

while retry_count < max_retries:
    try:
        print(f'Attempting to connect to database at {os.environ.get(\"DB_HOST\")}...')
        conn = pymysql.connect(
            host=os.environ.get('DB_HOST'),
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASSWORD'),
            database=os.environ.get('DB_NAME'),
            port=int(os.environ.get('DB_PORT', 3306))
        )
        print('Successfully connected to database!')
        conn.close()
        break
    except pymysql.OperationalError as e:
        retry_count += 1
        error_msg = str(e)
        print('=' * 50)
        print(f'Database connection failed (attempt {retry_count}/{max_retries})')
        print(f'Error: {error_msg}')
        print('=' * 50)
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
    exec python manage.py run_bulk_campaign_processor
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
  *)
    echo "Unknown service type: $SERVICE_TYPE"
    exit 1
    ;;
esac