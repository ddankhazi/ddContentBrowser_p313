"""
DD Content Browser Package
A powerful asset management and import tool for Maya

Author: ddankhazi
License: MIT
"""

# Version - SINGLE SOURCE OF TRUTH
# MUST be defined BEFORE importing other modules that use it!
__version__ = '1.9.5'

# Import all modules
from .config import ContentBrowserConfig
from .utils import get_maya_main_window, MAYA_AVAILABLE, PYSIDE_VERSION
from .cache import ThumbnailCache, ThumbnailDiskCache, ThumbnailGenerator
from .models import AssetItem, FileSystemModel
from .delegates import ThumbnailDelegate
from .widgets import BreadcrumbWidget, FilterPanel, PreviewPanel, MayaStyleListView
from .browser import DDContentBrowser, show_content_browser

# Package exports
__all__ = [
    # Config
    'ContentBrowserConfig',
    # Utils
    'get_maya_main_window',
    'MAYA_AVAILABLE',
    'PYSIDE_VERSION',
    # Cache
    'ThumbnailCache',
    'ThumbnailDiskCache',
    'ThumbnailGenerator',
    # Models
    'AssetItem',
    'FileSystemModel',
    # Delegates
    'ThumbnailDelegate',
    # Widgets
    'BreadcrumbWidget',
    'FilterPanel',
    'PreviewPanel',
    'MayaStyleListView',
    # Main browser
    'DDContentBrowser',
    'show_content_browser',
]
