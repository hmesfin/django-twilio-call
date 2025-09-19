#!/usr/bin/env python
"""
Django-Twilio-Call PyPI Publishing Script (Python Version)

This script publishes the package to PyPI using your API token.

Usage:
    python publish.py <API_TOKEN> [--test] [--skip-build]

Examples:
    python publish.py pypi-AgEIcHlwaS5vcmcCJGE4ZDM...  # Publish to PyPI
    python publish.py pypi-AgEIcHlwaS5vcmcCJGE4ZDM... --test  # Publish to Test PyPI
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ANSI color codes
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color


def print_status(message):
    """Print status message in blue."""
    print(f"{BLUE}[*]{NC} {message}")


def print_success(message):
    """Print success message in green."""
    print(f"{GREEN}[✓]{NC} {message}")


def print_error(message):
    """Print error message in red."""
    print(f"{RED}[✗]{NC} {message}")


def print_warning(message):
    """Print warning message in yellow."""
    print(f"{YELLOW}[!]{NC} {message}")


def print_banner():
    """Print the script banner."""
    print(f"{BLUE}")
    print("═" * 60)
    print("     Django-Twilio-Call PyPI Publishing Script")
    print("═" * 60)
    print(f"{NC}\n")


def check_dependencies():
    """Check if required dependencies are installed."""
    dependencies = {
        'twine': 'pip install twine',
        'build': 'pip install build',
    }

    missing = []
    for package, install_cmd in dependencies.items():
        try:
            __import__(package)
        except ImportError:
            missing.append((package, install_cmd))

    if missing:
        print_error("Missing required dependencies:")
        for package, cmd in missing:
            print(f"  - {package}: Install with '{cmd}'")
        return False

    return True


def get_package_version():
    """Get the package version from __init__.py."""
    try:
        import django_twilio_call
        return django_twilio_call.__version__
    except Exception:
        # Fallback: read from file
        init_file = Path("django_twilio_call/__init__.py")
        if init_file.exists():
            with open(init_file) as f:
                for line in f:
                    if line.startswith("__version__"):
                        return line.split("=")[1].strip().strip('"').strip("'")
        return "0.1.0"


def build_package(force_rebuild=False):
    """Build the package."""
    dist_dir = Path("dist")

    if dist_dir.exists() and not force_rebuild:
        files = list(dist_dir.glob("*"))
        if files:
            print_status(f"Found {len(files)} existing distribution files")
            response = input("Do you want to rebuild the package? (y/N) ").strip().lower()
            if response != 'y':
                return True

    # Clean old builds
    print_status("Cleaning old builds...")
    for path in ["dist", "build", "*.egg-info"]:
        if Path(path).exists():
            if Path(path).is_dir():
                shutil.rmtree(path)
            else:
                Path(path).unlink()

    # Build the package
    print_status("Building package...")
    result = subprocess.run([sys.executable, "-m", "build"], capture_output=True, text=True)

    if result.returncode == 0:
        print_success("Package built successfully!")

        # List built files
        dist_files = list(Path("dist").glob("*"))
        print_status("Built distributions:")
        for file in dist_files:
            size_mb = file.stat().st_size / (1024 * 1024)
            print(f"  - {file.name} ({size_mb:.2f} MB)")

        return True
    else:
        print_error("Failed to build package!")
        print(result.stderr)
        return False


def validate_package():
    """Validate the package with twine."""
    print_status("Validating package with twine...")
    result = subprocess.run(["twine", "check", "dist/*"], shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        print_success("Package validation passed!")
        return True
    else:
        print_error("Package validation failed!")
        print(result.stdout)
        return False


def upload_package(api_token, test_mode=False):
    """Upload the package to PyPI."""
    if test_mode:
        repository_url = "https://test.pypi.org/legacy/"
        pypi_name = "Test PyPI"
        view_url = "https://test.pypi.org/project/django-twilio-call/"
    else:
        repository_url = "https://upload.pypi.org/legacy/"
        pypi_name = "PyPI"
        view_url = "https://pypi.org/project/django-twilio-call/"

    version = get_package_version()

    # Confirm upload
    print_warning(f"Ready to upload django-twilio-call v{version} to {pypi_name}")
    response = input("Are you sure you want to continue? (y/N) ").strip().lower()

    if response != 'y':
        print_warning("Upload cancelled by user")
        return False

    # Upload using twine with API token
    print_status(f"Uploading to {pypi_name}...")

    env = os.environ.copy()
    env["TWINE_USERNAME"] = "__token__"
    env["TWINE_PASSWORD"] = api_token

    cmd = ["twine", "upload"]
    if test_mode:
        cmd.extend(["--repository-url", repository_url])
    cmd.append("dist/*")

    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if result.returncode == 0:
        print_success(f"🎉 Package successfully uploaded to {pypi_name}!")
        print("\n" + "═" * 60)
        print_success(f"View your package at: {view_url}")
        if test_mode:
            print_success(f"Install with: pip install -i https://test.pypi.org/simple/ django-twilio-call")
        else:
            print_success("Install with: pip install django-twilio-call")
        print("═" * 60 + "\n")

        # Offer to create git tag
        response = input(f"Do you want to create a git tag for v{version}? (y/N) ").strip().lower()
        if response == 'y':
            subprocess.run(["git", "tag", "-a", f"v{version}", "-m", f"Release v{version} to {pypi_name}"])
            subprocess.run(["git", "push", "origin", f"v{version}"])
            print_success(f"Git tag v{version} created and pushed!")

        return True
    else:
        print_error(f"Failed to upload package to {pypi_name}")
        print("Error output:")
        print(result.stderr)
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Publish django-twilio-call package to PyPI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s pypi-AgEI...          # Publish to PyPI
  %(prog)s pypi-AgEI... --test   # Publish to Test PyPI
  %(prog)s pypi-AgEI... --skip-build  # Skip rebuild if dist exists
        """
    )

    parser.add_argument(
        "api_token",
        help="Your PyPI API token (should start with 'pypi-')"
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Publish to Test PyPI instead of production"
    )

    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip building if dist directory exists"
    )

    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip package validation with twine check"
    )

    args = parser.parse_args()

    # Print banner
    print_banner()

    # Validate API token format
    if not args.api_token.startswith("pypi-"):
        print_error("Invalid API token format! Token should start with 'pypi-'")
        return 1

    # Mode notification
    if args.test:
        print_warning("TEST MODE: Publishing to Test PyPI")
    else:
        print_warning("PRODUCTION MODE: Publishing to PyPI")

    # Check dependencies
    if not check_dependencies():
        return 1

    # Build package
    if not args.skip_build:
        if not build_package():
            return 1
    else:
        dist_dir = Path("dist")
        if not dist_dir.exists() or not list(dist_dir.glob("*")):
            print_error("No distribution files found! Build the package first.")
            return 1

    # Validate package
    if not args.skip_validation:
        if not validate_package():
            return 1

    # Upload package
    if not upload_package(args.api_token, args.test):
        return 1

    # Cleanup option
    response = input("\nDo you want to clean up the dist directory? (y/N) ").strip().lower()
    if response == 'y':
        shutil.rmtree("dist", ignore_errors=True)
        shutil.rmtree("build", ignore_errors=True)
        for path in Path(".").glob("*.egg-info"):
            shutil.rmtree(path)
        print_success("Build artifacts cleaned up!")

    print_success("\nPublishing complete! 🚀")
    return 0


if __name__ == "__main__":
    sys.exit(main())