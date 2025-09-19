# Publishing django-twilio-call to PyPI

## 🔑 Prerequisites

1. **PyPI Account**: Create an account at <https://pypi.org>
2. **API Token**: Generate an API token from <https://pypi.org/manage/account/token/>
   - The token will start with `pypi-`
   - Save it securely (you won't be able to see it again)
3. **Test PyPI Account** (Optional): Create an account at <https://test.pypi.org> for testing

## 📦 Publishing Scripts

We provide two scripts for publishing:

### Option 1: Bash Script (Linux/Mac)

```bash
# Publish to PyPI (Production)
./publish_to_pypi.sh YOUR_PYPI_TOKEN

# Publish to Test PyPI first (Recommended)
./publish_to_pypi.sh YOUR_PYPI_TOKEN --test
```

### Option 2: Python Script (Cross-platform)

```bash
# Publish to PyPI (Production)
python publish.py YOUR_PYPI_TOKEN

# Publish to Test PyPI first (Recommended)
python publish.py YOUR_PYPI_TOKEN --test

# Skip rebuild if you already have dist files
python publish.py YOUR_PYPI_TOKEN --skip-build

# Skip validation (not recommended)
python publish.py YOUR_PYPI_TOKEN --skip-validation
```

## 🚀 Recommended Publishing Flow

### 1. Test PyPI First (Recommended)

```bash
# Build and upload to Test PyPI
python publish.py YOUR_TEST_PYPI_TOKEN --test

# Test installation from Test PyPI
pip install -i https://test.pypi.org/simple/ django-twilio-call

# Verify it works
python -c "import django_twilio_call; print(django_twilio_call.__version__)"
```

### 2. Production PyPI

Once verified on Test PyPI:

```bash
# Upload to Production PyPI
python publish.py YOUR_PYPI_TOKEN

# Install from PyPI
pip install django-twilio-call
```

## 📝 Manual Publishing (Alternative)

If you prefer to do it manually:

```bash
# 1. Install required tools
pip install build twine

# 2. Build the package
python -m build

# 3. Check the package
twine check dist/*

# 4. Upload to Test PyPI
twine upload --repository testpypi dist/*

# 5. Upload to PyPI
twine upload dist/*
```

## 🔐 Security Notes

1. **Never commit your API token** to version control
2. **Use environment variables** for CI/CD:

   ```bash
   export PYPI_TOKEN="your-token-here"
   python publish.py $PYPI_TOKEN
   ```

3. **Create project-specific tokens** for better security
4. **Use 2FA** on your PyPI account

## 🏷️ Version Management

Before publishing a new version:

1. Update version in `django_twilio_call/__init__.py`
2. Update `CHANGELOG.md` with release notes
3. Commit changes
4. The scripts will offer to create a git tag automatically

## ❓ Troubleshooting

### "Invalid API token format"

- Ensure your token starts with `pypi-`
- Check for extra spaces or quotes

### "Package validation failed"

- Run `twine check dist/*` to see specific issues
- Ensure README.md exists and is valid markdown

### "Failed to upload package"

- Check your internet connection
- Verify your API token has upload permissions
- Try Test PyPI first to debug issues

### "Package already exists"

- You can't overwrite an existing version on PyPI
- Increment the version number in `__init__.py`
- Rebuild and try again

## 📊 After Publishing

1. **Verify on PyPI**: <https://pypi.org/project/django-twilio-call/>
2. **Check installation**: `pip install django-twilio-call`
3. **Monitor downloads**: <https://pypistats.org/packages/django-twilio-call>
4. **Update documentation**: Ensure README and docs are current
5. **Announce release**: Twitter, blog post, etc.

## 🎯 GitHub Actions (Future)

For automated publishing, add this to `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: '3.x'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install build twine
    - name: Build package
      run: python -m build
    - name: Publish to PyPI
      env:
        TWINE_USERNAME: __token__
        TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
      run: twine upload dist/*
```

Then add your API token as a GitHub secret named `PYPI_API_TOKEN`.

---

**Ready to share django-twilio-call with the world! 🚀**
