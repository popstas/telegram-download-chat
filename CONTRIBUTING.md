# Contributing to Telegram Download Chat

Thank you for your interest in contributing to Telegram Download Chat! This document outlines the process for contributing to the project and making new releases.

## Development Setup

1. Fork the repository and clone it locally
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install the package in development mode with all dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
4. Install pre-commit hooks for code quality:
   ```bash
   pre-commit install
   ```

## Code Style

- Follow PEP 8 style guide
- Use type hints for all new code
- Run code formatters before committing:
  ```bash
  black .
  isort .
  ```
- Run linters:
  ```bash
  flake8 .
  mypy .
  ```

## Running Tests

Before submitting changes, please run the test suite:

```bash
pytest -v
```

### Running Specific Tests

Run tests matching a pattern:
```bash
pytest -k "test_name_pattern"
```

Run tests with coverage:
```bash
pytest --cov=telegram_download_chat
```

## Version Management

We use a combination of `bumpversion` and `setuptools-scm` for version management:

1. **bumpversion** is used to:
   - Update version in `__init__.py` and other files
   - Create git tags
   - Make commits with version bumps

2. **setuptools-scm** is used to:
   - Generate version numbers from git tags during builds
   - Create a `_version.py` file automatically
   - Ensure consistent versioning across built packages

### Updating the Version

Use one of these commands to update the version:

```bash
# For a patch release (0.0.1 -> 0.0.2)
bumpversion patch

# For a minor release (0.1.0 -> 0.2.0)
bumpversion minor

# For a major release (1.0.0 -> 2.0.0)
bumpversion major
```

Alternatively, you can run the deploy script with the desired level to bump the
version and publish in one step:

```bash
python deploy.py patch  # or minor/major
```

This will:
- Update version in all tracked files
- Create a git commit with the version bump
- Create a git tag with the new version

## Release Process

1. Ensure all changes for the release are merged to the main branch
2. Make sure all tests are passing
3. Update the CHANGELOG.md with the changes in this release
4. Run the deploy script with the desired bump level, e.g.:
   ```bash
   python deploy.py patch
   ```
5. Push the version bump commit and tag:
   ```bash
   git push
   git push --tags
   ```
6. Create a new release on GitHub with the changelog

## Building the Package

To build the package:
```bash
python -m build
```

To build the Windows executable:
```powershell
.\build_windows.ps1
```

## Debugging

For debugging the GUI, you can use the VS Code launch configuration in `.vscode/launch.json`.
- Create a git tag with the new version

### 3. Push Changes

Push the version bump commit and the new tag to the repository:

```bash
git push origin main
git push --tags
```

### 4. Build and Publish

Build and publish the package to PyPI using the deploy script. Pass the bump
level if you didn't bump it earlier:

```bash
python deploy.py patch  # or minor/major
```

This will:
1. Run the test suite
2. Build the package
3. Check the built package
4. Upload to PyPI

### 5. Create a GitHub Release

1. Go to the [Releases](https://github.com/yourusername/telegram-download-chat/releases) page on GitHub
2. Click "Draft a new release"
3. Select the tag you just pushed
4. Add release notes based on the CHANGELOG
5. Publish the release

## Code Style

Please follow these guidelines when contributing code:

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) for Python code
- Use type hints for all function signatures
- Include docstrings for all public functions and classes
- Keep lines under 100 characters when possible

## Pull Request Process

1. Fork the repository and create your feature branch (`git checkout -b feature/AmazingFeature`)
2. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
3. Push to the branch (`git push origin feature/AmazingFeature`)
4. Open a Pull Request

Please make sure all tests pass and include any relevant updates to documentation.
