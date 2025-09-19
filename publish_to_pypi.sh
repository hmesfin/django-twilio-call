#!/bin/bash

# Django-Twilio-Call PyPI Publishing Script
# This script publishes the package to PyPI using your API token

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Banner
echo -e "${BLUE}"
echo "═══════════════════════════════════════════════════════════"
echo "     Django-Twilio-Call PyPI Publishing Script             "
echo "═══════════════════════════════════════════════════════════"
echo -e "${NC}"

# Function to print colored messages
print_status() {
    echo -e "${BLUE}[*]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Check if API token is provided
if [ $# -eq 0 ]; then
    print_error "No API token provided!"
    echo ""
    echo "Usage: $0 <API_TOKEN> [--test]"
    echo ""
    echo "Arguments:"
    echo "  API_TOKEN    Your PyPI API token (starts with 'pypi-')"
    echo "  --test       Optional: Publish to Test PyPI instead of production"
    echo ""
    echo "Examples:"
    echo "  $0 pypi-AgEIcHlwaS5vcmcCJGE4ZDM...  # Publish to PyPI"
    echo "  $0 pypi-AgEIcHlwaS5vcmcCJGE4ZDM... --test  # Publish to Test PyPI"
    echo ""
    exit 1
fi

API_TOKEN=$1
TEST_MODE=false

# Check for test flag
if [ "$2" == "--test" ]; then
    TEST_MODE=true
    print_warning "TEST MODE: Publishing to Test PyPI"
else
    print_warning "PRODUCTION MODE: Publishing to PyPI"
fi

# Validate API token format
if [[ ! "$API_TOKEN" =~ ^pypi- ]]; then
    print_error "Invalid API token format! Token should start with 'pypi-'"
    exit 1
fi

# Check if twine is installed
if ! command -v twine &> /dev/null; then
    print_error "twine is not installed!"
    echo "Install it with: pip install twine"
    exit 1
fi

# Check if build tool is installed
if ! python -c "import build" &> /dev/null; then
    print_error "build is not installed!"
    echo "Install it with: pip install build"
    exit 1
fi

# Check if dist directory exists
if [ ! -d "dist" ]; then
    print_warning "dist directory not found. Building package..."

    # Clean any old builds
    rm -rf build *.egg-info

    # Build the package
    print_status "Building package..."
    python -m build

    if [ $? -eq 0 ]; then
        print_success "Package built successfully!"
    else
        print_error "Failed to build package!"
        exit 1
    fi
else
    print_status "Using existing dist directory"

    # Ask if user wants to rebuild
    read -p "Do you want to rebuild the package? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_status "Cleaning old builds..."
        rm -rf dist build *.egg-info

        print_status "Building package..."
        python -m build

        if [ $? -eq 0 ]; then
            print_success "Package rebuilt successfully!"
        else
            print_error "Failed to rebuild package!"
            exit 1
        fi
    fi
fi

# List the files to be uploaded
echo ""
print_status "Files to be uploaded:"
ls -lh dist/
echo ""

# Validate the package
print_status "Validating package with twine..."
twine check dist/*

if [ $? -ne 0 ]; then
    print_error "Package validation failed!"
    exit 1
fi
print_success "Package validation passed!"

# Get package version
VERSION=$(python -c "import django_twilio_call; print(django_twilio_call.__version__)")
print_status "Package version: $VERSION"

# Confirm before upload
echo ""
if [ "$TEST_MODE" = true ]; then
    PYPI_URL="https://test.pypi.org/legacy/"
    PYPI_NAME="Test PyPI"
    VIEW_URL="https://test.pypi.org/project/django-twilio-call/"
    INSTALL_CMD="pip install -i https://test.pypi.org/simple/ django-twilio-call"
else
    PYPI_URL="https://upload.pypi.org/legacy/"
    PYPI_NAME="PyPI"
    VIEW_URL="https://pypi.org/project/django-twilio-call/"
    INSTALL_CMD="pip install django-twilio-call"
fi

print_warning "Ready to upload django-twilio-call v$VERSION to $PYPI_NAME"
read -p "Are you sure you want to continue? (y/N) " -n 1 -r
echo

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_warning "Upload cancelled by user"
    exit 0
fi

# Create .pypirc temporarily with the token
print_status "Configuring authentication..."
PYPIRC_TEMP=$(mktemp)
cat > "$PYPIRC_TEMP" << EOF
[distutils]
index-servers = pypi

[pypi]
repository = $PYPI_URL
username = __token__
password = $API_TOKEN
EOF

# Upload to PyPI
print_status "Uploading to $PYPI_NAME..."
echo ""

if [ "$TEST_MODE" = true ]; then
    TWINE_CONFIG_FILE="$PYPIRC_TEMP" twine upload --repository-url "$PYPI_URL" dist/*
else
    TWINE_CONFIG_FILE="$PYPIRC_TEMP" twine upload --config-file "$PYPIRC_TEMP" dist/*
fi

UPLOAD_RESULT=$?

# Clean up temporary .pypirc
rm -f "$PYPIRC_TEMP"

if [ $UPLOAD_RESULT -eq 0 ]; then
    echo ""
    print_success "🎉 Package successfully uploaded to $PYPI_NAME!"
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    print_success "View your package at: $VIEW_URL"
    print_success "Install with: $INSTALL_CMD"
    echo "═══════════════════════════════════════════════════════════"
    echo ""

    # Create a git tag for the release
    read -p "Do you want to create a git tag for v$VERSION? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git tag -a "v$VERSION" -m "Release v$VERSION to $PYPI_NAME"
        git push origin "v$VERSION"
        print_success "Git tag v$VERSION created and pushed!"
    fi
else
    print_error "Failed to upload package to $PYPI_NAME"
    echo "Check the error messages above for details."
    exit 1
fi

# Cleanup option
echo ""
read -p "Do you want to clean up the dist directory? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf dist build *.egg-info
    print_success "Build artifacts cleaned up!"
fi

echo ""
print_success "Publishing complete! 🚀"