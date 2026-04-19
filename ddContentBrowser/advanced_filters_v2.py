# -*- coding: utf-8 -*-
"""
DD Content Browser - Advanced Filters Panel (Adobe Bridge style)
Metadata-based hierarchical filtering system

Author: ddankhazi
License: MIT
"""

from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set

# UI Font - Default value (can be overridden by browser at runtime)
UI_FONT = "Segoe UI"

try:
    from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                                   QPushButton, QScrollArea, QCheckBox, QFrame, QApplication)
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                                   QPushButton, QScrollArea, QCheckBox, QFrame, QApplication)
    from PySide2.QtCore import Qt, Signal
    from PySide2.QtGui import QFont
    PYSIDE_VERSION = 2

from .metadata_extractor import MetadataCache, FileMetadata

# Debug mode
DEBUG_MODE = False


class FilterCategory(QWidget):
    """A single collapsible filter category (like in Adobe Bridge)"""
    
    # Signal when checkboxes change
    selection_changed = Signal(str, list)  # category_name, selected_values
    
    def __init__(self, category_name, parent=None):
        super().__init__(parent)
        self.category_name = category_name
        self.is_collapsed = False
        self.checkboxes = {}  # {value: checkbox}
        self.value_counts = {}  # {value: count}
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI"""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(1)
        
        # Header with collapse button (no frame border) - entire header is clickable
        self.header_frame = QFrame()
        self.header_frame.setFrameShape(QFrame.NoFrame)
        # Minimal styling - let Maya handle colors
        self.header_frame.setStyleSheet("""
            QFrame {
                border: none;
                padding: 2px;
            }
        """)
        self.header_frame.setCursor(Qt.PointingHandCursor)
        
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(2, 1, 2, 1)  # Reduced from (3, 2, 3, 2)
        
        # Collapse arrow (now just a label, not button)
        self.collapse_arrow = QLabel("▾")  # Using U+25BE (down-pointing triangle)
        self.collapse_arrow.setStyleSheet("""
            QLabel {
                font-size: 14px;
                padding: 0px 3px;
                background: transparent;
                font-family: "Segoe UI Symbol", "Arial Unicode MS";
            }
        """)
        self.collapse_arrow.setFixedWidth(18)
        self.collapse_arrow.setAttribute(Qt.WA_TransparentForMouseEvents)  # Pass mouse events to parent
        header_layout.addWidget(self.collapse_arrow)
        
        # Category name
        self.name_label = QLabel(self.category_name)
        self.name_label.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 12px;
                background: transparent;
            }
        """)
        self.name_label.setAttribute(Qt.WA_TransparentForMouseEvents)  # Pass mouse events to parent
        header_layout.addWidget(self.name_label)
        header_layout.addStretch()
        
        self.main_layout.addWidget(self.header_frame)
        
        # Make header clickable
        self.header_frame.mousePressEvent = lambda event: self.toggle_collapse()
        
        # Content area (checkboxes) - using grid layout for 2 columns
        self.content_widget = QWidget()
        # We'll use QVBoxLayout but add checkboxes in groups
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(16, 1, 1, 1)  # Reduced from (20, 2, 2, 2)
        self.content_layout.setSpacing(0)  # Reduced from 1
        
        self.main_layout.addWidget(self.content_widget)
    
    def toggle_collapse(self):
        """Toggle category collapse state"""
        self.is_collapsed = not self.is_collapsed
        self.content_widget.setVisible(not self.is_collapsed)
        # Using matching triangle characters: ▸ (right) and ▾ (down)
        self.collapse_arrow.setText("▸" if self.is_collapsed else "▾")
    
    def set_values(self, value_counts: Dict[str, int]):
        """Set available filter values with counts"""
        self.value_counts = value_counts
        
        # Clear existing checkboxes
        for checkbox in self.checkboxes.values():
            checkbox.deleteLater()
        self.checkboxes.clear()
        
        # Clear existing row widgets
        while self.content_layout.count() > 0:
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Sort values based on category type
        if self.category_name == 'Resolution':
            # Sort resolution categories by size (S to Ultra)
            resolution_order = {
                "S (≤512px)": 0,
                "M (≤1K)": 1,
                "L (≤2K)": 2,
                "XL (≤4K)": 3,
                "XXL (≤8K)": 4,
                "XXXL (≤16K)": 5,
                "Ultra (>16K)": 6
            }
            sorted_items = sorted(value_counts.items(), key=lambda x: resolution_order.get(x[0], 999))
        elif self.category_name == 'File Size':
            # Sort file sizes by actual size (not alphabetically)
            size_order = {
                "Tiny (< 1 MB)": 0,
                "Small (1-10 MB)": 1,
                "Medium (10-100 MB)": 2,
                "Large (100 MB - 1 GB)": 3,
                "Huge (> 1 GB)": 4
            }
            sorted_items = sorted(value_counts.items(), key=lambda x: size_order.get(x[0], 999))
        else:
            # Default: alphabetical sorting
            sorted_items = sorted(value_counts.items())
        
        # Create checkboxes in 2-column layout
        for i in range(0, len(sorted_items), 2):
            # Create row widget
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)  # Reduced from 10
            
            # First checkbox in row
            value1, count1 = sorted_items[i]
            checkbox1 = QCheckBox(f"{value1} ({count1})")
            # Minimal styling - Maya handles most of it
            checkbox1.setStyleSheet("""
                QCheckBox {
                    font-size: 11px;
                    spacing: 4px;
                }
            """)
            checkbox1.stateChanged.connect(self.on_checkbox_changed)
            row_layout.addWidget(checkbox1)
            self.checkboxes[value1] = checkbox1
            
            # Second checkbox in row (if exists)
            if i + 1 < len(sorted_items):
                value2, count2 = sorted_items[i + 1]
                checkbox2 = QCheckBox(f"{value2} ({count2})")
                # Minimal styling - Maya handles most of it
                checkbox2.setStyleSheet("""
                    QCheckBox {
                        font-size: 11px;
                        spacing: 4px;
                    }
                """)
                checkbox2.stateChanged.connect(self.on_checkbox_changed)
                row_layout.addWidget(checkbox2)
                self.checkboxes[value2] = checkbox2
            else:
                # Add stretch if odd number of items
                row_layout.addStretch()
            
            self.content_layout.addWidget(row_widget)
    
    def on_checkbox_changed(self):
        """Handle checkbox state change"""
        selected = self.get_selected_values()
        self.selection_changed.emit(self.category_name, selected)
    
    def get_selected_values(self) -> List[str]:
        """Get list of selected values"""
        selected = []
        for value, checkbox in self.checkboxes.items():
            if checkbox.isChecked():
                selected.append(value)
        return selected
    
    def clear_selection(self):
        """Clear all selections"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(False)
    
    def update_counts(self, new_counts: Dict[str, int]):
        """Update counts on existing checkboxes"""
        for value, checkbox in self.checkboxes.items():
            count = new_counts.get(value, 0)
            # Update text but preserve check state
            checkbox.setText(f"{value} ({count})")
            # Disable if count is 0
            checkbox.setEnabled(count > 0)
    
    def update_checkbox_state(self, value: str, checked: bool):
        """Update a specific checkbox state without triggering signal"""
        if value in self.checkboxes:
            checkbox = self.checkboxes[value]
            # Block signals to avoid recursion
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)


class AdvancedFiltersPanelV2(QWidget):
    """Adobe Bridge style advanced filters panel"""
    
    # Signals
    filters_changed = Signal(dict)  # Emits active filters
    filters_cleared = Signal()
    filters_activated = Signal(bool)  # True when filters active, False when cleared (for disabling toolbar filters)
    
    def __init__(self, file_model, settings_manager=None, parent=None):
        super().__init__(parent)
        self.file_model = file_model
        self.settings_manager = settings_manager
        self.metadata_cache = MetadataCache()
        
        # Import MetadataManager for tags
        try:
            from .metadata import MetadataManager
            self.metadata_manager = MetadataManager()
        except Exception as e:
            print(f"[AdvancedFilters] Warning: Could not initialize MetadataManager: {e}")
            self.metadata_manager = None
        
        self.filter_categories = {}  # {category_name: FilterCategory widget}
        self.active_filters = {}  # {category_name: [selected_values]}
        self.original_assets = []  # Store original unfiltered asset list
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Top toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("padding: 4px;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 1, 4, 1)  # Reduced from (5, 2, 5, 2)
        
        # Analyze button (left aligned, wider to accommodate file counts)
        self.analyze_btn = QPushButton("🔄 Analyze Folder")
        self.analyze_btn.setMinimumWidth(180)
        # Let Maya handle button styling - no custom colors needed
        self.analyze_btn.clicked.connect(self.analyze_current_files)
        toolbar_layout.addWidget(self.analyze_btn)
        
        toolbar_layout.addStretch()
        
        # Clear all button
        self.clear_all_btn = QPushButton("✕ Clear")
        self.clear_all_btn.setFixedWidth(60)  # Fixed width to prevent shifting!
        self.clear_all_btn.setEnabled(False)  # Disabled by default (no filters active)
        self.clear_all_btn.clicked.connect(self.clear_all_filters)
        # Initial style (no filters) - normal gray
        self.clear_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                border: none;
                border-radius: 3px;
                padding: 5px;
                color: #aaa;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                color: #ccc;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
        toolbar_layout.addWidget(self.clear_all_btn)
        
        main_layout.addWidget(toolbar)
        
        # Scroll area for filter categories
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setSpacing(0)  # Reduced from 1
        self.scroll_layout.setContentsMargins(1, 1, 1, 1)  # Reduced from (2, 2, 2, 2)
        
        # Add stretch at bottom
        self.scroll_layout.addStretch()
        
        scroll.setWidget(self.scroll_content)
        main_layout.addWidget(scroll)
    
    def analyze_current_files(self):
        """Analyze current files and build filter categories - MANUAL trigger only"""
        import time
        start_total = time.time()
        
        if not hasattr(self.file_model, 'assets') or not self.file_model.assets:
            if DEBUG_MODE:
                print("[AdvancedFilters] No assets to analyze")
            return
        
        # Visual feedback: disable analyze button during processing
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("⏳ Analyzing...")
        
        # Store original unfiltered asset list
        start_prep = time.time()
        # Use _ungrouped_assets if available (to work with ungrouped files)
        # This ensures advanced filters work on individual files, not grouped sequences
        if hasattr(self.file_model, '_ungrouped_assets') and self.file_model._ungrouped_assets:
            self.original_assets = self.file_model._ungrouped_assets.copy()
            print(f"[AdvancedFilters] Using _ungrouped_assets: {len(self.original_assets)} assets")
        else:
            self.original_assets = self.file_model.assets.copy()
            print(f"[AdvancedFilters] Using assets: {len(self.original_assets)} assets")
        
        # Count folders
        folder_count = sum(1 for asset in self.original_assets if asset.is_folder)
        files_to_process = [asset for asset in self.original_assets if not asset.is_folder]
        file_count = len(files_to_process)
        print(f"[TIMER] Preparation: {time.time() - start_prep:.3f}s")
        
        # Process files in parallel using ThreadPoolExecutor
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import os
        
        # Use number of CPU cores (but max 8 to avoid overwhelming the system)
        max_workers = min(8, os.cpu_count() or 4)
        
        metadata_list = []
        processed_count = 0
        
        def process_single_file(asset):
            """Process a single file and return its metadata"""
            try:
                # Extract full metadata (including image dimensions, etc.)
                file_metadata = self.metadata_cache.get_or_create(asset.file_path)
                file_metadata.extract_full_metadata()  # Ensure full metadata is extracted
                metadata_dict = file_metadata.get_metadata()
                # Add file_path to metadata for tag lookup
                metadata_dict['file_path'] = str(asset.file_path)
                return metadata_dict
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[AdvancedFilters] Error processing {asset.file_path}: {e}")
                return None
        
        # Process files in parallel
        start_parallel = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            futures = {executor.submit(process_single_file, asset): asset for asset in files_to_process}
            
            # Collect results as they complete
            for future in as_completed(futures):
                result = future.result()
                if result:
                    metadata_list.append(result)
                
                # Update progress
                processed_count += 1
                self.analyze_btn.setText(f"⏳ Analyzing... {processed_count}/{file_count}")
                # Force UI update
                QApplication.processEvents()
        print(f"[TIMER] Parallel processing: {time.time() - start_parallel:.3f}s ({file_count} files)")
        
        # Build categories
        start_build = time.time()
        self.build_filter_categories(metadata_list, folder_count)
        print(f"[TIMER] Build categories: {time.time() - start_build:.3f}s")
        
        # Re-enable analyze button
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText("🔄 Analyze Folder")
        
        print(f"[TIMER] TOTAL analyze time: {time.time() - start_total:.3f}s")
        if DEBUG_MODE:
            print(f"[AdvancedFilters] Analyzed {file_count} files and {folder_count} folders (parallel mode with {max_workers} threads)")

    
    def build_filter_categories(self, metadata_list: List[Dict], folder_count: int = 0):
        """Build filter categories from metadata"""
        import time
        start_build = time.time()
        
        # Count values for each category
        category_values = defaultdict(lambda: defaultdict(int))
        
        # Add Folder to File Type category if there are folders
        if folder_count > 0:
            category_values['File Type']['Folder'] = folder_count
        
        start_aggregate = time.time()
        for metadata in metadata_list:
            # File Type
            if 'file_type' in metadata:
                category_values['File Type'][metadata['file_type']] += 1
            
            # Type Category
            if 'type_category' in metadata:
                category_values['Category'][metadata['type_category']] += 1
            
            # Size Category
            if 'file_size_category' in metadata:
                category_values['File Size'][metadata['file_size_category']] += 1
            
            # Resolution Category (replaces detailed Dimensions)
            if 'resolution_category' in metadata:
                category_values['Resolution'][metadata['resolution_category']] += 1
            
            # Aspect Ratio (for images)
            if 'aspect_ratio' in metadata:
                category_values['Aspect Ratio'][metadata['aspect_ratio']] += 1
            
            # Color Mode (for images)
            if 'color_mode' in metadata:
                category_values['Color Mode'][metadata['color_mode']] += 1
            
            # Bit Depth (for images)
            if 'bit_depth' in metadata:
                category_values['Bit Depth'][metadata['bit_depth']] += 1
            
            # EXIF Camera Data
            if 'camera_model' in metadata:
                category_values['Camera'][metadata['camera_model']] += 1
            
            if 'lens' in metadata:
                category_values['Lens'][metadata['lens']] += 1
            
            if 'iso_category' in metadata:
                category_values['ISO'][metadata['iso_category']] += 1
            
            if 'aperture_category' in metadata:
                category_values['Aperture'][metadata['aperture_category']] += 1
            
            if 'focal_length_category' in metadata:
                category_values['Focal Length'][metadata['focal_length_category']] += 1
        print(f"[TIMER]   - Aggregate metadata: {time.time() - start_aggregate:.3f}s")
        
        # Add Tags category (query from MetadataManager)
        start_tags = time.time()
        if self.metadata_manager:
            try:
                # OPTIMIZED: Build tag counts by iterating through files once, not tags
                # Old approach: for each tag, iterate through all files (N_tags * N_files queries)
                # New approach: for each file, get its tags once (N_files queries only)
                tag_counts = defaultdict(int)
                
                for metadata in metadata_list:
                    if 'file_path' in metadata:
                        file_path = metadata['file_path']
                        # Get file metadata once per file
                        file_metadata = self.metadata_manager.get_file_metadata(file_path)
                        if file_metadata and 'tags' in file_metadata:
                            # Count each tag this file has
                            for tag in file_metadata['tags']:
                                tag_name = tag.get('name')
                                if tag_name:
                                    tag_counts[tag_name] += 1
                
                # Add to category_values
                for tag_name, count in tag_counts.items():
                    if count > 0:
                        category_values['Tags'][tag_name] = count
                            
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[AdvancedFilters] ERROR loading tags: {e}")
                    import traceback
                    traceback.print_exc()
        print(f"[TIMER]   - Load tags: {time.time() - start_tags:.3f}s")
        
        # Create or update filter category widgets
        start_widgets = time.time()
        # Tags first, then other categories
        category_order = ['Tags', 'File Type', 'Category', 'File Size', 'Resolution', 
                         'Aspect Ratio', 'Color Mode', 'Bit Depth',
                         'Camera', 'Lens', 'ISO', 'Aperture', 'Focal Length']
        
        # Categories that should start collapsed (none by default now)
        collapsed_by_default = []
        
        for category_name in category_order:
            # IMPORTANT: Don't skip empty categories - we need to clear them!
            # Get values for this category (empty dict if no values)
            values_for_category = dict(category_values.get(category_name, {}))
            
            # Skip only if category never existed AND has no values
            if category_name not in self.filter_categories and len(values_for_category) == 0:
                continue
            
            if category_name not in self.filter_categories:
                # Create new category
                category_widget = FilterCategory(category_name)
                category_widget.selection_changed.connect(self.on_category_selection_changed)
                
                # Insert before stretch
                count = self.scroll_layout.count()
                self.scroll_layout.insertWidget(count - 1, category_widget)
                
                self.filter_categories[category_name] = category_widget
                
                # Collapse specific categories by default (AFTER inserting and storing)
                if category_name in collapsed_by_default:
                    category_widget.toggle_collapse()  # Start collapsed
            
            # Set/update values (even if empty - this will clear the category!)
            self.filter_categories[category_name].set_values(values_for_category)
        print(f"[TIMER]   - Create/update widgets: {time.time() - start_widgets:.3f}s")
        print(f"[TIMER]   - Total build_filter_categories: {time.time() - start_build:.3f}s")
    
    def on_category_selection_changed(self, category_name: str, selected_values: List[str]):
        """Handle filter selection change in a category"""
        if selected_values:
            self.active_filters[category_name] = selected_values
        else:
            # Remove from active filters if nothing selected
            if category_name in self.active_filters:
                del self.active_filters[category_name]
        
        # Apply filters (this will handle folder visibility internally)
        self.apply_active_filters()
    
    def apply_active_filters(self):
        """Apply currently active filters to file model
        
        EXCLUSIVE + ADDITIVE logic:
        - No filters active = show ALL
        - Filters active = show ONLY selected items (exclusive)
        - Multiple selections = additive (OR logic within same category, AND across categories)
        """
        if not self.active_filters:
            # No filters active - show all (clear any toolbar filters too)
            self.file_model.clearFilters()
            self.file_model.show_folders = True
            self.file_model.refresh()
            self.filters_cleared.emit()
            self.filters_activated.emit(False)  # Signal that advanced filters are NOT active
            
            # Reset clear button style to normal
            self.update_clear_button_style(has_filters=False)
            return
        
        # Get all assets from original unfiltered list
        all_assets = self.original_assets.copy() if self.original_assets else self.file_model.assets.copy()
        
        # Filter based on active filters
        filtered_assets = []
        
        # Check if "Folder" is in File Type filter (EXCLUSIVE mode)
        show_folders_in_filter = False
        if 'File Type' in self.active_filters:
            show_folders_in_filter = 'Folder' in self.active_filters['File Type']
        
        for asset in all_assets:
            if asset.is_folder:
                # In EXCLUSIVE mode: only show folders if explicitly selected
                if show_folders_in_filter:
                    filtered_assets.append(asset)
                continue
            
            metadata = self.metadata_cache.get_or_create(asset.file_path).get_metadata()
            
            # Check if asset matches ALL active filter categories (AND logic across categories)
            matches = True
            
            for category_name, selected_values in self.active_filters.items():
                # Map category to metadata key
                category_match = False
                
                if category_name == 'File Type':
                    # Filter out "Folder" from file type checks (handled above)
                    file_types = [t for t in selected_values if t != 'Folder']
                    if file_types:  # Only check if there are file types to match
                        category_match = metadata.get('file_type') in file_types
                    else:
                        # If only "Folder" was selected, files don't match (skip this file)
                        matches = False
                        break
                elif category_name == 'Category':
                    category_match = metadata.get('type_category') in selected_values
                elif category_name == 'File Size':
                    category_match = metadata.get('file_size_category') in selected_values
                elif category_name == 'Resolution':
                    category_match = metadata.get('resolution_category') in selected_values
                elif category_name == 'Aspect Ratio':
                    category_match = metadata.get('aspect_ratio') in selected_values
                elif category_name == 'Color Mode':
                    category_match = metadata.get('color_mode') in selected_values
                elif category_name == 'Bit Depth':
                    category_match = metadata.get('bit_depth') in selected_values
                elif category_name == 'Camera':
                    category_match = metadata.get('camera_model') in selected_values
                elif category_name == 'Lens':
                    category_match = metadata.get('lens') in selected_values
                elif category_name == 'ISO':
                    category_match = metadata.get('iso_category') in selected_values
                elif category_name == 'Aperture':
                    category_match = metadata.get('aperture_category') in selected_values
                elif category_name == 'Focal Length':
                    category_match = metadata.get('focal_length_category') in selected_values
                elif category_name == 'Tags':
                    # Check if file has ANY of the selected tags (OR logic within Tags)
                    if self.metadata_manager:
                        try:
                            file_metadata = self.metadata_manager.get_file_metadata(str(asset.file_path))
                            if file_metadata and 'tags' in file_metadata:
                                file_tag_names = [tag['name'] for tag in file_metadata['tags']]
                                # Match if file has at least one of the selected tags
                                category_match = any(tag_name in file_tag_names for tag_name in selected_values)
                            else:
                                category_match = False
                        except Exception as e:
                            if DEBUG_MODE:
                                print(f"[AdvancedFilters] Error checking tags for {asset.file_path}: {e}")
                            category_match = False
                    else:
                        category_match = False
                
                if not category_match:
                    matches = False
                    break
            
            if matches:
                filtered_assets.append(asset)
        
        # Update file model
        self.file_model.assets = filtered_assets
        
        # IMPORTANT: Also update _ungrouped_assets so sequence toggle works correctly
        # This ensures sequence mode toggle doesn't lose the advanced filter state
        self.file_model._ungrouped_assets = filtered_assets.copy()
        
        print(f"[AdvancedFilters] Applied filters: {len(filtered_assets)} assets (updated _ungrouped_assets)")
        
        # CRITICAL: If sequence mode is ON, reapply grouping to the filtered assets
        # This ensures the UI shows grouped sequences after filtering
        if self.file_model.sequence_mode:
            print(f"[AdvancedFilters] Sequence mode is ON - reapplying grouping after filter")
            self.file_model.reapplySequenceGrouping()
        else:
            # Only emit layoutChanged if we're NOT reapplying grouping (which emits it itself)
            self.file_model.layoutChanged.emit()
        
        # Emit signals
        self.filters_changed.emit(self.active_filters)
        self.filters_activated.emit(True)  # Signal that advanced filters are active
        
        # Update clear button style to highlight it (Maya blue)
        self.update_clear_button_style(has_filters=True)
        
        if DEBUG_MODE:
            print(f"[AdvancedFilters] Applied filters: {len(filtered_assets)} files match")
    
    def clear_all_filters(self):
        """Clear all active filters"""
        self.active_filters.clear()
        
        # Clear selections in all categories
        for category in self.filter_categories.values():
            category.clear_selection()
        
        # Reset file_model.show_folders to default (True)
        if not self.file_model.show_folders:
            self.file_model.setShowFolders(True)
        
        # OPTIMIZED: Don't call refresh() - just restore original assets
        # This prevents unnecessary re-scanning when clearing filters
        if hasattr(self, 'original_assets') and self.original_assets:
            # Restore the original unfiltered asset list
            self.file_model.assets = self.original_assets.copy()
            
            # Also update _ungrouped_assets to match
            self.file_model._ungrouped_assets = self.original_assets.copy()
            
            # Re-apply sorting to restore correct order
            self.file_model._sort_assets()
            
            # If sequence mode is on, reapply grouping
            if self.file_model.sequence_mode:
                self.file_model.reapplySequenceGrouping()
            else:
                # Just notify UI of the change
                self.file_model.layoutChanged.emit()
        else:
            # Fallback: if no original_assets stored, do full refresh
            self.file_model.clearFilters()
        
        # DON'T re-analyze - clearFilters already refreshed the model
        # The analyze will happen naturally when filters are next applied
        # self.analyze_current_files()  # REMOVED - unnecessary re-scan
        
        # Emit signals
        self.filters_cleared.emit()
        self.filters_activated.emit(False)  # Signal that advanced filters are cleared
        
        # Reset clear button style to normal
        self.update_clear_button_style(has_filters=False)
        
        if DEBUG_MODE:
            print("[AdvancedFilters] All filters cleared (without re-scan)")
    
    def update_clear_button_style(self, has_filters):
        """Update Clear button style and enabled state based on filter state
        
        Args:
            has_filters: True if filters are active (Maya blue + enabled), False for disabled
        """
        # Enable/disable button based on filter state
        self.clear_all_btn.setEnabled(has_filters)
        
        if has_filters:
            # Maya blue background when filters are active (NO font-weight to prevent shift!)
            self.clear_all_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4b7daa;
                    border: none;
                    border-radius: 3px;
                    padding: 5px;
                    color: white;
                }
                QPushButton:hover {
                    background-color: #5a8db8;
                }
                QPushButton:pressed {
                    background-color: #3a6d9a;
                }
            """)
        else:
            # Disabled gray style when no filters
            self.clear_all_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3a3a3a;
                    border: none;
                    border-radius: 3px;
                    padding: 5px;
                    color: #666;
                }
                QPushButton:disabled {
                    background-color: #2a2a2a;
                    color: #444;
                }
            """)
    
    def sync_folder_visibility_from_model(self):
        """Sync File Type 'Folder' checkbox with file_model.show_folders state"""
        if 'File Type' in self.filter_categories:
            file_type_category = self.filter_categories['File Type']
            show_folders = self.file_model.show_folders
            
            # Get current selected values
            current_selected = list(self.active_filters.get('File Type', []))
            
            # Update selection based on file_model state
            if show_folders and 'Folder' not in current_selected:
                # Need to check the Folder checkbox
                file_type_category.update_checkbox_state('Folder', True)
            elif not show_folders and 'Folder' in current_selected:
                # Need to uncheck the Folder checkbox
                file_type_category.update_checkbox_state('Folder', False)
    
    def refresh(self):
        """Refresh/clear filters when navigating to new directory
        
        Note: Does NOT auto-analyze - user must click "Analyze Folder" button
        """
        if DEBUG_MODE:
            print("[AdvancedFilters] refresh() called - clearing all filters and categories")
        
        # Clear metadata cache for new directory
        self.metadata_cache.clear()
        
        # Clear original_assets to prevent stale data
        self.original_assets = []
        
        # Clear active filters
        self.active_filters.clear()
        
        # Clear all category checkboxes
        for category in self.filter_categories.values():
            category.clear_selection()
        
        # Clear categories (will be rebuilt on analyze)
        for category_widget in self.filter_categories.values():
            category_widget.deleteLater()
        self.filter_categories.clear()
        
        if DEBUG_MODE:
            print("[AdvancedFilters] Cleared for new directory - waiting for manual analyze")
