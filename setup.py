"""Setup script for telegram-download-chat package."""

import os
import sys
from pathlib import Path

from setuptools import find_packages, setup

# Add src to path so we can import __version__
sys.path.insert(0, os.path.abspath("src"))
from telegram_download_chat import __version__

# Read the contents of README.md
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="telegram-download-chat",
    version=__version__,
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
        "gui": ["PySide6>=6.5.0"],
        "web": ["nicegui>=2.0.0"],
        "dev": [
            "pytest>=6.0",
            "black>=22.0",
            "isort>=5.0",
            "mypy>=0.900",
        ],
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
