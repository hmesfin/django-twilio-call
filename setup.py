#!/usr/bin/env python
"""Setup configuration for django-twilio-call package."""

import os
from pathlib import Path

from setuptools import find_packages, setup

# Read version from package
version_file = Path(__file__).parent / "django_twilio_call" / "__init__.py"
VERSION = "0.1.0"
if version_file.exists():
    with open(version_file) as f:
        for line in f:
            if line.startswith("__version__"):
                VERSION = line.split("=")[1].strip().strip('"').strip("'")
                break

# Read README for long description
README = Path(__file__).parent / "README.md"
long_description = README.read_text() if README.exists() else ""

setup(
    name="django-twilio-call",
    version=VERSION,
    author="Gojjo Tech",
    author_email="admin@gojjotech.com",
    description="A Django package for call center functionality using Twilio",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/hmesfin/django-twilio-call",
    packages=find_packages(exclude=["tests", "tests.*", "docker", "docs"]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Framework :: Django",
        "Framework :: Django :: 4.2",
        "Framework :: Django :: 5.0",
        "Framework :: Django :: 5.1",
        "Topic :: Communications :: Telephony",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.8",
    install_requires=[
        "Django>=4.2,<5.2",
        "djangorestframework>=3.14.0",
        "twilio>=8.0.0",
        "celery>=5.3.0",
        "django-celery-beat>=2.5.0",
        "redis>=4.5.0",
        "django-redis>=5.2.0",
        "django-cors-headers>=4.0.0",
        "django-environ>=0.10.0",
        "python-decouple>=3.8",
        "python-dateutil>=2.8.0",
        "pytz>=2023.3",
        "djangorestframework-simplejwt>=5.3.0",
        "django-ratelimit>=4.0.0",
        "cryptography>=41.0.0",
        "drf-spectacular>=0.26.0",
    ],
    extras_require={
        "dev": [
            "ruff>=0.1.0",
            "black>=23.0.0",
            "pytest>=7.4.0",
            "pytest-django>=4.5.0",
            "pytest-cov>=4.1.0",
            "pytest-asyncio>=0.21.0",
            "factory-boy>=3.3.0",
            "faker>=18.0.0",
            "responses>=0.23.0",
            "ipython>=8.0.0",
            "pre-commit>=3.0.0",
            "tox>=4.0.0",
            "twine>=4.0.0",
            "build>=0.10.0",
        ],
        "docs": [
            "sphinx>=7.0.0",
            "sphinx-rtd-theme>=1.3.0",
        ],
    },
    include_package_data=True,
    zip_safe=False,
    project_urls={
        "Documentation": "https://django-twilio-call.readthedocs.io/",
        "Source": "https://github.com/hmesfin/django-twilio-call",
        "Bug Reports": "https://github.com/hmesfin/django-twilio-call/issues",
        "Changelog": "https://github.com/hmesfin/django-twilio-call/blob/main/CHANGELOG.md",
    },
    keywords="django twilio call-center telephony ivr sms voice celery webhooks",
)
