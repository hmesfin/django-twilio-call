# Django-Twilio-Call Package Development Instructions

## Project Overview

This is a Django package that provides real-world call center functionality using Twilio APIs. The package should be installable via pip and integrate seamlessly with Django projects using Django REST Framework (DRF) for API endpoints.

## Core Principles

1. **API-First Design**: All functionality exposed through DRF endpoints
2. **Docker-First Development**: All development and testing through Docker containers
3. **No Shortcuts**: Build robust, production-ready code with proper error handling
4. **Follow Django Best Practices**: Use Django patterns for models, views, serializers
5. **Modular Architecture**: Keep components loosely coupled and highly cohesive

## Package Structure Convention

```markdown
django-twilio-call/
  django_twilio_call/          # Main package directory
    __init__.py
    admin.py                 # Django admin configurations
    apps.py                  # Django app configuration
    models.py                # Database models for calls, agents, etc.
    serializers.py           # DRF serializers
    views.py                 # DRF viewsets and API views
    urls.py                  # URL routing
    services/                # Business logic layer
      __init__.py
      twilio_service.py   # Twilio API integration
      call_service.py     # Call handling logic
      queue_service.py    # Queue management
    webhooks/                # Twilio webhook handlers
      __init__.py
      handlers.py
    utils/                   # Utility functions
      __init__.py
      validators.py
    migrations/              # Django migrations
    tests/                   # Test suite
      __init__.py
      test_models.py
      test_views.py
      test_services.py
    docker/                       # Docker configuration
      Dockerfile
      docker-compose.yml
    requirements/                 # Dependencies
      base.txt
      development.txt
      testing.txt
    setup.py                     # Package setup
    setup.cfg                    # Package configuration
    MANIFEST.in                  # Package manifest
    README.md                    # Public documentation
    CLAUDE.md                    # Development instructions
    PLAN.md                      # Project plan
    tox.ini                      # Test configuration
```

## Development Standards

### Code Style

- Follow Ruff for Python code
- Use type hints for all function signatures
- Document all classes and public methods with docstrings
- Use meaningful variable names

### API Design

- RESTful endpoints with proper HTTP methods
- Consistent response formats with pagination
- Proper status codes and error messages
- API versioning support (e.g., /api/v1/)

### Models

- Use appropriate Django field types
- Add indexes for frequently queried fields
- Include created_at and updated_at timestamps
- Use UUIDs for external identifiers

### Services Layer

- Keep views thin, move logic to services
- Services should be stateless
- Use dependency injection where appropriate
- Handle Twilio exceptions gracefully

### Testing

- Minimum 80% test coverage
- Mock external services (Twilio API)
- Test both success and error paths
- Use factories for test data generation

### Security

- Never commit sensitive credentials
- Use environment variables for configuration
- Validate and sanitize all inputs
- Implement proper authentication/authorization
- Rate limiting for API endpoints

## Twilio Integration Guidelines

- Use Twilio Python SDK
- Implement retry logic with exponential backoff
- Log all Twilio API interactions
- Handle webhook signature validation
- Support multiple Twilio accounts/subaccounts

## Docker Development Workflow

1. All dependencies installed via Docker
2. Use docker-compose for local development
3. Include Redis for caching/queuing
4. PostgreSQL as default database
5. Volume mounts for code hot-reloading

## Package Distribution

- Support Python 3.8+
- Django 4.2+ and 5.1 compatibility
- Semantic versioning (MAJOR.MINOR.PATCH)
- Include comprehensive changelog
- PyPI distribution ready

## Key Features to Implement

1. **Call Management**: Initiate, receive, transfer, hold, mute calls
2. **Queue Management**: Create queues, route calls, priority handling
3. **Agent Management**: Agent status, availability, skills-based routing
4. **Call Recording**: Record calls with compliance features
5. **IVR Support**: Interactive Voice Response flows
6. **Conference Calls**: Multi-party calling capabilities
7. **Call Analytics**: Track metrics, generate reports
8. **Webhook Handling**: Process Twilio callbacks
9. **SMS Integration**: Send/receive SMS related to calls
10. **Real-time Events**: WebSocket support for live updates

## Error Handling

- Custom exception classes for different error types
- Consistent error response format
- Detailed logging for debugging
- User-friendly error messages
- Graceful degradation for external service failures

## Performance Considerations

- Implement caching where appropriate
- Async task processing with Celery
- Database query optimization
- Pagination for list endpoints
- Connection pooling for external services
