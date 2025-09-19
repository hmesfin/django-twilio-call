#!/bin/bash
# Production-ready Celery worker startup script

set -e

# Environment variables with defaults
WORKER_TYPE=${WORKER_TYPE:-default}
CONCURRENCY=${CONCURRENCY:-2}
LOGLEVEL=${LOGLEVEL:-info}
MAX_TASKS_PER_CHILD=${MAX_TASKS_PER_CHILD:-1000}
MAX_MEMORY_PER_CHILD=${MAX_MEMORY_PER_CHILD:-200000}  # 200MB
PREFETCH_MULTIPLIER=${PREFETCH_MULTIPLIER:-1}

# Wait for dependencies
echo "Waiting for Redis..."
while ! redis-cli -h redis -p 6379 ping > /dev/null 2>&1; do
    echo "Redis is unavailable - sleeping"
    sleep 1
done
echo "Redis is up!"

echo "Waiting for PostgreSQL..."
while ! pg_isready -h postgres -p 5432 -U postgres > /dev/null 2>&1; do
    echo "PostgreSQL is unavailable - sleeping"
    sleep 1
done
echo "PostgreSQL is up!"

# Run Django migrations (only one worker should do this)
if [ "$WORKER_TYPE" = "realtime" ]; then
    echo "Running Django migrations..."
    python manage.py migrate --noinput
fi

# Configure worker based on type
case $WORKER_TYPE in
    "realtime")
        QUEUES="webhooks,realtime,notifications"
        CONCURRENCY=${CONCURRENCY:-4}
        HOSTNAME="realtime-worker"
        ;;
    "processing")
        QUEUES="recordings,analytics"
        CONCURRENCY=${CONCURRENCY:-2}
        HOSTNAME="processing-worker"
        ;;
    "reports")
        QUEUES="reports,exports"
        CONCURRENCY=${CONCURRENCY:-1}
        MAX_TASKS_PER_CHILD=100  # Lower for memory-intensive tasks
        HOSTNAME="reports-worker"
        ;;
    "maintenance")
        QUEUES="maintenance,email,retries"
        CONCURRENCY=${CONCURRENCY:-2}
        HOSTNAME="maintenance-worker"
        ;;
    *)
        QUEUES="celery"
        HOSTNAME="default-worker"
        ;;
esac

# Add hostname suffix
HOSTNAME="${HOSTNAME}@%h"

echo "Starting Celery worker:"
echo "  Type: $WORKER_TYPE"
echo "  Queues: $QUEUES"
echo "  Concurrency: $CONCURRENCY"
echo "  Hostname: $HOSTNAME"
echo "  Max tasks per child: $MAX_TASKS_PER_CHILD"
echo "  Max memory per child: ${MAX_MEMORY_PER_CHILD}KB"

# Start Celery worker with monitoring
exec celery -A django_twilio_call.celery worker \
    --loglevel=$LOGLEVEL \
    --queues=$QUEUES \
    --concurrency=$CONCURRENCY \
    --prefetch-multiplier=$PREFETCH_MULTIPLIER \
    --max-tasks-per-child=$MAX_TASKS_PER_CHILD \
    --max-memory-per-child=$MAX_MEMORY_PER_CHILD \
    --hostname=$HOSTNAME \
    --time-limit=1800 \
    --soft-time-limit=1500 \
    --without-gossip \
    --without-mingle \
    --without-heartbeat