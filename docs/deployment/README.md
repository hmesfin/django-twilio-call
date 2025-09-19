# Django-Twilio-Call Deployment Guide

This comprehensive guide covers deploying the Django-Twilio-Call package to production environments using various deployment strategies.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Configuration](#environment-configuration)
3. [Docker Deployment](#docker-deployment)
4. [Kubernetes Deployment](#kubernetes-deployment)
5. [Cloud Provider Specific Guides](#cloud-provider-specific-guides)
6. [Monitoring and Observability](#monitoring-and-observability)
7. [Security Considerations](#security-considerations)
8. [Performance Optimization](#performance-optimization)
9. [Backup and Recovery](#backup-and-recovery)
10. [Troubleshooting](#troubleshooting)

## Prerequisites

### System Requirements

- **CPU**: Minimum 2 cores, Recommended 4+ cores
- **Memory**: Minimum 4GB RAM, Recommended 8GB+ RAM
- **Storage**: Minimum 50GB, Recommended 100GB+ SSD
- **Network**: Stable internet connection with sufficient bandwidth for call traffic

### Software Requirements

- Docker 20.10+
- Docker Compose 2.0+
- Python 3.11+ (for local development)
- PostgreSQL 15+
- Redis 7+
- Kubernetes 1.25+ (for K8s deployment)

### External Services

- **Twilio Account**: Active account with phone numbers and API credentials
- **Cloud Storage**: AWS S3, Google Cloud Storage, or Azure Blob Storage
- **Monitoring**: Sentry, Prometheus, Grafana (optional but recommended)
- **Email Service**: SMTP server for notifications

## Environment Configuration

### Environment Variables

Create appropriate environment files based on your deployment type:

#### Production Environment (`.env.production`)

```bash
# Copy from .env.production.example and customize
cp .env.production.example .env.production
```

Key variables to configure:

```bash
# Security
SECRET_KEY=your-super-secret-key-here
ENCRYPTION_KEY=your-32-byte-base64-encoded-key
ALLOWED_HOSTS=yourdomain.com,api.yourdomain.com

# Database
DB_NAME=callcenter_prod
DB_USER=callcenter_user
DB_PASSWORD=secure-password-here
DB_HOST=your-db-host
DB_PORT=5432

# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_PHONE_NUMBER=+1234567890
TWILIO_WEBHOOK_BASE_URL=https://yourdomain.com

# Redis
REDIS_URL=redis://your-redis-host:6379/0

# Storage
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_STORAGE_BUCKET_NAME=your-bucket-name
```

### Secrets Management

For production deployments, use proper secrets management:

#### Docker Swarm Secrets
```bash
echo "your-secret-key" | docker secret create django_secret_key -
echo "your-db-password" | docker secret create db_password -
```

#### Kubernetes Secrets
```bash
kubectl create secret generic django-twilio-call-secrets \
  --from-literal=SECRET_KEY=your-secret-key \
  --from-literal=DB_PASSWORD=your-db-password \
  --from-literal=TWILIO_AUTH_TOKEN=your-twilio-token
```

#### Cloud Provider Secrets
- **AWS**: AWS Secrets Manager
- **Google Cloud**: Secret Manager
- **Azure**: Key Vault

## Docker Deployment

### Production Docker Compose

The production setup includes all necessary services:

```bash
# Deploy with production configuration
docker compose -f docker/docker-compose.production.yml up -d

# Check service status
docker compose -f docker/docker-compose.production.yml ps

# View logs
docker compose -f docker/docker-compose.production.yml logs -f web
```

### Service Architecture

The production deployment includes:

- **Web Service**: Django application with Gunicorn
- **Worker Service**: Celery workers for background tasks
- **Beat Service**: Celery beat for scheduled tasks
- **Database**: PostgreSQL with optimized configuration
- **Cache**: Redis for caching and message broker
- **Monitoring**: Prometheus, Grafana, Flower
- **Reverse Proxy**: Nginx with SSL termination

### Scaling Services

Scale individual services based on load:

```bash
# Scale web servers
docker compose -f docker/docker-compose.production.yml up -d --scale web=5

# Scale celery workers
docker compose -f docker/docker-compose.production.yml up -d --scale celery-worker=4

# Check resource usage
docker stats
```

## Kubernetes Deployment

### Cluster Requirements

- **Kubernetes Version**: 1.25+
- **Ingress Controller**: Nginx Ingress Controller
- **Storage Classes**:
  - `gp3` for database storage
  - `efs-sc` for shared media files
- **Cert Manager**: For SSL certificates
- **Metrics Server**: For autoscaling

### Deploy Base Resources

```bash
# Apply namespace and basic resources
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/configmap.yaml
kubectl apply -f k8s/base/secrets.yaml

# Deploy storage layer
kubectl apply -f k8s/base/postgresql.yaml
kubectl apply -f k8s/base/redis.yaml

# Wait for databases to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=postgresql --timeout=300s
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=redis --timeout=300s
```

### Deploy Application

```bash
# Deploy Django application
kubectl apply -f k8s/base/django-web.yaml

# Deploy Celery services
kubectl apply -f k8s/base/celery.yaml

# Deploy ingress
kubectl apply -f k8s/base/ingress.yaml

# Check deployment status
kubectl get pods -n django-twilio-call
kubectl get services -n django-twilio-call
kubectl get ingress -n django-twilio-call
```

### Production Overlay

For production-specific configurations:

```bash
# Deploy with production overlay
kubectl apply -k k8s/overlays/production/

# Verify deployment
kubectl get pods -n django-twilio-call -o wide
kubectl describe hpa -n django-twilio-call
```

### Monitoring Deployment

```bash
# Check application logs
kubectl logs -f deployment/django-web -n django-twilio-call

# Check health endpoints
kubectl port-forward service/django-web-service 8000:8000 -n django-twilio-call
curl http://localhost:8000/health/detailed/

# Monitor resource usage
kubectl top pods -n django-twilio-call
kubectl top nodes
```

## Cloud Provider Specific Guides

### AWS Deployment

#### ECS Fargate Deployment

1. **Create ECS Cluster**:
```bash
aws ecs create-cluster --cluster-name django-twilio-call-prod
```

2. **Create Task Definition**:
```bash
aws ecs register-task-definition --cli-input-json file://aws/task-definition.json
```

3. **Create Service**:
```bash
aws ecs create-service \
  --cluster django-twilio-call-prod \
  --service-name django-twilio-call \
  --task-definition django-twilio-call:1 \
  --desired-count 3
```

#### RDS Database Setup

```bash
# Create RDS instance
aws rds create-db-instance \
  --db-instance-identifier callcenter-prod \
  --db-instance-class db.r5.large \
  --engine postgres \
  --master-username callcenter_user \
  --master-user-password $DB_PASSWORD \
  --allocated-storage 100 \
  --storage-type gp3 \
  --vpc-security-group-ids sg-xxxxxxxx
```

#### ElastiCache Redis Setup

```bash
# Create Redis cluster
aws elasticache create-cache-cluster \
  --cache-cluster-id callcenter-redis-prod \
  --cache-node-type cache.r6g.large \
  --engine redis \
  --num-cache-nodes 1
```

### Google Cloud Platform

#### GKE Deployment

```bash
# Create GKE cluster
gcloud container clusters create django-twilio-call \
  --zone us-central1-a \
  --num-nodes 3 \
  --enable-autoscaling \
  --min-nodes 1 \
  --max-nodes 10

# Get credentials
gcloud container clusters get-credentials django-twilio-call --zone us-central1-a

# Deploy to GKE
kubectl apply -k k8s/overlays/production/
```

#### Cloud SQL Setup

```bash
# Create Cloud SQL instance
gcloud sql instances create callcenter-prod \
  --database-version POSTGRES_15 \
  --tier db-custom-2-4096 \
  --region us-central1
```

### Azure Deployment

#### AKS Deployment

```bash
# Create resource group
az group create --name django-twilio-call-rg --location eastus

# Create AKS cluster
az aks create \
  --resource-group django-twilio-call-rg \
  --name django-twilio-call-aks \
  --node-count 3 \
  --enable-addons monitoring \
  --generate-ssh-keys

# Get credentials
az aks get-credentials --resource-group django-twilio-call-rg --name django-twilio-call-aks

# Deploy to AKS
kubectl apply -k k8s/overlays/production/
```

## Monitoring and Observability

### Health Checks

The application provides comprehensive health check endpoints:

- `/health/` - Basic health check
- `/health/detailed/` - Detailed component status
- `/health/ready/` - Kubernetes readiness probe
- `/health/live/` - Kubernetes liveness probe
- `/metrics/` - Prometheus metrics
- `/info/` - Application information

### Prometheus Metrics

Key metrics exposed:

- `django_twilio_call_total` - Total number of calls
- `django_twilio_call_duration_seconds` - Call duration histogram
- `django_twilio_call_active_total` - Active calls gauge
- `django_twilio_call_queue_size` - Queue size gauge
- `django_twilio_call_celery_tasks_total` - Celery task metrics

### Grafana Dashboards

Import the provided Grafana dashboard:

```bash
# Import dashboard from grafana/dashboard.json
curl -X POST \
  http://grafana:3000/api/dashboards/db \
  -H 'Content-Type: application/json' \
  -d @grafana/dashboard.json
```

### Alerting Rules

Example Prometheus alerting rules:

```yaml
groups:
- name: django-twilio-call
  rules:
  - alert: HighCallVolume
    expr: django_twilio_call_active_total > 100
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: High call volume detected

  - alert: DatabaseConnectionError
    expr: up{job="django-web"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: Database connection lost
```

## Security Considerations

### Network Security

1. **Firewall Configuration**:
   - Only expose necessary ports (80, 443)
   - Restrict database access to application subnets
   - Use VPC/VNET for cloud deployments

2. **SSL/TLS Configuration**:
   - Use Let's Encrypt for free SSL certificates
   - Enable HSTS headers
   - Configure proper cipher suites

### Application Security

1. **Environment Variables**:
   - Never commit secrets to version control
   - Use proper secrets management
   - Rotate secrets regularly

2. **Database Security**:
   - Use connection encryption
   - Implement proper user permissions
   - Enable audit logging

3. **Twilio Security**:
   - Validate webhook signatures
   - Use HTTPS for all webhook URLs
   - Implement proper authentication

### Container Security

1. **Image Security**:
   - Use official base images
   - Run security scans regularly
   - Keep images updated

2. **Runtime Security**:
   - Run containers as non-root user
   - Use read-only filesystems where possible
   - Implement proper resource limits

## Performance Optimization

### Database Optimization

1. **Connection Pooling**:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django_db_connection_pool.backends.postgresql',
        'POOL_OPTIONS': {
            'POOL_SIZE': 20,
            'MAX_OVERFLOW': 0,
            'RECYCLE': 300,
        }
    }
}
```

2. **Query Optimization**:
   - Use select_related() and prefetch_related()
   - Implement database indexes
   - Monitor slow queries

### Caching Strategy

1. **Redis Configuration**:
   - Configure appropriate memory limits
   - Use appropriate eviction policies
   - Monitor cache hit rates

2. **Application Caching**:
   - Cache expensive computations
   - Use cache versioning
   - Implement cache warming

### Gunicorn Configuration

```bash
# Optimal worker configuration
GUNICORN_WORKERS=$(($(nproc) * 2 + 1))
GUNICORN_WORKER_CLASS=gthread
GUNICORN_THREADS=2
GUNICORN_TIMEOUT=30
GUNICORN_KEEPALIVE=5
```

## Backup and Recovery

### Database Backups

1. **Automated Backups**:
```bash
# Create backup script
#!/bin/bash
BACKUP_DIR="/var/backups/postgresql"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
pg_dump -h $DB_HOST -U $DB_USER $DB_NAME | gzip > "$BACKUP_DIR/backup_$TIMESTAMP.sql.gz"

# Keep only last 30 days
find $BACKUP_DIR -name "backup_*.sql.gz" -mtime +30 -delete
```

2. **Cloud Backups**:
   - AWS RDS automated backups
   - GCP Cloud SQL backups
   - Azure Database backups

### File Storage Backups

1. **Media Files**:
```bash
# Sync to backup bucket
aws s3 sync s3://primary-bucket s3://backup-bucket --delete
```

2. **Configuration Backups**:
   - Backup Kubernetes manifests
   - Backup environment configurations
   - Document deployment procedures

### Disaster Recovery

1. **Recovery Procedures**:
   - Document step-by-step recovery process
   - Test recovery procedures regularly
   - Maintain infrastructure as code

2. **Multi-Region Setup**:
   - Deploy to multiple availability zones
   - Implement database replication
   - Use global load balancing

## Troubleshooting

### Common Issues

1. **Database Connection Issues**:
```bash
# Check database connectivity
kubectl exec -it deployment/django-web -- python manage.py dbshell

# Verify connection pool
kubectl logs deployment/django-web | grep "database"
```

2. **Celery Task Issues**:
```bash
# Check Celery worker status
celery -A django_twilio_call inspect ping

# Monitor task queue
celery -A django_twilio_call inspect active
```

3. **Twilio Webhook Issues**:
```bash
# Verify webhook signature validation
curl -X POST https://your-domain.com/webhooks/voice/ \
  -H "X-Twilio-Signature: signature" \
  -d "CallSid=test"

# Check webhook logs
kubectl logs deployment/django-web | grep "webhook"
```

### Performance Issues

1. **High CPU Usage**:
   - Scale up replicas
   - Optimize database queries
   - Review Celery task efficiency

2. **High Memory Usage**:
   - Increase memory limits
   - Check for memory leaks
   - Optimize data structures

3. **Network Latency**:
   - Deploy closer to users
   - Use CDN for static assets
   - Optimize database queries

### Monitoring Commands

```bash
# Check pod resource usage
kubectl top pods -n django-twilio-call

# View detailed pod information
kubectl describe pod <pod-name> -n django-twilio-call

# Check events
kubectl get events -n django-twilio-call --sort-by=.metadata.creationTimestamp

# Monitor logs in real-time
kubectl logs -f deployment/django-web -n django-twilio-call
```

## Next Steps

After successful deployment:

1. **Configure Monitoring**: Set up alerts and dashboards
2. **Performance Testing**: Load test your deployment
3. **Security Audit**: Conduct security assessment
4. **Documentation**: Update operational procedures
5. **Training**: Train operations team

For additional support, refer to:
- [Operations Guide](./operations.md)
- [Monitoring Guide](./monitoring.md)
- [Security Guide](./security.md)
- [Troubleshooting Guide](../TROUBLESHOOTING.md)