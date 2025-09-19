#!/bin/bash

# Production entrypoint script for Django-Twilio-Call
set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}" >&2
}

warning() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

# Wait for database to be ready
wait_for_db() {
    log "Waiting for database connection..."

    until python manage.py dbshell --command="SELECT 1;" > /dev/null 2>&1; do
        warning "Database is unavailable - sleeping"
        sleep 2
    done

    log "Database is available!"
}

# Wait for Redis to be ready
wait_for_redis() {
    log "Waiting for Redis connection..."

    if [ -n "$REDIS_URL" ]; then
        until python -c "
import redis
import os
r = redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'))
r.ping()
" > /dev/null 2>&1; do
            warning "Redis is unavailable - sleeping"
            sleep 2
        done

        log "Redis is available!"
    else
        warning "REDIS_URL not set, skipping Redis check"
    fi
}

# Run database migrations
run_migrations() {
    log "Running database migrations..."
    python manage.py migrate --noinput

    if [ $? -eq 0 ]; then
        log "Migrations completed successfully"
    else
        error "Migration failed"
        exit 1
    fi
}

# Collect static files
collect_static() {
    log "Collecting static files..."
    python manage.py collectstatic --noinput --clear

    if [ $? -eq 0 ]; then
        log "Static files collected successfully"
    else
        error "Static file collection failed"
        exit 1
    fi
}

# Create superuser if it doesn't exist
create_superuser() {
    if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
        log "Creating superuser..."
        python manage.py shell << EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists():
    User.objects.create_superuser('$DJANGO_SUPERUSER_USERNAME', '$DJANGO_SUPERUSER_EMAIL', '$DJANGO_SUPERUSER_PASSWORD')
    print('Superuser created successfully')
else:
    print('Superuser already exists')
EOF
    else
        warning "Superuser environment variables not set, skipping superuser creation"
    fi
}

# Validate configuration
validate_config() {
    log "Validating Django configuration..."
    python manage.py check --deploy

    if [ $? -eq 0 ]; then
        log "Configuration validation passed"
    else
        error "Configuration validation failed"
        exit 1
    fi
}

# Start Gunicorn server
start_gunicorn() {
    log "Starting Gunicorn server..."

    exec gunicorn callcenter.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers ${GUNICORN_WORKERS:-4} \
        --worker-class gthread \
        --threads 2 \
        --timeout ${GUNICORN_TIMEOUT:-30} \
        --keepalive ${GUNICORN_KEEPALIVE:-2} \
        --max-requests ${GUNICORN_MAX_REQUESTS:-1000} \
        --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-100} \
        --preload \
        --access-logfile - \
        --error-logfile - \
        --capture-output \
        --enable-stdio-inheritance \
        --log-level info
}

# Start Celery worker
start_celery_worker() {
    log "Starting Celery worker..."

    exec celery -A django_twilio_call worker \
        --loglevel=info \
        --concurrency=${CELERY_WORKER_CONCURRENCY:-4} \
        --pool=threads \
        --queues=${CELERY_WORKER_QUEUES:-celery,twilio,high_priority} \
        --heartbeat-interval=30 \
        --without-gossip \
        --without-mingle
}

# Start Celery beat
start_celery_beat() {
    log "Starting Celery beat..."

    exec celery -A django_twilio_call beat \
        --loglevel=info \
        --scheduler django_celery_beat.schedulers:DatabaseScheduler \
        --pidfile=/tmp/celerybeat.pid
}

# Start Flower monitoring
start_flower() {
    log "Starting Flower monitoring..."

    exec celery -A django_twilio_call flower \
        --port=5555 \
        --broker=${CELERY_BROKER_URL:-redis://redis:6379/0} \
        --basic_auth=${FLOWER_BASIC_AUTH:-admin:admin} \
        --url_prefix=${FLOWER_URL_PREFIX:-flower}
}

# Main execution logic
main() {
    log "Starting Django-Twilio-Call application..."

    # Wait for dependencies
    wait_for_db
    wait_for_redis

    # Common setup for all services
    case "${1:-web}" in
        web|gunicorn)
            validate_config
            run_migrations
            collect_static
            create_superuser
            start_gunicorn
            ;;
        worker|celery-worker)
            wait_for_db
            start_celery_worker
            ;;
        beat|celery-beat)
            wait_for_db
            start_celery_beat
            ;;
        flower)
            start_flower
            ;;
        migrate)
            run_migrations
            ;;
        collectstatic)
            collect_static
            ;;
        shell)
            python manage.py shell
            ;;
        bash)
            exec bash
            ;;
        *)
            log "Available commands: web, worker, beat, flower, migrate, collectstatic, shell, bash"
            log "Running custom command: $@"
            exec "$@"
            ;;
    esac
}

# Error handling
trap 'error "Script failed at line $LINENO"' ERR

# Run main function with all arguments
main "$@"