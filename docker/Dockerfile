FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CELERY_BROKER_URL=redis://redis:6379/0 \
    CELERY_RESULT_BACKEND=redis://redis:6379/1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libpq-dev \
    postgresql-client \
    redis-tools \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements first for better caching
COPY setup.py setup.cfg MANIFEST.in /app/
COPY django_twilio_call/__init__.py /app/django_twilio_call/

# Install the package in development mode with dependencies
RUN pip install --upgrade pip \
    && pip install -e .[dev]

# Copy project
COPY . /app/

# Create directories for logs and temporary files
RUN mkdir -p /app/logs /app/tmp /app/media /app/static

# Create a non-root user with proper permissions
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app \
    && chmod +x /app/manage.py
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# Default command (can be overridden in docker-compose)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]