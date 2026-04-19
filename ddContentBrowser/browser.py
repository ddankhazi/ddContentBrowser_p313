# -*- coding: utf-8 -*-
"""
DD Content Browser - Main Browser Window
The main DDContentBrowser window class

Author: ddankhazi
License: MIT
"""

import os
import sys
import shutil
from pathlib import Path
from datetime import datetime

# Import from package modules
from . import __version__
from .config import ContentBrowserConfig
from .utils import get_maya_main_window, MAYA_AVAILABLE
from .cache import ThumbnailCache, ThumbnailDiskCache, ThumbnailGenerator
from .models import AssetItem, FileSystemModel
from .delegates import ThumbnailDelegate
from .widgets import BreadcrumbWidget, PreviewPanel, MayaStyleListView
from .settings import SettingsManager, SettingsDialog
from .advanced_filters_v2 import AdvancedFiltersPanelV2

# PySide imports
try:
    from PySide6 import QtCore, QtWidgets, QtGui
    from PySide6.QtCore import Qt, QTimer, qInstallMessageHandler
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2 import QtCore, QtWidgets, QtGui
    from PySide2.QtCore import Qt, QTimer, qInstallMessageHandler
    PYSIDE_VERSION = 2

# Custom Qt message handler to suppress TGA warnings globally
def qt_message_handler(msg_type, context, message):
    """Suppress QTgaHandler allocation warnings (we handle large TGA files properly)"""
    # Suppress ALL TGA-related warnings (Qt's TGA handler is unreliable)
    if "QTgaHandler" in message:
        return
    
    # Pass through other messages
    if PYSIDE_VERSION == 6:
        from PySide6.QtCore import QtMsgType
    else:
        from PySide2.QtCore import QtMsgType
    
    if msg_type == QtMsgType.QtDebugMsg:
        print(f"Qt Debug: {message}")
    elif msg_type == QtMsgType.QtWarningMsg:
        print(f"Qt Warning: {message}")
    elif msg_type == QtMsgType.QtCriticalMsg:
        print(f"Qt Critical: {message}")
    elif msg_type == QtMsgType.QtFatalMsg:
        print(f"Qt Fatal: {message}")



# Install the message handler GLOBALLY (affects all Qt operations including cache.py)
qInstallMessageHandler(qt_message_handler)

# Maya imports
try:
    import maya.cmds as cmds
    import maya.mel as mel
except ImportError:
    pass  # Already handled by utils.MAYA_AVAILABLE

# Debug flag - set to False to disable verbose logging
DEBUG_MODE = False  # Performance optimizations active

class FavoritesColorBarDelegate(QtWidgets.QStyledItemDelegate):
    """Custom delegate to draw a colored bar on the left side of favorite items"""
    
    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser
    
    def paint(self, painter, option, index):
        # Get the item and its widget (QLabel)
        item = self.browser.favorites_list.item(index.row())
        if item:
            label = self.browser.favorites_list.itemWidget(item)
            if label:
                # Get color from favorites config
                path = label.property("fullPath")
                if path:
                    favorites = self.browser.config.config.get("favorites", [])
                    for fav in favorites:
                        fav_dict = self.browser._normalize_favorite(fav)
                        if fav_dict and fav_dict["path"] == path:
                            if fav_dict["color"]:
                                # Draw colored bar first
                                painter.save()
                                painter.setPen(Qt.NoPen)
                                from PySide6.QtGui import QColor
                                from PySide6.QtCore import QRect
                                painter.setBrush(QColor(fav_dict["color"]))
                                
                                # Bar: 6px wide on the left edge
                                bar_rect = QRect(option.rect.left(), option.rect.top(), 6, option.rect.height())
                                painter.drawRect(bar_rect)
                                
                                painter.restore()
                                
                                # Adjust widget position to shift right by 12px
                                if label:
                                    label.setContentsMargins(12, 0, 0, 0)
                                
                                # Draw default item with normal rect
                                super().paint(painter, option, index)
                                return
                            break  # Found the favorite, no color
        
        # No color - draw normally without margin
        if item:
            label = self.browser.favorites_list.itemWidget(item)
            if label:
                label.setContentsMargins(0, 0, 0, 0)
        
        super().paint(painter, option, index)


class SortHeaderWidget(QtWidgets.QWidget):
    """Custom sort header widget that handles right-click for filters"""
    
    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser
        
    def mousePressEvent(self, event):
        """Handle right-click for filter menu"""
        if event.button() == Qt.RightButton:
            # Don't show filter menu if advanced filters are active
            if self.browser.advanced_filters_active:
                return  # Ignore right-click when advanced filters are active
            # Determine which column was right-clicked
            clicked_column = self.get_clicked_column(event.pos())
            self.show_filter_menu(event.pos(), clicked_column)
        else:
            super().mousePressEvent(event)
    
    def get_clicked_column(self, position):
        """Determine which column header was clicked"""
        # Calculate approximate column boundaries based on layout proportions
        total_width = self.width()
        name_end = total_width * 0.4
        type_end = total_width * 0.6  # 40% + 20%
        size_end = total_width * 0.8  # 40% + 20% + 20%
        
        if position.x() <= name_end:
            return "name"
        elif position.x() <= type_end:
            return "type"
        elif position.x() <= size_end:
            return "size"
        else:
            return "date"
    
    def show_filter_menu(self, position, column=None):
        """Show contextual filter menu based on clicked column"""
        menu = QtWidgets.QMenu(self)
        
        if column == "name":
            # NAME column - no filters available
            no_filters_action = menu.addAction("No filters available for Name column")
            no_filters_action.setEnabled(False)
            
        elif column == "type":
            # TYPE column - folder visibility and file type filters
            # First add folder visibility toggle
            folders_action = menu.addAction("Show Folders")
            folders_action.setCheckable(True)
            folders_action.setChecked(self.browser.file_model.show_folders)
            folders_action.triggered.connect(self.toggle_show_folders)
            
            menu.addSeparator()
            
            # Then file type filters - using central registry
            from .utils import reload_file_formats_config, get_filter_groups
            reload_file_formats_config()  # Force reload to get latest config
            
            current_types = self.browser.file_model.filter_file_types
            
            file_type_groups = get_filter_groups()
            
            for group_name, extensions in file_type_groups:
                action = menu.addAction(group_name)
                action.setCheckable(True)
                # Fixed logic: if no filter is set, everything is shown (checked)
                # If filter is set, check if ALL extensions from this group are in the filter
                if not current_types:  # No filter = show all
                    is_checked = True
                else:  # Filter exists = check if this group is included
                    is_checked = all(ext in current_types for ext in extensions)
                
                action.setChecked(is_checked)
                action.triggered.connect(lambda checked=None, exts=extensions, act=action: self.toggle_file_type_group(exts, act.isChecked()))
            
        elif column == "size":
            # SIZE column - size filters
            size_options = [
                ("All Sizes", 0, 0),
                ("< 10 MB", 0, 10 * 1024 * 1024),
                ("10-100 MB", 10 * 1024 * 1024, 100 * 1024 * 1024),
                ("> 100 MB", 100 * 1024 * 1024, 0)
            ]
            
            current_min = self.browser.file_model.filter_min_size
            current_max = self.browser.file_model.filter_max_size
            
            for label, min_size, max_size in size_options:
                action = menu.addAction(label)
                action.setCheckable(True)
                # Check if this matches current filter
                is_current = (current_min == min_size and current_max == max_size)
                action.setChecked(is_current)
                action.triggered.connect(lambda checked=None, min_s=min_size, max_s=max_size: self.set_size_filter(min_s, max_s))
            
        elif column == "date":
            # DATE column - date filters
            from datetime import datetime, timedelta
            
            date_options = [
                ("All Dates", None, None),
                ("Today", datetime.now().replace(hour=0, minute=0, second=0), None),
                ("This Week", datetime.now() - timedelta(days=7), None),
                ("This Month", datetime.now() - timedelta(days=30), None)
            ]
            
            for label, date_from, date_to in date_options:
                action = menu.addAction(label)
                action.setCheckable(True)
                
                # Check current filter state
                current_from = self.browser.file_model.filter_date_from
                current_to = self.browser.file_model.filter_date_to
                
                if label == "All Dates":
                    # "All Dates" is checked when no date filter is active
                    action.setChecked(current_from is None and current_to is None)
                else:
                    # For specific date ranges, check if they match current filter
                    # Compare dates (ignoring time for today/week/month comparisons)
                    if date_from is not None and current_from is not None:
                        # Convert to date for comparison (ignore time)
                        filter_date = date_from.date() if hasattr(date_from, 'date') else date_from
                        current_date = current_from.date() if hasattr(current_from, 'date') else current_from
                        action.setChecked(filter_date == current_date)
                    else:
                        action.setChecked(False)
                        
                action.triggered.connect(lambda checked=None, df=date_from, dt=date_to: self.set_date_filter(df, dt))
        
        # Add column-specific clear option
        if menu.actions():  # Only if we added some actions
            menu.addSeparator()
            if column == "type":
                clear_action = menu.addAction("Clear Type Filters")
                clear_action.triggered.connect(self.clear_type_filters)
            elif column == "size":
                clear_action = menu.addAction("Clear Size Filters")
                clear_action.triggered.connect(self.clear_size_filters)
            elif column == "date":
                clear_action = menu.addAction("Clear Date Filters")
                clear_action.triggered.connect(self.clear_date_filters)
        
        # Show menu at cursor position
        global_pos = self.mapToGlobal(position)
        menu.exec_(global_pos)
    
    def toggle_show_folders(self):
        """Toggle folder visibility"""
        current = self.browser.file_model.show_folders
        self.browser.file_model.setShowFolders(not current)
        self.browser.update_filter_visual_feedback()
    
    def toggle_show_images(self):
        """Toggle image file visibility"""
        current = self.browser.file_model.show_images
        self.browser.file_model.setShowImages(not current)
        self.browser.update_filter_visual_feedback()
    
    def toggle_show_scripts(self):
        """Toggle script file visibility"""
        current = self.browser.file_model.show_scripts
        self.browser.file_model.setShowScripts(not current)
        self.browser.update_filter_visual_feedback()
    
    def toggle_file_type_group(self, extensions, checked):
        """Toggle a group of file types"""
        current_types = self.browser.file_model.filter_file_types.copy()
        
        if checked:
            # Enable this group - add to filter if filter exists, or keep empty (show all)
            if current_types:  # If there's already a filter
                for ext in extensions:
                    if ext not in current_types:
                        current_types.append(ext)
            # If no filter exists (empty list), keep it empty to show all
        else:
            # Disable this group
            if not current_types:  # If no filter (show all), create filter excluding this group
                # Add all other supported extensions except this group
                # Use the actual supported formats from the model
                all_extensions = self.browser.file_model.supported_formats.copy()
                current_types = [ext for ext in all_extensions if ext not in extensions]
            else:  # Filter exists, remove this group
                for ext in extensions:
                    if ext in current_types:
                        current_types.remove(ext)
        
        self.browser.file_model.setFilterFileTypes(current_types)
        self.browser.update_filter_visual_feedback()
    
    def set_size_filter(self, min_size, max_size):
        """Set size filter"""
        self.browser.file_model.setFilterSize(min_size, max_size)
        self.browser.update_filter_visual_feedback()
    
    def set_date_filter(self, date_from, date_to):
        """Set date filter"""
        self.browser.file_model.setFilterDate(date_from, date_to)
        self.browser.update_filter_visual_feedback()
    
    def clear_type_filters(self):
        """Clear only type-related filters"""
        self.browser.file_model.setFilterFileTypes([])
        self.browser.file_model.setShowFolders(True)  # Reset folders visibility
        self.browser.update_filter_visual_feedback()
    
    def clear_size_filters(self):
        """Clear only size filters"""
        self.browser.file_model.setFilterSize(0, 0)  # Reset to no size limits
        self.browser.update_filter_visual_feedback()
    
    def clear_date_filters(self):
        """Clear only date filters"""
        self.browser.file_model.setFilterDate(None, None)
        self.browser.update_filter_visual_feedback()
    
    def clear_all_filters(self):
        """Clear all filters"""
        self.browser.file_model.clearFilters()
        self.browser.update_filter_visual_feedback()


# Singleton instance
_content_browser_instance = None


def show_content_browser(force_reload=False):
    """Show the content browser window (singleton)
    
    Args:
        force_reload (bool): If True, forces recreation of the browser instance and clears Python cache
    """
    global _content_browser_instance
    
    # Force reload: delete existing instance AND clear Python cache
    if force_reload and _content_browser_instance is not None:
        try:
            _content_browser_instance.close()
            _content_browser_instance.deleteLater()
        except:
            pass
        _content_browser_instance = None
        
        # Clear Python module cache for this package
        import sys
        modules_to_reload = [k for k in sys.modules.keys() if k.startswith('ddContentBrowser')]
        for mod in modules_to_reload:
            del sys.modules[mod]
        if DEBUG_MODE:
            print(f"[Reload] Cleared {len(modules_to_reload)} module(s) from cache")
    
    if _content_browser_instance is None:
        _content_browser_instance = DDContentBrowser()
    
    _content_browser_instance.show()
    _content_browser_instance.raise_()
    _content_browser_instance.activateWindow()
    
    return _content_browser_instance


