"""
Settings management for ddContentBrowser
Handles application settings storage, loading, and GUI dialog.
"""

import os
import json
from pathlib import Path

try:
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                                   QWidget, QLabel, QLineEdit, QPushButton, QCheckBox,
                                   QComboBox, QSlider, QSpinBox, QGroupBox, QFileDialog,
                                   QDialogButtonBox, QMessageBox, QTableWidget, QTableWidgetItem,
                                   QHeaderView, QAbstractItemView, QColorDialog, QStyledItemDelegate, QStyle)
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QColor, QLinearGradient, QPen
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                                   QWidget, QLabel, QLineEdit, QPushButton, QCheckBox,
                                   QComboBox, QSlider, QSpinBox, QGroupBox, QFileDialog,
                                   QDialogButtonBox, QMessageBox, QTableWidget, QTableWidgetItem,
                                   QHeaderView, QAbstractItemView, QColorDialog, QStyledItemDelegate, QStyle)
    from PySide2.QtCore import Qt, Signal
    from PySide2.QtGui import QColor, QLinearGradient, QPen
    PYSIDE_VERSION = 2

# Debug flag - set to False to disable verbose logging
DEBUG_MODE = False


class SettingsManager:
    """Manages application settings with JSON persistence"""
    
    def __init__(self):
        # Store settings in user home directory for persistence across updates
        self.settings_dir = Path.home() / ".ddContentBrowser"
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.settings_dir / "settings.json"
        self.settings = self.load_default_settings()
        self.load()
    
    def load_default_settings(self):
        """Return default settings dictionary"""
        return {
            # General settings
            "general": {
                "startup_directory": "",
                "remember_window_size": True,
                "window_width": 1200,
                "window_height": 800,
                "confirm_delete": True,
                "auto_refresh": False,
                "refresh_interval": 5,  # seconds
                "ui_font": "Segoe UI"  # Default UI font family (Windows standard, matches Maya UI)
            },
            # Thumbnail settings
            "thumbnails": {
                "size": 128,
                "memory_cache_size": 2000,  # Number of thumbnails in RAM
                "cache_size_mb": 500,  # Disk cache size in MB
                "quality": "medium",  # low, medium, high
                "generate_for_3d": True,
                "worker_threads": 0  # 0 = Auto-detect based on CPU cores (max 12), 1-12 = manual override
            },
            # Preview settings
            "preview": {
                "resolution": 1024,
                "hdr_cache_size": 5,
                "default_exposure": 0.0,
                "auto_fit": True,
                "background_mode": "dark_gray"  # dark_gray, light_gray, checkered, black, white
            },
            # Filter settings
            "filters": {
                "show_images": True,
                "show_3d": True,
                "show_hdr": True,
                "show_video": True,
                "custom_extensions": [],
                "show_hidden": False,
                "case_sensitive_search": False,
                "regex_search": False,
                "max_recursive_files": 10000,  # Maximum files when browsing subfolders
                "max_search_files": 100000  # Maximum files when searching in subfolders
            },
            # Advanced Filters - saved filter presets
            "advanced_filters": {
                "saved_presets": []  # List of saved filter preset configurations
            }
        }
    
    def load(self):
        """Load settings from JSON file"""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    self._merge_settings(self.settings, loaded)
                if DEBUG_MODE:
                    print(f"[Settings] Loaded from {self.settings_file}")
            except Exception as e:
                print(f"[Settings] Error loading settings: {e}")
                print("[Settings] Using default settings")
    
    def _merge_settings(self, default, loaded):
        """Recursively merge loaded settings with defaults"""
        for key, value in loaded.items():
            if key in default:
                if isinstance(value, dict) and isinstance(default[key], dict):
                    self._merge_settings(default[key], value)
                else:
                    default[key] = value
    
    def save(self):
        """Save settings to JSON file"""
        try:
            # Ensure parent directory exists
            self.settings_dir.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
            if DEBUG_MODE:
                print(f"[Settings] Saved to {self.settings_file}")
            return True
        except Exception as e:
            print(f"[Settings] Error saving settings: {e}")
            return False
    
    def get(self, category, key, default=None):
        """Get a setting value"""
        try:
            return self.settings.get(category, {}).get(key, default)
        except:
            return default
    
    def set(self, category, key, value):
        """Set a setting value and save to disk"""
        if category not in self.settings:
            self.settings[category] = {}
        self.settings[category][key] = value
        # Auto-save after setting value
        self.save()
    
    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        self.settings = self.load_default_settings()
        self.save()


