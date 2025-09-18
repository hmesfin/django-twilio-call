# Example Call Center Project

This is a complete example Django project demonstrating how to use django-twilio-call to build a functional call center application.

## Features Demonstrated

- Complete call center setup
- Agent dashboard
- Queue management
- Real-time metrics
- IVR configuration
- Call recording
- Analytics dashboard

## Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/your-repo/django-twilio-call.git
cd django-twilio-call/example_project

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file:

```bash
# Django settings
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=postgresql://user:pass@localhost/callcenter

# Twilio (get from https://console.twilio.com)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1234567890
TWILIO_WEBHOOK_BASE_URL=https://your-domain.com

# Redis (optional)
REDIS_URL=redis://localhost:6379/0

# AWS (optional, for recordings)
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_STORAGE_BUCKET_NAME=your_bucket
```

### 3. Initialize Database

```bash
# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Load sample data
python manage.py load_sample_data
```

### 4. Configure Twilio

```bash
# Use ngrok for local development
ngrok http 8000

# Note the HTTPS URL (e.g., https://abc123.ngrok.io)
# Update your .env file:
TWILIO_WEBHOOK_BASE_URL=https://abc123.ngrok.io
```

In Twilio Console:

1. Go to Phone Numbers → Manage → Active Numbers
2. Click your phone number
3. Set Voice webhook: `https://abc123.ngrok.io/api/v1/webhooks/voice/`

### 5. Run the Application

```bash
# Start Django server
python manage.py runserver

# In another terminal, start Celery (optional)
celery -A callcenter worker -l info

# In another terminal, start Celery Beat (optional)
celery -A callcenter beat -l info
```

### 6. Access the Application

- Admin Panel: <http://localhost:8000/admin/>
- API Documentation: <http://localhost:8000/api/v1/docs/>
- Agent Dashboard: <http://localhost:8000/dashboard/>
- Analytics: <http://localhost:8000/analytics/>

## Project Structure

```markdown
example_project/
├── callcenter/              # Django project settings
│   ├── settings.py          # Main settings
│   ├── urls.py              # URL configuration
│   └── wsgi.py              # WSGI application
├── apps/                    # Custom applications
│   ├── dashboard/           # Agent dashboard
│   ├── analytics/           # Analytics views
│   └── webhooks/            # Webhook handlers
├── templates/               # HTML templates
├── static/                  # CSS, JS, images
├── management/              # Management commands
│   └── commands/
│       ├── load_sample_data.py
│       └── test_call.py
├── requirements.txt         # Python dependencies
├── .env.example            # Environment variables template
└── docker-compose.yml      # Docker configuration
```

## Usage Examples

### Make a Test Call

```bash
python manage.py test_call --to=+1234567890
```

### Create Agents

```bash
python manage.py shell

from apps.dashboard.utils import create_agent
create_agent(
    username='agent1',
    email='agent1@example.com',
    extension='1001',
    queues=['support', 'sales']
)
```

### Configure IVR

Visit <http://localhost:8000/admin/django_twilio_call/ivr/> to configure IVR flows.

## Docker Deployment

```bash
# Build and run with Docker
docker-compose up --build

# Access at http://localhost:8000
```

## Testing

```bash
# Run tests
python manage.py test

# With coverage
coverage run --source='.' manage.py test
coverage report
```

## Customization

### Custom Agent Dashboard

See `apps/dashboard/views.py` for customizing the agent interface.

### Custom Analytics

See `apps/analytics/views.py` for adding custom reports.

### Custom Webhooks

See `apps/webhooks/handlers.py` for custom webhook logic.

## Common Scenarios

### Business Hours Routing

```python
# apps/webhooks/handlers.py
from django_twilio_call.services import ivr_service
import datetime

def route_by_business_hours(call):
    now = datetime.datetime.now()
    if 9 <= now.hour < 17:  # 9 AM - 5 PM
        return 'main_queue'
    else:
        return 'after_hours_voicemail'
```

### VIP Customer Routing

```python
# apps/webhooks/handlers.py
VIP_NUMBERS = ['+1234567890', '+0987654321']

def route_vip_customers(call):
    if call.from_number in VIP_NUMBERS:
        return 'vip_queue'
    return 'standard_queue'
```

### Skills-Based Routing

```python
# Configure in admin or via API
queue = Queue.objects.get(name='technical_support')
queue.routing_strategy = 'skills_based'
queue.required_skills = ['python', 'django']
queue.save()

# Agents with matching skills will receive calls
agent = Agent.objects.get(extension='1001')
agent.skills = ['python', 'django', 'twilio']
agent.save()
```

## Production Checklist

- [ ] Set `DEBUG=False`
- [ ] Configure proper `ALLOWED_HOSTS`
- [ ] Use PostgreSQL database
- [ ] Set up Redis for caching
- [ ] Configure S3 for recording storage
- [ ] Enable webhook signature validation
- [ ] Set up SSL certificate
- [ ] Configure monitoring (Sentry)
- [ ] Set up log aggregation
- [ ] Configure backup strategy

## Troubleshooting

See the main [Troubleshooting Guide](../docs/TROUBLESHOOTING.md) for common issues.

## Support

- Documentation: `/api/v1/docs/`
- Admin Interface: `/admin/`
- Logs: Check `logs/django.log`

## License

This example project is provided as-is for demonstration purposes.
