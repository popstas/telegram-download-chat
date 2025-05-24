# Contributing to Telegram Download Chat

Thank you for your interest in contributing to Telegram Download Chat! This document outlines the process for contributing to the project and making new releases.

## Development Setup

1. Fork the repository and clone it locally
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

## Running Tests

Before submitting changes, please run the test suite:

```bash
pytest -v
```

## Release Process

### 1. Prepare the Release

1. Ensure all changes for the release are merged to the main branch
2. Make sure all tests are passing
3. Update the CHANGELOG.md with the changes in this release

### 2. Bump the Version

The project uses `bumpversion` to manage version numbers. To bump the version, run one of:

```bash
# For a patch release (0.0.1 -> 0.0.2)
bumpversion patch

# For a minor release (0.1.0 -> 0.2.0)
bumpversion minor

# For a major release (1.0.0 -> 2.0.0)
bumpversion major
```

This will:
- Update the version in all relevant files (pyproject.toml, setup.py, __init__.py)
- Create a git commit with the version bump
- Create a git tag with the new version

### 3. Push Changes

Push the version bump commit and the new tag to the repository:

```bash
git push origin main
git push --tags
```

### 4. Build and Publish

Build and publish the package to PyPI using the deploy script:

```bash
python deploy.py
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