class GeneralSettingsTab(QWidget):
    """General settings tab"""
    
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings = settings_manager
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Startup directory group
        startup_group = QGroupBox("Startup")
        startup_layout = QVBoxLayout()
        
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Startup Directory:"))
        self.startup_dir_edit = QLineEdit(self.settings.get("general", "startup_directory", ""))
        dir_layout.addWidget(self.startup_dir_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_directory)
        dir_layout.addWidget(browse_btn)
        startup_layout.addLayout(dir_layout)
        
        startup_group.setLayout(startup_layout)
        layout.addWidget(startup_group)
        
        # Window settings group
        window_group = QGroupBox("Window")
        window_layout = QVBoxLayout()
        
        self.remember_size_cb = QCheckBox("Remember window size and position")
        self.remember_size_cb.setChecked(self.settings.get("general", "remember_window_size", True))
        window_layout.addWidget(self.remember_size_cb)
        
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Default Size:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(800, 3840)
        self.width_spin.setValue(self.settings.get("general", "window_width", 1200))
        self.width_spin.setSuffix(" px")
        size_layout.addWidget(QLabel("Width:"))
        size_layout.addWidget(self.width_spin)
        
        self.height_spin = QSpinBox()
        self.height_spin.setRange(600, 2160)
        self.height_spin.setValue(self.settings.get("general", "window_height", 800))
        self.height_spin.setSuffix(" px")
        size_layout.addWidget(QLabel("Height:"))
        size_layout.addWidget(self.height_spin)
        size_layout.addStretch()
        window_layout.addLayout(size_layout)
        
        # UI Font selection
        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("UI Font:"))
        self.font_combo = QComboBox()
        self.font_combo.addItems(["Segoe UI", "Arial", "Calibri", "Verdana", "Tahoma"])
        current_font = self.settings.get("general", "ui_font", "Segoe UI")
        index = self.font_combo.findText(current_font)
        if index >= 0:
            self.font_combo.setCurrentIndex(index)
        font_layout.addWidget(self.font_combo)
        font_layout.addWidget(QLabel("(restart required)"))
        font_layout.addStretch()
        window_layout.addLayout(font_layout)
        
        window_group.setLayout(window_layout)
        layout.addWidget(window_group)
        
        # Behavior group
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QVBoxLayout()
        
        self.confirm_delete_cb = QCheckBox("Confirm before deleting files")
        self.confirm_delete_cb.setChecked(self.settings.get("general", "confirm_delete", True))
        behavior_layout.addWidget(self.confirm_delete_cb)
        
        self.auto_refresh_cb = QCheckBox("Auto-refresh directory")
        self.auto_refresh_cb.setChecked(self.settings.get("general", "auto_refresh", False))
        behavior_layout.addWidget(self.auto_refresh_cb)
        
        refresh_layout = QHBoxLayout()
        refresh_layout.addWidget(QLabel("    Refresh interval:"))
        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(1, 60)
        self.refresh_spin.setValue(self.settings.get("general", "refresh_interval", 5))
        self.refresh_spin.setSuffix(" sec")
        refresh_layout.addWidget(self.refresh_spin)
        refresh_layout.addStretch()
        behavior_layout.addLayout(refresh_layout)
        
        behavior_group.setLayout(behavior_layout)
        layout.addWidget(behavior_group)
        
        # Database group
        database_group = QGroupBox("Database")
        database_layout = QVBoxLayout()
        
        # Tag database reset button
        reset_layout = QHBoxLayout()
        reset_layout.addWidget(QLabel("Tag Database:"))
        self.reset_tags_btn = QPushButton("🗑️ Clear All Tag Assignments")
        self.reset_tags_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 6px 12px;
                color: #cccccc;
            }
            QPushButton:hover {
                background-color: #8B0000;
                border-color: #A00000;
                color: white;
            }
            QPushButton:pressed {
                background-color: #6B0000;
            }
        """)
        self.reset_tags_btn.clicked.connect(self.clear_tag_assignments)
        self.reset_tags_btn.setToolTip("Remove all tag assignments from files (tag names are preserved)")
        reset_layout.addWidget(self.reset_tags_btn)
        reset_layout.addStretch()
        database_layout.addLayout(reset_layout)
        
        # Load default tags button
        default_tags_layout = QHBoxLayout()
        default_tags_layout.addWidget(QLabel("Default Tags:"))
        self.load_defaults_btn = QPushButton("📥 Load Default Tags")
        self.load_defaults_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 6px 12px;
                color: #cccccc;
            }
            QPushButton:hover {
                background-color: #2a5a2a;
                border-color: #3a7a3a;
                color: #90EE90;
            }
            QPushButton:pressed {
                background-color: #1a4a1a;
            }
        """)
        self.load_defaults_btn.clicked.connect(self.load_default_tags)
        self.load_defaults_btn.setToolTip("Load default tags from default_tags.json (won't duplicate existing tags)")
        default_tags_layout.addWidget(self.load_defaults_btn)
        default_tags_layout.addStretch()
        database_layout.addLayout(default_tags_layout)
        
        database_group.setLayout(database_layout)
        layout.addWidget(database_group)
        
        layout.addStretch()
    
    def browse_directory(self):
        """Browse for startup directory"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Startup Directory",
                                                     self.startup_dir_edit.text())
        if dir_path:
            self.startup_dir_edit.setText(dir_path)
    
    def clear_tag_assignments(self):
        """Clear all tag assignments but keep tag names"""
        reply = QMessageBox.warning(
            self,
            "⚠️ Clear Tag Assignments",
            "This will remove ALL tag assignments from all files!\n\n"
            "Tag names will be preserved and can be reused.\n\n"
            "This cannot be undone!\n\n"
            "Are you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            mm.clear_all_tag_assignments()
            
            QMessageBox.information(
                self,
                "Success",
                "All tag assignments have been cleared.\n\n"
                "Tag names are preserved and available for reuse."
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to clear tag assignments:\n{str(e)}"
            )
    
    def load_default_tags(self):
        """Load default tags from default_tags.json"""
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            
            added_count = mm.load_default_tags()
            
            if added_count > 0:
                QMessageBox.information(
                    self,
                    "Success",
                    f"Loaded {added_count} default tags!\n\n"
                    "Tags are now available in the Browse Tags dialog."
                )
            else:
                QMessageBox.information(
                    self,
                    "No Changes",
                    "All default tags are already loaded.\n\n"
                    "No new tags were added."
                )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load default tags:\n{str(e)}"
            )
    
    def save_settings(self):
        """Save settings from UI to settings manager"""
        self.settings.set("general", "startup_directory", self.startup_dir_edit.text())
        self.settings.set("general", "remember_window_size", self.remember_size_cb.isChecked())
        self.settings.set("general", "window_width", self.width_spin.value())
        self.settings.set("general", "window_height", self.height_spin.value())
        self.settings.set("general", "ui_font", self.font_combo.currentText())
        self.settings.set("general", "confirm_delete", self.confirm_delete_cb.isChecked())
        self.settings.set("general", "auto_refresh", self.auto_refresh_cb.isChecked())
        self.settings.set("general", "refresh_interval", self.refresh_spin.value())


class ThumbnailSettingsTab(QWidget):
    """Thumbnail settings tab"""
    
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings = settings_manager
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Size group
        size_group = QGroupBox("Thumbnail Generation Size")
        size_layout = QVBoxLayout()
        
        # Add explanation label
        explanation = QLabel(
            "Set the resolution of generated thumbnail files (cached to disk).\n"
            "Higher = better quality when zooming, but larger cache size.\n"
            "Note: Grid/List display size is adjusted separately with the toolbar slider."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("QLabel { color: #888; font-size: 10px; padding: 5px; }")
        size_layout.addWidget(explanation)
        
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("Size:"))
        
        # Define discrete thumbnail sizes (max 256px - matches browser slider max)
        self.size_values = [32, 64, 128, 256]
        
        # Create slider with indices (0-3)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(0, len(self.size_values) - 1)
        
        # Find current value index
        current_size = self.settings.get("thumbnails", "size", 128)
        if current_size in self.size_values:
            current_index = self.size_values.index(current_size)
        else:
            # Find closest value
            current_index = min(range(len(self.size_values)), 
                              key=lambda i: abs(self.size_values[i] - current_size))
        
        self.size_slider.setValue(current_index)
        self.size_slider.setTickInterval(1)
        self.size_slider.setTickPosition(QSlider.TicksBelow)
        slider_layout.addWidget(self.size_slider)
        
        self.size_label = QLabel(f"{self.size_values[self.size_slider.value()]} px")
        self.size_label.setMinimumWidth(60)
        slider_layout.addWidget(self.size_label)
        self.size_slider.valueChanged.connect(
            lambda idx: self.size_label.setText(f"{self.size_values[idx]} px")
        )
        
        size_layout.addLayout(slider_layout)
        size_group.setLayout(size_layout)
        layout.addWidget(size_group)
        
        # Quality group
        quality_group = QGroupBox("Quality")
        quality_layout = QVBoxLayout()
        
        quality_h_layout = QHBoxLayout()
        quality_h_layout.addWidget(QLabel("Thumbnail Quality:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Low (Fast)", "Medium", "High (Slow)"])
        current_quality = self.settings.get("thumbnails", "quality", "medium")
        quality_map = {"low": 0, "medium": 1, "high": 2}
        self.quality_combo.setCurrentIndex(quality_map.get(current_quality, 1))
        quality_h_layout.addWidget(self.quality_combo)
        quality_h_layout.addStretch()
        quality_layout.addLayout(quality_h_layout)
        
        self.generate_3d_cb = QCheckBox("Generate thumbnails for 3D files (slower)")
        self.generate_3d_cb.setChecked(self.settings.get("thumbnails", "generate_for_3d", True))
        quality_layout.addWidget(self.generate_3d_cb)
        
        quality_group.setLayout(quality_layout)
        layout.addWidget(quality_group)
        
        # Performance group
        performance_group = QGroupBox("Performance (Multithreading)")
        performance_layout = QVBoxLayout()
        
        # Worker threads setting
        worker_threads_layout = QHBoxLayout()
        worker_threads_layout.addWidget(QLabel("Parallel Worker Threads:"))
        self.worker_threads_spin = QSpinBox()
        self.worker_threads_spin.setRange(0, 12)  # 0 = auto-detect, 1-12 = manual
        self.worker_threads_spin.setValue(self.settings.get("thumbnails", "worker_threads", 0))
        self.worker_threads_spin.setToolTip(
            "Number of parallel threads for thumbnail generation.\n"
            "Higher = faster on multi-core CPUs, but more memory/CPU usage.\n\n"
            "  • 0 = Auto-detect (recommended) - uses CPU core count, max 12\n"
            "  • 1-12 = Manual override\n\n"
            "Requires browser restart to take effect."
        )
        worker_threads_layout.addWidget(self.worker_threads_spin)
        worker_threads_layout.addStretch()
        performance_layout.addLayout(worker_threads_layout)
        
        # Info label
        perf_info = QLabel(
            "⚡ Multithreading speeds up thumbnail generation for large files (TIFF, EXR, HDR).\n"
            "Setting value to 1 disables multithreading (single-threaded mode)."
        )
        perf_info.setWordWrap(True)
        perf_info.setStyleSheet("QLabel { color: #888; font-size: 10px; padding: 5px; }")
        performance_layout.addWidget(perf_info)
        
        performance_group.setLayout(performance_layout)
        layout.addWidget(performance_group)
        
        # Cache group
        cache_group = QGroupBox("Cache")
        cache_layout = QVBoxLayout()
        
        # Memory cache size (number of thumbnails in RAM)
        memory_cache_layout = QHBoxLayout()
        memory_cache_layout.addWidget(QLabel("Memory Cache Size:"))
        self.memory_cache_spin = QSpinBox()
        self.memory_cache_spin.setRange(100, 10000)
        self.memory_cache_spin.setSingleStep(100)
        self.memory_cache_spin.setValue(self.settings.get("thumbnails", "memory_cache_size", 2000))
        self.memory_cache_spin.setSuffix(" thumbnails")
        self.memory_cache_spin.setToolTip("Number of thumbnails to keep in memory (RAM). Increase for large folders.")
        memory_cache_layout.addWidget(self.memory_cache_spin)
        memory_cache_layout.addStretch()
        cache_layout.addLayout(memory_cache_layout)
        
        # Disk cache size (MB)
        cache_size_layout = QHBoxLayout()
        cache_size_layout.addWidget(QLabel("Disk Cache Size Limit:"))
        self.cache_size_spin = QSpinBox()
        self.cache_size_spin.setRange(50, 5000)
        self.cache_size_spin.setValue(self.settings.get("thumbnails", "cache_size_mb", 500))
        self.cache_size_spin.setSuffix(" MB")
        self.cache_size_spin.setToolTip("Maximum disk space for thumbnail cache.")
        cache_size_layout.addWidget(self.cache_size_spin)
        cache_size_layout.addStretch()
        cache_layout.addLayout(cache_size_layout)
        
        clear_cache_layout = QHBoxLayout()
        self.cache_info_label = QLabel("Current cache size: Calculating...")
        clear_cache_layout.addWidget(self.cache_info_label)
        clear_cache_btn = QPushButton("Clear Cache")
        clear_cache_btn.clicked.connect(self.clear_cache)
        clear_cache_layout.addWidget(clear_cache_btn)
        cache_layout.addLayout(clear_cache_layout)
        
        cache_group.setLayout(cache_layout)
        layout.addWidget(cache_group)
        
        layout.addStretch()
        
        # Calculate cache size
        self.update_cache_info()
    
    def update_cache_info(self):
        """Update cache size information"""
        try:
            # Unified cache directory
            cache_dir = Path.home() / ".ddContentBrowser" / "thumbnails"
            if cache_dir.exists():
                total_size = sum(f.stat().st_size for f in cache_dir.rglob('*') if f.is_file())
                size_mb = total_size / (1024 * 1024)
                self.cache_info_label.setText(f"Current cache size: {size_mb:.1f} MB")
            else:
                self.cache_info_label.setText("Current cache size: 0 MB")
        except Exception as e:
            self.cache_info_label.setText(f"Error calculating cache size: {e}")
    
    def clear_cache(self):
        """Clear thumbnail cache"""
        reply = QMessageBox.question(self, "Clear Cache",
                                     "Are you sure you want to clear the thumbnail cache?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                # Unified cache directory
                cache_dir = Path.home() / ".ddContentBrowser" / "thumbnails"
                if cache_dir.exists():
                    import shutil
                    shutil.rmtree(cache_dir)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    self.update_cache_info()
                    QMessageBox.information(self, "Success", "Cache cleared successfully!")
                else:
                    self.update_cache_info()
                    QMessageBox.information(self, "Info", "Cache directory does not exist.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to clear cache: {e}")
    
    def save_settings(self):
        """Save settings from UI to settings manager"""
        # Get actual size value from slider index
        size_index = self.size_slider.value()
        actual_size = self.size_values[size_index]
        self.settings.set("thumbnails", "size", actual_size)
        
        quality_map = {0: "low", 1: "medium", 2: "high"}
        self.settings.set("thumbnails", "quality", quality_map[self.quality_combo.currentIndex()])
        self.settings.set("thumbnails", "memory_cache_size", self.memory_cache_spin.value())
        self.settings.set("thumbnails", "cache_size_mb", self.cache_size_spin.value())
        self.settings.set("thumbnails", "generate_for_3d", self.generate_3d_cb.isChecked())
        self.settings.set("thumbnails", "worker_threads", self.worker_threads_spin.value())


class PreviewSettingsTab(QWidget):
    """Preview panel settings tab"""
    
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings = settings_manager
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Resolution group
        resolution_group = QGroupBox("Preview Resolution")
        resolution_layout = QVBoxLayout()
        
        res_layout = QHBoxLayout()
        res_layout.addWidget(QLabel("Resolution:"))
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["512 px (Fast)", "1024 px (Balanced)", 
                                       "2048 px (High Quality)", "4096 px (Maximum)"])
        current_res = self.settings.get("preview", "resolution", 1024)
        res_map = {512: 0, 1024: 1, 2048: 2, 4096: 3}
        self.resolution_combo.setCurrentIndex(res_map.get(current_res, 1))
        res_layout.addWidget(self.resolution_combo)
        res_layout.addStretch()
        resolution_layout.addLayout(res_layout)
        
        res_info = QLabel("⚠ Higher resolution = slower HDR/EXR processing")
        res_info.setStyleSheet("color: #888; font-size: 10px;")
        resolution_layout.addWidget(res_info)
        
        resolution_group.setLayout(resolution_layout)
        layout.addWidget(resolution_group)
        
        # HDR settings group
        hdr_group = QGroupBox("HDR/EXR Settings")
        hdr_layout = QVBoxLayout()
        
        cache_layout = QHBoxLayout()
        cache_layout.addWidget(QLabel("Raw HDR Cache Size:"))
        self.hdr_cache_spin = QSpinBox()
        self.hdr_cache_spin.setRange(1, 20)
        self.hdr_cache_spin.setValue(self.settings.get("preview", "hdr_cache_size", 5))
        self.hdr_cache_spin.setSuffix(" files")
        cache_layout.addWidget(self.hdr_cache_spin)
        cache_layout.addStretch()
        hdr_layout.addLayout(cache_layout)
        
        cache_info = QLabel("ℹ Each cached file uses ~20-30 MB of RAM")
        cache_info.setStyleSheet("color: #888; font-size: 10px;")
        hdr_layout.addWidget(cache_info)
        
        exposure_layout = QHBoxLayout()
        exposure_layout.addWidget(QLabel("Default Exposure:"))
        self.exposure_spin = QSpinBox()
        self.exposure_spin.setRange(-10, 10)
        self.exposure_spin.setValue(int(self.settings.get("preview", "default_exposure", 0.0)))
        self.exposure_spin.setSuffix(" EV")
        exposure_layout.addWidget(self.exposure_spin)
        exposure_layout.addStretch()
        hdr_layout.addLayout(exposure_layout)
        
        hdr_group.setLayout(hdr_layout)
        layout.addWidget(hdr_group)
        
        # Display settings group
        display_group = QGroupBox("Display")
        display_layout = QVBoxLayout()
        
        self.auto_fit_cb = QCheckBox("Auto-fit images to window")
        self.auto_fit_cb.setChecked(self.settings.get("preview", "auto_fit", True))
        display_layout.addWidget(self.auto_fit_cb)
        
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)
        
        layout.addStretch()
    
    def save_settings(self):
        """Save settings from UI to settings manager"""
        res_map = {0: 512, 1: 1024, 2: 2048, 3: 4096}
        self.settings.set("preview", "resolution", res_map[self.resolution_combo.currentIndex()])
        self.settings.set("preview", "hdr_cache_size", self.hdr_cache_spin.value())
        self.settings.set("preview", "default_exposure", float(self.exposure_spin.value()))
        self.settings.set("preview", "auto_fit", self.auto_fit_cb.isChecked())


class FiltersSettingsTab(QWidget):
    """File filters settings tab"""
    
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings = settings_manager
        self.init_ui()
    
    def _generate_supported_formats_html(self):
        """Generate HTML description of supported formats from config"""
        from .utils import ensure_file_formats_config, get_extensions_by_category
        
        config = ensure_file_formats_config()
        categories = config.get('categories', {})
        
        # Import & Reference capable formats (importable=True)
        importable_html = "<b>🔵 Import & Reference to Maya:</b><br>"
        for cat_name, cat_data in categories.items():
            if cat_data.get('importable', False):
                extensions = get_extensions_by_category(cat_name)
                if extensions:
                    ext_list = ", ".join(sorted(extensions))
                    importable_html += f"• <b>{cat_data.get('name', cat_name)}:</b> {ext_list}<br>"
        
        # Browse & Preview only formats (importable=False)
        browse_html = "<b>⚪ Browse & Preview Only:</b><br>"
        for cat_name, cat_data in categories.items():
            if not cat_data.get('importable', False):
                extensions = get_extensions_by_category(cat_name)
                if extensions:
                    ext_list = ", ".join(sorted(extensions))
                    browse_html += f"• <b>{cat_data.get('name', cat_name)}:</b> {ext_list}<br>"
        
        return importable_html, browse_html
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # File types group - Split into Import/Reference vs Browse-only
        types_group = QGroupBox("Supported File Types")
        types_layout = QVBoxLayout()
        
        # Generate HTML from config
        import_html, browse_html = self._generate_supported_formats_html()
        
        # Import & Reference capable formats (store reference for refresh)
        self.import_label = QLabel(import_html)
        self.import_label.setWordWrap(True)
        self.import_label.setStyleSheet("QLabel { color: #4CAF50; font-size: 11px; padding: 5px; }")
        types_layout.addWidget(self.import_label)
        
        # Browse/Preview only formats (store reference for refresh)
        self.browse_label = QLabel(browse_html)
        self.browse_label.setWordWrap(True)
        self.browse_label.setStyleSheet("QLabel { color: #888; font-size: 11px; padding: 5px; }")
        types_layout.addWidget(self.browse_label)
        
        types_group.setLayout(types_layout)
        layout.addWidget(types_group)
        
        # Info label - redirect to File Formats tab
        info_label = QLabel(
            "💡 <b>To add new file formats:</b> Go to the <b>File Formats</b> tab where you can "
            "add/edit/remove formats with full control over colors, thumbnails, and categories."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("QLabel { color: #5dade2; font-size: 10px; padding: 10px; background-color: rgba(93, 173, 226, 0.1); border-radius: 5px; }")
        layout.addWidget(info_label)
        
        # Visibility group
        visibility_group = QGroupBox("Visibility")
        visibility_layout = QVBoxLayout()
        
        self.show_hidden_cb = QCheckBox("Show hidden files")
        self.show_hidden_cb.setChecked(self.settings.get("filters", "show_hidden", False))
        visibility_layout.addWidget(self.show_hidden_cb)
        
        visibility_group.setLayout(visibility_layout)
        layout.addWidget(visibility_group)
        
        # Search options group
        search_group = QGroupBox("Search Options")
        search_layout = QVBoxLayout()
        
        self.case_sensitive_cb = QCheckBox("Case-sensitive search")
        self.case_sensitive_cb.setChecked(self.settings.get("filters", "case_sensitive_search", False))
        search_layout.addWidget(self.case_sensitive_cb)
        
        self.regex_search_cb = QCheckBox("Enable regex search")
        self.regex_search_cb.setChecked(self.settings.get("filters", "regex_search", False))
        search_layout.addWidget(self.regex_search_cb)
        
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)
        
        # Recursive browsing group
        recursive_group = QGroupBox("Recursive Browsing")
        recursive_layout = QVBoxLayout()
        
        # Description
        recursive_desc = QLabel(
            "When 'Include Subfolders' is enabled, limit the maximum number of files to load for performance."
        )
        recursive_desc.setWordWrap(True)
        recursive_desc.setStyleSheet("QLabel { color: #888; font-size: 9px; padding: 5px; }")
        recursive_layout.addWidget(recursive_desc)
        
        # Max files spinner
        max_files_layout = QHBoxLayout()
        max_files_layout.addWidget(QLabel("Max files (Include Subfolders):"))
        self.max_recursive_spin = QSpinBox()
        self.max_recursive_spin.setRange(100, 100000)
        self.max_recursive_spin.setSingleStep(1000)
        self.max_recursive_spin.setValue(self.settings.get("filters", "max_recursive_files", 10000))
        self.max_recursive_spin.setSuffix(" files")
        self.max_recursive_spin.setToolTip("Limit when browsing all files in subfolders (Include Subfolders checkbox)")
        max_files_layout.addWidget(self.max_recursive_spin)
        max_files_layout.addStretch()
        recursive_layout.addLayout(max_files_layout)
        
        # Max search files spinner
        max_search_layout = QHBoxLayout()
        max_search_layout.addWidget(QLabel("Max files (Search Subfolders):"))
        self.max_search_spin = QSpinBox()
        self.max_search_spin.setRange(1000, 1000000)
        self.max_search_spin.setSingleStep(10000)
        self.max_search_spin.setValue(self.settings.get("filters", "max_search_files", 100000))
        self.max_search_spin.setSuffix(" files")
        self.max_search_spin.setToolTip("Limit when searching in subfolders (higher limit since results are filtered)")
        max_search_layout.addWidget(self.max_search_spin)
        max_search_layout.addStretch()
        recursive_layout.addLayout(max_search_layout)
        
        recursive_group.setLayout(recursive_layout)
        layout.addWidget(recursive_group)
        
        layout.addStretch()
    
    def refresh_formats_display(self):
        """Refresh the supported formats display from current config"""
        from .utils import reload_file_formats_config
        
        # Force reload config
        reload_file_formats_config()
        
        # Regenerate HTML
        import_html, browse_html = self._generate_supported_formats_html()
        
        # Update labels
        self.import_label.setText(import_html)
        self.browse_label.setText(browse_html)
    
    def save_settings(self):
        """Save settings from UI to settings manager"""
        # Save settings
        self.settings.set("filters", "show_hidden", self.show_hidden_cb.isChecked())
        self.settings.set("filters", "case_sensitive_search", self.case_sensitive_cb.isChecked())
        self.settings.set("filters", "regex_search", self.regex_search_cb.isChecked())
        self.settings.set("filters", "max_recursive_files", self.max_recursive_spin.value())
        self.settings.set("filters", "max_search_files", self.max_search_spin.value())


class FileFormatEditDialog(QDialog):
    """Dialog for adding/editing file format configuration"""
    
    def __init__(self, parent=None, edit_mode=False, extension="", config_data=None):
        super().__init__(parent)
        self.edit_mode = edit_mode
        self.extension = extension
        self.config_data = config_data or {}
        
        self.setWindowTitle("Edit Format" if edit_mode else "Add Format")
        self.resize(500, 600)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Extension
        ext_layout = QHBoxLayout()
        ext_layout.addWidget(QLabel("Extension:"))
        self.ext_input = QLineEdit()
        self.ext_input.setPlaceholderText(".ext")
        if self.edit_mode:
            self.ext_input.setText(self.extension)
            self.ext_input.setReadOnly(True)  # Can't change extension when editing
        ext_layout.addWidget(self.ext_input)
        layout.addLayout(ext_layout)
        
        # Category
        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "maya", "models", "images", "scripts", "pdf", "text", "other"
        ])
        current_category = self.config_data.get('category', 'other')
        index = self.category_combo.findText(current_category)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        cat_layout.addWidget(self.category_combo)
        layout.addLayout(cat_layout)
        
        # Enabled
        self.enabled_cb = QCheckBox("Enabled (show in browser)")
        self.enabled_cb.setChecked(self.config_data.get('enabled', True))
        layout.addWidget(self.enabled_cb)
        
        # Show in filters
        self.show_filters_cb = QCheckBox("Show in file type filters")
        self.show_filters_cb.setChecked(self.config_data.get('show_in_filters', True))
        layout.addWidget(self.show_filters_cb)
        
        # Icon colors group
        colors_group = QGroupBox("Icon Colors")
        colors_layout = QVBoxLayout()
        
        # Primary color
        primary_layout = QHBoxLayout()
        primary_layout.addWidget(QLabel("Primary Color:"))
        self.primary_btn = QPushButton()
        self.primary_color = QColor(*self.config_data.get('icon_color_primary', [100, 100, 100]))
        self.update_color_button(self.primary_btn, self.primary_color)
        self.primary_btn.clicked.connect(lambda: self.pick_color('primary'))
        primary_layout.addWidget(self.primary_btn)
        primary_layout.addStretch()
        colors_layout.addLayout(primary_layout)
        
        # Secondary color
        secondary_layout = QHBoxLayout()
        secondary_layout.addWidget(QLabel("Secondary Color:"))
        self.secondary_btn = QPushButton()
        self.secondary_color = QColor(*self.config_data.get('icon_color_secondary', [150, 150, 150]))
        self.update_color_button(self.secondary_btn, self.secondary_color)
        self.secondary_btn.clicked.connect(lambda: self.pick_color('secondary'))
        secondary_layout.addWidget(self.secondary_btn)
        secondary_layout.addStretch()
        colors_layout.addLayout(secondary_layout)
        
        colors_group.setLayout(colors_layout)
        layout.addWidget(colors_group)
        
        # Thumbnail settings group
        thumb_group = QGroupBox("Thumbnail Generation")
        thumb_layout = QVBoxLayout()
        
        self.thumb_generate_cb = QCheckBox("Generate thumbnails")
        thumb_config = self.config_data.get('thumbnail', {})
        self.thumb_generate_cb.setChecked(thumb_config.get('generate', False))
        thumb_layout.addWidget(self.thumb_generate_cb)
        
        # Thumbnail method
        method_layout = QHBoxLayout()
        method_layout.addWidget(QLabel("Method:"))
        self.thumb_method_combo = QComboBox()
        
        # Add methods with tooltips
        methods = [
            ("none", "No thumbnail generation (show icon only)"),
            ("qimage", "Standard Qt image loader (JPG, PNG, BMP, GIF)"),
            ("qimage_optimized", "⭐ RECOMMENDED for JPG/PNG/GIF - Fast scaled loading (4-5× faster)"),
            ("opencv", "OpenCV loader (TIFF, HDR, TGA, advanced formats)"),
            ("opencv_optimized", "⭐ RECOMMENDED for TIFF - DCT subsampling (2-8× faster)"),
            ("openexr", "OpenEXR loader (EXR files with HDR)"),
            ("pymupdf", "PyMuPDF loader (PDF first page)"),
            ("oiio", "⭐ RECOMMENDED for .tx - OpenImageIO (RenderMan textures, all compressions)"),
            ("video", "Video frame extractor (MP4, MOV, AVI, MKV - extracts middle frame)")
        ]
        
        for method, tooltip in methods:
            self.thumb_method_combo.addItem(method)
            self.thumb_method_combo.setItemData(
                self.thumb_method_combo.count() - 1, 
                tooltip, 
                Qt.ToolTipRole
            )
        
        current_method = thumb_config.get('method', 'none')
        index = self.thumb_method_combo.findText(current_method)
        if index >= 0:
            self.thumb_method_combo.setCurrentIndex(index)
        
        # Set tooltip for the combo itself
        self.thumb_method_combo.setToolTip(
            "Thumbnail generation method:\n"
            "• qimage_optimized - Best for JPG/PNG/GIF (fast)\n"
            "• opencv_optimized - Best for TIFF (fast)\n"
            "• oiio - Best for .tx RenderMan textures\n"
            "• video - Best for video files (MP4, MOV, AVI, MKV)\n"
            "• none - No thumbnails (show colored icon only)"
        )
        
        method_layout.addWidget(self.thumb_method_combo)
        
        # Help button for method info
        help_btn = QPushButton("?")
        help_btn.setMaximumWidth(30)
        help_btn.setToolTip("Show detailed method recommendations")
        help_btn.clicked.connect(self.show_method_help)
        method_layout.addWidget(help_btn)
        
        thumb_layout.addLayout(method_layout)
        
        # Max size MB
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Max Size (MB):"))
        self.thumb_size_spin = QSpinBox()
        self.thumb_size_spin.setRange(0, 1000)
        self.thumb_size_spin.setSpecialValueText("No limit")
        max_size = thumb_config.get('max_size_mb')
        self.thumb_size_spin.setValue(max_size if max_size else 0)
        size_layout.addWidget(self.thumb_size_spin)
        size_layout.addStretch()
        thumb_layout.addLayout(size_layout)
        
        thumb_group.setLayout(thumb_layout)
        layout.addWidget(thumb_group)
        
        # Maya import type
        maya_layout = QHBoxLayout()
        maya_layout.addWidget(QLabel("Maya Import Type:"))
        self.maya_import_combo = QComboBox()
        self.maya_import_combo.addItems(["None", "OBJ", "FBX", "Alembic", "USD"])
        current_maya = self.config_data.get('maya_import_type')
        if current_maya:
            index = self.maya_import_combo.findText(current_maya)
            if index >= 0:
                self.maya_import_combo.setCurrentIndex(index)
        maya_layout.addWidget(self.maya_import_combo)
        layout.addLayout(maya_layout)
        
        layout.addStretch()
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def update_color_button(self, button, color):
        """Update button appearance with color"""
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: rgb({color.red()}, {color.green()}, {color.blue()});
                border: 2px solid #555;
                min-width: 100px;
                min-height: 30px;
            }}
        """)
        button.setText(f"RGB({color.red()}, {color.green()}, {color.blue()})")
    
    def pick_color(self, color_type):
        """Open color picker dialog"""
        current_color = self.primary_color if color_type == 'primary' else self.secondary_color
        
        color = QColorDialog.getColor(current_color, self, "Choose Color")
        
        if color.isValid():
            if color_type == 'primary':
                self.primary_color = color
                self.update_color_button(self.primary_btn, color)
            else:
                self.secondary_color = color
                self.update_color_button(self.secondary_btn, color)
    
    def show_method_help(self):
        """Show detailed help for thumbnail methods"""
        help_text = """
<h3>Thumbnail Generation Methods</h3>

<p><b>Recommended Methods:</b></p>

<table border="1" cellpadding="5" cellspacing="0">
<tr><th>Format</th><th>Best Method</th><th>Speed Gain</th></tr>
<tr><td>JPG, PNG, GIF</td><td><b>qimage_optimized</b></td><td>4-5× faster</td></tr>
<tr><td>TIFF</td><td><b>opencv_optimized</b></td><td>2-8× faster</td></tr>
<tr><td>RenderMan .tx</td><td><b>oiio</b></td><td>All compressions</td></tr>
<tr><td>EXR</td><td><b>openexr</b></td><td>HDR support</td></tr>
<tr><td>PDF</td><td><b>pymupdf</b></td><td>First page</td></tr>
</table>

<p><b>Method Details:</b></p>

<ul>
<li><b>none</b> - No thumbnail, show colored icon only (fastest, no preview)</li>
<li><b>qimage</b> - Standard Qt loader (works for most images, slower)</li>
<li><b>qimage_optimized</b> ⭐ - Fast scaled loading using Qt (JPG DCT subsampling, PNG progressive decode)</li>
<li><b>opencv</b> - OpenCV loader (16/32-bit TIFF, HDR, advanced formats)</li>
<li><b>opencv_optimized</b> ⭐ - OpenCV with IMREAD_REDUCED_* flags (2-8× faster for TIFF)</li>
<li><b>openexr</b> - Native EXR loader with HDR tone mapping</li>
<li><b>pymupdf</b> - PDF renderer (first page only)</li>
<li><b>oiio</b> ⭐ - OpenImageIO (RenderMan .tx with all compressions, mipmaps, HDR)</li>
</ul>

<p><b>Performance Tips:</b></p>
<ul>
<li>Use <b>optimized</b> methods when available (huge speed boost!)</li>
<li>Set <b>max_size_mb</b> limit for large files (skip thumbnails > limit)</li>
<li>Use <b>none</b> for 3D models (they need special rendering)</li>
</ul>
        """
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Thumbnail Method Help")
        msg.setTextFormat(Qt.RichText)
        msg.setText(help_text)
        msg.setIcon(QMessageBox.Information)
        msg.exec_()
    
    def validate_and_accept(self):
        """Validate input and accept dialog"""
        # Validate extension
        ext = self.ext_input.text().strip()
        if not ext:
            QMessageBox.warning(self, "Invalid Input", "Extension cannot be empty!")
            return
        
        if not ext.startswith('.'):
            QMessageBox.warning(self, "Invalid Input", "Extension must start with a dot (e.g., .ext)")
            return
        
        self.accept()
    
    def get_extension(self):
        """Get extension string"""
        return self.ext_input.text().strip().lower()
    
    def get_config_data(self):
        """Get configuration data dict"""
        max_size_mb = self.thumb_size_spin.value()
        maya_import = self.maya_import_combo.currentText()
        
        return {
            "category": self.category_combo.currentText(),
            "enabled": self.enabled_cb.isChecked(),
            "show_in_filters": self.show_filters_cb.isChecked(),
            "icon_color_primary": [self.primary_color.red(), self.primary_color.green(), self.primary_color.blue()],
            "icon_color_secondary": [self.secondary_color.red(), self.secondary_color.green(), self.secondary_color.blue()],
            "thumbnail": {
                "generate": self.thumb_generate_cb.isChecked(),
                "method": self.thumb_method_combo.currentText(),
                "max_size_mb": max_size_mb if max_size_mb > 0 else None
            },
            "maya_import_type": maya_import if maya_import != "None" else None
        }


