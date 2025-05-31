"""
Custom implementation of PyInstaller's pyimod02_importers to suppress pkg_resources warnings.
This module will be imported before the original PyInstaller module.
"""
import warnings
import sys

# Suppress the pkg_resources deprecation warning
warnings.filterwarnings(
    'ignore',
    message='pkg_resources is deprecated as an API',
    category=UserWarning,
    module='pyimod02_importers'
)

# Import the original module
from PyInstaller.loader.pyimod02_importers import *
