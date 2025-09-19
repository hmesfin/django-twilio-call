# Quick Start Production Deployment

This guide provides the fastest path to deploy Django-Twilio-Call to production using Docker Compose.

## Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Domain name with DNS access
- Twilio account with phone number
- SSL certificate (Let's Encrypt recommended)

## 1. Server Setup

### Minimum Server Requirements
- **CPU**: 4 cores
- **RAM**: 8GB
- **Storage**: 100GB SSD
- **OS**: Ubuntu 20.04+ or similar

### Install Docker
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Add user to docker group
sudo usermod -aG docker $USER
```

### Setup Project Directory
```bash
# Create project directory
mkdir -p /opt/django-twilio-call
cd /opt/django-twilio-call

# Clone repository
git clone https://github.com/your-org/django-twilio-call.git .

# Create data directories
sudo mkdir -p /var/lib/callcenter/{postgres,redis,prometheus,grafana,nginx_logs}
sudo chown -R $USER:$USER /var/lib/callcenter
```

## 2. Environment Configuration

### Create Production Environment File
```bash
cp .env.production.example .env.production
```

### Configure Required Variables
Edit `.env.production` with your values:

```bash
# Security (REQUIRED)
SECRET_KEY=your-50-character-secret-key-here
ENCRYPTION_KEY=your-32-byte-base64-encoded-key
DOMAIN=yourdomain.com
ALLOWED_HOSTS=yourdomain.com,api.yourdomain.com,webhooks.yourdomain.com

# Database (REQUIRED)
DB_NAME=callcenter_prod
DB_USER=callcenter_user
DB_PASSWORD=your-secure-database-password

# Twilio (REQUIRED)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-twilio-auth-token
TWILIO_PHONE_NUMBER=+1234567890
TWILIO_WEBHOOK_BASE_URL=https://webhooks.yourdomain.com

# Storage (REQUIRED for production)
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
AWS_STORAGE_BUCKET_NAME=your-recordings-bucket
AWS_S3_REGION_NAME=us-east-1

# Monitoring (OPTIONAL)
SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
GRAFANA_ADMIN_PASSWORD=your-secure-grafana-password
FLOWER_BASIC_AUTH=admin:your-secure-flower-password
```

### Generate Secure Keys
```bash
# Generate Django secret key
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Generate encryption key
python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

## 3. SSL Certificate Setup

### Option A: Let's Encrypt (Recommended)
```bash
# Install Certbot
sudo apt update
sudo apt install certbot

# Obtain certificate
sudo certbot certonly --standalone -d yourdomain.com -d api.yourdomain.com -d webhooks.yourdomain.com

# Copy certificates to Docker directory
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem docker/nginx/ssl/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem docker/nginx/ssl/
sudo chown $USER:$USER docker/nginx/ssl/*
```

### Option B: Self-Signed (Development Only)
```bash
# Create self-signed certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout docker/nginx/ssl/privkey.pem \
  -out docker/nginx/ssl/fullchain.pem \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=yourdomain.com"
```

## 4. Deploy Services

### Build and Start Services
```bash
# Build production images
docker compose -f docker/docker-compose.production.yml build

# Start all services
docker compose -f docker/docker-compose.production.yml up -d

# Check service status
docker compose -f docker/docker-compose.production.yml ps
```

### Initialize Database
```bash
# Wait for database to be ready
docker compose -f docker/docker-compose.production.yml exec web python manage.py check --deploy

# Run migrations
docker compose -f docker/docker-compose.production.yml exec web python manage.py migrate

# Create superuser
docker compose -f docker/docker-compose.production.yml exec web python manage.py createsuperuser

# Collect static files
docker compose -f docker/docker-compose.production.yml exec web python manage.py collectstatic --noinput
```

## 5. Verify Deployment

### Health Checks
```bash
# Basic health check
curl -f https://yourdomain.com/health/

# Detailed health check
curl -s https://yourdomain.com/health/detailed/ | jq .

# Check individual services
curl -f https://yourdomain.com/admin/
curl -f https://flower.yourdomain.com/
curl -f https://grafana.yourdomain.com/
```

### Service Logs
```bash
# Check all service logs
docker compose -f docker/docker-compose.production.yml logs

# Check specific service
docker compose -f docker/docker-compose.production.yml logs web
docker compose -f docker/docker-compose.production.yml logs celery-worker
docker compose -f docker/docker-compose.production.yml logs db
```

### Performance Check
```bash
# Check resource usage
docker stats

# Check service metrics
curl -s https://yourdomain.com/metrics/ | grep django_twilio_call
```

## 6. Configure Monitoring

### Access Monitoring Services

- **Grafana**: https://grafana.yourdomain.com/ (admin/your-password)
- **Flower**: https://flower.yourdomain.com/ (admin/your-password)
- **Application**: https://yourdomain.com/admin/

### Setup Alerts
```bash
# Configure Grafana alerts
# Import dashboard from grafana/dashboard.json
# Setup notification channels
```

## 7. DNS Configuration

Configure your DNS to point to your server:

```dns
yourdomain.com.        A     YOUR_SERVER_IP
api.yourdomain.com.    A     YOUR_SERVER_IP
webhooks.yourdomain.com. A   YOUR_SERVER_IP
flower.yourdomain.com. A     YOUR_SERVER_IP
grafana.yourdomain.com. A    YOUR_SERVER_IP
```

## 8. Twilio Configuration

### Configure Webhooks
In your Twilio Console, set the webhook URLs:

- **Voice URL**: `https://webhooks.yourdomain.com/webhooks/voice/`
- **Status Callback URL**: `https://webhooks.yourdomain.com/webhooks/status/`

### Test Call Flow
```bash
# Make a test call to your Twilio number
# Check webhook logs
docker compose -f docker/docker-compose.production.yml logs web | grep webhook
```

## 9. Backup Setup

### Database Backups
```bash
# Create backup script
cat > /opt/django-twilio-call/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/var/lib/callcenter/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# Database backup
docker compose -f /opt/django-twilio-call/docker/docker-compose.production.yml exec -T db pg_dump -U callcenter_user callcenter_prod | gzip > "$BACKUP_DIR/db_backup_$TIMESTAMP.sql.gz"

# Configuration backup
tar -czf "$BACKUP_DIR/config_backup_$TIMESTAMP.tar.gz" .env.production docker/

# Keep only last 30 days
find $BACKUP_DIR -name "*_backup_*.gz" -mtime +30 -delete

echo "Backup completed: $TIMESTAMP"
EOF

chmod +x /opt/django-twilio-call/backup.sh

# Schedule daily backups
(crontab -l ; echo "0 2 * * * /opt/django-twilio-call/backup.sh") | crontab -
```

## 10. Security Hardening

### Firewall Configuration
```bash
# Configure UFW firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### System Updates
```bash
# Setup automatic security updates
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### Log Monitoring
```bash
# Setup log rotation
sudo tee /etc/logrotate.d/django-twilio-call << EOF
/var/lib/callcenter/nginx_logs/*.log {
    daily
    missingok
    rotate 52
    compress
    delaycompress
    notifempty
    create 644 nobody adm
    postrotate
        docker compose -f /opt/django-twilio-call/docker/docker-compose.production.yml exec nginx nginx -s reload
    endscript
}
EOF
```

## 11. Maintenance Procedures

### Update Application
```bash
# Pull latest changes
git pull origin main

# Rebuild images
docker compose -f docker/docker-compose.production.yml build

# Rolling update
docker compose -f docker/docker-compose.production.yml up -d --no-deps web
docker compose -f docker/docker-compose.production.yml up -d --no-deps celery-worker

# Run migrations if needed
docker compose -f docker/docker-compose.production.yml exec web python manage.py migrate

# Verify deployment
curl -f https://yourdomain.com/health/detailed/
```

### Scale Services
```bash
# Scale web servers
docker compose -f docker/docker-compose.production.yml up -d --scale web=5

# Scale Celery workers
docker compose -f docker/docker-compose.production.yml up -d --scale celery-worker=4
```

## 12. Troubleshooting

### Common Issues

#### Service Won't Start
```bash
# Check service logs
docker compose -f docker/docker-compose.production.yml logs service-name

# Check resource usage
docker stats
df -h
free -h
```

#### Database Connection Issues
```bash
# Test database connection
docker compose -f docker/docker-compose.production.yml exec web python manage.py dbshell

# Check database logs
docker compose -f docker/docker-compose.production.yml logs db
```

#### SSL Certificate Issues
```bash
# Verify certificate
openssl x509 -in docker/nginx/ssl/fullchain.pem -text -noout

# Test SSL connection
openssl s_client -connect yourdomain.com:443
```

### Performance Issues
```bash
# Monitor resource usage
htop
iotop
nethogs

# Check application performance
curl -w "@curl-format.txt" -o /dev/null -s https://yourdomain.com/health/
```

## Success Criteria

Your deployment is successful when:

- [ ] All health checks return "healthy"
- [ ] Web interface accessible at https://yourdomain.com/
- [ ] API endpoints responding correctly
- [ ] Webhooks processing Twilio callbacks
- [ ] Celery tasks processing
- [ ] Monitoring dashboards showing data
- [ ] SSL certificates valid
- [ ] Backups running successfully

## Next Steps

1. **Load Testing**: Test with expected call volume
2. **Monitoring Setup**: Configure alerts and dashboards
3. **Documentation**: Document your specific configuration
4. **Team Training**: Train operations team on maintenance
5. **Performance Optimization**: Tune based on usage patterns

## Support

For issues and questions:

- Check the [Troubleshooting Guide](../TROUBLESHOOTING.md)
- Review application logs
- Monitor system resources
- Check Twilio webhook logs

**Congratulations! Your Django-Twilio-Call production deployment is complete.**