class ColorPreviewDelegate(QStyledItemDelegate):
    """Custom delegate to show color preview in table cell"""
    
    def paint(self, painter, option, index):
        """Custom paint to show gradient color preview"""
        # Get color data from item
        color_text = index.data(Qt.DisplayRole)
        
        if color_text and "RGB(" in color_text:
            # Parse primary and secondary colors from text
            try:
                parts = color_text.split("→")
                primary_part = parts[0].strip()
                secondary_part = parts[1].strip() if len(parts) > 1 else primary_part
                
                # Extract RGB values
                import re
                primary_match = re.search(r'RGB\((\d+),(\d+),(\d+)\)', primary_part)
                secondary_match = re.search(r'RGB\((\d+),(\d+),(\d+)\)', secondary_part)
                
                if primary_match:
                    primary_color = QColor(int(primary_match.group(1)), 
                                          int(primary_match.group(2)), 
                                          int(primary_match.group(3)))
                    
                    if secondary_match:
                        secondary_color = QColor(int(secondary_match.group(1)), 
                                                int(secondary_match.group(2)), 
                                                int(secondary_match.group(3)))
                    else:
                        secondary_color = primary_color
                    
                    # Draw gradient background (always visible, even when selected)
                    painter.save()
                    
                    gradient = QLinearGradient(option.rect.topLeft(), option.rect.bottomRight())
                    gradient.setColorAt(0, primary_color)
                    gradient.setColorAt(1, secondary_color)
                    
                    painter.fillRect(option.rect, gradient)
                    
                    # Draw text with contrasting color
                    text_color = QColor(255, 255, 255) if primary_color.lightness() < 128 else QColor(0, 0, 0)
                    painter.setPen(text_color)
                    painter.drawText(option.rect, Qt.AlignCenter, color_text)
                    
                    # Draw selection border if selected (instead of background)
                    if option.state & QStyle.State_Selected:
                        painter.setPen(QPen(option.palette.highlight().color(), 2))
                        painter.drawRect(option.rect.adjusted(1, 1, -1, -1))
                    
                    painter.restore()
                    return
            except:
                pass
        
        # Fallback to default painting
        super().paint(painter, option, index)


