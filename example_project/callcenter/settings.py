"""
Django settings loader for Django-Twilio-Call project.

This file determines which settings module to load based on the DJANGO_SETTINGS_MODULE
environment variable or defaults to development settings.
"""

import os
from decouple import config

# Determine which settings to use
ENVIRONMENT = config("ENVIRONMENT", default="development")

if ENVIRONMENT == "production":
    from .settings.production import *
elif ENVIRONMENT == "staging":
    from .settings.staging import *
elif ENVIRONMENT == "testing":
    from .settings.testing import *
else:
    from .settings.development import *

# Export current environment for debugging
CURRENT_ENVIRONMENT = ENVIRONMENT