class DDContentBrowser(QtWidgets.QMainWindow):
    """Main Content Browser window"""
    
    def __init__(self, parent=None):
        if parent is None:
            parent = get_maya_main_window()
        
        super().__init__(parent)
        
        # Settings manager (load first, before config)
        self.settings_manager = SettingsManager()
        
        # Apply UI font from settings
        self._apply_ui_font()
        
        # Configuration and cache
        self.config = ContentBrowserConfig()
        
        # Ensure file formats config exists (auto-generates on first run)
        from .utils import ensure_file_formats_config
        self.file_formats_config = ensure_file_formats_config()
        if DEBUG_MODE:
            print(f"[Browser] File formats config loaded: {len(self.file_formats_config.get('extensions', {}))} extensions")
        
        # Sync memory cache size from settings to config (settings takes precedence)
        memory_cache_size = self.settings_manager.get("thumbnails", "memory_cache_size", 2000)
        self.config.config["thumbnail_cache_size"] = memory_cache_size
        
        # Initialize cache systems
        self.memory_cache = ThumbnailCache(self.config.config["thumbnail_cache_size"])
        disk_cache_size_mb = self.settings_manager.get("thumbnails", "cache_size_mb", 500)
        self.disk_cache = ThumbnailDiskCache(max_size_mb=disk_cache_size_mb)
        
        # Get metadata manager for tag-based operations (needed by thumbnail generator)
        from .metadata import get_metadata_manager
        self.metadata_manager = get_metadata_manager()
        
        # Initialize thumbnail generator with size and quality from settings (not config!)
        # This is the GENERATION size (how big thumbnails are created and cached)
        # Display size (grid/list slider) is separate and stored in config.json
        thumbnail_generation_size = self.settings_manager.get("thumbnails", "size", 128)
        
        # Get JPEG quality from settings and convert to numeric value
        quality_str = self.settings_manager.get("thumbnails", "quality", "medium")
        quality_map = {"low": 60, "medium": 85, "high": 95}
        jpeg_quality = quality_map.get(quality_str, 85)
        
        # Get worker thread count from settings (default: None = auto-detect based on CPU cores)
        # Higher values = faster thumbnail generation but more CPU/memory usage
        # If set to 0, auto-detect optimal count (recommended)
        max_workers = self.settings_manager.get("thumbnails", "worker_threads", 0)
        if max_workers == 0:
            max_workers = None  # Auto-detect based on CPU cores
        
        self.thumbnail_generator = ThumbnailGenerator(
            self.memory_cache,
            self.disk_cache,
            thumbnail_generation_size,
            jpeg_quality,
            self.metadata_manager,  # Pass metadata_manager for auto-tagging
            max_workers  # Number of parallel worker threads (None = auto-detect)
        )
        
        # Connect thumbnail generator signals
        self.thumbnail_generator.thumbnail_ready.connect(self.on_thumbnail_ready)
        self.thumbnail_generator.progress_update.connect(self.on_thumbnail_progress)
        self.thumbnail_generator.generation_failed.connect(self.on_thumbnail_failed)
        
        # Connect cache_status signal if available (may not exist after hot reload)
        if hasattr(self.thumbnail_generator, 'cache_status'):
            self.thumbnail_generator.cache_status.connect(self.on_cache_status)
        
        # Track cache vs generation stats
        self.cache_hits = 0
        self.generations = 0
        
        # Track loading state (to prevent thumbnail progress from overwriting loading messages)
        self._loading_in_progress = False
        self._limit_reached_shown = False
        
        # Track advanced filters state
        self.advanced_filters_active = False
        
        # Track current collection (for remove from collection feature)
        self.current_collection_name = None
        
        # Quick View window (macOS Quick Look style)
        self.quick_view_window = None
        
        # File system watcher for automatic refresh
        if PYSIDE_VERSION == 6:
            from PySide6.QtCore import QFileSystemWatcher
        else:
            from PySide2.QtCore import QFileSystemWatcher
        self.file_watcher = QFileSystemWatcher()
        self.file_watcher.directoryChanged.connect(self.on_directory_changed)
        
        # Debounce timer flag (simpler approach without QTimer object)
        self._watcher_pending_refresh = False
        
        # Start thumbnail generator thread
        self.thumbnail_generator.start()
        
        # Navigation history
        self.history = []
        self.history_index = -1
        self.is_navigating_history = False
        self.is_navigating_from_recent = False  # Don't update recent list when navigating from it
        self.is_navigating_from_favorites = False  # Don't clear favorites selection when navigating from it
        
        # Let Maya handle most styling - only minimal overrides
        # This gives us native Maya look without fighting the system
        # Set Maya-style tooltip colors (dark gray background, white text)
        self.setStyleSheet("""
            QToolTip {
                background-color: #3a3a3a;
                color: #e0e0e0;
                border: 1px solid #555;
                padding: 3px;
                font-size: 11px;
            }
        """)
        
        # UI setup
        self.setup_ui()
        self.setup_connections()
        
        # Initialize navigation buttons
        self.update_navigation_buttons()
        
        # Set initial view mode from config (default: grid)
        saved_view_mode = self.config.config.get("view_mode", "grid")
        self.set_view_mode(saved_view_mode == "grid")  # True = Grid, False = List
        
        # Update toolbar buttons to match
        if saved_view_mode == "grid":
            self.grid_mode_btn.setChecked(True)
            self.list_mode_btn.setChecked(False)
        else:
            self.grid_mode_btn.setChecked(False)
            self.list_mode_btn.setChecked(True)
        
        # Restore preview panel visibility
        preview_visible = self.config.config.get("preview_panel_visible", True)
        self.preview_panel.setVisible(preview_visible)
        self.preview_toggle_btn.setChecked(preview_visible)
        
        # Restore sequence mode from config (UI state)
        sequence_mode = self.config.config.get("sequence_mode", False)
        self.sequence_mode_checkbox.setChecked(sequence_mode)
        self.file_model.sequence_mode = sequence_mode
        
        # Apply settings from settings manager (overrides config if exists)
        self.apply_settings()
        
        # Set initial path
        initial_path = self.config.config.get("last_path", str(Path.home()))
        # Check if there's a startup directory in settings
        startup_dir = self.settings_manager.get("general", "startup_directory", "")
        if startup_dir and os.path.exists(startup_dir):
            initial_path = startup_dir
        self.navigate_to_path(initial_path)
        
        # Restore window geometry
        if self.config.config.get("window_geometry"):
            try:
                geometry = QtCore.QByteArray.fromBase64(
                    self.config.config["window_geometry"].encode()
                )
                self.restoreGeometry(geometry)
            except:
                pass
    
    def _apply_ui_font(self):
        """Apply UI font from settings to all modules"""
        ui_font = self.settings_manager.get("general", "ui_font", "Segoe UI")
        
        # Update font in all modules that use UI_FONT
        try:
            from . import widgets, delegates, cache, models, advanced_filters_v2, quick_view
            widgets.UI_FONT = ui_font
            delegates.UI_FONT = ui_font
            cache.UI_FONT = ui_font
            models.UI_FONT = ui_font
            advanced_filters_v2.UI_FONT = ui_font
            quick_view.UI_FONT = ui_font
        except Exception as e:
            print(f"Warning: Could not apply UI font: {e}")
    
    def setup_ui(self):
        """Setup UI"""
        self.setWindowTitle(f"Content Browser for Maya | v{__version__} | by Denes Dankhazi")
        self.setMinimumSize(800, 600)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Central widget
        central_widget = QtWidgets.QWidget()
        central_widget.setContentsMargins(0, 0, 0, 0)  # Remove default margins
        self.setCentralWidget(central_widget)
        
        # Main layout - match Maya spacing
        main_layout = QtWidgets.QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)  # No margins, let widgets handle spacing
        main_layout.setSpacing(4)  # Tight spacing between menubar and toolbar
        
        # Create toolbar
        self.create_toolbar(main_layout)
        
        # Content area
        self.content_splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.content_splitter.setHandleWidth(3)
        self.content_splitter.setChildrenCollapsible(False)  # Prevent panels from collapsing
        # Use opaque resize (real-time resize) for smooth dragging
        # With UniformItemSizes=True on file_list, this is VERY fast!
        self.content_splitter.setOpaqueResize(True)
        main_layout.addWidget(self.content_splitter)
        
        # Left panel - Navigation
        self.create_navigation_panel(self.content_splitter)
        
        # Middle panel - File browser
        self.create_browser_panel(self.content_splitter)
        
        # Right panel - Preview (initially visible)
        self.preview_panel = PreviewPanel(self.settings_manager, config=self.config, metadata_manager=self.metadata_manager)
        self.content_splitter.addWidget(self.preview_panel)
        
        # Set splitter initial sizes (20% nav, 50% browser, 30% preview)
        # Load saved splitter position or use default
        splitter_pos = self.config.config.get("splitter_position", None)
        if splitter_pos:
            # Restore from base64 encoded state
            state_bytes = QtCore.QByteArray.fromBase64(splitter_pos.encode())
            self.content_splitter.restoreState(state_bytes)
        else:
            # Default: 20% nav, 50% browser, 30% preview
            total_width = 1400  # Default window width
            self.content_splitter.setSizes([
                int(total_width * 0.2), 
                int(total_width * 0.5), 
                int(total_width * 0.3)
            ])
        
        # Connect splitter moved signal to save position
        self.content_splitter.splitterMoved.connect(self.on_splitter_moved)
        # Track splitter performance metrics
        self._splitter_move_count = 0  # Track how many times splitter moved
        self._splitter_drag_start_time = None  # Track drag start time
        self._viewport_paint_times = []  # Track viewport paint durations
        
        # Status bar with thumbnail progress on the right
        self.status_bar = self.statusBar()
        self.status_bar.setStyleSheet("""
            QStatusBar {
                border: none;
            }
            QStatusBar::item {
                border: none;
            }
        """)
        
        # Thumbnail progress label (permanent widget on the right)
        if PYSIDE_VERSION == 6:
            from PySide6.QtWidgets import QLabel
        else:
            from PySide2.QtWidgets import QLabel
        
        self.thumbnail_status_label = QLabel("")
        self.thumbnail_status_label.setStyleSheet("""
            QLabel { 
                padding: 0 10px; 
                border: none; 
                background: transparent;
                margin: 0;
            }
        """)
        self.thumbnail_status_label.setFrameShape(QLabel.NoFrame)
        self.thumbnail_status_label.setAutoFillBackground(False)
        self.status_bar.addPermanentWidget(self.thumbnail_status_label)
        
        self.safe_show_status("Ready")
    
    def safe_show_status(self, message, timeout=0):
        """Safely show status bar message, handling deleted widget cases"""
        try:
            if hasattr(self, 'status_bar') and self.status_bar is not None:
                self.status_bar.showMessage(message, timeout)
        except RuntimeError:
            # C++ object already deleted, safely ignore
            pass
    
    def create_menu_bar(self):
        """Create menu bar with Tools menu"""
        menu_bar = self.menuBar()
        
        # Tools menu
        tools_menu = menu_bar.addMenu("Tools")
        
        # Settings action
        # In PySide6, QAction is in QtGui, in PySide2 it's in QtWidgets
        QAction = QtGui.QAction if PYSIDE_VERSION == 6 else QtWidgets.QAction
        
        settings_action = QAction("Settings...", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.show_settings_dialog)
        tools_menu.addAction(settings_action)
        
        # Batch Rename action
        batch_rename_action = QAction("Batch Rename...", self)
        batch_rename_action.setShortcut("Ctrl+R")
        batch_rename_action.triggered.connect(self.show_batch_rename_dialog)
        tools_menu.addAction(batch_rename_action)
        
        # Separator
        tools_menu.addSeparator()
        
        # Clear cache action
        clear_cache_action = QAction("Clear Thumbnail Cache", self)
        clear_cache_action.triggered.connect(self.clear_thumbnail_cache)
        tools_menu.addAction(clear_cache_action)
        
        # Show Maya status in standalone mode
        if not MAYA_AVAILABLE:
            tools_menu.addSeparator()
            maya_status = QAction("⚠️ Standalone Mode (Maya features disabled)", self)
            maya_status.setEnabled(False)
            tools_menu.addAction(maya_status)
    
    def create_toolbar(self, parent_layout):
        """Create toolbar"""
        toolbar_layout = QtWidgets.QHBoxLayout()
        
        # Recent folders dropdown button (before Back/Forward)
        self.recent_btn = QtWidgets.QPushButton(u"\U0001F552")  # Clock emoji
        self.recent_btn.setMaximumWidth(35)
        self.recent_btn.setMinimumHeight(28)
        self.recent_btn.setStyleSheet("""
            QPushButton { 
                font-size: 16px; 
                background-color: transparent;
                border: none;
            }
            QPushButton::menu-indicator { 
                width: 0px; 
            }
            QPushButton:hover { 
                background-color: rgba(255, 255, 255, 30);
                border-radius: 3px;
            }
        """)
        self.recent_btn.setToolTip("Recent Folders")
        recent_menu = QtWidgets.QMenu(self.recent_btn)
        from . import widgets
        recent_menu.setFont(QtGui.QFont(widgets.UI_FONT, 9))
        recent_menu.setToolTipsVisible(True)  # Enable tooltips on menu items
        self.recent_btn.setMenu(recent_menu)
        toolbar_layout.addWidget(self.recent_btn)
        
        # Back/Forward buttons
        self.back_btn = QtWidgets.QPushButton("◀")
        self.back_btn.setMaximumWidth(30)
        self.back_btn.setToolTip("Back")
        toolbar_layout.addWidget(self.back_btn)
        
        self.forward_btn = QtWidgets.QPushButton("▶")
        self.forward_btn.setMaximumWidth(30)
        self.forward_btn.setToolTip("Forward")
        toolbar_layout.addWidget(self.forward_btn)
        
        # Breadcrumb navigation
        self.breadcrumb = BreadcrumbWidget()
        toolbar_layout.addWidget(self.breadcrumb, 1)  # Stretch factor 1 - takes available space
        
        # Browse button
        self.browse_btn = QtWidgets.QPushButton("Browse...")
        toolbar_layout.addWidget(self.browse_btn)
        
        # Preview panel toggle button
        self.preview_toggle_btn = QtWidgets.QPushButton("👁️ Preview")
        self.preview_toggle_btn.setCheckable(True)
        self.preview_toggle_btn.setChecked(True)  # Initially visible
        self.preview_toggle_btn.setToolTip("Toggle Preview Panel")
        toolbar_layout.addWidget(self.preview_toggle_btn)
        
        parent_layout.addLayout(toolbar_layout)
    
    def create_navigation_panel(self, parent_splitter):
        """Create navigation panel"""
        nav_widget = QtWidgets.QWidget()
        nav_widget.setMinimumWidth(150)  # Minimum width
        nav_layout = QtWidgets.QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create vertical splitter for navigation tabs and collection/filter tabs
        self.nav_splitter = QtWidgets.QSplitter(Qt.Vertical)
        self.nav_splitter.setHandleWidth(3)
        # Ghost line mode for cleaner rendering
        self.nav_splitter.setOpaqueResize(False)
        self.nav_splitter.setChildrenCollapsible(False)
        self.nav_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #555;
            }
            QSplitter::handle:hover {
                background-color: #777;
            }
        """)
        
        # Top tab widget - Favourites & Folders
        self.nav_top_tabs = QtWidgets.QTabWidget()
        self.nav_top_tabs.setMovable(True)  # Enable drag & drop tab reordering
        self.nav_top_tabs.tabBar().tabMoved.connect(self.on_nav_top_tabs_moved)
        
        # Store tab widgets with identifiers for restoration
        self.nav_top_tab_widgets = {}
        
        # Favourites tab
        fav_widget = QtWidgets.QWidget()
        fav_layout = QtWidgets.QVBoxLayout(fav_widget)
        fav_layout.setContentsMargins(5, 5, 5, 5)
        
        # Search box for favorites
        self.favorites_search = QtWidgets.QLineEdit()
        self.favorites_search.setPlaceholderText("Search favorites...")
        self.favorites_search.setClearButtonEnabled(True)
        self.favorites_search.textChanged.connect(self.filter_favorites)
        fav_layout.addWidget(self.favorites_search)
        
        self.favorites_list = QtWidgets.QListWidget()
        self.favorites_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)  # Enable multi-select
        self.favorites_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.favorites_list.customContextMenuRequested.connect(self.show_favorites_context_menu)
        
        # Maya-style selection color (same as collections)
        self.favorites_list.setStyleSheet("""
            QListWidget::item:selected {
                background-color: #4b7daa;
                color: white;
            }
            QListWidget::item:hover {
                background-color: rgba(75, 125, 170, 0.3);
            }
        """)
        
        # Set custom delegate for colored bar
        self.favorites_color_delegate = FavoritesColorBarDelegate(self, self.favorites_list)
        self.favorites_list.setItemDelegate(self.favorites_color_delegate)
        
        # Install resize event filter to update elided text dynamically
        self.favorites_list.viewport().installEventFilter(self)
        
        # Enable drag-and-drop reordering with middle mouse button (Maya style)
        self.favorites_list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.favorites_list.setDefaultDropAction(Qt.MoveAction)
        self.favorites_list.setDragEnabled(False)  # Disabled by default, enabled on MMB press
        
        # Install event filter for middle mouse button drag
        self.favorites_list.viewport().installEventFilter(self)
        
        # Connect model change to save new order
        self.favorites_list.model().rowsMoved.connect(self.on_favorites_reordered)
        
        fav_layout.addWidget(self.favorites_list)
        self.nav_top_tab_widgets["Favourites"] = fav_widget
        
        # Folders tab - folder tree navigation
        folders_widget = QtWidgets.QWidget()
        folders_layout = QtWidgets.QVBoxLayout(folders_widget)
        folders_layout.setContentsMargins(5, 5, 5, 5)
        
        # Create folder tree view
        self.folder_tree = QtWidgets.QTreeView()
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setAnimated(True)
        self.folder_tree.setIndentation(20)
        self.folder_tree.setSortingEnabled(True)
        
        # Create file system model for folder tree
        self.folder_model = QtWidgets.QFileSystemModel()
        self.folder_model.setRootPath("")
        self.folder_model.setFilter(QtCore.QDir.AllDirs | QtCore.QDir.NoDotAndDotDot)
        
        self.folder_tree.setModel(self.folder_model)
        
        # Sort alphabetically (A→Z) by name column
        self.folder_tree.sortByColumn(0, Qt.AscendingOrder)
        
        # Hide all columns except name
        for i in range(1, self.folder_model.columnCount()):
            self.folder_tree.hideColumn(i)
        
        # Set root to "This PC" (empty string shows all drives)
        self.folder_tree.setRootIndex(self.folder_model.index(""))
        
        # Connect folder tree selection
        self.folder_tree.clicked.connect(self.navigate_from_folder_tree)
        
        folders_layout.addWidget(self.folder_tree)
        self.nav_top_tab_widgets["Folders"] = folders_widget
        
        # Restore tab order or add in default order
        nav_top_order = self.config.config.get("nav_top_tabs_order", ["Favourites", "Folders"])
        for tab_name in nav_top_order:
            if tab_name in self.nav_top_tab_widgets:
                self.nav_top_tabs.addTab(self.nav_top_tab_widgets[tab_name], tab_name)
        
        self.nav_splitter.addWidget(self.nav_top_tabs)
        
        # Bottom tab widget - Collections & Advanced Filters
        self.nav_tabs = QtWidgets.QTabWidget()
        self.nav_tabs.setMovable(True)  # Enable drag & drop tab reordering
        self.nav_tabs.tabBar().tabMoved.connect(self.on_nav_tabs_moved)
        
        # Store tab widgets with identifiers for restoration
        self.nav_tab_widgets = {}
        
        # Collections tab - Initialize Collections Manager and Panel
        from .asset_collections import CollectionManager
        from .collections_panel import CollectionsPanel
        
        self.collection_manager = CollectionManager()  # Auto-loads from ~/.ddContentBrowser/collections.json
        self.collections_panel = CollectionsPanel(self.collection_manager)
        
        # Connect signals
        self.collections_panel.collection_selected.connect(self.on_collection_selected)
        self.collections_panel.collection_cleared.connect(self.on_collection_cleared)
        
        self.nav_tab_widgets["Collections"] = self.collections_panel
        
        # Advanced Filters tab - will be initialized later in setup_connections
        # (after file_model is created)
        self.advanced_filters_widget = QtWidgets.QWidget()
        self.advanced_filters_layout = QtWidgets.QVBoxLayout(self.advanced_filters_widget)
        self.advanced_filters_layout.setContentsMargins(5, 5, 5, 5)
        self.nav_tab_widgets["Advanced Filters"] = self.advanced_filters_widget
        
        # Restore tab order or add in default order
        nav_tabs_order = self.config.config.get("nav_tabs_order", ["Collections", "Advanced Filters"])
        for tab_name in nav_tabs_order:
            if tab_name in self.nav_tab_widgets:
                self.nav_tabs.addTab(self.nav_tab_widgets[tab_name], tab_name)
        
        self.nav_splitter.addWidget(self.nav_tabs)
        
        # Restore nav splitter position or set default
        nav_splitter_pos = self.config.config.get("nav_splitter_position", None)
        if nav_splitter_pos:
            state_bytes = QtCore.QByteArray.fromBase64(nav_splitter_pos.encode())
            self.nav_splitter.restoreState(state_bytes)
        else:
            # Default: 60% navigation tabs (top), 40% collection/filter tabs (bottom)
            self.nav_splitter.setSizes([300, 200])
        
        # Connect nav splitter moved signal
        self.nav_splitter.splitterMoved.connect(self.on_nav_splitter_moved)
        
        nav_layout.addWidget(self.nav_splitter)
        
        parent_splitter.addWidget(nav_widget)
        
        # Fill favorites and initialize recent menu
        self.update_favorites_list()
        self.update_recent_menu()  # Initialize recent dropdown menu
    
    def create_browser_panel(self, parent_splitter):
        """Create browser panel"""
        browser_widget = QtWidgets.QWidget()
        browser_layout = QtWidgets.QVBoxLayout(browser_widget)
        
        # View options toolbar
        view_toolbar = QtWidgets.QHBoxLayout()
        
        # View mode toggle
        self.view_mode_group = QtWidgets.QButtonGroup()
        self.list_mode_btn = QtWidgets.QPushButton("☰ List")
        self.grid_mode_btn = QtWidgets.QPushButton("⊞ Grid")
        self.list_mode_btn.setCheckable(True)
        self.grid_mode_btn.setCheckable(True)
        self.list_mode_btn.setChecked(True)
        self.view_mode_group.addButton(self.list_mode_btn, 0)
        self.view_mode_group.addButton(self.grid_mode_btn, 1)
        
        view_toolbar.addWidget(QtWidgets.QLabel("View:"))
        view_toolbar.addWidget(self.list_mode_btn)
        view_toolbar.addWidget(self.grid_mode_btn)
        
        # Thumbnail size slider
        view_toolbar.addWidget(QtWidgets.QLabel("Size:"))
        self.size_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.size_slider.setMinimum(16)  # Extended down to 16 for compact list view
        self.size_slider.setMaximum(256)
        # Load saved thumbnail sizes from config (separate for grid and list)
        self.grid_thumbnail_size = self.config.config.get("grid_thumbnail_size", 128)
        self.list_thumbnail_size = self.config.config.get("list_thumbnail_size", 24)  # Default 24px for list
        # Start with appropriate size based on saved view mode
        saved_view_mode = self.config.config.get("view_mode", "grid")
        initial_size = self.grid_thumbnail_size if saved_view_mode == "grid" else self.list_thumbnail_size
        self.size_slider.setValue(initial_size)
        self.size_slider.setMaximumWidth(150)
        self.size_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.size_slider.setTickInterval(32)  # More tick marks
        view_toolbar.addWidget(self.size_slider)
        
        self.size_label = QtWidgets.QLabel(str(initial_size))
        self.size_label.setMinimumWidth(30)
        view_toolbar.addWidget(self.size_label)
        
        # Include subfolders checkbox (moved here from top toolbar)
        view_toolbar.addWidget(QtWidgets.QLabel("  |  "))  # Separator
        self.include_subfolders_checkbox = QtWidgets.QCheckBox("Show Files from Subfolders")
        self.include_subfolders_checkbox.setToolTip("Show files from all subfolders recursively")
        self.include_subfolders_checkbox.setChecked(False)
        view_toolbar.addWidget(self.include_subfolders_checkbox)
        
        # Thumbnail toggle
        view_toolbar.addWidget(QtWidgets.QLabel("  |  "))  # Separator
        self.thumbnails_enabled_checkbox = QtWidgets.QCheckBox("Thumbnails")
        self.thumbnails_enabled_checkbox.setChecked(self.config.config.get("thumbnails_enabled", True))
        self.thumbnails_enabled_checkbox.setToolTip("Enable/disable thumbnail generation and loading")
        view_toolbar.addWidget(self.thumbnails_enabled_checkbox)
        
        # Sequence mode toggle checkbox (will be initialized later from settings)
        self.sequence_mode_checkbox = QtWidgets.QCheckBox("Sequences")
        self.sequence_mode_checkbox.setToolTip("Group image sequences into single items\n(e.g. render_0001-0120.jpg → render_####.jpg)")
        view_toolbar.addWidget(self.sequence_mode_checkbox)
        
        # Spacer before Load More button
        view_toolbar.addStretch()
        
        # Load More button (initially hidden) - placed at far right of view toolbar
        if PYSIDE_VERSION == 6:
            from PySide6.QtWidgets import QPushButton
        else:
            from PySide2.QtWidgets import QPushButton
        
        self.load_more_btn = QPushButton("Load More (+10k)")
        self.load_more_btn.clicked.connect(self.on_load_more_clicked)
        self.load_more_btn.setVisible(False)
        self.load_more_btn.setToolTip("Load 10,000 more files from subfolders")
        view_toolbar.addWidget(self.load_more_btn)
        
        browser_layout.addLayout(view_toolbar)
        
        # Enhanced Search Bar with Clear Filters button
        from .widgets import EnhancedSearchBar
        search_layout = QtWidgets.QHBoxLayout()
        
        self.search_bar = EnhancedSearchBar()
        search_layout.addWidget(self.search_bar)
        
        # Add stretch to keep search bar size consistent
        search_layout.addStretch()
        
        # Clear Filters button (fixed position, visibility controlled)
        self.clear_filters_btn = QtWidgets.QPushButton("✕ Clear Filters")
        self.clear_filters_btn.setFixedWidth(120)  # Fixed width instead of maximum
        self.clear_filters_btn.setVisible(False)  # Initially hidden
        self.clear_filters_btn.clicked.connect(self.clear_all_filters)
        self.clear_filters_btn.setStyleSheet("""
            QPushButton {
                background-color: #4b7daa;
                border: none;
                border-radius: 3px;
                padding: 5px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a8db8;
            }
            QPushButton:pressed {
                background-color: #3a6d9a;
            }
        """)
        search_layout.addWidget(self.clear_filters_btn)
        
        browser_layout.addLayout(search_layout)
        
        # Sort Header (only visible in List mode)
        self.sort_header = self.create_sort_header()
        browser_layout.addWidget(self.sort_header)
        
        # File list with custom delegate - Use MayaStyleListView
        self.file_model = FileSystemModel()
        self.file_list = MayaStyleListView()
        self.file_list.setModel(self.file_model)
        self.file_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.file_list.setResizeMode(QtWidgets.QListView.Adjust)
        # CRITICAL: UniformItemSizes=True for MUCH better splitter performance
        # Treats all items as same size = no individual calculations = 6x faster!
        self.file_list.setUniformItemSizes(True)
        self.file_list.setSpacing(5)
        
        # Enable drag and drop
        # LEFT BUTTON (default) = Box selection (rubber band drag)
        # ALT + LEFT BUTTON = Standard Maya file drag-and-drop
        # CTRL/SHIFT + CLICK = Selection modifiers (Qt built-in)
        # MIDDLE BUTTON = Batch import dialog (handled in MayaStyleListView)
        self.file_list.setDragEnabled(False)  # Disabled by default, enabled when Alt pressed
        self.file_list.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)  # Only drag, no drop into list itself
        self.file_list.setAcceptDrops(True)
        self.file_list.setDropIndicatorShown(True)
        self.file_list.setDefaultDropAction(Qt.CopyAction)
        
        # Scrolling mode - use ScrollPerItem for better performance with many files
        # ScrollPerPixel is smoother but MUCH slower with large lists (repaints every pixel)
        self.file_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerItem)
        self.file_list.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerItem)
        
        # Enable context menu
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_context_menu)
        
        # Configure tooltips for better display
        self.file_list.setMouseTracking(True)
        
        # Create and set custom delegate with appropriate thumbnail size based on saved view mode
        saved_view_mode = self.config.config.get("view_mode", "grid")
        initial_size = self.grid_thumbnail_size if saved_view_mode == "grid" else self.list_thumbnail_size
        self.thumbnail_delegate = ThumbnailDelegate(self.memory_cache, thumbnail_size=initial_size)
        self.thumbnail_delegate.set_browser(self)  # Pass browser reference for column widths
        self.file_list.setItemDelegate(self.thumbnail_delegate)
        
        # Install event filter for Ctrl+Scroll zoom on both file_list and viewport
        self.file_list.installEventFilter(self)
        self.file_list.viewport().installEventFilter(self)
        
        browser_layout.addWidget(self.file_list)
        
        # Info bar (selection info + controls hint)
        info_bar_layout = QtWidgets.QHBoxLayout()
        info_bar_layout.setContentsMargins(5, 2, 5, 2)
        info_bar_layout.setSpacing(10)
        
        # Left: Selection info
        self.selection_info_label = QtWidgets.QLabel("")
        self.selection_info_label.setStyleSheet("color: #aaa; font-size: 11px; padding: 2px;")
        info_bar_layout.addWidget(self.selection_info_label)
        
        info_bar_layout.addStretch()
        
        # Right: Controls hint
        if MAYA_AVAILABLE:
            controls_hint = QtWidgets.QLabel("💡 LMB: Selection, Space: Quick View, Alt+LMB+Drag: Standard Import, MMB+Drag: Batch Import")
        else:
            controls_hint = QtWidgets.QLabel("💡 LMB: Selection, Space: Quick View, Alt+LMB+Drag: Standard Import")
        controls_hint.setStyleSheet("color: #888; font-size: 11px; padding: 2px;")
        info_bar_layout.addWidget(controls_hint)
        
        browser_layout.addLayout(info_bar_layout)
        
        # Action buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.import_btn = QtWidgets.QPushButton("Import")
        self.reference_btn = QtWidgets.QPushButton("Reference")
        self.open_btn = QtWidgets.QPushButton("Open")
        self.add_favorite_btn = QtWidgets.QPushButton("Add to Favorites")
        
        button_layout.addWidget(self.import_btn)
        button_layout.addWidget(self.reference_btn)
        button_layout.addWidget(self.open_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.add_favorite_btn)
        
        browser_layout.addLayout(button_layout)
        
        # Initialize visual feedback for filters
        QtCore.QTimer.singleShot(0, self.update_filter_visual_feedback)
        
        parent_splitter.addWidget(browser_widget)
    
    def create_sort_header(self):
        """Create sort header for list view"""
        header_widget = SortHeaderWidget(self)
        header_widget.setMaximumHeight(25)
        
        # Use QSplitter for resizable columns
        self.header_splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.header_splitter.setHandleWidth(3)
        # Ghost line mode for cleaner rendering
        self.header_splitter.setOpaqueResize(False)
        self.header_splitter.setChildrenCollapsible(False)
        self.header_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #555;
            }
            QSplitter::handle:hover {
                background-color: #777;
            }
        """)
        
        # Style for header buttons
        header_style = """
            QPushButton {
                background-color: #3a3a3a;
                border: 1px solid #555;
                padding: 3px 8px;
                text-align: left;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
        """
        
        # Name column
        self.sort_name_btn = QtWidgets.QPushButton("Name")
        self.sort_name_btn.setStyleSheet(header_style)
        self.sort_name_btn.setToolTip("Left click to sort\nRight click to filter")
        self.sort_name_btn.clicked.connect(lambda: self.toggle_sort("name"))
        self.header_splitter.addWidget(self.sort_name_btn)
        
        # Type column
        self.sort_type_btn = QtWidgets.QPushButton("Type")
        self.sort_type_btn.setStyleSheet(header_style)
        self.sort_type_btn.setToolTip("Left click to sort\nRight click to filter")
        self.sort_type_btn.clicked.connect(lambda: self.toggle_sort("type"))
        self.header_splitter.addWidget(self.sort_type_btn)
        
        # Size column
        self.sort_size_btn = QtWidgets.QPushButton("Size")
        self.sort_size_btn.setStyleSheet(header_style)
        self.sort_size_btn.setToolTip("Left click to sort\nRight click to filter")
        self.sort_size_btn.clicked.connect(lambda: self.toggle_sort("size"))
        self.header_splitter.addWidget(self.sort_size_btn)
        
        # Date column
        self.sort_date_btn = QtWidgets.QPushButton("Modified")
        self.sort_date_btn.setStyleSheet(header_style)
        self.sort_date_btn.setToolTip("Left click to sort\nRight click to filter")
        self.sort_date_btn.clicked.connect(lambda: self.toggle_sort("date"))
        self.header_splitter.addWidget(self.sort_date_btn)
        
        # Set initial sizes (40%, 20%, 20%, 20%)
        self.header_splitter.setSizes([400, 200, 200, 200])
        
        # Connect splitter moved signal to refresh list view
        self.header_splitter.splitterMoved.connect(self.on_column_width_changed)
        
        # Add splitter to header widget
        header_layout = QtWidgets.QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 0, 5, 0)
        header_layout.setSpacing(0)
        header_layout.addWidget(self.header_splitter)
        
        # Don't call update_sort_indicators here - will be called after file_model is created
        return header_widget
    
    def toggle_sort(self, column):
        """Toggle sort order for column"""
        if self.file_model.sort_column == column:
            # Toggle ascending/descending
            self.file_model.setSortOrder(column, not self.file_model.sort_ascending)
        else:
            # New column, sort ascending
            self.file_model.setSortOrder(column, True)
        
        self.update_sort_indicators()
        
        # Request thumbnails for newly visible items after sorting
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
    
    def update_sort_indicators(self):
        """Update sort indicator arrows on header buttons"""
        # Clear all indicators
        self.sort_name_btn.setText("Name")
        self.sort_type_btn.setText("Type")
        self.sort_size_btn.setText("Size")
        self.sort_date_btn.setText("Modified")
        
        # Add arrow to current sort column
        arrow = " ▲" if self.file_model.sort_ascending else " ▼"
        
        if self.file_model.sort_column == "name":
            self.sort_name_btn.setText("Name" + arrow)
        elif self.file_model.sort_column == "type":
            self.sort_type_btn.setText("Type" + arrow)
        elif self.file_model.sort_column == "size":
            self.sort_size_btn.setText("Size" + arrow)
        elif self.file_model.sort_column == "date":
            self.sort_date_btn.setText("Modified" + arrow)
    
    def setup_connections(self):
        """Setup signal-slot connections"""
        # Toolbar connections
        self.back_btn.clicked.connect(self.navigate_back)
        self.forward_btn.clicked.connect(self.navigate_forward)
        self.browse_btn.clicked.connect(self.browse_for_folder)
        self.breadcrumb.path_clicked.connect(self.navigate_to_path)
        self.preview_toggle_btn.clicked.connect(self.toggle_preview_panel)
        self.sequence_mode_checkbox.stateChanged.connect(self.toggle_sequence_mode)
        self.include_subfolders_checkbox.stateChanged.connect(self.on_subfolder_toggle)
        
        # Search bar connections
        self.search_bar.textChanged.connect(self.on_search_text_changed)
        self.search_bar.optionsChanged.connect(self.on_search_options_changed)
        self.search_bar.searchRequested.connect(self.on_subfolder_search_requested)
        self.search_bar.searchCleared.connect(self.on_search_cleared)
        
        # View mode connections
        self.list_mode_btn.clicked.connect(lambda: self.set_view_mode(False))
        self.grid_mode_btn.clicked.connect(lambda: self.set_view_mode(True))
        self.size_slider.valueChanged.connect(self.on_size_slider_changed)
        self.thumbnails_enabled_checkbox.stateChanged.connect(self.on_thumbnails_toggle)
        
        # Navigation connections
        # self.recent_list.itemClicked.connect(self.navigate_from_recent)  # Removed - now using dropdown menu
        self.favorites_list.itemClicked.connect(self.navigate_from_favorites)
        
        # File list connections
        self.file_list.doubleClicked.connect(self.on_item_double_clicked)
        self.file_list.selectionModel().selectionChanged.connect(self.on_selection_changed)
        
        # Model change connections - trigger thumbnail loading when filters change
        self.file_model.modelReset.connect(self.on_model_reset)
        
        # Progress connections
        self.file_model.searchProgress.connect(self.on_search_progress)
        self.file_model.loadProgress.connect(self.on_load_progress)
        self.file_model.limitReached.connect(self.on_limit_reached)
        
        # Scrollbar connection - load thumbnails when scrolling
        scrollbar = self.file_list.verticalScrollBar()
        if scrollbar:
            scrollbar.valueChanged.connect(self.on_scroll_changed)
        
        # Action buttons
        self.import_btn.clicked.connect(self.import_selected_file)
        self.reference_btn.clicked.connect(self.reference_selected_file)
        self.open_btn.clicked.connect(self.open_selected_files)
        self.add_favorite_btn.clicked.connect(self.add_current_to_favorites)
        
        # Initialize sort indicators now that file_model exists
        self.update_sort_indicators()
        
        # Load search settings from settings manager and apply to search bar
        case_sensitive = self.settings_manager.get("filters", "case_sensitive_search", False)
        regex_enabled = self.settings_manager.get("filters", "regex_search", False)
        search_subfolders = self.settings_manager.get("filters", "search_in_subfolders", False)
        self.file_model.case_sensitive_search = case_sensitive
        self.file_model.regex_search = regex_enabled
        self.file_model.search_in_subfolders = search_subfolders
        self.search_bar.set_case_sensitive(case_sensitive)
        self.search_bar.set_regex_enabled(regex_enabled)
        self.search_bar.set_subfolders_enabled(search_subfolders)
        
        # Initialize Advanced Filters panel now that file_model exists
        self.init_advanced_filters()
        
        # Install event filter for Quick View (Space key)
        self.file_list.installEventFilter(self)
        
        # Restore sort and filter state from last session
        self.restore_browser_state()
    
    def init_advanced_filters(self):
        """Initialize Advanced Filters panel after file_model is created"""
        # Create the advanced filters panel (V2 - Adobe Bridge style)
        self.advanced_filters_panel = AdvancedFiltersPanelV2(self.file_model, self.settings_manager)
        self.advanced_filters_panel.filters_changed.connect(self.on_advanced_filters_changed)
        self.advanced_filters_panel.filters_cleared.connect(self.on_advanced_filters_cleared)
        self.advanced_filters_panel.filters_activated.connect(self.on_advanced_filters_activated)
        
        # Add to layout
        self.advanced_filters_layout.addWidget(self.advanced_filters_panel)
        
        if DEBUG_MODE:
            print("[Browser] Advanced Filters V2 panel initialized")
    
    def on_search_text_changed(self, text):
        """Handle search text change (only called when Subfolders is OFF - real-time search)"""
        # CLEAR thumbnail generator queue when search changes
        if hasattr(self, 'thumbnail_generator'):
            self.thumbnail_generator.clear_queue()
        
        # If clearing search, clear progress display
        if not text:
            self.search_bar.clear_search_progress()
        
        self.file_model.setFilterText(text)
        # Update match count (will be called after model refresh)
        QTimer.singleShot(50, self.update_search_match_count)
        # Request thumbnails for new filtered results
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
    
    def on_subfolder_search_requested(self):
        """Handle manual subfolder search request (search button clicked or Enter pressed)"""
        # Get search text
        search_text = self.search_bar.get_text()
        if not search_text:
            # Empty search - clear any existing search and return to folder view
            if self.file_model.filter_text:
                # Had search before, now clearing it
                self.file_model.setFilterText("")
                self.safe_show_status("Search cleared - showing current folder")
                QTimer.singleShot(50, self.update_search_match_count)
                QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
            else:
                # Already no search
                self.safe_show_status("Enter search text first")
            return
        
        # Show initial progress
        self.search_bar.set_search_progress(0, 0)
        
        # Trigger search with current text
        self.file_model.setFilterText(search_text)
        
        # Update match count after search completes
        QTimer.singleShot(50, self.update_search_match_count)
        # Request thumbnails for results
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
    
    def on_search_cleared(self):
        """Handle search clear button click - reset to current folder"""
        # DON'T reset subfolders checkbox - user might want it for next search
        # Just clear the search and return to current folder view
        
        # Interrupt any ongoing search BEFORE calling setFilterText
        # This must happen first to avoid nested beginResetModel() calls
        self.file_model.interrupt_search()
        
        # Small delay to let the interrupt take effect
        QTimer.singleShot(50, self._finish_search_clear)
    
    def _finish_search_clear(self):
        """Finish clearing search after interrupt has taken effect"""
        # CLEAR thumbnail generator queue when clearing search
        if hasattr(self, 'thumbnail_generator'):
            self.thumbnail_generator.clear_queue()
        
        # Clear filter text and force refresh to current folder
        self.file_model.setFilterText("")
        # Clear progress
        self.search_bar.clear_search_progress()
        # Update UI
        QTimer.singleShot(50, self.update_search_match_count)
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
        self.safe_show_status("Search cleared - showing current folder")
    
    def on_search_progress(self, scanned, matches):
        """Handle search progress updates from file model"""
        self.search_bar.set_search_progress(scanned, matches)
    
    def on_load_progress(self, loaded, scanned):
        """Handle recursive loading progress updates (include subfolders mode)"""
        # Set flag to prevent thumbnail progress from overwriting this
        self._loading_in_progress = True
        # Hide Load More button while loading
        self.load_more_btn.setVisible(False)
        # Show progress in status bar
        self.safe_show_status(f"⏳ Loading files... {loaded} loaded from {scanned} scanned")
    
    def on_limit_reached(self, loaded, scanned):
        """Handle limit reached signal - show Load More button"""
        # Set flag to prevent thumbnail progress from overwriting the message
        self._limit_reached_shown = True
        # Show the Load More button
        self.load_more_btn.setVisible(True)
        self.safe_show_status(f"⚠️ Limit reached: {loaded} files loaded. Click 'Load More' to continue.")
    
    def on_load_more_clicked(self):
        """Handle Load More button click"""
        # Hide the button temporarily
        self.load_more_btn.setVisible(False)
        # Clear the limit flag
        self._limit_reached_shown = False
        # Load more files
        self.file_model.load_more(increment=10000)
        
        # Check if limit was reached again after loading
        if self.file_model.limit_reached:
            self.load_more_btn.setVisible(True)
            self._limit_reached_shown = True
            file_count = len(self.file_model.assets)
            self.safe_show_status(f"⚠️ Limit reached: {file_count} files loaded. Click 'Load More' to continue.")
        else:
            file_count = len(self.file_model.assets)
            self.safe_show_status(f"✓ Loaded {file_count} files from subfolders")
    
    def on_search_options_changed(self):
        """Handle search option (case/regex/subfolders) toggle"""
        self.file_model.case_sensitive_search = self.search_bar.is_case_sensitive()
        self.file_model.regex_search = self.search_bar.is_regex_enabled()
        
        # Check if subfolders setting changed
        old_subfolders = self.file_model.search_in_subfolders
        new_subfolders = self.search_bar.is_subfolders_enabled()
        subfolders_changed = old_subfolders != new_subfolders
        
        self.file_model.search_in_subfolders = new_subfolders
        
        # Save to settings
        self.settings_manager.set("filters", "case_sensitive_search", self.search_bar.is_case_sensitive())
        self.settings_manager.set("filters", "regex_search", self.search_bar.is_regex_enabled())
        self.settings_manager.set("filters", "search_in_subfolders", new_subfolders)
        self.settings_manager.save()
        
        # Refresh search with new options
        # Use force=True if subfolders setting changed to bypass cache
        if self.search_bar.get_text():
            # Has search text - refresh with force if subfolders changed
            if subfolders_changed:
                # Subfolders changed - need full model reset
                self.file_model.beginResetModel()
                self.file_model.refresh(force=True)
                self.file_model.endResetModel()
            else:
                # Just options changed - regular refresh
                self.file_model.refresh()
            QTimer.singleShot(50, self.update_search_match_count)
            QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
        elif subfolders_changed and old_subfolders and not new_subfolders:
            # No search text, but subfolders was just disabled (going from subfolder search to normal)
            # Force refresh to return to current folder view
            self.file_model.beginResetModel()
            self.file_model.refresh(force=True)
            self.file_model.endResetModel()
            QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
    
    def update_search_match_count(self):
        """Update search match count display"""
        # Clear progress indicator when count is finalized
        self.search_bar.clear_search_progress()
        
        if self.search_bar.get_text():
            match_count = self.file_model.rowCount()
            total_count = len(self.file_model.assets) if hasattr(self.file_model, 'assets') else 0
            self.search_bar.set_match_count(match_count, total_count)
        else:
            self.search_bar.set_match_count(0, 0)
    
    def clear_search_state(self):
        """Clear all search-related state (call this when navigating away or changing modes)"""
        # Clear search input
        if self.search_bar.search_input.text():
            self.search_bar.search_input.clear()
        
        # Clear search progress and match count
        self.search_bar.clear_search_progress()
        self.search_bar.set_match_count(0, 0)
        
        # Clear filter text in model
        # DON'T clear search_in_subfolders - it's a user preference that should persist
        if self.file_model.filter_text:
            self.file_model.filter_text = ""
    
    def on_subfolder_toggle(self, state):
        """Handle include subfolders checkbox toggle"""
        # Handle both PySide2 (int) and PySide6 (enum) properly
        include_subfolders = bool(state == Qt.Checked or state == 2)
        self.file_model.include_subfolders = include_subfolders
        
        # Clear advanced filters when subfolders toggle (asset list will change)
        if hasattr(self, 'advanced_filters_panel'):
            print(f"[Browser] Subfolders toggled to {include_subfolders} - clearing advanced filters")
            self.advanced_filters_panel.refresh()
        
        # Hide Load More button when toggling
        self.load_more_btn.setVisible(False)
        self._limit_reached_shown = False
        
        # Show status message
        if include_subfolders:
            self.safe_show_status("⏳ Loading files from subfolders...")
        else:
            self.safe_show_status("Showing current folder only")
        
        # Refresh the file list with force=True to bypass cache
        # (cache doesn't track include_subfolders state)
        self.file_model.beginResetModel()
        self.file_model.refresh(force=True)
        self.file_model.endResetModel()
        
        # Clear loading flag so thumbnail progress can resume
        self._loading_in_progress = False
        
        # Check if limit was reached and show button
        if self.file_model.limit_reached:
            self.load_more_btn.setVisible(True)
            self._limit_reached_shown = True
        
        # Update status bar with file count
        file_count = len(self.file_model.assets)
        if include_subfolders:
            if self.file_model.limit_reached:
                self.safe_show_status(f"⚠️ Limit reached: {file_count} files loaded. Click 'Load More' to continue.")
            else:
                self.safe_show_status(f"✓ Loaded {file_count} files from subfolders")
        else:
            self.safe_show_status(f"✓ Loaded {file_count} files")
        
        # Request thumbnails for visible items
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
    
    def navigate_to_path(self, path):
        """Navigate to specified path"""
        path = Path(path)
        if not path.exists() or not path.is_dir():
            self.safe_show_status(f"Invalid path: {path}")
            return
        
        # Exit collection mode if active
        if self.file_model.collection_mode:
            self.on_collection_cleared()
        
        # Disable subfolder mode when navigating to new path
        if self.include_subfolders_checkbox.isChecked():
            self.include_subfolders_checkbox.setChecked(False)
            self.file_model.include_subfolders = False
        
        # Clear all search state (input, progress, match count)
        self.clear_search_state()
        
        # Clear all filters when navigating to new path
        self.file_model.clearFilters()
        
        # Update UI to reflect cleared filters
        self.update_filter_visual_feedback()
        
        # Update file watcher to monitor new directory
        self._update_file_watcher(path)
        
        # Add to history if not navigating through history
        if not self.is_navigating_history:
            # Remove forward history if we navigate from middle of history
            if self.history_index < len(self.history) - 1:
                self.history = self.history[:self.history_index + 1]
            
            # Add new path to history
            path_str = str(path)
            if not self.history or self.history[-1] != path_str:
                self.history.append(path_str)
                self.history_index = len(self.history) - 1
        
        self.file_model.setPath(path)
        self.breadcrumb.set_path(path)
        
        # CLEAR thumbnail generator queue when navigating to new folder
        # This prevents generating thumbnails for old folder after navigation
        if hasattr(self, 'thumbnail_generator'):
            self.thumbnail_generator.clear_queue()
        
        # Reset thumbnail progress counters for new folder
        if hasattr(self, 'thumbnail_generator'):
            self.thumbnail_generator.processed_count = 0
            self.thumbnail_generator.total_count = 0
        
        # Reset cache statistics for new folder
        self.cache_hits = 0
        self.generations = 0
        
        # Clear preview panel when navigating to new folder
        if hasattr(self, 'preview_panel'):
            self.preview_panel.show_empty_state()
        
        # Clear favorites selection when navigating (unless navigating FROM favorites)
        if hasattr(self, 'favorites_list') and not getattr(self, 'is_navigating_from_favorites', False):
            self.favorites_list.clearSelection()
        
        # Sync folder tree to current path
        if hasattr(self, 'folder_tree') and hasattr(self, 'folder_model'):
            folder_index = self.folder_model.index(str(path))
            if folder_index.isValid():
                self.folder_tree.setCurrentIndex(folder_index)
                self.folder_tree.scrollTo(folder_index)
                # Expand parent folders to show current path
                parent_index = folder_index.parent()
                while parent_index.isValid():
                    self.folder_tree.expand(parent_index)
                    parent_index = parent_index.parent()
        
        # Clear advanced filters for new directory (categories will be rebuilt on manual analyze)
        if hasattr(self, 'advanced_filters_panel'):
            self.advanced_filters_panel.refresh()
        
        # Only update recent list if not navigating FROM recent list
        if not self.is_navigating_from_recent:
            self.config.add_recent_path(path)
            self.update_recent_list()
            self.update_recent_menu()  # Update dropdown menu
        
        self.config.config["last_path"] = str(path)
        self.config.save_config()
        self.update_navigation_buttons()
        self.safe_show_status(f"Loaded: {path}")
        
        # Request thumbnails for visible items
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
    
    def navigate_back(self):
        """Navigate to previous path in history (or exit collection view if active)"""
        # If in collection mode, exit it instead of navigating history
        if self.file_model.collection_mode:
            self.on_collection_cleared()
            return
        
        if self.history_index > 0:
            self.is_navigating_history = True
            self.history_index -= 1
            path = self.history[self.history_index]
            
            # Clear search state when navigating back
            self.clear_search_state()
            
            # Disable subfolder mode when navigating
            if self.include_subfolders_checkbox.isChecked():
                self.include_subfolders_checkbox.setChecked(False)
                self.file_model.include_subfolders = False
            
            # Clear filters to ensure clean state
            self.file_model.clearFilters()
            
            # Force refresh to avoid cached search results
            self.file_model.setPath(Path(path))
            self.file_model.refresh(force=True)
            
            self.breadcrumb.set_path(path)
            self.update_navigation_buttons()
            self.safe_show_status(f"Back: {path}")
            
            self.is_navigating_history = False
    
    def navigate_forward(self):
        """Navigate to next path in history"""
        if self.history_index < len(self.history) - 1:
            self.is_navigating_history = True
            self.history_index += 1
            path = self.history[self.history_index]
            
            # Clear search state when navigating forward
            self.clear_search_state()
            
            # Disable subfolder mode when navigating
            if self.include_subfolders_checkbox.isChecked():
                self.include_subfolders_checkbox.setChecked(False)
                self.file_model.include_subfolders = False
            
            # Clear filters to ensure clean state
            self.file_model.clearFilters()
            
            # Force refresh to avoid cached search results
            self.file_model.setPath(Path(path))
            self.file_model.refresh(force=True)
            
            self.breadcrumb.set_path(path)
            self.update_navigation_buttons()
            self.safe_show_status(f"Forward: {path}")
            
            self.is_navigating_history = False
    
    def update_navigation_buttons(self):
        """Update back/forward button states"""
        # Back button is enabled if in collection mode OR if there's history to go back to
        self.back_btn.setEnabled(self.file_model.collection_mode or self.history_index > 0)
        self.forward_btn.setEnabled(self.history_index < len(self.history) - 1)
    
    def set_view_mode(self, icon_mode):
        """Switch between list and grid view modes"""
        self.thumbnail_delegate.set_view_mode(icon_mode)
        
        if icon_mode:
            # Grid mode
            self.file_list.setViewMode(QtWidgets.QListView.IconMode)
            self.file_list.setFlow(QtWidgets.QListView.LeftToRight)
            self.file_list.setWrapping(True)
            # Allow drag but prevent item repositioning in grid
            # Use Snap movement - allows drag-and-drop but items snap back to grid positions
            self.file_list.setMovement(QtWidgets.QListView.Snap)
            self.size_slider.setEnabled(True)
            # Show sort header in grid mode too (user requested)
            self.sort_header.show()
            
            # Load grid thumbnail size and update slider
            size = self.grid_thumbnail_size
            self.size_slider.blockSignals(True)
            self.size_slider.setValue(size)
            self.size_slider.blockSignals(False)
            self.size_label.setText(str(size))
            
            # Update delegate and icon size
            self.thumbnail_delegate.set_thumbnail_size(size)
            self.thumbnail_size = size
            self.icon_size = QtCore.QSize(size, size)
            self.file_list.setIconSize(self.icon_size)
            
            # Set grid spacing
            spacing = max(5, int(size * 0.08))
            self.file_list.setSpacing(spacing)
            self.file_list.setGridSize(QtCore.QSize(size + spacing * 2, size + spacing * 2 + 20))
        else:
            # List mode
            self.file_list.setViewMode(QtWidgets.QListView.ListMode)
            self.file_list.setFlow(QtWidgets.QListView.TopToBottom)
            self.file_list.setWrapping(False)
            self.size_slider.setEnabled(True)  # Enable slider in list mode too
            # Sort header visible in list mode
            self.sort_header.show()
            
            # Load list thumbnail size and update slider
            size = self.list_thumbnail_size
            self.size_slider.blockSignals(True)
            self.size_slider.setValue(size)
            self.size_slider.blockSignals(False)
            self.size_label.setText(str(size))
            
            # Update delegate and icon size
            self.thumbnail_delegate.set_thumbnail_size(size)
            self.thumbnail_size = size
            self.icon_size = QtCore.QSize(size, size)
            self.file_list.setIconSize(self.icon_size)
            
            # Compact spacing for list mode
            self.file_list.setSpacing(0)
            # Reset grid size (not used in list mode)
            self.file_list.setGridSize(QtCore.QSize())
            # Trigger layout update
            self.file_list.scheduleDelayedItemsLayout()
        
        # Save view mode to config
        self.config.config["view_mode"] = "grid" if icon_mode else "list"
        self.config.save_config()
        
        # Schedule deferred update instead of immediate refresh (faster)
        self.file_list.scheduleDelayedItemsLayout()
        self.safe_show_status(f"View mode: {'Grid' if icon_mode else 'List'}")
        
        # Request thumbnails for newly visible items after view mode change
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
    
    def on_size_slider_changed(self, value):
        """Handle thumbnail size slider change"""
        # Save current scroll position - priority: 1) hovered item, 2) center item, 3) first visible
        anchor_index = None
        
        if self.file_list.model() and self.file_list.model().rowCount() > 0:
            # 1. Try to get item under cursor (hovered)
            cursor_pos = self.file_list.viewport().mapFromGlobal(QtGui.QCursor.pos())
            anchor_index = self.file_list.indexAt(cursor_pos)
            
            # 2. If no hovered item, get center visible item
            if not anchor_index.isValid():
                viewport_rect = self.file_list.viewport().rect()
                center_point = viewport_rect.center()
                anchor_index = self.file_list.indexAt(center_point)
            
            # 3. If still no item (empty center), get first visible item
            if not anchor_index.isValid():
                viewport_rect = self.file_list.viewport().rect()
                for row in range(self.file_list.model().rowCount()):
                    index = self.file_list.model().index(row, 0)
                    item_rect = self.file_list.visualRect(index)
                    if viewport_rect.intersects(item_rect):
                        anchor_index = index
                        break
        
        # Snap to common sizes - added 16 and 24 for compact list view
        if self.grid_mode_btn.isChecked():
            # Grid mode: 32px minimum
            sizes = [32, 64, 96, 128, 160, 192, 224, 256]
        else:
            # List mode: can go down to 16px for very compact view
            sizes = [16, 24, 32, 64, 96, 128, 160, 192, 224, 256]
        
        # Find closest size
        size = min(sizes, key=lambda x: abs(x - value))
        
        # Update label
        self.size_label.setText(str(size))
        
        # Update delegate
        self.thumbnail_delegate.set_thumbnail_size(size)
        
        # Update slider to snapped value (without triggering signal)
        self.size_slider.blockSignals(True)
        self.size_slider.setValue(size)
        self.size_slider.blockSignals(False)
        
        # Update icon size
        self.thumbnail_size = size
        self.icon_size = QtCore.QSize(size, size)
        self.file_list.setIconSize(self.icon_size)
        
        # Update grid size and spacing for grid mode
        if self.grid_mode_btn.isChecked():
            spacing = max(5, int(size * 0.08))
            self.file_list.setSpacing(spacing)
            self.file_list.setGridSize(QtCore.QSize(size + spacing * 2, size + spacing * 2 + 20))
            # Save grid thumbnail size
            self.grid_thumbnail_size = size
            self.config.config["grid_thumbnail_size"] = size
        else:
            # In list mode, reset spacing and grid size to allow row heights to update
            self.file_list.setSpacing(0)
            # Trigger delegate to recalculate row heights
            self.file_list.scheduleDelayedItemsLayout()
            # Save list thumbnail size
            self.list_thumbnail_size = size
            self.config.config["list_thumbnail_size"] = size
        
        # Save config
        self.config.save_config()
        
        # Schedule deferred update instead of immediate refresh (faster)
        self.file_list.scheduleDelayedItemsLayout()
        
        # Restore scroll position after layout update - use center positioning for smooth experience
        if anchor_index and anchor_index.isValid():
            # Use QTimer to ensure layout is complete before scrolling
            QTimer.singleShot(10, lambda: self.file_list.scrollTo(
                anchor_index, 
                QtWidgets.QAbstractItemView.PositionAtCenter
            ))
        
        # Request thumbnails for newly visible items after size change
        # Use timer to debounce rapid size changes (e.g., Ctrl+scroll)
        if hasattr(self, '_size_change_timer'):
            self._size_change_timer.stop()
        
        self._size_change_timer = QTimer()
        self._size_change_timer.setSingleShot(True)
        self._size_change_timer.timeout.connect(self.request_thumbnails_for_visible_items)
        self._size_change_timer.start(200)  # Wait 200ms after size change stops
    
    def on_thumbnails_toggle(self, state):
        """Handle thumbnail enable/disable toggle"""
        enabled = self.thumbnails_enabled_checkbox.isChecked()
        
        # Save to config
        self.config.config["thumbnails_enabled"] = enabled
        self.config.save_config()
        
        if enabled:
            # Re-enable thumbnails - request visible items
            QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
        else:
            # Clear thumbnail queue when disabled
            if hasattr(self, 'thumbnail_generator'):
                self.thumbnail_generator.clear_queue()
        
        # Schedule deferred update (Qt will refresh automatically)
        self.file_list.scheduleDelayedItemsLayout()
    
    def browse_for_folder(self):
        """Browse for folder dialog"""
        current_path = self.breadcrumb.current_path or str(Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Folder",
            current_path
        )
        if folder:
            self.navigate_to_path(folder)
    
    def navigate_from_recent(self, item):
        """Navigate from recent list"""
        path = item.text()
        # Set flag to prevent recent list update
        self.is_navigating_from_recent = True
        self.navigate_to_path(path)
        self.is_navigating_from_recent = False
    
    def navigate_from_favorites(self, item):
        """Navigate from favorites list"""
        # Get path from the custom widget label (stored in fullPath property)
        label = self.favorites_list.itemWidget(item)
        if label:
            path = label.property("fullPath")
        else:
            # Fallback to item text (for backwards compatibility)
            path = item.text()
        
        if path:
            # Set flag to prevent clearing favorites selection
            self.is_navigating_from_favorites = True
            self.navigate_to_path(path)
            self.is_navigating_from_favorites = False
    
    def navigate_from_folder_tree(self, index):
        """Navigate from folder tree view"""
        if not index.isValid():
            return
        
        # Get the path from the folder model
        path = self.folder_model.filePath(index)
        
        if path and Path(path).is_dir():
            self.navigate_to_path(path)
    
    def on_nav_top_tabs_moved(self, from_index, to_index):
        """Save navigation top tabs order when tabs are moved"""
        # Get current tab order
        tab_order = []
        for i in range(self.nav_top_tabs.count()):
            tab_order.append(self.nav_top_tabs.tabText(i))
        
        # Save to config
        self.config.config["nav_top_tabs_order"] = tab_order
        self.config.save_config()
    
    def on_nav_tabs_moved(self, from_index, to_index):
        """Save navigation tabs order when tabs are moved"""
        # Get current tab order
        tab_order = []
        for i in range(self.nav_tabs.count()):
            tab_order.append(self.nav_tabs.tabText(i))
        
        # Save to config
        self.config.config["nav_tabs_order"] = tab_order
        self.config.save_config()
    
    def update_recent_list(self):
        """Update recent list widget (legacy - no longer used, kept for compatibility)"""
        # Recent list UI removed - now using dropdown menu (recent_btn)
        # This function is kept empty for compatibility with existing code
        pass
    
    def update_recent_menu(self):
        """Update recent folders dropdown menu"""
        menu = self.recent_btn.menu()
        menu.clear()
        
        # Apply UI font from settings
        from . import widgets
        font = QtGui.QFont(widgets.UI_FONT, 9)
        menu.setFont(font)
        
        recent_paths = self.config.config.get("recent_paths", [])
        
        if not recent_paths:
            # No recent paths
            no_recent_action = menu.addAction("No recent folders")
            no_recent_action.setEnabled(False)
        else:
            # Add recent paths (max 20)
            for path in recent_paths:
                if Path(path).exists():
                    # Show full path (shortened if too long)
                    path_str = str(path)
                    
                    # Shorten path if longer than 60 chars
                    if len(path_str) > 60:
                        # Keep drive/start and last 2 parts: "D:\...\parent\folder"
                        parts = Path(path).parts
                        if len(parts) > 3:
                            shortened = f"{parts[0]}\\...\\{parts[-2]}\\{parts[-1]}"
                        else:
                            shortened = path_str
                        display_text = shortened
                    else:
                        display_text = path_str
                    
                    action = menu.addAction(display_text)
                    action.setToolTip(path_str)  # Full path in tooltip
                    action.setData(path_str)  # Store full path
                    action.triggered.connect(lambda checked=False, p=path: self.navigate_to_path(p))
            
            # Separator
            menu.addSeparator()
            
            # Clear recent action
            clear_action = menu.addAction("Clear Recent Folders")
            clear_action.triggered.connect(self.clear_recent_paths)
    
    def clear_recent_paths(self):
        """Clear all recent paths"""
        self.config.config["recent_paths"] = []
        self.config.save_config()
        self.update_recent_menu()
        self.update_recent_list()
        self.safe_show_status("Recent folders cleared")
    
    def add_current_to_favorites(self):
        """Add current path to favorites"""
        current_path = self.breadcrumb.current_path.strip()
        
        if not current_path:
            self.safe_show_status("No path selected")
            return
        
        # Normalize path for comparison
        normalized_path = str(Path(current_path).resolve())
        
        # Check if already in favorites (compare normalized paths)
        favorites = self.config.config.get("favorites", [])
        for fav in favorites:
            fav_dict = self._normalize_favorite(fav)
            if fav_dict and str(Path(fav_dict["path"]).resolve()) == normalized_path:
                self.safe_show_status(f"Already in favorites: {Path(current_path).name}")
                return
        
        # Add to favorites (new dict format)
        new_favorite = {
            "path": normalized_path,
            "alias": None,
            "color": None
        }
        self.config.config["favorites"].append(new_favorite)
        self.config.save_config()
        self.update_favorites_list()
        self.safe_show_status(f"Added to favorites: {Path(current_path).name}")
    
    def _normalize_favorite(self, fav):
        """
        Normalize favorite entry to dict format with backward compatibility.
        Old format: string path
        New format: {"path": str, "alias": str, "color": str}
        """
        if isinstance(fav, str):
            # Old format - convert to new
            return {
                "path": fav,
                "alias": None,
                "color": None
            }
        elif isinstance(fav, dict):
            # New format - ensure all keys exist
            return {
                "path": fav.get("path", ""),
                "alias": fav.get("alias"),
                "color": fav.get("color")
            }
        return None
    
    def update_favorites_list(self):
        """Update favorites list"""
        self.favorites_list.clear()
        favorites = self.config.config.get("favorites", [])
        
        for fav in favorites:
            fav_dict = self._normalize_favorite(fav)
            if not fav_dict:
                continue
            
            path = fav_dict["path"]
            if not Path(path).exists():
                continue
            
            # Get display name (alias or path)
            display_name = fav_dict["alias"] if fav_dict["alias"] else path
            
            # Create list item
            item = QtWidgets.QListWidgetItem()
            item.setToolTip(f"{path}\nAlias: {fav_dict['alias'] or 'None'}")
            
            # Create a custom label widget
            label = QtWidgets.QLabel(display_name)
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(False)
            label.setToolTip(item.toolTip())
            
            # Apply color bar if color is set
            if fav_dict["color"]:
                label.setStyleSheet(f"""
                    QLabel {{
                        background-color: transparent;
                        border-left: 6px solid {fav_dict["color"]};
                        padding-left: 6px;
                    }}
                """)
            else:
                label.setStyleSheet("""
                    QLabel {
                        background-color: transparent;
                    }
                """)
            
            # Make label transparent to mouse events so clicks go to the item
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            
            # Store all data in label for dynamic resizing and navigation
            label.setProperty("fullPath", path)
            label.setProperty("displayName", display_name)
            label.setProperty("alias", fav_dict["alias"])
            label.setProperty("color", fav_dict["color"])
            
            self.favorites_list.addItem(item)
            self.favorites_list.setItemWidget(item, label)
        
        # Update eliding after all items added
        self.update_favorites_eliding()
    
    def update_favorites_eliding(self):
        """Update elided text for all favorites based on current width"""
        available_width = self.favorites_list.viewport().width() - 10  # Some padding
        
        for i in range(self.favorites_list.count()):
            item = self.favorites_list.item(i)
            label = self.favorites_list.itemWidget(item)
            if label:
                # Use displayName (alias or path) for eliding
                display_name = label.property("displayName")
                if display_name:
                    font_metrics = label.fontMetrics()
                    
                    # Custom eliding: 30% start, 70% end (prioritize folder name at end)
                    text_width = font_metrics.horizontalAdvance(display_name) if hasattr(font_metrics, 'horizontalAdvance') else font_metrics.width(display_name)
                    
                    if text_width > available_width:
                        # Need to elide
                        ellipsis = "..."
                        ellipsis_width = font_metrics.horizontalAdvance(ellipsis) if hasattr(font_metrics, 'horizontalAdvance') else font_metrics.width(ellipsis)
                        
                        # 30% for start, 70% for end
                        start_width = int((available_width - ellipsis_width) * 0.3)
                        end_width = int((available_width - ellipsis_width) * 0.7)
                        
                        # Find start text
                        start_text = ""
                        for j in range(len(display_name)):
                            test = display_name[:j+1]
                            w = font_metrics.horizontalAdvance(test) if hasattr(font_metrics, 'horizontalAdvance') else font_metrics.width(test)
                            if w > start_width:
                                break
                            start_text = test
                        
                        # Find end text
                        end_text = ""
                        for j in range(len(display_name)):
                            test = display_name[-(j+1):]
                            w = font_metrics.horizontalAdvance(test) if hasattr(font_metrics, 'horizontalAdvance') else font_metrics.width(test)
                            if w > end_width:
                                break
                            end_text = test
                        
                        elided_text = start_text + ellipsis + end_text
                    else:
                        elided_text = display_name
                    
                    label.setText(elided_text)
    
    def filter_favorites(self, search_text):
        """Filter favorites list based on search text (searches in path and alias)"""
        search_text = search_text.lower()
        
        for i in range(self.favorites_list.count()):
            item = self.favorites_list.item(i)
            label = self.favorites_list.itemWidget(item)
            if label:
                full_path = label.property("fullPath") or ""
                alias = label.property("alias") or ""
                
                # Search in path and alias
                if (search_text in full_path.lower() or 
                    search_text in alias.lower()):
                    item.setHidden(False)
                else:
                    item.setHidden(True)
            else:
                item.setHidden(True)
    
    
    def on_favorites_reordered(self, parent, start, end, destination, row):
        """Handle favorites list reordering - save new order to config"""
        # Read current order from list widget
        new_order = []
        for i in range(self.favorites_list.count()):
            item = self.favorites_list.item(i)
            label = self.favorites_list.itemWidget(item)
            if label:
                # Get the full favorite dict
                path = label.property("fullPath")
                alias = label.property("alias")
                
                # Get color from stylesheet (need to extract from current config)
                favorites = self.config.config.get("favorites", [])
                color = None
                for fav in favorites:
                    fav_dict = self._normalize_favorite(fav)
                    if fav_dict and fav_dict["path"] == path:
                        color = fav_dict["color"]
                        break
                
                new_order.append({
                    "path": path,
                    "alias": alias,
                    "color": color
                })
        
        # Update config with new order
        self.config.config["favorites"] = new_order
        self.config.save_config()
        
        if DEBUG_MODE:
            print(f"[Browser] Favorites reordered: {len(new_order)} items")
        
        self.safe_show_status("Favorites order saved", 2000)
    
    def set_favorite_alias(self, item):
        """Set alias for favorite"""
        label = self.favorites_list.itemWidget(item)
        if not label:
            return
        
        path = label.property("fullPath")
        current_alias = label.property("alias") or ""
        
        # Dialog with path as default
        text, ok = QtWidgets.QInputDialog.getText(
            self, 
            "Set Alias", 
            f"Alias for:\n{path}\n\nEnter display name:",
            QtWidgets.QLineEdit.Normal,
            current_alias or path  # Pre-fill with path if no alias
        )
        
        if ok:
            new_alias = text.strip() or None
            self._update_favorite_property(path, alias=new_alias)
            self.safe_show_status(f"Alias updated: {new_alias or 'cleared'}")
    
    def clear_favorite_alias(self, item):
        """Clear alias from favorite"""
        label = self.favorites_list.itemWidget(item)
        if not label:
            return
        
        path = label.property("fullPath")
        self._update_favorite_property(path, alias=None)
        self.safe_show_status("Alias cleared")
    
    def make_color_icon(self, hexcode):
        """Create a color icon for menu items"""
        from PySide6.QtGui import QIcon, QPixmap, QColor
        pix = QPixmap(16, 16)
        pix.fill(QColor(hexcode))
        return QIcon(pix)
    
    def set_favorite_color_from_palette(self, item, hexcode):
        """Set color for favorite from palette"""
        label = self.favorites_list.itemWidget(item)
        if not label:
            return
        
        path = label.property("fullPath")
        self._update_favorite_property(path, color=hexcode)
        self.safe_show_status(f"Color updated")
    
    def clear_favorite_color(self, item):
        """Clear color from favorite"""
        label = self.favorites_list.itemWidget(item)
        if not label:
            return
        
        path = label.property("fullPath")
        self._update_favorite_property(path, color=None)
        self.safe_show_status("Color cleared")
    
    def _update_favorite_property(self, path, alias=..., color=..., skip_refresh=False):
        """Update specific property of a favorite (use ... to skip)"""
        favorites = self.config.config.get("favorites", [])
        
        for i, fav in enumerate(favorites):
            fav_dict = self._normalize_favorite(fav)
            if fav_dict and fav_dict["path"] == path:
                # Update only specified properties
                if alias is not ...:
                    fav_dict["alias"] = alias
                if color is not ...:
                    fav_dict["color"] = color
                
                favorites[i] = fav_dict
                break
        
        self.config.save_config()
        
        # Only refresh if not skipped (for batch updates)
        if not skip_refresh:
            self.update_favorites_list()
    
    def show_favorites_context_menu(self, position):
        """Show context menu for favorites list"""
        # Check if clicked on an actual item
        item_at_pos = self.favorites_list.itemAt(position)
        
        # If clicked on empty area, don't show menu
        if not item_at_pos:
            return
        
        # Get selected items (can be multiple)
        selected_items = self.favorites_list.selectedItems()
        
        menu = QtWidgets.QMenu()
        
        # If no items selected - shouldn't happen now but keep check
        if not selected_items:
            return
        
        # Edit options
        set_alias_action = None
        clear_alias_action = None
        set_color_menu = None
        color_actions = []
        clear_color_action = None
        
        # Single selection - show alias options
        if len(selected_items) == 1:
            set_alias_action = menu.addAction("Set Alias...")
            
            # Check if item has alias
            label = self.favorites_list.itemWidget(selected_items[0])
            if label and label.property("alias"):
                clear_alias_action = menu.addAction("Clear Alias")
            
            menu.addSeparator()
        
        # Color options - available for both single and multiple selection
        set_color_menu = QtWidgets.QMenu("Set Color", self)
        palette = [
            ("Default", "#282828"),  # Dark gray
            ("Sky Blue", "#87CEEB"),
            ("Light Green", "#90EE90"),
            ("Yellow", "#FFD700"),
            ("Orange", "#FFA500"),
            ("Coral", "#FF7F50"),
            ("Lavender", "#E6E6FA"),
            ("Pink", "#FFB6C1"),
            ("Light Gray", "#D3D3D3"),
            ("Mint", "#98FF98"),
            ("Sand", "#F4A460"),
            ("Aqua", "#00CED1")
        ]
        for name, hexcode in palette:
            act = set_color_menu.addAction(name)
            if hexcode:
                act.setIcon(self.make_color_icon(hexcode))
            color_actions.append((act, hexcode))
        menu.addMenu(set_color_menu)
        
        # Clear color - check if any selected item has color
        has_color = False
        for item in selected_items:
            label = self.favorites_list.itemWidget(item)
            if label:
                path = label.property("fullPath")
                if path:
                    favorites = self.config.config.get("favorites", [])
                    for fav in favorites:
                        fav_dict = self._normalize_favorite(fav)
                        if fav_dict and fav_dict["path"] == path and fav_dict["color"]:
                            has_color = True
                            break
                if has_color:
                    break
        
        if has_color:
            if len(selected_items) > 1:
                clear_color_action = menu.addAction(f"Clear Color ({len(selected_items)} items)")
            else:
                clear_color_action = menu.addAction("Clear Color")
            
            menu.addSeparator()
        
        # Remove from Favorites action - show count if multiple selected
        if len(selected_items) > 1:
            remove_action = menu.addAction(f"Remove {len(selected_items)} from Favorites")
        else:
            remove_action = menu.addAction("Remove from Favorites")
        
        action = menu.exec_(self.favorites_list.mapToGlobal(position))
        
        # If no action selected (clicked outside menu), return
        if action is None:
            return
        
        if action == set_alias_action:
            self.set_favorite_alias(selected_items[0])
        elif action == clear_alias_action:
            self.clear_favorite_alias(selected_items[0])
        elif action == clear_color_action:
            # Clear color for all selected items (batch update)
            for i, item in enumerate(selected_items):
                label = self.favorites_list.itemWidget(item)
                if label:
                    path = label.property("fullPath")
                    # Skip refresh for all but the last item
                    skip_refresh = (i < len(selected_items) - 1)
                    self._update_favorite_property(path, color=None, skip_refresh=skip_refresh)
            self.safe_show_status(f"Color cleared from {len(selected_items)} item(s)")
        elif action == remove_action:
            self.remove_from_favorites_multi(selected_items)
        elif set_color_menu:
            # Check if a color was selected
            for act, hexcode in color_actions:
                if action == act:
                    # Apply color to all selected items (batch update)
                    for i, item in enumerate(selected_items):
                        label = self.favorites_list.itemWidget(item)
                        if label:
                            path = label.property("fullPath")
                            # Skip refresh for all but the last item
                            skip_refresh = (i < len(selected_items) - 1)
                            self._update_favorite_property(path, color=hexcode, skip_refresh=skip_refresh)
                    self.safe_show_status(f"Color updated for {len(selected_items)} item(s)")
                    break
    
    def remove_from_favorites(self, item):
        """Remove single path from favorites (legacy function)"""
        label = self.favorites_list.itemWidget(item)
        if not label:
            return
        
        path_to_remove = label.property("fullPath")
        
        # Normalize path for comparison
        normalized_to_remove = str(Path(path_to_remove).resolve())
        
        # Remove from config (compare normalized paths)
        favorites = self.config.config.get("favorites", [])
        for i, fav in enumerate(favorites):
            fav_dict = self._normalize_favorite(fav)
            if fav_dict and str(Path(fav_dict["path"]).resolve()) == normalized_to_remove:
                del self.config.config["favorites"][i]
                self.config.save_config()
                self.update_favorites_list()
                self.safe_show_status(f"Removed from favorites: {Path(path_to_remove).name}")
                return
        
        self.safe_show_status(f"Path not found in favorites")
    
    def remove_from_favorites_multi(self, items):
        """Remove multiple paths from favorites"""
        if not items:
            return
        
        # Get paths to remove from labels
        paths_to_remove = []
        for item in items:
            label = self.favorites_list.itemWidget(item)
            if label:
                path = label.property("fullPath")
                if path:
                    paths_to_remove.append(path)
        
        if not paths_to_remove:
            return
        
        normalized_to_remove = [str(Path(p).resolve()) for p in paths_to_remove]
        
        # Get current favorites
        favorites = self.config.config.get("favorites", [])
        
        # Remove all selected items
        removed_count = 0
        i = 0
        while i < len(favorites):
            fav_dict = self._normalize_favorite(favorites[i])
            if fav_dict:
                norm_path = str(Path(fav_dict["path"]).resolve())
                if norm_path in normalized_to_remove:
                    del favorites[i]
                    removed_count += 1
                    continue
            i += 1
        
        # Save and update
        if removed_count > 0:
            self.config.config["favorites"] = favorites
            self.config.save_config()
            self.update_favorites_list()
            if removed_count == 1:
                self.safe_show_status(f"Removed 1 item from favorites")
            else:
                self.safe_show_status(f"Removed {removed_count} items from favorites")
        else:
            self.safe_show_status("No items were removed")
    
    def get_selected_assets(self):
        """Get selected assets"""
        selected_indexes = self.file_list.selectedIndexes()
        assets = []
        for index in selected_indexes:
            asset = self.file_model.data(index, Qt.UserRole)
            if asset:
                assets.append(asset)
        return assets
    
    def on_selection_changed(self, selected, deselected):
        """Handle file selection change - update preview panel (deferred)"""
        # Defer preview update slightly to not block selection
        QTimer.singleShot(10, self._update_preview_deferred)
        
        # Update selection info immediately
        self.update_selection_info()
    
    def update_selection_info(self):
        """Update selection info label (left side of info bar)"""
        assets = self.get_selected_assets()
        count = len(assets)
        
        if count == 0:
            self.selection_info_label.setText("")
        else:
            # Count files and folders separately
            file_count = sum(1 for asset in assets if not asset.is_folder)
            folder_count = sum(1 for asset in assets if asset.is_folder)
            
            parts = []
            if file_count > 0:
                parts.append(f"{file_count} file{'s' if file_count != 1 else ''}")
            if folder_count > 0:
                parts.append(f"{folder_count} folder{'s' if folder_count != 1 else ''}")
            
            if parts:
                self.selection_info_label.setText(" + ".join(parts) + " selected")
            else:
                self.selection_info_label.setText(f"{count} selected")
    
    def _update_preview_deferred(self):
        """Deferred preview update (doesn't block selection)"""
        assets = self.get_selected_assets()
        
        # Only update preview if panel is visible (performance optimization)
        if self.preview_panel.isVisible():
            self.preview_panel.update_preview(assets)
        
        # Update Quick View if open and not pinned
        self.update_quick_view()
    
    def on_model_reset(self):
        """Handle model reset (after filter changes) - trigger thumbnail loading"""
        # Small delay to let the view update, then request thumbnails
        QtCore.QTimer.singleShot(10, self.request_thumbnails_for_visible_items)
    
    def on_scroll_changed(self, value):
        """Handle scroll - load thumbnails for newly visible items"""
        # Request thumbnails immediately for instant feedback
        self.request_thumbnails_for_visible_items()
        
        # Also set up a debounce timer for when scrolling continues
        # This prevents overwhelming the queue during rapid scrolling
        if hasattr(self, '_scroll_timer'):
            self._scroll_timer.stop()
        
        self._scroll_timer = QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self.request_thumbnails_for_visible_items)
        self._scroll_timer.start(150)  # Reduced from 300ms for faster response
    
    def toggle_preview_panel(self):
        """Toggle preview panel visibility"""
        is_visible = self.preview_panel.isVisible()
        
        if is_visible:
            # Save ALL current sizes before hiding
            current_sizes = self.content_splitter.sizes()
            if len(current_sizes) == 3:
                self.nav_panel_last_width = current_sizes[0]
                self.browser_panel_last_width = current_sizes[1]
                self.preview_panel_last_width = current_sizes[2]
            
            # Hide panel
            self.preview_panel.setVisible(False)
            
            # Clear thumbnail queue and refresh for currently visible items
            # This stops generating thumbnails for items that scrolled out of view
            if hasattr(self, 'thumbnail_generator'):
                self.thumbnail_generator.clear_queue()
            QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
        else:
            # Show panel and restore last sizes
            self.preview_panel.setVisible(True)
            
            # Refresh preview with current selection
            assets = self.get_selected_assets()
            self.preview_panel.update_preview(assets)
            
            # Clear thumbnail queue and refresh for currently visible items
            # This stops generating thumbnails for items that scrolled out of view
            if hasattr(self, 'thumbnail_generator'):
                self.thumbnail_generator.clear_queue()
            QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
            
            # Restore previous sizes if available
            current_sizes = self.content_splitter.sizes()
            if len(current_sizes) == 3:
                # Use saved sizes or calculate defaults
                nav_size = getattr(self, 'nav_panel_last_width', current_sizes[0])
                browser_size = getattr(self, 'browser_panel_last_width', current_sizes[1])
                preview_size = getattr(self, 'preview_panel_last_width', 300)
                
                # Ensure minimum sizes
                if preview_size < 250:
                    preview_size = 300
                if browser_size < 400:
                    browser_size = 400
                if nav_size < 150:
                    nav_size = 200
                
                total_width = sum(current_sizes)
                
                # Adjust if total exceeds available width
                total_needed = nav_size + browser_size + preview_size
                if total_needed > total_width:
                    # Shrink browser panel to fit
                    browser_size = total_width - nav_size - preview_size
                    if browser_size < 400:
                        browser_size = 400
                        preview_size = total_width - nav_size - browser_size
                
                self.content_splitter.setSizes([nav_size, browser_size, preview_size])
        
        # Update button state
        self.preview_toggle_btn.setChecked(not is_visible)
        
        # Save state to config
        self.config.config["preview_panel_visible"] = not is_visible
        self.config.save_config()
    
    def toggle_sequence_mode(self):
        """Toggle image sequence grouping mode"""
        is_checked = self.sequence_mode_checkbox.isChecked()
        
        # Update model
        self.file_model.sequence_mode = is_checked
        
        # Clear thumbnail cache to regenerate with correct cache keys
        self.memory_cache.clear()
        
        # Reapply sequence grouping WITHOUT reloading from filesystem
        # This uses the stored ungrouped assets list for instant toggle
        self.file_model.beginResetModel()
        self.file_model.reapplySequenceGrouping()
        self.file_model.endResetModel()
        
        # Request thumbnails for new state
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
        
        # Update status
        if is_checked:
            self.safe_show_status("Sequence mode enabled - Image sequences are grouped")
        else:
            self.safe_show_status("Sequence mode disabled - Showing individual files")
        
        # Save state to config (UI state, not settings)
        self.config.config["sequence_mode"] = is_checked
        self.config.save_config()

    
    def on_item_double_clicked(self, index):
        """Handle double-click on item - navigate into folders or import files"""
        asset = self.file_model.data(index, Qt.UserRole)
        if not asset:
            return
        
        if asset.is_folder:
            # Navigate into folder
            self.navigate_to_path(asset.file_path)
        else:
            # Check if file is importable to Maya - using registry
            from .utils import get_importable_extensions
            maya_importable = get_importable_extensions()
            
            if asset.extension in maya_importable or asset.is_script_file or asset.is_image_file:
                # Import file (default action for importable files)
                self.import_selected_file()
            else:
                # Not importable - show message and offer to open with default app
                self.safe_show_status(f"Cannot import {asset.extension} files to Maya. Use 'Open' to view.", 4000)
    
    def import_selected_file(self):
        """Import selected file or navigate into folder"""
        assets = self.get_selected_assets()
        if not assets:
            self.safe_show_status("No file selected")
            return
        
        # If single folder selected - navigate into it
        if len(assets) == 1 and assets[0].is_folder:
            self.navigate_to_path(assets[0].file_path)
            return
        
        if not MAYA_AVAILABLE:
            print("Maya not available")
            return
        
        imported_count = 0
        error_count = 0
        skipped_count = 0
        
        # Get importable extensions from registry
        from .utils import get_importable_extensions
        maya_importable = get_importable_extensions()
        
        for asset in assets:
            # Skip folders
            if asset.is_folder:
                skipped_count += 1
                continue
            
            # Check if file type is importable
            if not (asset.extension in maya_importable or asset.is_script_file or asset.is_image_file):
                skipped_count += 1
                self.safe_show_status(f"Skipped {asset.name}: Cannot import {asset.extension} files", 2000)
                continue
                
            try:
                if asset.is_sbsar_file:
                    # Substance Archive - create substance texture node
                    # TODO: Test and refine based on actual Substance plugin behavior
                    try:
                        # Try to load substance plugin if not loaded
                        # Note: Plugin name might need adjustment (e.g., 'substancePlugin', 'Substance', etc.)
                        try:
                            if not cmds.pluginInfo('substance', query=True, loaded=True):
                                cmds.loadPlugin('substance')
                        except:
                            # Plugin might have different name or not be installed
                            pass
                        
                        # Create substance texture node (treating like texture, Maya handles the rest)
                        # Node type might need adjustment based on actual plugin
                        substance_node = cmds.shadingNode('substance', asTexture=True)
                        cmds.setAttr(f"{substance_node}.filePath", str(asset.file_path), type="string")
                        
                        imported_count += 1
                        self.safe_show_status(f"Substance texture created: {substance_node}", 2000)
                    except Exception as e:
                        error_count += 1
                        self.safe_show_status(f"Substance import error: {e}", 3000)
                        print(f"Substance import error: {e}")
                
                elif asset.is_maya_file:
                    # Maya files - regular import
                    cmds.file(str(asset.file_path), i=True, type="mayaAscii" if asset.extension == ".ma" else "mayaBinary")
                    imported_count += 1
                
                elif asset.is_script_file:
                    # Script files - source/exec them
                    if asset.extension == ".mel":
                        # MEL script - use mel.eval to source it
                        # Convert backslashes to forward slashes for MEL
                        mel_path = str(asset.file_path).replace('\\', '/')
                        mel.eval(f'source "{mel_path}"')
                        imported_count += 1
                    elif asset.extension == ".py":
                        # Python script - exec it
                        with open(asset.file_path, 'r') as f:
                            script_content = f.read()
                        exec(script_content, {'__name__': '__main__'})
                        imported_count += 1
                    
                elif asset.is_image_file:
                    # Image files - create file texture node
                    file_node = cmds.shadingNode('file', asTexture=True, isColorManaged=True)
                    cmds.setAttr(f"{file_node}.fileTextureName", str(asset.file_path), type="string")
                    
                    # Also create place2dTexture node and connect
                    place2d = cmds.shadingNode('place2dTexture', asUtility=True)
                    cmds.connectAttr(f"{place2d}.coverage", f"{file_node}.coverage", force=True)
                    cmds.connectAttr(f"{place2d}.translateFrame", f"{file_node}.translateFrame", force=True)
                    cmds.connectAttr(f"{place2d}.rotateFrame", f"{file_node}.rotateFrame", force=True)
                    cmds.connectAttr(f"{place2d}.mirrorU", f"{file_node}.mirrorU", force=True)
                    cmds.connectAttr(f"{place2d}.mirrorV", f"{file_node}.mirrorV", force=True)
                    cmds.connectAttr(f"{place2d}.stagger", f"{file_node}.stagger", force=True)
                    cmds.connectAttr(f"{place2d}.wrapU", f"{file_node}.wrapU", force=True)
                    cmds.connectAttr(f"{place2d}.wrapV", f"{file_node}.wrapV", force=True)
                    cmds.connectAttr(f"{place2d}.repeatUV", f"{file_node}.repeatUV", force=True)
                    cmds.connectAttr(f"{place2d}.offset", f"{file_node}.offset", force=True)
                    cmds.connectAttr(f"{place2d}.rotateUV", f"{file_node}.rotateUV", force=True)
                    cmds.connectAttr(f"{place2d}.noiseUV", f"{file_node}.noiseUV", force=True)
                    cmds.connectAttr(f"{place2d}.vertexUvOne", f"{file_node}.vertexUvOne", force=True)
                    cmds.connectAttr(f"{place2d}.vertexUvTwo", f"{file_node}.vertexUvTwo", force=True)
                    cmds.connectAttr(f"{place2d}.vertexUvThree", f"{file_node}.vertexUvThree", force=True)
                    cmds.connectAttr(f"{place2d}.vertexCameraOne", f"{file_node}.vertexCameraOne", force=True)
                    cmds.connectAttr(f"{place2d}.outUV", f"{file_node}.uv", force=True)
                    cmds.connectAttr(f"{place2d}.outUvFilterSize", f"{file_node}.uvFilterSize", force=True)
                    
                    imported_count += 1
                    
                else:
                    # Other 3D file types (OBJ, FBX, ABC, USD, DAE, STL, etc.)
                    from .utils import get_maya_import_type
                    
                    file_path = str(asset.file_path)
                    
                    # Get Maya import type from config
                    file_type = get_maya_import_type(asset.extension)
                    
                    if file_type:
                        # Import with type specification
                        cmds.file(file_path, i=True, type=file_type, ignoreVersion=True,
                                 mergeNamespacesOnClash=False, namespace=':',
                                 options='v=0', preserveReferences=True)
                        imported_count += 1
                    else:
                        # Unknown 3D format, try without type specification
                        try:
                            cmds.file(file_path, i=True)
                            imported_count += 1
                        except:
                            # Skip if import fails
                            pass
                    
            except Exception as e:
                error_count += 1
                self.safe_show_status(f"Import error ({asset.name}): {e}", 3000)
                print(f"Import error {asset.name}: {e}")
        
        # Summary message
        if imported_count > 0:
            msg = f"✓ Imported {imported_count} file(s)"
            if error_count > 0:
                msg += f", {error_count} error(s)"
            if skipped_count > 0:
                msg += f", {skipped_count} skipped"
            self.safe_show_status(msg, 4000)
        elif error_count > 0:
            self.safe_show_status(f"✗ Import failed: {error_count} error(s)", 4000)
        elif skipped_count > 0:
            self.safe_show_status(f"No files imported ({skipped_count} skipped)", 3000)
    
    def reference_selected_file(self):
        """Reference selected file"""
        assets = self.get_selected_assets()
        if not assets:
            self.safe_show_status("No file selected")
            return
        
        if not MAYA_AVAILABLE:
            print("Maya not available")
            return
        
        for asset in assets:
            try:
                if asset.is_maya_file:
                    namespace = asset.file_path.stem  # filename without extension
                    cmds.file(str(asset.file_path), r=True, namespace=namespace)
                    self.safe_show_status(f"Referenced: {asset.name} ({namespace})")
                else:
                    self.safe_show_status(f"Reference only supported for Maya files")
            except Exception as e:
                self.safe_show_status(f"Reference error: {e}")
                print(f"Reference error {asset.name}: {e}")
    
    def open_selected_files(self):
        """Open selected files with Windows default application"""
        import os
        import subprocess
        
        assets = self.get_selected_assets()
        if not assets:
            self.safe_show_status("No file selected")
            return
        
        for asset in assets:
            try:
                file_path = str(asset.file_path)
                
                # Use os.startfile on Windows (best option)
                if os.name == 'nt':  # Windows
                    os.startfile(file_path)
                    self.safe_show_status(f"Opening: {asset.name}")
                else:
                    # macOS and Linux fallback
                    if sys.platform == 'darwin':  # macOS
                        subprocess.Popen(['open', file_path])
                    else:  # Linux
                        subprocess.Popen(['xdg-open', file_path])
                    self.safe_show_status(f"Opening: {asset.name}")
                    
            except Exception as e:
                self.safe_show_status(f"Open error: {e}")
                print(f"Open error {asset.name}: {e}")
    
    def clear_all_filters(self):
        """Clear all active filters"""
        self.file_model.clearFilters()
        self.update_filter_visual_feedback()
        self.safe_show_status("All filters cleared")
    
    def on_thumbnail_ready(self, file_path, pixmap):
        """Handle thumbnail ready from generator"""
        # Use fast O(1) lookup instead of looping through all rows
        model = self.file_list.model()
        if model:
            row = model.get_row_for_path(file_path)
            if row is not None:
                index = model.index(row, 0)
                # Update the model data with the new thumbnail
                model.setData(index, pixmap, Qt.DecorationRole)
                # Force the view to repaint this specific item
                self.file_list.update(index)
        
        # Also update viewport for good measure
        self.file_list.viewport().update()
    
    def on_cache_status(self, status):
        """Handle cache status updates"""
        if status == "cache":
            self.cache_hits += 1
        elif status == "generating":
            self.generations += 1
    
    def on_thumbnail_progress(self, current, total):
        """Handle thumbnail generation progress - shows in right side of status bar"""
        try:
            if not hasattr(self, 'thumbnail_status_label') or self.thumbnail_status_label is None:
                return
            
            if total > 0:
                if current >= total:
                    # Show final stats
                    msg = f"Thumbnails: cached {self.cache_hits}, generated {self.generations}"
                    self.thumbnail_status_label.setText(msg)
                else:
                    # Show progress with stats
                    msg = f"Thumbnails: {current}/{total} (cached: {self.cache_hits}, generating: {self.generations})"
                    self.thumbnail_status_label.setText(msg)
        except RuntimeError:
            # C++ object already deleted, safely ignore
            pass
    
    def on_thumbnail_failed(self, file_path, error_message):
        """Handle thumbnail generation failure"""
        print(f"Thumbnail generation failed for {file_path}: {error_message}")
    
    def request_thumbnails_for_visible_items(self):
        """Request thumbnail generation for currently visible items only"""
        # Check if thumbnails are enabled
        if not self.thumbnails_enabled_checkbox.isChecked():
            return
        
        if not hasattr(self, 'thumbnail_generator'):
            return
        
        # Get visible items from the list view
        model = self.file_list.model()
        if not model:
            return
        
        # OPTIMIZATION: Get viewport rectangle once
        viewport_rect = self.file_list.viewport().rect()
        
        # OPTIMIZATION: Early exit if no rows
        row_count = model.rowCount()
        if row_count == 0:
            return
        
        # Collect visible items that need thumbnails
        visible_items = []
        
        # Find visible items by checking which items intersect with viewport
        # More reliable than indexAt() which doesn't work well in all cases
        start_row = None
        end_row = None
        
        for row in range(row_count):
            index = model.index(row, 0)
            rect = self.file_list.visualRect(index)
            
            # Check if this item is visible
            if rect.isValid() and viewport_rect.intersects(rect):
                if start_row is None:
                    start_row = row
                end_row = row
        
        # If we found visible items, add buffer
        if start_row is not None and end_row is not None:
            start_row = max(0, start_row - 5)
            end_row = min(row_count - 1, end_row + 10)
        else:
            # No visible items found - load first batch as fallback
            start_row = 0
            end_row = min(row_count - 1, 50)
        
        # Only loop through visible rows (huge performance gain!)
        for row in range(start_row, end_row + 1):
            index = model.index(row, 0)
            asset = model.data(index, Qt.UserRole)
            
            if asset and asset.should_generate_thumbnail:
                file_path_str = str(asset.file_path)
                
                # For sequences, check cache using pattern as key
                cache_key = file_path_str
                if asset.is_sequence and asset.sequence:
                    cache_key = str(asset.sequence.pattern)
                
                # OPTIMIZATION: Skip disk refresh check during scroll (too slow!)
                # Only check memory cache - disk cache check happens on folder navigation
                if self.memory_cache.get(cache_key) is None:
                    # Not in memory cache - try to load from disk first
                    cached_from_disk = self.disk_cache.get(file_path_str, asset.modified_time)
                    if cached_from_disk:
                        self.memory_cache.set(cache_key, cached_from_disk)
                        # Update display immediately with cached thumbnail
                        model.setData(index, cached_from_disk, Qt.DecorationRole)
                        # Signal change (batch emit is more efficient)
                        model.dataChanged.emit(index, index, [Qt.DecorationRole])
                    else:
                        # Not in disk cache either - need to generate
                        visible_items.append((file_path_str, asset.modified_time, asset))
        
        # CLEAR the queue and add ONLY visible items with PRIORITY
        # This ensures we prioritize what user is currently viewing
        if visible_items:
            # Clear old queue (non-visible items) and reset counters
            self.thumbnail_generator.clear_queue()
            
            # Add visible items to queue in REVERSE order so they process top-to-bottom
            # (since we pop() from the end, last added = first processed)
            for file_path, modified_time, asset in reversed(visible_items):
                self.thumbnail_generator.add_to_queue(file_path, modified_time, priority=True, asset=asset)
        
        # Background loading DISABLED during scroll for performance
        # (preload_all_thumbnails feature removed from scroll event)
    
    def on_splitter_moved(self, pos, index):
        """Handle splitter movement - optimized for fast updates"""
        # Count moves for performance measurement
        self._splitter_move_count += 1
        
        # First move - start timer and prepare for fast dragging
        if self._splitter_move_count == 1:
            import time
            self._splitter_drag_start_time = time.time()
            
            if DEBUG_MODE:
                print(f"\n{'='*60}")
                print(f"[PERF] Splitter drag STARTED (first move detected)")
                print(f"[PERF] Items in view: {self.file_model.rowCount()}")
                print(f"{'='*60}\n")
            
            # NO LONGER DISABLING UPDATES - opaque resize handles it smoothly
            # UniformItemSizes=True makes real-time resize FAST enough
        
        if DEBUG_MODE:
            print(f"[Splitter] Moved to position {pos} (move #{self._splitter_move_count})")
        
        # NO CONFIG SAVING HERE - only save on window close for better performance
        # The position will be saved in closeEvent()
        
        # Use timer to detect end of drag (no more moves for 100ms = drag ended)
        if hasattr(self, '_splitter_end_timer'):
            self._splitter_end_timer.stop()
        
        self._splitter_end_timer = QTimer()
        self._splitter_end_timer.setSingleShot(True)
        self._splitter_end_timer.timeout.connect(self._on_splitter_drag_ended)
        self._splitter_end_timer.start(100)  # 100ms delay to detect end
    
    def _on_splitter_drag_ended(self):
        """Called when splitter drag has ended (no moves for 100ms)"""
        # Always reset counters (must be outside DEBUG check!)
        move_count = self._splitter_move_count
        self._viewport_paint_times = []
        self._splitter_move_count = 0
        
        # Request thumbnails for newly visible items after resize
        QTimer.singleShot(50, self.request_thumbnails_for_visible_items)
        
        if DEBUG_MODE and move_count > 0:
            import time
            drag_duration = time.time() - self._splitter_drag_start_time
            avg_time_per_move = (drag_duration / move_count * 1000) if move_count > 0 else 0
            fps = move_count / drag_duration if drag_duration > 0 else 0
            
            # Calculate viewport paint statistics
            paint_count = len(self._viewport_paint_times)
            if paint_count > 0:
                avg_paint_time = sum(self._viewport_paint_times) / paint_count
                max_paint_time = max(self._viewport_paint_times)
                min_paint_time = min(self._viewport_paint_times)
                paint_fps = paint_count / drag_duration if drag_duration > 0 else 0
            else:
                avg_paint_time = max_paint_time = min_paint_time = paint_fps = 0
            
            print(f"\n{'='*60}")
            print(f"[PERF] Splitter drag ENDED")
            print(f"[PERF] Duration: {drag_duration:.2f}s")
            print(f"[PERF] Total moves: {move_count}")
            print(f"[PERF] Average time per move: {avg_time_per_move:.2f}ms")
            print(f"[PERF] Estimated FPS: {fps:.1f}")
            print(f"")
            print(f"[PERF] Viewport repaints: {paint_count}")
            print(f"[PERF] Avg paint time: {avg_paint_time:.2f}ms")
            print(f"[PERF] Min/Max paint: {min_paint_time:.2f}ms / {max_paint_time:.2f}ms")
            print(f"[PERF] Paint FPS: {paint_fps:.1f}")
            print(f"{'='*60}\n")
        
        # NO LONGER NEEDED - updates were never disabled
        # Just ensure a final refresh for good measure
        if hasattr(self, 'file_list'):
            self.file_list.viewport().update()
    
    def on_column_width_changed(self, pos, index):
        """Refresh list view when column widths change"""
        # Use timer to debounce rapid column resizing
        if hasattr(self, '_column_resize_timer'):
            self._column_resize_timer.stop()
        
        self._column_resize_timer = QTimer()
        self._column_resize_timer.setSingleShot(True)
        self._column_resize_timer.timeout.connect(self._finish_column_resize)
        self._column_resize_timer.start(50)  # Very short delay for responsive feel
    
    def _finish_column_resize(self):
        """Complete column resize after debounce timer"""
        # Schedule deferred layout update (more efficient than viewport().update())
        if hasattr(self, 'file_list'):
            self.file_list.scheduleDelayedItemsLayout()
        
        # Request thumbnails for newly visible items
        if hasattr(self, '_column_thumb_timer'):
            self._column_thumb_timer.stop()
        
        self._column_thumb_timer = QTimer()
        self._column_thumb_timer.setSingleShot(True)
        self._column_thumb_timer.timeout.connect(self.request_thumbnails_for_visible_items)
        self._column_thumb_timer.start(200)  # Wait 200ms after column resize stops
    
    def on_nav_splitter_moved(self, pos, index):
        """Handle nav splitter movement - no config saving during drag for performance"""
        # NO CONFIG SAVING HERE - only save on window close for better performance
        pass
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        key = event.key()
        modifiers = event.modifiers()
        
        # Ctrl+F - Focus search bar
        if key == Qt.Key_F and modifiers == Qt.ControlModifier:
            self.search_bar.search_input.setFocus()
            self.search_bar.search_input.selectAll()
            event.accept()
            return
        
        # F5 - Refresh current folder
        if key == Qt.Key_F5:
            self.refresh_current_folder()
            event.accept()
            return
        
        # Delete - Delete selected file(s)
        if key == Qt.Key_Delete:
            self.delete_selected_files()
            event.accept()
            return
        
        # F2 - Rename selected file
        if key == Qt.Key_F2:
            self.rename_selected_file()
            event.accept()
            return
        
        # Ctrl+C - Copy path to clipboard
        if key == Qt.Key_C and modifiers == Qt.ControlModifier:
            self.copy_path_to_clipboard()
            event.accept()
            return
        
        # Enter - Import selected file
        if key == Qt.Key_Return or key == Qt.Key_Enter:
            self.import_selected_file()
            event.accept()
            return
        
        # Backspace - Go to parent folder
        if key == Qt.Key_Backspace:
            self.navigate_to_parent()
            event.accept()
            return
        
        # Pass to parent for unhandled keys
        super().keyPressEvent(event)
    
    def resizeEvent(self, event):
        """Handle window resize - load thumbnails for newly visible items"""
        super().resizeEvent(event)
        
        # Use timer to debounce resize events (avoid generating on every pixel)
        if hasattr(self, '_resize_timer'):
            self._resize_timer.stop()
        
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.request_thumbnails_for_visible_items)
        self._resize_timer.start(300)  # Wait 300ms after resize stops
    
    def show_settings_dialog(self):
        """Show settings dialog"""
        dialog = SettingsDialog(self.settings_manager, self)
        dialog.settings_changed.connect(self.apply_settings)
        dialog.exec_()
    
    def apply_settings(self):
        """Apply settings to the application"""
        if DEBUG_MODE:
            print("[Browser] Applying settings...")
        
        # Apply UI font to all modules
        self._apply_ui_font()
        
        # Apply memory cache size from settings to config
        memory_cache_size = self.settings_manager.get("thumbnails", "memory_cache_size", 2000)
        self.config.config["thumbnail_cache_size"] = memory_cache_size
        self.config.save_config()
        
        # Update existing memory cache max size
        if hasattr(self, 'memory_cache'):
            self.memory_cache.max_size = memory_cache_size
            if DEBUG_MODE:
                print(f"[Browser] Updated memory cache size to {memory_cache_size}")
        
        # Rebuild filter panel with updated file formats
        if hasattr(self, 'filter_panel'):
            self.filter_panel.rebuild_type_filters()
            if DEBUG_MODE:
                print("[Browser] Rebuilt filter panel with updated formats")
        
        # Apply preview settings to PreviewPanel
        preview_resolution = self.settings_manager.get("preview", "resolution", 1024)
        hdr_cache_size = self.settings_manager.get("preview", "hdr_cache_size", 5)
        if hasattr(self, 'preview_panel'):
            self.preview_panel.max_preview_size = preview_resolution
            self.preview_panel.hdr_cache_max_size = hdr_cache_size
            self.preview_panel.max_hdr_cache_size = hdr_cache_size  # Both attributes for compatibility
            # Clear and resize cache
            self.preview_panel.hdr_raw_cache.clear()
            if DEBUG_MODE:
                print(f"[Browser] Preview resolution set to {preview_resolution}px, HDR cache size: {hdr_cache_size}")
        
        # Apply thumbnail generation size and quality from settings
        thumbnail_generation_size = self.settings_manager.get("thumbnails", "size", 128)
        quality_str = self.settings_manager.get("thumbnails", "quality", "medium")
        quality_map = {"low": 60, "medium": 85, "high": 95}
        jpeg_quality = quality_map.get(quality_str, 85)
        
        if hasattr(self, 'thumbnail_generator'):
            self.thumbnail_generator.thumbnail_size = thumbnail_generation_size
            self.thumbnail_generator.jpeg_quality = jpeg_quality
            if DEBUG_MODE:
                print(f"[Browser] Updated thumbnail generation: size={thumbnail_generation_size}px, quality={jpeg_quality}")
        
        # Note: Grid/List display sizes (toolbar slider) are separate and stored in config.json
        # Those are managed by set_view_mode() and update_thumbnail_size()
        
        # Apply recursive file limits from settings
        max_recursive = self.settings_manager.get("filters", "max_recursive_files", 10000)
        max_search = self.settings_manager.get("filters", "max_search_files", 100000)
        if hasattr(self, 'file_model'):
            self.file_model.max_recursive_files = max_recursive
            self.file_model.max_search_files = max_search
            if DEBUG_MODE:
                print(f"[Browser] Updated file limits: recursive={max_recursive}, search={max_search}")
        
        # Apply search/filter settings to file model
        case_sensitive = self.settings_manager.get("filters", "case_sensitive_search", False)
        regex_enabled = self.settings_manager.get("filters", "regex_search", False)
        custom_extensions = self.settings_manager.get("filters", "custom_extensions", [])
        max_recursive_files = self.settings_manager.get("filters", "max_recursive_files", 10000)
        
        if hasattr(self, 'file_model'):
            self.file_model.case_sensitive_search = case_sensitive
            self.file_model.regex_search = regex_enabled
            self.file_model.max_recursive_files = max_recursive_files
            
            # Apply custom extensions (check if method exists - for compatibility)
            if custom_extensions and hasattr(self.file_model, 'set_custom_extensions'):
                self.file_model.set_custom_extensions(custom_extensions)
                if DEBUG_MODE:
                    print(f"[Browser] Custom extensions loaded: {custom_extensions}")
            elif custom_extensions:
                print(f"[Browser] Warning: set_custom_extensions not available. Please reload the module.")
            
            # Refresh search if text is present
            if self.file_model.filter_text:
                self.file_model.refresh()
            if DEBUG_MODE:
                print(f"[Browser] Search settings: case_sensitive={case_sensitive}, regex={regex_enabled}")
        
            if DEBUG_MODE:
                print("[Browser] Settings applied successfully")
        self.safe_show_status("Settings applied", 3000)
    
    def restore_browser_state(self):
        """Restore sort and filter state from last session"""
        if not hasattr(self, 'file_model'):
            return
        
        # Restore sort settings from config.json (session state)
        sort_column = self.config.config.get("sort_column", "name")
        sort_ascending = self.config.config.get("sort_ascending", True)
        self.file_model.sort_column = sort_column
        self.file_model.sort_ascending = sort_ascending
        
        # Restore filter settings from config.json (session state)
        filter_file_types = self.config.config.get("filter_file_types", [])
        show_folders = self.config.config.get("show_folders", True)
        filter_min_size = self.config.config.get("filter_min_size", 0)
        filter_max_size = self.config.config.get("filter_max_size", 0)
        
        self.file_model.filter_file_types = filter_file_types
        self.file_model.show_folders = show_folders
        self.file_model.filter_min_size = filter_min_size
        self.file_model.filter_max_size = filter_max_size
        
        # Restore date filters (convert from ISO string to datetime)
        date_from_str = self.config.config.get("filter_date_from", None)
        date_to_str = self.config.config.get("filter_date_to", None)
        
        if date_from_str:
            try:
                self.file_model.filter_date_from = datetime.fromisoformat(date_from_str)
            except (ValueError, TypeError):
                self.file_model.filter_date_from = None
        else:
            self.file_model.filter_date_from = None
        
        if date_to_str:
            try:
                self.file_model.filter_date_to = datetime.fromisoformat(date_to_str)
            except (ValueError, TypeError):
                self.file_model.filter_date_to = None
        else:
            self.file_model.filter_date_to = None
        
        # Update UI to reflect restored state
        self.update_sort_indicators()
        self.update_filter_visual_feedback()
        
        if DEBUG_MODE:
            print(f"[Browser] Restored browser state: sort={sort_column} {'↑' if sort_ascending else '↓'}, "
                  f"filters={len(filter_file_types)} types, folders={'on' if show_folders else 'off'}")
    
    def clear_thumbnail_cache(self):
        """Clear thumbnail cache from menu"""
        reply = QtWidgets.QMessageBox.question(
            self, "Clear Cache",
            "Are you sure you want to clear the thumbnail cache?\nThumbnails will be regenerated on next view.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                # Clear memory cache
                if hasattr(self, 'memory_cache'):
                    self.memory_cache.clear()
                
                # Clear disk cache
                if hasattr(self, 'disk_cache'):
                    cache_dir = Path.home() / ".ddContentBrowser" / "cache"
                    if cache_dir.exists():
                        import shutil
                        shutil.rmtree(cache_dir)
                        cache_dir.mkdir(parents=True, exist_ok=True)
                
                QtWidgets.QMessageBox.information(self, "Success", "Thumbnail cache cleared successfully!")
                self.safe_show_status("Cache cleared", 3000)
                
                # Request thumbnail regeneration
                QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", f"Failed to clear cache: {e}")
    
    # ========== Quick View System ==========
    
    def eventFilter(self, obj, event):
        """Event filter for handling Ctrl+Scroll zoom, Space key for Quick View, MMB drag for Favorites reordering, AND viewport paint measurement"""
        
        # === FILE LIST VIEWPORT RESIZE - Request thumbnails for newly visible items ===
        if hasattr(self, 'file_list') and obj == self.file_list.viewport():
            if event.type() == QtCore.QEvent.Resize:
                # Use timer to debounce rapid resize events (during splitter drag)
                if hasattr(self, '_viewport_resize_timer'):
                    self._viewport_resize_timer.stop()
                
                self._viewport_resize_timer = QTimer()
                self._viewport_resize_timer.setSingleShot(True)
                self._viewport_resize_timer.timeout.connect(self.request_thumbnails_for_visible_items)
                self._viewport_resize_timer.start(100)  # Wait 100ms after resize stops
                return False
        
        # === FAVORITES LIST RESIZE - Update elided text ===
        if hasattr(self, 'favorites_list') and obj == self.favorites_list.viewport():
            if event.type() == QtCore.QEvent.Resize:
                self.update_favorites_eliding()
                return False
        
        # === FAVORITES LIST MIDDLE MOUSE BUTTON DRAG ===
        if hasattr(self, 'favorites_list') and obj == self.favorites_list.viewport():
            # Middle mouse button press - enable drag
            if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == Qt.MiddleButton:
                self.favorites_list.setDragEnabled(True)
                # Start drag with middle button (simulate left button press for drag)
                # Store that we're in MMB drag mode
                self._favorites_mmb_dragging = True
                if DEBUG_MODE:
                    print("[Browser] Favorites MMB drag enabled")
                return False  # Let Qt handle the drag
            
            # Middle mouse button release - disable drag
            if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.MiddleButton:
                self.favorites_list.setDragEnabled(False)
                self._favorites_mmb_dragging = False
                if DEBUG_MODE:
                    print("[Browser] Favorites MMB drag disabled")
                return False
            
            # If we're in MMB drag mode and mouse moves, this might be a drag operation
            if event.type() == QtCore.QEvent.MouseMove and getattr(self, '_favorites_mmb_dragging', False):
                # Qt will handle the drag, just ensure it's enabled
                if not self.favorites_list.dragEnabled():
                    self.favorites_list.setDragEnabled(True)
        
        # Check if event is from file list or its viewport (only if file_list exists)
        if hasattr(self, 'file_list') and (obj == self.file_list or obj == self.file_list.viewport()):
            # === VIEWPORT PAINT PERFORMANCE MEASUREMENT ===
            # Measure viewport paint times during splitter drag
            if obj == self.file_list.viewport() and event.type() == QtCore.QEvent.Paint:
                # Check if we're in the middle of a drag (move_count > 0)
                if getattr(self, '_splitter_move_count', 0) > 0:
                    import time
                    paint_start = time.time()
                    # Let the paint happen
                    result = super(DDContentBrowser, self).eventFilter(obj, event)
                    paint_duration = (time.time() - paint_start) * 1000  # Convert to ms
                    self._viewport_paint_times.append(paint_duration)
                    return result
                    return result
            
            # === CTRL+SCROLL ZOOM ===
            # Check for wheel event with Ctrl modifier
            try:
                wheel_type = QtCore.QEvent.Type.Wheel if hasattr(QtCore.QEvent, 'Type') else QtCore.QEvent.Wheel
            except:
                wheel_type = QtCore.QEvent.Wheel
            
            if event.type() == wheel_type:
                modifiers = QtWidgets.QApplication.keyboardModifiers()
                
                if modifiers == Qt.ControlModifier:
                    # Zoom works in both grid and list mode
                    # Get wheel delta (positive = scroll up, negative = scroll down)
                    delta = event.angleDelta().y()
                    
                    # Define size steps based on current view mode
                    if self.grid_mode_btn.isChecked():
                        # Grid mode: 32px minimum
                        sizes = [32, 64, 96, 128, 160, 192, 224, 256]
                    else:
                        # List mode: can go down to 16px for very compact view
                        sizes = [16, 24, 32, 64, 96, 128, 160, 192, 224, 256]
                    
                    # Get current ACTUAL thumbnail size (not slider value which might be mid-snap)
                    current_size = getattr(self, 'thumbnail_size', self.size_slider.value())
                    
                    # Find current index
                    try:
                        current_index = sizes.index(current_size)
                    except ValueError:
                        # If not in list, find closest
                        current_index = min(range(len(sizes)), key=lambda i: abs(sizes[i] - current_size))
                    
                    # Adjust index (scroll up = zoom in, scroll down = zoom out)
                    if delta > 0:
                        new_index = min(current_index + 1, len(sizes) - 1)
                    else:
                        new_index = max(current_index - 1, 0)
                    
                    new_size = sizes[new_index]
                    
                    # Update only if changed
                    if new_size != current_size:
                        # Block signals to prevent double-snapping
                        self.size_slider.blockSignals(True)
                        self.size_slider.setValue(new_size)
                        self.size_slider.blockSignals(False)
                        
                        # Manually trigger the size change
                        self.on_size_slider_changed(new_size)
                        
                        if DEBUG_MODE:
                            print(f"[Browser] Ctrl+Scroll zoom to {new_size}px")
                    
                    return True  # Event handled, prevent scrolling
            
            # === SPACE KEY FOR QUICK VIEW ===
            if event.type() == QtCore.QEvent.KeyPress and event.key() == Qt.Key_Space:
                # If there are selected files, open quick view and consume the event
                selected = self.get_selected_assets()
                if selected:
                    self.toggle_quick_view()
                    return True
        
        return super().eventFilter(obj, event)
    
    def toggle_quick_view(self):
        """Toggle Quick View window (Space key)"""
        from .quick_view import QuickViewWindow
        
        # Create window if doesn't exist
        if self.quick_view_window is None:
            self.quick_view_window = QuickViewWindow(self)
            self.quick_view_window.closed.connect(self.on_quick_view_closed)
            
            if DEBUG_MODE:
                if DEBUG_MODE:
                    print("[Browser] Quick View window created")
        
        # Toggle visibility
        is_visible = self.quick_view_window.isVisible()
        
        if is_visible:
            self.quick_view_window.close()
        else:
            # Get selected assets
            assets = self.get_selected_assets()
            
            if assets:
                self.quick_view_window.show_preview(assets)
                self.quick_view_window.show()
                self.quick_view_window.raise_()
                
                # Focus behavior: In Maya, keep focus on browser for keyboard navigation
                # In standalone, let Quick View get focus for better UX
                if MAYA_AVAILABLE:
                    # DON'T activate Quick View - keep focus on browser
                    self.activateWindow()
                    self.file_list.setFocus()
                else:
                    # Standalone: activate Quick View for immediate keyboard control
                    self.quick_view_window.activateWindow()
                
                if DEBUG_MODE:
                    if DEBUG_MODE:
                        print(f"[Browser] Quick View opened with {len(assets)} asset(s)")
    
    def on_quick_view_closed(self):
        """Handle Quick View window closed"""
        if DEBUG_MODE:
            if DEBUG_MODE:
                print("[Browser] Quick View closed")
    
    def update_quick_view(self):
        """Update Quick View if it's visible and not pinned"""
        if self.quick_view_window and self.quick_view_window.isVisible():
            if not self.quick_view_window.pinned:
                assets = self.get_selected_assets()
                if DEBUG_MODE:
                    asset_names = [Path(a.file_path).name for a in assets] if assets else []
                    if DEBUG_MODE:
                        print(f"[Browser] update_quick_view: Updating with {len(assets)} asset(s): {asset_names}")
                if assets:
                    self.quick_view_window.show_preview(assets)
    
    # ========== Window Close ==========
    
    def closeEvent(self, event):
        """Save configuration before closing window"""
        global _content_browser_instance
        
        # Close Quick View if open
        if self.quick_view_window and self.quick_view_window.isVisible():
            self.quick_view_window.close()
        
        # Cleanup preview panel (stop video playback, etc.)
        if hasattr(self, 'preview_panel') and self.preview_panel:
            self.preview_panel.cleanup()
        
        # Disconnect thumbnail generator signals BEFORE stopping (prevents RuntimeError)
        if hasattr(self, 'thumbnail_generator'):
            try:
                self.thumbnail_generator.thumbnail_ready.disconnect()
                self.thumbnail_generator.progress_update.disconnect()
                self.thumbnail_generator.generation_failed.disconnect()
                if hasattr(self.thumbnail_generator, 'cache_status'):
                    self.thumbnail_generator.cache_status.disconnect()
            except:
                pass  # Already disconnected or never connected
            
            # Now stop the thread
            self.thumbnail_generator.stop()
            self.thumbnail_generator.wait(5000)  # Wait max 5 seconds for graceful shutdown
            
            # Force quit if still running
            if self.thumbnail_generator.isRunning():
                self.thumbnail_generator.quit()
                self.thumbnail_generator.wait(1000)  # Wait another second
        
        # Save geometry
        geometry = self.saveGeometry().toBase64().data().decode()
        self.config.config["window_geometry"] = geometry
        
        # Save main splitter position
        if hasattr(self, 'content_splitter'):
            splitter_state = self.content_splitter.saveState().toBase64().data().decode()
            self.config.config["splitter_position"] = splitter_state
        
        # Save nav panel splitter position
        if hasattr(self, 'nav_splitter'):
            nav_splitter_state = self.nav_splitter.saveState().toBase64().data().decode()
            self.config.config["nav_splitter_position"] = nav_splitter_state
        
        # Save sort and filter state to config.json (session state)
        if hasattr(self, 'file_model'):
            self.config.config["sort_column"] = self.file_model.sort_column
            self.config.config["sort_ascending"] = self.file_model.sort_ascending
            self.config.config["filter_file_types"] = self.file_model.filter_file_types
            self.config.config["show_folders"] = self.file_model.show_folders
            self.config.config["filter_min_size"] = self.file_model.filter_min_size
            self.config.config["filter_max_size"] = self.file_model.filter_max_size
            
            # Convert datetime to ISO string for JSON serialization
            date_from_str = self.file_model.filter_date_from.isoformat() if self.file_model.filter_date_from else None
            date_to_str = self.file_model.filter_date_to.isoformat() if self.file_model.filter_date_to else None
            self.config.config["filter_date_from"] = date_from_str
            self.config.config["filter_date_to"] = date_to_str
        
        self.config.save_config()
        
        # Clear singleton instance so next open will reload modules
        _content_browser_instance = None
        
        event.accept()
    
    # Keyboard shortcut handlers
    
    def refresh_current_folder(self):
        """Refresh current folder (F5) - Force refresh bypasses cache"""
        # CLEAR thumbnail generator queue when refreshing
        if hasattr(self, 'thumbnail_generator'):
            self.thumbnail_generator.clear_queue()
        
        self.file_model.refresh(force=True)
        self.safe_show_status("Refreshed (cache bypassed)")
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
    
    def navigate_to_parent(self):
        """Navigate to parent folder (Backspace)"""
        if self.breadcrumb.current_path:
            current = Path(self.breadcrumb.current_path)
            parent = current.parent
            if parent != current:  # Has parent
                self.navigate_to_path(parent)
    
    def copy_path_to_clipboard(self):
        """Copy selected file path(s) to clipboard (Ctrl+C)"""
        assets = self.get_selected_assets()
        if not assets:
            # If no file selected, copy current folder path
            if self.breadcrumb.current_path:
                QtWidgets.QApplication.clipboard().setText(self.breadcrumb.current_path)
                self.safe_show_status(f"Copied to clipboard: {self.breadcrumb.current_path}")
            return
        
        if len(assets) == 1:
            # Single selection - copy just the path
            path = str(assets[0].file_path)
            QtWidgets.QApplication.clipboard().setText(path)
            self.safe_show_status(f"Copied to clipboard: {assets[0].name}")
        else:
            # Multiple selection - copy all paths, each on a new line
            paths = [str(asset.file_path) for asset in assets]
            combined_paths = '\n'.join(paths)
            QtWidgets.QApplication.clipboard().setText(combined_paths)
            self.safe_show_status(f"Copied {len(assets)} paths to clipboard")
    
    def copy_filename_to_clipboard(self):
        """Copy selected filename(s) to clipboard (without path)"""
        assets = self.get_selected_assets()
        if not assets:
            self.safe_show_status("No file selected")
            return
        
        if len(assets) == 1:
            # Single selection - copy just the filename
            filename = assets[0].name
            QtWidgets.QApplication.clipboard().setText(filename)
            self.safe_show_status(f"Copied filename: {filename}")
        else:
            # Multiple selection - copy all filenames, each on a new line
            filenames = [asset.name for asset in assets]
            combined_filenames = '\n'.join(filenames)
            QtWidgets.QApplication.clipboard().setText(combined_filenames)
            self.safe_show_status(f"Copied {len(assets)} filenames to clipboard")
    
    def delete_selected_files(self):
        """Delete selected files and folders (Delete key)"""
        assets = self.get_selected_assets()
        if not assets:
            self.safe_show_status("No file selected")
            return
        
        # Confirmation dialog
        file_names = ", ".join([a.name for a in assets[:3]])
        if len(assets) > 3:
            file_names += f" and {len(assets) - 3} more"
        
        # Count files vs folders for better message
        file_count = sum(1 for a in assets if not a.is_folder)
        folder_count = sum(1 for a in assets if a.is_folder)
        
        if folder_count > 0 and file_count > 0:
            msg = f"Are you sure you want to delete:\n{file_names}?\n\n({file_count} file(s) and {folder_count} folder(s))"
        elif folder_count > 0:
            msg = f"Are you sure you want to delete:\n{file_names}?\n\n({folder_count} folder(s) and their contents)"
        else:
            msg = f"Are you sure you want to delete:\n{file_names}?"
        
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Files",
            msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            # Clear preview panel to release any file handles (important for videos!)
            if hasattr(self, 'preview_panel') and self.preview_panel:
                try:
                    self.preview_panel.show_empty_state()
                    # Force process events to ensure cleanup is complete
                    QtWidgets.QApplication.processEvents()
                except Exception as e:
                    print(f"[DELETE] Warning: Error clearing preview panel: {e}")
            
            deleted_count = 0
            failed_files = []
            
            for asset in assets:
                file_path = str(asset.file_path)
                
                try:
                    if asset.is_folder:
                        # Delete folder (with all contents if not empty)
                        shutil.rmtree(file_path)
                    else:
                        # Delete file
                        os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    failed_files.append((asset.name, str(e)))
            
            # Show results
            if deleted_count > 0:
                self.safe_show_status(f"Deleted {deleted_count} item(s)")
                self.refresh_current_folder()
            
            # Show detailed error if some files failed
            if failed_files:
                error_msg = f"Failed to delete {len(failed_files)} item(s):\n\n"
                for name, error in failed_files[:5]:  # Show first 5 errors
                    error_msg += f"• {name}: {error}\n"
                if len(failed_files) > 5:
                    error_msg += f"\n...and {len(failed_files) - 5} more"
                
                QtWidgets.QMessageBox.warning(
                    self,
                    "Delete Errors",
                    error_msg
                )
    
    def rename_selected_file(self):
        """Rename selected file (F2)"""
        assets = self.get_selected_assets()
        if not assets:
            self.safe_show_status("No file selected")
            return
        
        if len(assets) > 1:
            self.safe_show_status("Can only rename one file at a time")
            return
        
        asset = assets[0]
        old_name = asset.name
        
        # Input dialog for new name
        new_name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Rename File",
            "New name:",
            QtWidgets.QLineEdit.Normal,
            old_name
        )
        
        if ok and new_name and new_name != old_name:
            try:
                new_path = asset.file_path.parent / new_name
                asset.file_path.rename(new_path)
                self.safe_show_status(f"Renamed: {old_name} → {new_name}")
                self.refresh_current_folder()
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Rename Error",
                    f"Could not rename file:\n{e}"
                )
    
    def show_context_menu(self, position):
        """Show context menu for file list"""
        # Get item at position
        index = self.file_list.indexAt(position)
        
        # Check if Ctrl is held - if yes, always show empty space menu
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        force_empty_menu = (modifiers == Qt.ControlModifier)
        
        # Create menu
        menu = QtWidgets.QMenu(self)
        
        if index.isValid() and not force_empty_menu:
            # Get asset
            asset = self.file_model.data(index, Qt.UserRole)
            
            if asset:
                if asset.is_folder:
                    # Folder context menu
                    open_action = menu.addAction("📁 Open Folder")
                    open_action.triggered.connect(lambda: self.navigate_to_path(asset.file_path))
                    
                    menu.addSeparator()
                    
                    add_fav_action = menu.addAction("⭐ Add to Favorites")
                    add_fav_action.triggered.connect(lambda: self.add_folder_to_favorites(asset.file_path))
                else:
                    # File context menu
                    import_action = menu.addAction("📥 Import")
                    import_action.triggered.connect(self.import_selected_file)
                    
                    # Reference option only for Maya files (not for shaders like .sbsar)
                    if asset.is_maya_file:
                        reference_action = menu.addAction("🔗 Reference")
                        reference_action.triggered.connect(self.reference_selected_file)
                    
                    open_action = menu.addAction("📂 Open")
                    open_action.triggered.connect(self.open_selected_files)
                    
                    menu.addSeparator()
                
                # Common actions for both files and folders
                open_explorer_action = menu.addAction("📁 Open in Explorer")
                open_explorer_action.triggered.connect(lambda: self.open_in_explorer(asset.file_path))
                
                # Show in Content Browser (only if in collection mode, subfolder mode, or search mode)
                if self.file_model.collection_mode or self.file_model.include_subfolders or self.file_model.search_in_subfolders:
                    show_in_browser_action = menu.addAction("🔍 Show in Content Browser")
                    show_in_browser_action.triggered.connect(lambda: self.show_in_content_browser(asset.file_path))
                
                # Dynamic Copy Path text based on selection count
                selected_assets = self.get_selected_assets()
                if len(selected_assets) > 1:
                    copy_path_text = f"📋 Copy {len(selected_assets)} Paths"
                    copy_filename_text = f"📝 Copy {len(selected_assets)} Filenames"
                else:
                    copy_path_text = "📋 Copy Path"
                    copy_filename_text = "📝 Copy Filename"
                
                copy_path_action = menu.addAction(copy_path_text)
                copy_path_action.triggered.connect(self.copy_path_to_clipboard)
                copy_path_action.setShortcut("Ctrl+C")
                
                copy_filename_action = menu.addAction(copy_filename_text)
                copy_filename_action.triggered.connect(self.copy_filename_to_clipboard)
                
                menu.addSeparator()
                
                # Add to Collection submenu (for both files and folders)
                self.add_collection_submenu(menu, selected_assets)
                
                # Remove from Collection (only if in collection mode)
                if self.file_model.collection_mode:
                    remove_action = menu.addAction("➖ Remove from Collection")
                    remove_action.triggered.connect(lambda: self.remove_files_from_current_collection(selected_assets))
                
                menu.addSeparator()
                
                rename_action = menu.addAction("✏️ Rename")
                rename_action.triggered.connect(self.rename_selected_file)
                rename_action.setShortcut("F2")
                
                delete_action = menu.addAction("🗑️ Delete")
                delete_action.triggered.connect(self.delete_selected_files)
                delete_action.setShortcut("Del")
                
                menu.addSeparator()
                
                # Regenerate thumbnail (only for files with thumbnails)
                if not asset.is_folder:
                    regen_thumb_text = f"🔄 Regenerate Thumbnail" if len(selected_assets) == 1 else f"🔄 Regenerate {len(selected_assets)} Thumbnails"
                    regen_thumb_action = menu.addAction(regen_thumb_text)
                    regen_thumb_action.triggered.connect(self.regenerate_selected_thumbnails)
                    
                    # Auto-detect Color Space (only for HDR/EXR/TX files)
                    hdr_files = [a for a in selected_assets if str(a.file_path).lower().endswith(('.exr', '.hdr', '.tx'))]
                    if hdr_files:
                        auto_tag_text = f"🎨 Auto-detect Color Space" if len(hdr_files) == 1 else f"🎨 Auto-detect Color Space ({len(hdr_files)} files)"
                        auto_tag_action = menu.addAction(auto_tag_text)
                        auto_tag_action.triggered.connect(self.auto_detect_colorspace_for_selected)
                    
                    menu.addSeparator()
                
                properties_action = menu.addAction("ℹ️ Properties")
                properties_action.triggered.connect(lambda: self.show_file_properties(asset))
        else:
            # Empty space context menu
            refresh_action = menu.addAction("🔄 Refresh")
            refresh_action.triggered.connect(self.refresh_current_folder)
            refresh_action.setShortcut("F5")
            
            menu.addSeparator()
            
            # Open current folder in Explorer
            if self.file_model.current_path:
                open_explorer_action = menu.addAction("📁 Open in Explorer")
                open_explorer_action.triggered.connect(lambda: self.open_folder_in_explorer(self.file_model.current_path))
            
            menu.addSeparator()
            
            paste_action = menu.addAction("📋 Paste Path and Navigate")
            paste_action.triggered.connect(self.paste_path_from_clipboard)
            
            add_current_fav_action = menu.addAction("⭐ Add Current Folder to Favorites")
            add_current_fav_action.triggered.connect(self.add_current_to_favorites)
        
        # Show menu at cursor position
        menu.exec_(self.file_list.viewport().mapToGlobal(position))
    
    def open_in_explorer(self, path):
        """Open file/folder in system file explorer and select it"""
        import subprocess
        
        path = Path(path)
        
        try:
            if sys.platform == 'win32':
                # Windows - use /select, parameter to select the file/folder
                subprocess.Popen(['explorer', '/select,', str(path)])
            elif sys.platform == 'darwin':
                # macOS - use -R flag to reveal in Finder
                subprocess.Popen(['open', '-R', str(path)])
            else:
                # Linux - xdg-open doesn't support selecting, just open parent
                subprocess.Popen(['xdg-open', str(path.parent)])
            
            self.safe_show_status(f"Opened in Explorer: {path.name}")
        except Exception as e:
            self.safe_show_status(f"Could not open in Explorer: {e}")
    
    def open_folder_in_explorer(self, folder_path):
        """Open folder in system file explorer (not selecting it, but opening it)"""
        import subprocess
        
        folder_path = Path(folder_path)
        
        try:
            if sys.platform == 'win32':
                # Windows - just open the folder without /select
                subprocess.Popen(['explorer', str(folder_path)])
            elif sys.platform == 'darwin':
                # macOS - open the folder
                subprocess.Popen(['open', str(folder_path)])
            else:
                # Linux
                subprocess.Popen(['xdg-open', str(folder_path)])
            
            self.safe_show_status(f"Opened folder in Explorer: {folder_path.name}")
        except Exception as e:
            self.safe_show_status(f"Could not open folder in Explorer: {e}")
    
    def show_in_content_browser(self, file_path):
        """Navigate to the file's parent directory and select the file in content browser"""
        from pathlib import Path
        
        file_path = Path(file_path)
        
        # If it's a folder, just navigate to it
        if file_path.is_dir():
            self.navigate_to_path(file_path)
            self.safe_show_status(f"Navigated to: {file_path.name}")
            return
        
        # For files, navigate to parent directory
        parent_dir = file_path.parent
        if not parent_dir.exists():
            self.safe_show_status(f"Parent directory not found: {parent_dir}")
            return
        
        # Exit collection mode if active
        if self.file_model.collection_mode:
            self.on_collection_cleared()
        
        # Interrupt any ongoing search before mode changes
        self.file_model.interrupt_search()
        
        # Delay the rest to let interrupt take effect
        QTimer.singleShot(50, lambda: self._finish_show_in_browser(parent_dir, file_path))
    
    def _finish_show_in_browser(self, parent_dir, file_path):
        """Finish showing file in browser after interrupt has taken effect"""
        # Disable subfolder mode if active
        if self.include_subfolders_checkbox.isChecked():
            self.include_subfolders_checkbox.setChecked(False)
            self.file_model.include_subfolders = False
        
        # Disable search in subfolders mode if active
        if self.search_bar.subfolders_checkbox.isChecked():
            self.search_bar.subfolders_checkbox.setChecked(False)
            self.file_model.search_in_subfolders = False
        
        # Clear search text if present
        if self.search_bar.search_input.text():
            self.search_bar.search_input.clear()
        
        # Navigate to parent directory
        self.navigate_to_path(parent_dir)
        
        # Wait for the model to update, then select the file
        def select_file():
            # Find the file in the current view
            for row in range(self.file_model.rowCount()):
                index = self.file_model.index(row, 0)
                asset = self.file_model.data(index, Qt.UserRole)
                if asset:
                    asset_path = Path(asset.file_path)
                    if asset_path == file_path:
                        # Clear selection and select this item
                        self.file_list.clearSelection()
                        self.file_list.setCurrentIndex(index)
                        self.file_list.scrollTo(index)
                        self.file_list.setFocus()
                        self.safe_show_status(f"Found and selected: {file_path.name}")
                        return
            
            self.safe_show_status(f"File shown in directory: {file_path.name}")
        
        # Delay selection to ensure view is updated
        QTimer.singleShot(300, select_file)
    
    def regenerate_selected_thumbnails(self):
        """Regenerate thumbnails for selected files by clearing their cache entries"""
        selected_assets = self.get_selected_assets()
        
        if not selected_assets:
            return
        
        # Filter out folders - only regenerate for files
        file_assets = [asset for asset in selected_assets if not asset.is_folder]
        
        if not file_assets:
            self.safe_show_status("No files selected for thumbnail regeneration")
            return
        
        # Clear thumbnail cache for each file (and all frames if sequence)
        cleared_count = 0
        for asset in file_assets:
            try:
                # If it's a sequence, clear cache for all frames
                if asset.is_sequence and asset.sequence:
                    for frame_path in asset.sequence.files:
                        if self.disk_cache.clear_thumbnail(frame_path):
                            cleared_count += 1
                else:
                    # Single file
                    if self.disk_cache.clear_thumbnail(asset.file_path):
                        cleared_count += 1
            except Exception as e:
                print(f"Failed to clear cache for {asset.file_path}: {e}")
        
        # Show status
        if cleared_count > 0:
            plural = "s" if cleared_count > 1 else ""
            self.safe_show_status(f"Cleared {cleared_count} thumbnail{plural} - regenerating...")
            
            # Clear in-memory cache too (including sequence pattern keys)
            self.memory_cache.clear()
            
            # Clear delegate's scaled pixmap cache (CRITICAL for UI refresh!)
            self.thumbnail_delegate._scaled_cache.clear()
            
            # Request thumbnail regeneration for visible items
            # Use a longer delay to ensure caches are fully cleared
            QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
            
            # Force delegate redraw by emitting dataChanged (no viewport().update() needed)
            model = self.file_list.model()
            if model and model.rowCount() > 0:
                top_left = model.index(0, 0)
                bottom_right = model.index(model.rowCount() - 1, 0)
                model.dataChanged.emit(top_left, bottom_right)
        else:
            self.safe_show_status("No thumbnails were cleared")
    
    def auto_detect_colorspace_for_selected(self):
        """Auto-detect and apply color space tags for selected HDR/EXR/TX files"""
        selected_assets = self.get_selected_assets()
        
        if not selected_assets:
            return
        
        # Filter HDR/EXR/TX files only
        hdr_files = [asset for asset in selected_assets 
                     if not asset.is_folder and 
                     str(asset.file_path).lower().endswith(('.exr', '.hdr', '.tx'))]
        
        if not hdr_files:
            self.safe_show_status("No HDR/EXR/TX files selected")
            return
        
        # Run auto-tagging on each file
        from .aces_color import auto_tag_file_colorspace
        
        tagged_count = 0
        for asset in hdr_files:
            try:
                result = auto_tag_file_colorspace(asset.file_path, self.metadata_manager)
                if result:
                    tagged_count += 1
            except Exception as e:
                # Silent fail for individual files
                pass
        
        # Show status
        if tagged_count > 0:
            plural = "s" if tagged_count > 1 else ""
            self.safe_show_status(f"Auto-tagged {tagged_count} file{plural} with color space")
            
            # Refresh preview if one of the tagged files is currently displayed
            if self.preview_panel and self.preview_panel.current_hdr_path:
                current_path = str(self.preview_panel.current_hdr_path)
                if any(str(asset.file_path) == current_path for asset in hdr_files):
                    # Clear raw cache for this file to force reload with new color management
                    if current_path in self.preview_panel.hdr_raw_cache:
                        del self.preview_panel.hdr_raw_cache[current_path]
                    # Clear preview cache too
                    if current_path in self.preview_panel.preview_cache:
                        del self.preview_panel.preview_cache[current_path]
                    # Reload preview with new tags
                    selected_indices = self.file_list.selectionModel().selectedIndexes()
                    if selected_indices:
                        # Get the asset for the selected index
                        asset = self.file_model.data(selected_indices[0], Qt.UserRole)
                        if asset and not asset.is_folder:
                            # Use update_preview with list of assets
                            self.preview_panel.update_preview([asset])
        else:
            self.safe_show_status("No files were tagged (already have color space tags)")
    
    def add_folder_to_favorites(self, path):
        """Add folder to favorites"""
        path_str = str(path)
        normalized_path = str(Path(path_str).resolve())
        
        # Check if already in favorites
        existing_normalized = [str(Path(p).resolve()) for p in self.config.config["favorites"]]
        
        if normalized_path not in existing_normalized:
            self.config.config["favorites"].append(path_str)
            self.config.save_config()
            self.update_favorites_list()
            self.safe_show_status(f"Added to favorites: {Path(path_str).name}")
        else:
            self.safe_show_status(f"Already in favorites: {Path(path_str).name}")
    
    def show_file_properties(self, asset):
        """Show file properties dialog"""
        info = f"""
File: {asset.name}
Path: {asset.file_path.parent}
Size: {asset.get_size_string()}
Modified: {asset.get_modified_string()}
Type: {'Folder' if asset.is_folder else asset.extension.upper()[1:] + ' File'}
        """
        
        QtWidgets.QMessageBox.information(
            self,
            f"Properties - {asset.name}",
            info.strip()
        )
    
    def paste_path_from_clipboard(self):
        """Navigate to path from clipboard"""
        clipboard_text = QtWidgets.QApplication.clipboard().text().strip()
        
        if clipboard_text:
            path = Path(clipboard_text)
            if path.exists() and path.is_dir():
                self.navigate_to_path(path)
            else:
                self.safe_show_status("Invalid path in clipboard")
    
    def update_filter_visual_feedback(self):
        """Update visual feedback for active filters"""
        # Note: No sync with advanced filters needed - they use exclusive logic
        
        # Check if any filters are active
        model = self.file_model
        has_active_filters = (
            len(model.filter_file_types) > 0 or
            not model.show_folders or  # Folder visibility counts as active filter
            model.filter_min_size > 0 or
            model.filter_max_size > 0 or
            model.filter_date_from is not None or
            model.filter_date_to is not None
        )
        
        # Check specific filter types
        has_type_filters = (len(model.filter_file_types) > 0 or 
                           not model.show_folders)  # Include folder visibility as type filter
        has_size_filters = model.filter_min_size > 0 or model.filter_max_size > 0
        has_date_filters = model.filter_date_from is not None or model.filter_date_to is not None
        
        # Update individual header buttons based on their specific filters
        button_filter_map = []
        if hasattr(self, 'sort_name_btn'):
            button_filter_map.append((self.sort_name_btn, False))  # Name column has no specific filters
        if hasattr(self, 'sort_type_btn'):
            button_filter_map.append((self.sort_type_btn, has_type_filters))
        if hasattr(self, 'sort_size_btn'):
            button_filter_map.append((self.sort_size_btn, has_size_filters))
        if hasattr(self, 'sort_date_btn'):
            button_filter_map.append((self.sort_date_btn, has_date_filters))
        
        for button, has_specific_filter in button_filter_map:
            if has_specific_filter:
                # Subtle blue accent for active filters
                button.setStyleSheet("""
                    QPushButton {
                        background-color: #3a3a3a;
                        border: 1px solid #555;
                        border-left: 3px solid #4b7daa;
                        padding: 3px 8px;
                        text-align: left;
                        font-weight: bold;
                        color: #e0e0e0;
                    }
                    QPushButton:hover {
                        background-color: #4a4a4a;
                        border-left: 3px solid #5a8db8;
                    }
                """)
            else:
                # Reset to default styling
                button.setStyleSheet("""
                    QPushButton {
                        background-color: #3a3a3a;
                        border: 1px solid #555;
                        padding: 3px 8px;
                        text-align: left;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #4a4a4a;
                    }
                """)
        
        # Update Clear Filters button visibility
        if hasattr(self, 'clear_filters_btn'):
            # Hide Clear Filters button if advanced filters are active (they have their own Clear button)
            if self.advanced_filters_active:
                self.clear_filters_btn.setVisible(False)
            else:
                # Show Clear Filters button only if basic filters are active
                self.clear_filters_btn.setVisible(has_active_filters)
    
    def on_advanced_filters_changed(self, active_filters):
        """Handle advanced filter changes"""
        # Refresh visual feedback
        self.update_filter_visual_feedback()
        
        # Count active filters
        filter_count = sum(len(values) for values in active_filters.values())
        file_count = self.file_model.rowCount()
        
        self.safe_show_status(f"Advanced filters: {filter_count} active - {file_count} files shown", 4000)
        
        # Request thumbnails for filtered results
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
        
        if DEBUG_MODE:
            if DEBUG_MODE:
                print(f"[Browser] Advanced filters changed: {filter_count} filters, {file_count} files")
    
    def on_advanced_filters_cleared(self):
        """Handle advanced filters cleared"""
        # Refresh visual feedback
        self.update_filter_visual_feedback()
        
        file_count = self.file_model.rowCount()
        self.safe_show_status(f"Advanced filters cleared - {file_count} files shown", 3000)
        
        # Request thumbnails
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
        
        if DEBUG_MODE:
            if DEBUG_MODE:
                print("[Browser] Advanced filters cleared")
    
    def on_advanced_filters_activated(self, is_active):
        """Handle advanced filters activation state change
        
        Args:
            is_active: True when advanced filters are active, False when cleared
        """
        # Store the state
        self.advanced_filters_active = is_active
        
        # Hide Clear Filters button when advanced filters are active
        if hasattr(self, 'clear_filters_btn'):
            if is_active:
                self.clear_filters_btn.setVisible(False)
            else:
                # Update visibility based on basic filters when advanced filters are cleared
                self.update_filter_visual_feedback()
        
        # Note: Sort buttons remain enabled even when advanced filters are active
        # Only the right-click filter menu is disabled (handled in SortHeaderWidget.mousePressEvent)
        # Users can still sort filtered results by clicking the column headers
        
        if DEBUG_MODE:
            print(f"[Browser] Advanced filters {'activated' if is_active else 'deactivated'} - toolbar filters {'disabled' if is_active else 'enabled'}")
    
    def show_batch_rename_dialog(self):
        """Show batch rename dialog for selected files"""
        selected_assets = self.get_selected_assets()
        if not selected_assets:
            self.safe_show_status("No files selected for rename")
            return
        
        # Filter out folders and collect file paths
        file_paths = []
        for asset in selected_assets:
            if not asset.is_folder:
                file_paths.append(asset.file_path)
        
        if not file_paths:
            self.safe_show_status("No files selected (folders cannot be renamed in batch)")
            return
        
        # Reload the batch_rename module to pick up any changes
        import sys
        if 'ddContentBrowser.batch_rename' in sys.modules:
            del sys.modules['ddContentBrowser.batch_rename']
        
        # Import and show the batch rename dialog
        from .batch_rename import BatchRenameDialog
        dialog = BatchRenameDialog(file_paths, self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            # Refresh the current directory after rename
            self.refresh_current_directory()
    
    def refresh_current_directory(self):
        """Refresh the current directory to show updated file names"""
        if hasattr(self, 'breadcrumb') and self.breadcrumb.current_path:
            # Re-navigate to current path to refresh file list
            current_path = self.breadcrumb.current_path
            self.navigate_to_path(current_path)
    
    # ========== Collection Filter Methods ==========
    
    def on_collection_selected(self, collection_name: str):
        """Handle collection selection - filter files to show only collection items"""
        from .asset_collections import ManualCollection
        
        collection = self.collection_manager.get_collection(collection_name)
        if not collection:
            return
        
        if isinstance(collection, ManualCollection):
            # Get files from collection (only existing files)
            collection_files = collection.get_existing_files()
            
            if not collection_files:
                self.safe_show_status(f"Collection '{collection_name}' is empty")
                return
            
            # Clear all search state (input, progress, match count)
            self.clear_search_state()
            
            # Disable subfolder mode when entering collection
            if self.include_subfolders_checkbox.isChecked():
                self.include_subfolders_checkbox.setChecked(False)
                self.file_model.include_subfolders = False
            
            # Apply collection filter to file model
            self.file_model.setCollectionFilter(collection_files)
            
            # Store current collection name
            self.current_collection_name = collection_name
            
            # Update breadcrumb to show collection name (not path)
            self.breadcrumb.set_collection_mode(collection_name)
            
            # Stop watching directory in collection mode
            watched_dirs = self.file_watcher.directories()
            if watched_dirs:
                self.file_watcher.removePaths(watched_dirs)
            
            # Update status
            self.safe_show_status(f"📁 Collection: {collection_name} ({len(collection_files)} items)")
            
            # Update navigation buttons (enable back button)
            self.update_navigation_buttons()
            
            # Request thumbnails for visible items
            QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
            
            # CRITICAL: Refresh Advanced Filters panel to enable re-analysis
            # This ensures the "Analyze Folder" button works with the new collection items
            if hasattr(self, 'advanced_filters_panel'):
                self.advanced_filters_panel.refresh()
            
            if DEBUG_MODE:
                print(f"[Browser] Applied collection filter: {collection_name}")
    
    def on_collection_cleared(self):
        """Handle collection filter clear - show all files"""
        # CLEAR thumbnail generator queue when clearing collection
        if hasattr(self, 'thumbnail_generator'):
            self.thumbnail_generator.clear_queue()
        
        # Clear all search state BEFORE clearing collection filter
        # This ensures we return to normal folder view, not cached search results
        self.clear_search_state()
        
        # Clear collection filter
        self.file_model.clearCollectionFilter()
        
        # Clear current collection name
        self.current_collection_name = None
        
        # Reset breadcrumb to normal mode
        self.breadcrumb.clear_collection_mode()
        
        # Hide exit collection view button
        self.collections_panel.clear_btn.setVisible(False)
        
        # Resume watching current directory
        if self.breadcrumb.current_path:
            self._update_file_watcher(Path(self.breadcrumb.current_path))
        
        # Update navigation buttons (may disable back button if no history)
        self.update_navigation_buttons()
        
        # Update status
        self.safe_show_status("Returned to folder view")
        
        # Request thumbnails for visible items
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
        
        # CRITICAL: Refresh Advanced Filters panel to enable re-analysis
        # This ensures the "Analyze Folder" button works after returning to folder view
        if hasattr(self, 'advanced_filters_panel'):
            self.advanced_filters_panel.refresh()
        
        if DEBUG_MODE:
            print("[Browser] Cleared collection filter")
    
    def add_collection_submenu(self, parent_menu, selected_assets):
        """Add 'Add to Collection >' submenu with list of manual collections"""
        # Get all manual collections
        manual_collections = self.collection_manager.get_manual_collections()
        
        if not manual_collections:
            # No collections available - show disabled menu item
            no_collections_action = parent_menu.addAction("📁 Add to Collection >")
            no_collections_action.setEnabled(False)
            return
        
        # Create submenu
        collections_submenu = parent_menu.addMenu("📁 Add to Collection")
        
        # Add each manual collection as menu item
        for collection in sorted(manual_collections, key=lambda c: c.name.lower()):
            collection_action = collections_submenu.addAction(f"▸ {collection.name}")
            # Use lambda with default argument to capture collection name
            collection_action.triggered.connect(
                lambda checked=False, coll_name=collection.name: 
                self.add_files_to_collection(coll_name, selected_assets)
            )
    
    def add_files_to_collection(self, collection_name, assets):
        """Add selected files and folders to a collection"""
        from .asset_collections import ManualCollection
        
        collection = self.collection_manager.get_collection(collection_name)
        if not collection or not isinstance(collection, ManualCollection):
            return
        
        # Get file paths from assets (now includes folders too)
        file_paths = [str(asset.file_path) for asset in assets]
        
        if not file_paths:
            return
        
        # Add files and folders to collection
        collection.add_files(file_paths)
        self.collection_manager.save()
        
        # Refresh collections panel to update file count
        self.collections_panel.refresh_collections_list()
        
        # Show feedback
        item_count = len(file_paths)
        item_word = "item" if item_count == 1 else "items"
        self.safe_show_status(f"Added {item_count} {item_word} to collection '{collection_name}'")
        
        if DEBUG_MODE:
            if DEBUG_MODE:
                print(f"[Browser] Added {item_count} items to collection '{collection_name}'")
    
    def remove_files_from_current_collection(self, assets):
        """Remove selected files and folders from the currently active collection"""
        from .asset_collections import ManualCollection
        
        if not self.current_collection_name:
            return
        
        collection = self.collection_manager.get_collection(self.current_collection_name)
        if not collection or not isinstance(collection, ManualCollection):
            return
        
        # Get file paths from assets (now includes folders too)
        file_paths = [str(asset.file_path) for asset in assets]
        
        if not file_paths:
            return
        
        # Remove files and folders from collection
        for file_path in file_paths:
            collection.remove_file(file_path)
        
        self.collection_manager.save()
        
        # Refresh collections panel to update file count
        self.collections_panel.refresh_collections_list()
        
        # Refresh the collection view to remove the items from display
        collection_files = collection.get_existing_files()
        if collection_files:
            self.file_model.setCollectionFilter(collection_files)
        else:
            # Collection is now empty, exit collection mode
            self.on_collection_cleared()
            self.safe_show_status(f"Collection '{self.current_collection_name}' is now empty")
            return
        
        # Show feedback
        item_count = len(file_paths)
        item_word = "item" if item_count == 1 else "items"
        self.safe_show_status(f"Removed {item_count} {item_word} from collection '{self.current_collection_name}'")
        
        # Request thumbnails for remaining visible items
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)
        
        if DEBUG_MODE:
            print(f"[Browser] Removed {item_count} {item_word} from collection '{self.current_collection_name}'")
    
    # ========== File System Watcher Methods ==========
    
    def _update_file_watcher(self, path):
        """Update file system watcher to monitor new directory"""
        # Remove all previously watched directories
        watched_dirs = self.file_watcher.directories()
        if watched_dirs:
            self.file_watcher.removePaths(watched_dirs)
        
        # Add new directory to watch (only in normal browse mode)
        if path and not self.file_model.collection_mode:
            path_str = str(path)
            self.file_watcher.addPath(path_str)
    
    def on_directory_changed(self, path):
        """Handle directory change event from file system watcher"""
        try:
            # Ignore if in collection mode or search mode
            if self.file_model.collection_mode:
                return
            if hasattr(self, 'include_subfolders_checkbox') and self.include_subfolders_checkbox.isChecked():
                return
            if hasattr(self, 'search_input') and self.search_input.text().strip():
                return
            
            # Debounce: only schedule refresh if not already pending
            if not self._watcher_pending_refresh:
                self._watcher_pending_refresh = True
                QTimer.singleShot(300, self._refresh_from_watcher)
            
        except Exception as e:
            import traceback
            print(f"[FileWatcher] ERROR: {e}")
            traceback.print_exc()
    
    def _refresh_from_watcher(self):
        """Refresh directory view after file system change detected"""
        # Reset pending flag
        self._watcher_pending_refresh = False
        
        # Clear thumbnail generator queue
        if hasattr(self, 'thumbnail_generator'):
            self.thumbnail_generator.clear_queue()
        
        # Refresh file model with proper reset signals (force=True to bypass cache)
        self.file_model.beginResetModel()
        self.file_model.refresh(force=True)
        self.file_model.endResetModel()
        
        # Update status
        self.safe_show_status("📂 Directory updated automatically")
        
        # Request thumbnails for visible items
        QTimer.singleShot(100, self.request_thumbnails_for_visible_items)