class FileFormatsSettingsTab(QWidget):
    """File Formats settings tab - manage supported file formats"""
    
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings = settings_manager
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Description
        desc = QLabel(
            "Manage supported file formats, colors, and categories.<br>"
            "Changes are saved to <b>file_formats.json</b> and apply immediately."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("QLabel { color: #888; font-size: 9px; padding: 5px; }")
        layout.addWidget(desc)
        
        # Toolbar
        toolbar = QHBoxLayout()
        
        self.add_btn = QPushButton("Add Format")
        self.add_btn.clicked.connect(self.add_format)
        toolbar.addWidget(self.add_btn)
        
        self.edit_btn = QPushButton("Edit Selected")
        self.edit_btn.clicked.connect(self.edit_format)
        toolbar.addWidget(self.edit_btn)
        
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self.remove_format)
        toolbar.addWidget(self.remove_btn)
        
        toolbar.addStretch()
        
        self.import_btn = QPushButton("Import...")
        self.import_btn.clicked.connect(self.import_config)
        toolbar.addWidget(self.import_btn)
        
        self.export_btn = QPushButton("Export...")
        self.export_btn.clicked.connect(self.export_config)
        toolbar.addWidget(self.export_btn)
        
        layout.addLayout(toolbar)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Extension", "Category", "Enabled", "Icon Colors", "Thumbnail Method"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.itemDoubleClicked.connect(self.edit_format)
        
        # Set custom delegate for Icon Colors column (column 3)
        self.color_delegate = ColorPreviewDelegate(self.table)
        self.table.setItemDelegateForColumn(3, self.color_delegate)
        
        layout.addWidget(self.table)
        
        # Load current formats
        self.load_formats()
    
    def load_formats(self):
        """Load file formats from config and populate table"""
        from .utils import ensure_file_formats_config
        
        config = ensure_file_formats_config()
        extensions = config.get('extensions', {})
        
        self.table.setRowCount(len(extensions))
        
        for row, (ext, ext_config) in enumerate(sorted(extensions.items())):
            # Extension
            ext_item = QTableWidgetItem(ext)
            ext_item.setFlags(ext_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, ext_item)
            
            # Category
            category_item = QTableWidgetItem(ext_config.get('category', 'unknown'))
            category_item.setFlags(category_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, category_item)
            
            # Enabled checkbox
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(enabled_item.flags() | Qt.ItemIsUserCheckable)
            enabled_item.setFlags(enabled_item.flags() & ~Qt.ItemIsEditable)
            enabled_item.setCheckState(Qt.Checked if ext_config.get('enabled', True) else Qt.Unchecked)
            self.table.setItem(row, 2, enabled_item)
            
            # Icon colors (visual preview) - delegate will handle rendering
            color_primary = ext_config.get('icon_color_primary', [100, 100, 100])
            color_secondary = ext_config.get('icon_color_secondary', [150, 150, 150])
            color_text = f"RGB({color_primary[0]},{color_primary[1]},{color_primary[2]}) → RGB({color_secondary[0]},{color_secondary[1]},{color_secondary[2]})"
            color_item = QTableWidgetItem(color_text)
            color_item.setFlags(color_item.flags() & ~Qt.ItemIsEditable)
            # Don't set background - ColorPreviewDelegate will handle rendering
            self.table.setItem(row, 3, color_item)
            
            # Thumbnail method
            thumb_method = ext_config.get('thumbnail', {}).get('method', 'none')
            method_item = QTableWidgetItem(thumb_method)
            method_item.setFlags(method_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 4, method_item)
    
    def add_format(self):
        """Add new file format"""
        dialog = FileFormatEditDialog(parent=self, edit_mode=False)
        if dialog.exec_():
            # Get new format data
            ext = dialog.get_extension()
            config_data = dialog.get_config_data()
            
            # Add to config
            from .utils import ensure_file_formats_config, save_file_formats_config
            config = ensure_file_formats_config()
            
            if ext in config.get('extensions', {}):
                QMessageBox.warning(self, "Duplicate", f"Format <b>{ext}</b> already exists!")
                return
            
            config['extensions'][ext] = config_data
            
            if save_file_formats_config(config):
                QMessageBox.information(self, "Success", f"Format <b>{ext}</b> added successfully!")
                self.load_formats()  # Reload table
            else:
                QMessageBox.warning(self, "Error", "Failed to save config!")
    
    def edit_format(self):
        """Edit selected format"""
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a format to edit.")
            return
        
        ext = self.table.item(current_row, 0).text()
        
        # Load current config
        from .utils import ensure_file_formats_config, save_file_formats_config
        config = ensure_file_formats_config()
        ext_config = config['extensions'].get(ext)
        
        if not ext_config:
            QMessageBox.warning(self, "Error", f"Config for <b>{ext}</b> not found!")
            return
        
        # Open edit dialog
        dialog = FileFormatEditDialog(parent=self, edit_mode=True, extension=ext, config_data=ext_config)
        if dialog.exec_():
            # Update config
            updated_config = dialog.get_config_data()
            config['extensions'][ext] = updated_config
            
            if save_file_formats_config(config):
                QMessageBox.information(self, "Success", f"Format <b>{ext}</b> updated successfully!")
                self.load_formats()  # Reload table
            else:
                QMessageBox.warning(self, "Error", "Failed to save config!")
    
    def remove_format(self):
        """Remove selected format"""
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a format to remove.")
            return
        
        ext = self.table.item(current_row, 0).text()
        reply = QMessageBox.question(
            self, "Remove Format",
            f"Remove format <b>{ext}</b>?<br>This will remove it from file_formats.json.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            from .utils import ensure_file_formats_config, save_file_formats_config
            config = ensure_file_formats_config()
            
            if ext in config.get('extensions', {}):
                del config['extensions'][ext]
                
                if save_file_formats_config(config):
                    QMessageBox.information(self, "Success", f"Format <b>{ext}</b> removed successfully!")
                    self.load_formats()  # Reload table
                else:
                    QMessageBox.warning(self, "Error", "Failed to save config!")
            else:
                QMessageBox.warning(self, "Error", f"Format <b>{ext}</b> not found in config!")
    
    def import_config(self):
        """Import file_formats.json from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import File Formats Config",
            "", "JSON Files (*.json)"
        )
        
        if file_path:
            try:
                import json
                with open(file_path, 'r', encoding='utf-8') as f:
                    imported_config = json.load(f)
                
                # Validate structure
                if 'extensions' not in imported_config or 'categories' not in imported_config:
                    QMessageBox.warning(self, "Invalid Config", "Invalid file_formats.json structure!")
                    return
                
                # Save imported config
                from .utils import save_file_formats_config
                if save_file_formats_config(imported_config):
                    QMessageBox.information(
                        self, "Success", 
                        f"Imported {len(imported_config['extensions'])} formats successfully!"
                    )
                    self.load_formats()  # Reload table
                else:
                    QMessageBox.warning(self, "Error", "Failed to save imported config!")
                    
            except Exception as e:
                QMessageBox.warning(self, "Import Error", f"Failed to import config:\n{e}")
    
    def export_config(self):
        """Export file_formats.json to file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export File Formats Config",
            "file_formats.json", "JSON Files (*.json)"
        )
        
        if file_path:
            try:
                from .utils import ensure_file_formats_config
                import json
                
                config = ensure_file_formats_config()
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                
                QMessageBox.information(
                    self, "Success",
                    f"Exported {len(config['extensions'])} formats to:\n{file_path}"
                )
                
            except Exception as e:
                QMessageBox.warning(self, "Export Error", f"Failed to export config:\n{e}")
    
    def save_settings(self):
        """Save settings (enabled state changes)"""
        from .utils import ensure_file_formats_config, save_file_formats_config
        
        config = ensure_file_formats_config()
        
        # Update enabled states from table checkboxes
        for row in range(self.table.rowCount()):
            ext = self.table.item(row, 0).text()
            enabled_item = self.table.item(row, 2)
            
            if ext in config['extensions']:
                config['extensions'][ext]['enabled'] = (enabled_item.checkState() == Qt.Checked)
        
        save_file_formats_config(config)


