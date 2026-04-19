# -*- coding: utf-8 -*-
"""
DD Content Browser - Collections Panel UI
UI for managing manual and smart collections

Author: ddankhazi
License: MIT
"""

from pathlib import Path

try:
    from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                                   QListWidget, QListWidgetItem, QMenu, QInputDialog,
                                   QMessageBox, QFileDialog)
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont, QIcon, QColor
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                                   QListWidget, QListWidgetItem, QMenu, QInputDialog,
                                   QMessageBox, QFileDialog)
    from PySide2.QtCore import Qt, Signal
    from PySide2.QtGui import QFont, QIcon, QColor
    PYSIDE_VERSION = 2

from .asset_collections import CollectionManager, ManualCollection, SmartCollection
from .widgets import DragDropCollectionListWidget

# UI Font - Default value (can be overridden by browser at runtime)
UI_FONT = "Segoe UI"

# Debug flag
DEBUG_MODE = False


class CollectionsPanel(QWidget):
    """Collections panel widget"""
    
    # Signals
    collection_selected = Signal(str)  # collection_name
    collection_cleared = Signal()      # Clear filter (show all files)
    
    def __init__(self, collection_manager: CollectionManager, parent=None):
        super().__init__(parent)
        self.collection_manager = collection_manager
        
        self.setup_ui()
        self.refresh_collections_list()
    
    def setup_ui(self):
        """Setup UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Toolbar with buttons
        toolbar = QHBoxLayout()
        
        self.new_btn = QPushButton("+ New")
        self.new_btn.setToolTip("Create new collection")
        self.new_btn.clicked.connect(self.create_new_collection)
        toolbar.addWidget(self.new_btn)
        
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # Collections list - with drag & drop support
        self.collections_list = DragDropCollectionListWidget()
        self.collections_list.setFont(QFont(UI_FONT, 9))
        self.collections_list.setSelectionMode(QListWidget.ExtendedSelection)  # Enable multi-select (Ctrl+Click, Shift+Click)
        self.collections_list.itemClicked.connect(self.on_collection_clicked)
        self.collections_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.collections_list.customContextMenuRequested.connect(self.show_context_menu)
        
        # Maya-style selection color
        self.collections_list.setStyleSheet("""
            QListWidget::item:selected {
                background-color: #4b7daa;
                color: white;
            }
            QListWidget::item:hover {
                background-color: rgba(75, 125, 170, 0.3);
            }
        """)
        # Connect drag & drop signal
        self.collections_list.files_dropped_on_collection.connect(self.on_files_dropped)
        layout.addWidget(self.collections_list)
        
        # Exit collection view button (only visible/enabled when in collection mode)
        self.clear_btn = QPushButton("Exit Collection View")
        self.clear_btn.setToolTip("Return to folder browsing")
        self.clear_btn.clicked.connect(self.clear_collection_filter)
        self.clear_btn.setVisible(False)  # Hidden by default
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #4b7daa;
                color: white;
                border: none;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a8dba;
            }
            QPushButton:pressed {
                background-color: #3a6d9a;
            }
        """)
        layout.addWidget(self.clear_btn)
    
    def refresh_collections_list(self):
        """Refresh collections list"""
        self.collections_list.clear()
        
        collections = self.collection_manager.get_all_collections()
        
        if not collections:
            # Show empty state
            item = QListWidgetItem("No collections yet")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setForeground(Qt.gray)
            self.collections_list.addItem(item)
            return
        
        # Sort: Manual first, then Smart, then alphabetically
        manual_cols = sorted([c for c in collections if c.type == 'manual'], key=lambda c: c.name.lower())
        smart_cols = sorted([c for c in collections if c.type == 'smart'], key=lambda c: c.name.lower())
        
        # Add manual collections
        if manual_cols:
            for collection in manual_cols:
                item_text = f"{collection.name}"
                if isinstance(collection, ManualCollection):
                    file_count = len(collection.get_existing_files())
                    item_text += f" ({file_count})"
                
                item = QListWidgetItem()
                item.setData(Qt.UserRole, collection.name)  # Store collection name
                
                # Create a custom label widget for consistent styling with favorites
                if PYSIDE_VERSION == 6:
                    from PySide6.QtWidgets import QLabel
                else:
                    from PySide2.QtWidgets import QLabel
                label = QLabel(item_text)
                label.setFont(QFont(UI_FONT, 9))
                
                # Apply color bar if bg_color is set
                bg_color = getattr(collection, 'bg_color', None)
                if bg_color:
                    label.setStyleSheet(f"""
                        QLabel {{
                            background-color: transparent;
                            border-left: 6px solid {bg_color};
                            padding-left: 6px;
                        }}
                    """)
                else:
                    label.setStyleSheet("""
                        QLabel {
                            background-color: transparent;
                        }
                    """)
                
                self.collections_list.addItem(item)
                self.collections_list.setItemWidget(item, label)
        
        # Add smart collections (future)
        if smart_cols:
            for collection in smart_cols:
                item_text = f"🧠 {collection.name}"
                item = QListWidgetItem()
                item.setData(Qt.UserRole, collection.name)
                
                if PYSIDE_VERSION == 6:
                    from PySide6.QtWidgets import QLabel
                else:
                    from PySide2.QtWidgets import QLabel
                label = QLabel(item_text)
                label.setFont(QFont(UI_FONT, 9))
                label.setStyleSheet("""
                    QLabel {
                        background-color: transparent;
                    }
                """)
                
                self.collections_list.addItem(item)
                self.collections_list.setItemWidget(item, label)
    
    def create_new_collection(self):
        """Create new manual collection"""
        name, ok = QInputDialog.getText(
            self,
            "New Collection",
            "Collection name:",
            text="New Collection"
        )
        
        if ok and name:
            try:
                self.collection_manager.create_manual_collection(name)
                self.refresh_collections_list()
                
                if DEBUG_MODE:
                    print(f"[CollectionsPanel] Created collection: {name}")
            
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))
    
    def on_collection_clicked(self, item):
        """Handle collection click"""
        collection_name = item.data(Qt.UserRole)
        if collection_name:
            self.collection_selected.emit(collection_name)
            # Show exit button when collection is active
            self.clear_btn.setVisible(True)
            
            if DEBUG_MODE:
                print(f"[CollectionsPanel] Selected collection: {collection_name}")
    
    def clear_collection_filter(self):
        """Clear collection filter"""
        self.collections_list.clearSelection()
        self.collection_cleared.emit()
        # Hide exit button when returning to folder view
        self.clear_btn.setVisible(False)
        
        if DEBUG_MODE:
            print("[CollectionsPanel] Cleared collection filter")
    
    def show_context_menu(self, position):
        """Show context menu for collections"""
        item = self.collections_list.itemAt(position)
        if not item:
            return
        collection_name = item.data(Qt.UserRole)
        if not collection_name:
            return
        collection = self.collection_manager.get_collection(collection_name)
        if not collection:
            return
        menu = QMenu()
        # Rename action
        rename_action = menu.addAction("Rename...")
        # Delete action
        delete_action = menu.addAction("Delete")
        # Set background color (manual collections only)
        if isinstance(collection, ManualCollection):
            color_menu = QMenu("Set Background Color", self)
            palette = [
                ("Default", "#282828"),  # Dark gray (Maya default)
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
            color_actions = []
            for name, hexcode in palette:
                act = color_menu.addAction(name)
                if hexcode:
                    act.setIcon(self.make_color_icon(hexcode))
                color_actions.append((act, hexcode))
            menu.addMenu(color_menu)
            
            # Clear color option if collection has color
            clear_color_action = None
            if collection and getattr(collection, 'bg_color', None):
                clear_color_action = menu.addAction("Clear Color")
        else:
            color_menu = None
            color_actions = []
            clear_color_action = None
        menu.addSeparator()
        # Export to Folder action (manual collections only)
        if isinstance(collection, ManualCollection):
            export_action = menu.addAction("\U0001F4E6 Export to Folder...")
        else:
            export_action = None
        # Cleanup action (manual collections only)
        if isinstance(collection, ManualCollection):
            menu.addSeparator()
            cleanup_action = menu.addAction("Clean up missing files")
        else:
            cleanup_action = None
        # Execute menu
        action = menu.exec_(self.collections_list.mapToGlobal(position))
        
        # Check if no action (clicked outside menu)
        if action is None:
            return
        
        # Handle actions
        if action == rename_action:
            self.rename_collection(collection_name)
        elif action == delete_action:
            self.delete_collection(collection_name)
        elif action == clear_color_action:
            self.clear_collection_bg_color(collection_name)
        elif export_action and action == export_action:
            self.export_collection_to_folder(collection_name)
        elif cleanup_action and action == cleanup_action:
            self.cleanup_collection(collection_name)
        elif color_menu:
            # Check if it's a color action
            for act, hexcode in color_actions:
                if action == act:
                    self.set_collection_bg_color(collection_name, item, hexcode)
                    break

    def set_collection_bg_color(self, collection_name, item, hexcode):
        from PySide6.QtGui import QColor
        color = QColor(hexcode) if hexcode else QColor("#31363b")
        collection = self.collection_manager.get_collection(collection_name)
        if collection:
            setattr(collection, 'bg_color', color.name())
            self.collection_manager.save()
            # Force refresh to update delegate rendering
            self.refresh_collections_list()
    
    def clear_collection_bg_color(self, collection_name):
        """Clear background color from collection"""
        collection = self.collection_manager.get_collection(collection_name)
        if collection:
            # Remove bg_color attribute
            if hasattr(collection, 'bg_color'):
                delattr(collection, 'bg_color')
            self.collection_manager.save()
            # Force refresh to update delegate rendering
            self.refresh_collections_list()

    def make_color_icon(self, hexcode):
        from PySide6.QtGui import QIcon, QPixmap, QColor
        pix = QPixmap(16, 16)
        pix.fill(QColor(hexcode))
        return QIcon(pix)
    
    def rename_collection(self, old_name: str):
        """Rename collection"""
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Collection",
            "New name:",
            text=old_name
        )
        
        if ok and new_name and new_name != old_name:
            try:
                self.collection_manager.rename_collection(old_name, new_name)
                self.refresh_collections_list()
                
                if DEBUG_MODE:
                    print(f"[CollectionsPanel] Renamed: {old_name} → {new_name}")
            
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))
    
    def delete_collection(self, name: str):
        """Delete collection"""
        reply = QMessageBox.question(
            self,
            "Delete Collection",
            f"Are you sure you want to delete '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.collection_manager.delete_collection(name)
                self.refresh_collections_list()
                self.collection_cleared.emit()  # Clear filter
                
                if DEBUG_MODE:
                    print(f"[CollectionsPanel] Deleted: {name}")
            
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))
    
    def cleanup_collection(self, name: str):
        """Clean up missing files from collection"""
        collection = self.collection_manager.get_collection(name)
        if not isinstance(collection, ManualCollection):
            return
        
        before_count = len(collection.files)
        collection.cleanup_missing_files()
        after_count = len(collection.files)
        removed_count = before_count - after_count
        
        if removed_count > 0:
            self.collection_manager.save()
            self.refresh_collections_list()
            QMessageBox.information(
                self,
                "Cleanup Complete",
                f"Removed {removed_count} missing file(s) from '{name}'"
            )
        else:
            QMessageBox.information(
                self,
                "Cleanup Complete",
                "No missing files found"
            )
    
    def export_collection_to_folder(self, collection_name: str):
        """Export collection items (files and folders) to a folder"""
        import shutil
        
        collection = self.collection_manager.get_collection(collection_name)
        if not isinstance(collection, ManualCollection):
            return
        
        # Get existing files/folders
        items = collection.get_existing_files()
        if not items:
            QMessageBox.information(self, "Empty Collection", "This collection has no items to export")
            return
        
        # Select destination folder
        dest_folder = QFileDialog.getExistingDirectory(
            self,
            f"Export '{collection_name}' to Folder",
            str(Path.home())
        )
        
        if not dest_folder:
            return
        
        dest_path = Path(dest_folder)
        
        # Ask for conflict handling strategy
        reply = QMessageBox.question(
            self,
            "Conflict Handling",
            f"How to handle existing files/folders?\n\n"
            f"Yes = Overwrite existing\n"
            f"No = Skip existing\n"
            f"Cancel = Rename duplicates",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )
        
        if reply == QMessageBox.Yes:
            conflict_mode = "overwrite"
        elif reply == QMessageBox.No:
            conflict_mode = "skip"
        else:
            conflict_mode = "rename"
        
        # Copy items with progress
        copied_files = 0
        copied_folders = 0
        skipped = 0
        errors = []
        
        for item_path in items:
            src = Path(item_path)
            dest = dest_path / src.name
            
            try:
                # Check if it's a folder or file
                if src.is_dir():
                    # Handle folder conflicts
                    if dest.exists():
                        if conflict_mode == "skip":
                            skipped += 1
                            continue
                        elif conflict_mode == "rename":
                            # Find unique name for folder
                            counter = 1
                            base_name = dest.name
                            while dest.exists():
                                dest = dest_path / f"{base_name}_{counter}"
                                counter += 1
                        elif conflict_mode == "overwrite":
                            # Remove existing folder
                            shutil.rmtree(dest)
                    
                    # Copy entire folder recursively
                    shutil.copytree(src, dest)
                    copied_folders += 1
                    
                else:
                    # Handle file conflicts
                    if dest.exists():
                        if conflict_mode == "skip":
                            skipped += 1
                            continue
                        elif conflict_mode == "rename":
                            # Find unique name for file
                            counter = 1
                            stem = dest.stem
                            suffix = dest.suffix
                            while dest.exists():
                                dest = dest_path / f"{stem}_{counter}{suffix}"
                                counter += 1
                    
                    # Copy file
                    shutil.copy2(src, dest)
                    copied_files += 1
                
            except Exception as e:
                errors.append(f"{src.name}: {str(e)}")
        
        # Show results
        msg = f"Export complete!\n\n"
        if copied_files > 0:
            msg += f"Copied: {copied_files} file(s)\n"
        if copied_folders > 0:
            msg += f"Copied: {copied_folders} folder(s)\n"
        if skipped > 0:
            msg += f"Skipped: {skipped} item(s)\n"
        if errors:
            msg += f"\nErrors ({len(errors)}):\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                msg += f"\n... and {len(errors) - 5} more"
        
        QMessageBox.information(self, "Export Complete", msg)
        
        if DEBUG_MODE:
            print(f"[CollectionsPanel] Exported {copied_files} files and {copied_folders} folders from '{collection_name}' to {dest_folder}")
    
    def add_files_to_collection(self, collection_name: str, file_paths: list):
        """Add files and folders to a collection"""
        collection = self.collection_manager.get_collection(collection_name)
        if not isinstance(collection, ManualCollection):
            QMessageBox.warning(self, "Error", "Can only add items to manual collections")
            return
        
        collection.add_files(file_paths)
        self.collection_manager.save()
        self.refresh_collections_list()
        
        if DEBUG_MODE:
            print(f"[CollectionsPanel] Added {len(file_paths)} item(s) to {collection_name}")
    
    def on_files_dropped(self, collection_name: str, file_paths: list):
        """Handle files and folders dropped onto collection (via middle-button drag)"""
        collection = self.collection_manager.get_collection(collection_name)
        
        if not isinstance(collection, ManualCollection):
            QMessageBox.warning(self, "Error", "Can only add items to manual collections")
            return
        
        # Add files to collection
        added_count = 0
        for file_path in file_paths:
            if file_path not in collection.files:
                collection.add_file(file_path)
                added_count += 1
        
        if added_count > 0:
            self.collection_manager.save()
            self.refresh_collections_list()
            
            # Show confirmation message
            browser = self.parent()
            while browser and not hasattr(browser, 'status_bar'):
                browser = browser.parent()
            if browser and hasattr(browser, 'status_bar'):
                try:
                    browser.status_bar.showMessage(
                        f"Added {added_count} file(s) to '{collection_name}'",
                        2000
                    )
                except RuntimeError:
                    pass  # Widget already deleted
