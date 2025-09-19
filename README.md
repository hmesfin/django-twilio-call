# django-twilio-call

[![PyPI version](https://badge.fury.io/py/django-twilio-call.svg)](https://badge.fury.io/py/django-twilio-call)
[![Python Support](https://img.shields.io/pypi/pyversions/django-twilio-call.svg)](https://pypi.org/project/django-twilio-call/)
[![Django Support](https://img.shields.io/badge/django-4.2%20%7C%205.0%20%7C%205.1-44B78B)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/hmesfin/django-twilio-call/actions/workflows/ci.yml/badge.svg)](https://github.com/hmesfin/django-twilio-call/actions)
[![Coverage](https://codecov.io/gh/hmesfin/django-twilio-call/branch/main/graph/badge.svg)](https://codecov.io/gh/hmesfin/django-twilio-call)
[![Documentation](https://readthedocs.org/projects/django-twilio-call/badge/?version=latest)](https://django-twilio-call.readthedocs.io/)

**django-twilio-call** is an enterprise-grade Django package for building sophisticated call center applications using Twilio's powerful communication APIs. Build production-ready call centers with features like IVR, call routing, recording, real-time monitoring, and comprehensive analytics.

## ✨ Features

### Core Call Center Functionality
- 📞 **Inbound/Outbound Calls** - Handle both incoming and outgoing calls with ease
- 🔀 **Intelligent Call Routing** - Route calls based on skills, availability, and priority
- 👥 **Agent Management** - Complete agent system with status tracking and queue assignment
- 📊 **Queue Management** - Sophisticated queue system with priority and overflow handling
- 🎙️ **Call Recording** - Record calls with compliance features and transcription support
- 🔊 **IVR System** - Build complex Interactive Voice Response flows
- 🎯 **Real-time Monitoring** - Track call center metrics and agent performance in real-time

### Enterprise Features
- 🔐 **JWT Authentication** - Secure API access with JSON Web Tokens
- ⚡ **Rate Limiting** - Protect your APIs from abuse with configurable rate limits
- 🛡️ **RBAC** - Role-Based Access Control for agents and supervisors
- 📈 **Analytics & Reporting** - Comprehensive call analytics and performance metrics
- 🔄 **WebSocket Support** - Real-time updates for live dashboards
- 📡 **Webhook Handling** - Secure webhook processing with signature validation
- ⚙️ **Celery Integration** - Asynchronous task processing for scalability

### Production Ready
- 🐳 **Docker Support** - Complete Docker configuration for easy deployment
- ☸️ **Kubernetes Ready** - Kubernetes manifests for cloud-native deployment
- 📊 **Monitoring** - Prometheus metrics and health check endpoints
- 🚀 **Performance** - Redis caching and database optimization
- 🔒 **Security** - Enterprise-grade security with input validation and encryption
- 📝 **Documentation** - Comprehensive documentation with examples

## 🚀 Quick Start

### Installation

```bash
pip install django-twilio-call
```

### Basic Setup

1. **Add to INSTALLED_APPS**

```python
INSTALLED_APPS = [
    ...
    'django_twilio_call',
    'rest_framework',
    'corsheaders',
    ...
]
```

2. **Configure Twilio Settings**

```python
# settings.py
TWILIO_ACCOUNT_SID = 'your_account_sid'
TWILIO_AUTH_TOKEN = 'your_auth_token'
TWILIO_PHONE_NUMBER = '+1234567890'
TWILIO_WEBHOOK_URL = 'https://your-domain.com/webhooks/twilio/'
```

3. **Run Migrations**

```bash
python manage.py migrate django_twilio_call
```

4. **Include URLs**

```python
# urls.py
urlpatterns = [
    ...
    path('api/call-center/', include('django_twilio_call.urls')),
    ...
]
```

## 📖 Usage Examples

### Making an Outbound Call

```python
from django_twilio_call import call_service

# Make a call
call = call_service.create_call(
    to_number='+1987654321',
    from_number='+1234567890',
    agent_id=agent.id
)
```

### Handling Inbound Calls

```python
from django_twilio_call.webhooks import VoiceWebhookView

class InboundCallHandler(VoiceWebhookView):
    def handle_incoming_call(self, call_data):
        # Route to available agent
        agent = self.find_available_agent()
        if agent:
            return self.route_to_agent(call, agent)
        else:
            return self.route_to_queue(call)
```

### Managing Agents

```python
from django_twilio_call import agent_service

# Update agent status
agent_service.update_status(agent_id, 'available')

# Assign agent to queue
agent_service.assign_to_queue(agent_id, queue_id)

# Get agent statistics
stats = agent_service.get_statistics(agent_id)
```

### Queue Management

```python
from django_twilio_call import queue_service

# Create a queue
queue = queue_service.create_queue(
    name='Support Queue',
    max_size=50,
    timeout_seconds=300
)

# Get queue statistics
stats = queue_service.get_queue_statistics(queue_id)
```

## 🔧 Advanced Configuration

### Celery Setup

```python
# settings.py
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

# Enable async task processing
DJANGO_TWILIO_ASYNC_TASKS = True
```

### JWT Authentication

```python
# settings.py
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
}
```

### Rate Limiting

```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_RATES': {
        'burst': '60/min',
        'sustained': '1000/hour',
        'call_api': '100/hour',
    }
}
```

## 🐳 Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose up -d

# Scale workers
docker-compose scale celery_worker=3
```

## 📊 Monitoring

The package includes built-in monitoring endpoints:

- `/health/` - Basic health check
- `/health/detailed/` - Detailed component status
- `/metrics/` - Prometheus metrics

## 🧪 Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=django_twilio_call

# Run with tox for multiple environments
tox
```

## 📚 Documentation

Full documentation is available at [https://django-twilio-call.readthedocs.io/](https://django-twilio-call.readthedocs.io/)

### Key Documentation Sections:
- [Installation Guide](https://django-twilio-call.readthedocs.io/en/latest/installation/)
- [Configuration](https://django-twilio-call.readthedocs.io/en/latest/configuration/)
- [API Reference](https://django-twilio-call.readthedocs.io/en/latest/api/)
- [Deployment Guide](https://django-twilio-call.readthedocs.io/en/latest/deployment/)
- [Examples](https://django-twilio-call.readthedocs.io/en/latest/examples/)

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

```bash
# Clone the repository
git clone https://github.com/hmesfin/django-twilio-call.git

# Install development dependencies
pip install -e .[dev]

# Run tests
pytest

# Run linters
ruff check .
```

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [Django](https://www.djangoproject.com/) and [Django REST Framework](https://www.django-rest-framework.org/)
- Powered by [Twilio](https://www.twilio.com/) APIs
- Async tasks handled by [Celery](https://docs.celeryproject.org/)

## 📞 Support

- 📧 Email: admin@gojjotech.com
- 🐛 Issues: [GitHub Issues](https://github.com/hmesfin/django-twilio-call/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/hmesfin/django-twilio-call/discussions)

## 🚦 Project Status

This project is actively maintained and ready for production use. We follow semantic versioning and maintain backward compatibility within major versions.

---

**Made with ❤️ by Gojjo Tech**