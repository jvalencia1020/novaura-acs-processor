#!/bin/bash
set -e

# Wait for the database to be ready
echo "Waiting for database..."
python -c "
import sys
import time
import pymysql
while True:
    try:
        pymysql.connect(
            host='$DB_HOST',
            user='$DB_USER',
            password='$DB_PASSWORD',
            database='$DB_NAME'
        )
        break
    except pymysql.OperationalError:
        sys.stderr.write('Database not ready yet. Waiting...\n')
        time.sleep(1)
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