"""Setup script for telegram-download-chat package."""

from pathlib import Path
from setuptools import setup, find_packages

# Read the contents of README.md
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

setup(
    name="telegram-download-chat",
    version="0.3.0",
    description="CLI utility for downloading Telegram chat history to JSON",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Stanislav Popov",
    author_email="popstas@gmail.com",
    url="https://github.com/popstas/telegram-download-chat",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.8",
    install_requires=[
        "telethon>=1.34.0",
        "PyYAML>=6.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=6.0",
            "black>=22.0",
            "isort>=5.0",
            "mypy>=0.900",
        ]
    },
    entry_points={
        "console_scripts": [
            "telegram-download-chat=telegram_download_chat.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Communications :: Chat",
        "Topic :: Utilities",
    ],
    include_package_data=True,
    package_data={
        "": ["*.yml"],
    },
)