class SettingsDialog(QDialog):
    """Main settings dialog with tabs"""
    
    settings_changed = Signal()
    
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings = settings_manager
        self.setWindowTitle("ddContentBrowser Settings")
        self.resize(600, 500)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        
        # Create tabs
        self.general_tab = GeneralSettingsTab(self.settings)
        self.thumbnail_tab = ThumbnailSettingsTab(self.settings)
        self.preview_tab = PreviewSettingsTab(self.settings)
        self.filters_tab = FiltersSettingsTab(self.settings)
        self.file_formats_tab = FileFormatsSettingsTab(self.settings)
        
        self.tab_widget.addTab(self.general_tab, "General")
        self.tab_widget.addTab(self.thumbnail_tab, "Thumbnails")
        self.tab_widget.addTab(self.preview_tab, "Preview")
        self.tab_widget.addTab(self.filters_tab, "Filters")
        self.tab_widget.addTab(self.file_formats_tab, "File Formats")
        
        # Connect tab changed signal to refresh Filters tab when switching to it
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        layout.addWidget(self.tab_widget)
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | 
                                      QDialogButtonBox.RestoreDefaults)
        button_box.accepted.connect(self.accept_settings)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        
        layout.addWidget(button_box)
    
    def on_tab_changed(self, index):
        """Handle tab change - refresh Filters tab if switching to it"""
        # Index 3 is Filters tab (0=General, 1=Thumbnails, 2=Preview, 3=Filters, 4=File Formats)
        if index == 3:
            self.filters_tab.refresh_formats_display()
    
    def accept_settings(self):
        """Save all settings and close dialog"""
        # Save settings from all tabs
        self.general_tab.save_settings()
        self.thumbnail_tab.save_settings()
        self.preview_tab.save_settings()
        self.filters_tab.save_settings()
        self.file_formats_tab.save_settings()
        
        # Refresh Filters tab display with updated file formats
        self.filters_tab.refresh_formats_display()
        
        # Save to disk
        if self.settings.save():
            self.settings_changed.emit()
            self.accept()
        else:
            QMessageBox.warning(self, "Error", "Failed to save settings!")
    
    def restore_defaults(self):
        """Restore default settings"""
        reply = QMessageBox.question(self, "Restore Defaults",
                                     "Are you sure you want to restore all settings to default values?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.settings.reset_to_defaults()
            self.settings_changed.emit()
            QMessageBox.information(self, "Success", 
                                   "Settings restored to defaults. Please restart the browser.")
            self.accept()
