"""
Runtime hook to suppress pkg_resources deprecation warnings in PyInstaller's pyimod02_importers.
"""
import warnings

# Suppress the pkg_resources deprecation warning
warnings.filterwarnings(
    'ignore',
    message='pkg_resources is deprecated as an API',
    category=UserWarning,
    module='pyimod02_importers'
)
