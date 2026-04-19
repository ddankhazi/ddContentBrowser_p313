"""
DD Content Browser - UI Widgets
Breadcrumb navigation, filter panel, and custom list view

NOTE: PreviewPanel has been extracted to preview_panel.py for better maintainability

Author: ddankhazi
License: MIT
"""

import os
from pathlib import Path
from datetime import datetime, timedelta

# UI Font - Default value (can be overridden by browser at runtime)
# Set to Segoe UI to match Windows/Maya default
UI_FONT = "Segoe UI"

# Add external_libs to path for OpenEXR
import sys
_external_libs = os.path.join(os.path.dirname(__file__), "external_libs")
if os.path.exists(_external_libs) and _external_libs not in sys.path:
    sys.path.insert(0, _external_libs)

# NumPy is built into Maya 2026+
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("NumPy not available")

# Try to import OpenEXR for proper HDR/EXR support
try:
    import OpenEXR
    import Imath
    OPENEXR_AVAILABLE = True
    # print(f"OpenEXR loaded - Full EXR support enabled")  # Commented to avoid duplicate messages
except ImportError:
    OPENEXR_AVAILABLE = False
    # print("OpenEXR not available - EXR preview will be limited")

# Try to import OpenCV for Radiance HDR (.hdr) support
try:
    import cv2
    OPENCV_AVAILABLE = True
    # print(f"OpenCV loaded - Full HDR support enabled")
except ImportError:
    OPENCV_AVAILABLE = False
    # print("OpenCV not available - HDR preview will be limited")

# Try to import PyMuPDF (fitz) for PDF support
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
    # print(f"PyMuPDF loaded - PDF support enabled")
except ImportError:
    PYMUPDF_AVAILABLE = False
    # print("PyMuPDF not available - PDF preview will be limited")

try:
    from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                                    QLineEdit, QScrollArea, QFrame, QGroupBox, QCheckBox, 
                                    QSpinBox, QFormLayout, QDateEdit, QDialog, QGraphicsView,
                                    QApplication, QListView, QListWidget, QCompleter, QAbstractItemView)
    from PySide6.QtCore import Signal, Qt, QEvent, QPoint, QSize, QDate, QRect
    from PySide6.QtGui import QPixmap, QColor, QPainter, QImageReader, QImage, QCursor, QFont
    from PySide6 import QtCore, QtGui, QtWidgets
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                    QLineEdit, QScrollArea, QFrame, QGroupBox, QCheckBox,
                                    QSpinBox, QFormLayout, QDateEdit, QDialog, QGraphicsView,
                                    QApplication, QListView, QListWidget, QCompleter, QAbstractItemView)
    from PySide2.QtCore import Signal, Qt, QEvent, QPoint, QSize, QDate, QRect
    from PySide2.QtGui import QPixmap, QColor, QPainter, QImageReader, QImage, QCursor, QFont
    from PySide2 import QtCore, QtGui, QtWidgets
    PYSIDE_VERSION = 2

# Maya API for HDR/EXR loading (optional - only needed for Maya-specific operations)
try:
    import maya.api.OpenMaya as om
    MAYA_API_AVAILABLE = True
except ImportError:
    om = None
    MAYA_API_AVAILABLE = False

# Maya availability check
try:
    import maya.cmds as cmds
    MAYA_AVAILABLE = True
except ImportError:
    MAYA_AVAILABLE = False

# Import PreviewPanel from separate module (extracted for maintainability)
from .preview_panel import PreviewPanel


class ClickableWidget(QWidget):
    """Widget that emits a signal when clicked on empty space"""
    clicked = Signal()
    
    def mousePressEvent(self, event):
        """Emit clicked signal when widget is clicked"""
        self.clicked.emit()
        super().mousePressEvent(event)


class FlowLayout(QtWidgets.QLayout):
    """Flow layout that wraps widgets horizontally like tag chips (Qt example-based)"""
    
    def __init__(self, parent=None, margin=0, hSpacing=-1, vSpacing=-1):
        super().__init__(parent)
        self.itemList = []
        self.m_hSpace = hSpacing
        self.m_vSpace = vSpacing
        
        self.setContentsMargins(margin, margin, margin, margin)
    
    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)
    
    def addItem(self, item):
        self.itemList.append(item)
    
    def addWidget(self, widget):
        """Add widget to the flow layout"""
        self.addItem(QtWidgets.QWidgetItem(widget))
    
    def horizontalSpacing(self):
        if self.m_hSpace >= 0:
            return self.m_hSpace
        else:
            return self.smartSpacing(QtWidgets.QStyle.PM_LayoutHorizontalSpacing)
    
    def verticalSpacing(self):
        if self.m_vSpace >= 0:
            return self.m_vSpace
        else:
            return self.smartSpacing(QtWidgets.QStyle.PM_LayoutVerticalSpacing)
    
    def count(self):
        return len(self.itemList)
    
    def itemAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None
    
    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None
    
    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))
    
    def hasHeightForWidth(self):
        return True
    
    def heightForWidth(self, width):
        height = self.doLayout(QRect(0, 0, width, 0), True)
        return height
    
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)
    
    def sizeHint(self):
        return self.minimumSize()
    
    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size
    
    def doLayout(self, rect, testOnly):
        left, top, right, bottom = self.getContentsMargins()
        effectiveRect = rect.adjusted(+left, +top, -right, -bottom)
        x = effectiveRect.x()
        y = effectiveRect.y()
        lineHeight = 0
        
        for item in self.itemList:
            wid = item.widget()
            spaceX = self.horizontalSpacing()
            if spaceX == -1:
                spaceX = wid.style().layoutSpacing(
                    QtWidgets.QSizePolicy.PushButton,
                    QtWidgets.QSizePolicy.PushButton,
                    Qt.Horizontal
                )
            spaceY = self.verticalSpacing()
            if spaceY == -1:
                spaceY = wid.style().layoutSpacing(
                    QtWidgets.QSizePolicy.PushButton,
                    QtWidgets.QSizePolicy.PushButton,
                    Qt.Vertical
                )
            
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > effectiveRect.right() and lineHeight > 0:
                x = effectiveRect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0
            
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            
            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())
        
        return y + lineHeight - rect.y() + bottom
    
    def smartSpacing(self, pm):
        parent = self.parent()
        if not parent:
            return -1
        elif parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        else:
            return parent.spacing()
    
    def clear(self):
        """Remove all widgets from layout"""
        while self.count():
            item = self.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


class BreadcrumbWidget(QWidget):
    """Breadcrumb navigation widget with clickable path segments"""
    
    path_clicked = Signal(str)  # Emitted when a breadcrumb is clicked
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_path = ""
        self.setFixedHeight(32)  # Fixed widget height
        
        # Dark background for better visibility
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(60, 60, 60))  # Dark gray background
        self.setPalette(palette)
        
        # Main layout
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)  # Even margins
        self.layout.setSpacing(0)
        
        # Scroll area for breadcrumbs
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFixedHeight(28)  # Fixed height, no max/min
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        
        # Dark background for scroll area too
        scroll_palette = self.scroll_area.palette()
        scroll_palette.setColor(self.scroll_area.backgroundRole(), QColor(60, 60, 60))
        self.scroll_area.setPalette(scroll_palette)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: #3c3c3c; border: none; }")
        
        # Container for breadcrumb buttons (custom widget to catch clicks)
        self.breadcrumb_container = ClickableWidget()
        self.breadcrumb_container.clicked.connect(self.enter_edit_mode)  # Click on empty space = edit mode
        self.breadcrumb_container.setStyleSheet("QWidget { background-color: #3c3c3c; }")
        self.breadcrumb_layout = QHBoxLayout(self.breadcrumb_container)
        self.breadcrumb_layout.setContentsMargins(0, 0, 0, 0)
        self.breadcrumb_layout.setSpacing(2)
        self.breadcrumb_layout.addStretch()
        
        self.scroll_area.setWidget(self.breadcrumb_container)
        self.layout.addWidget(self.scroll_area, 1, Qt.AlignVCenter)  # Explicit vertical center alignment
        
        # Hidden line edit for manual path entry (activated by clicking on empty breadcrumb area)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Enter path and press Enter (or Escape to cancel)...")
        self.path_edit.setStyleSheet(f"""
            QLineEdit {{
                font-size: 12px;
                font-family: {UI_FONT};
                padding: 2px 4px;
                border: 1px solid #555;
                background-color: #3c3c3c;
            }}
        """)
        self.path_edit.setFixedHeight(28)  # Exact height match
        self.path_edit.hide()
        self.path_edit.returnPressed.connect(self.exit_edit_mode)
        # Install event filter to catch Escape key
        self.path_edit.installEventFilter(self)
        self.layout.addWidget(self.path_edit, 1, Qt.AlignVCenter)  # Explicit vertical center alignment, stretch
    
    def eventFilter(self, obj, event):
        """Event filter to catch Escape key and focus loss in path edit"""
        if obj == self.path_edit:
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    # Cancel edit mode without changing path
                    self.path_edit.hide()
                    self.scroll_area.show()
                    return True
            elif event.type() == QEvent.FocusOut:
                # Exit edit mode when focus is lost (clicked elsewhere)
                # Use a short timer to avoid conflicts with returnPressed
                QtCore.QTimer.singleShot(100, self.cancel_edit_mode)
                return False  # Let the event propagate
        return super().eventFilter(obj, event)
    
    def sizeHint(self):
        """Override to return consistent size"""
        return QSize(self.width(), 32)
    
    def minimumSizeHint(self):
        """Override to return consistent minimum size"""
        return QSize(100, 32)
        
    def set_path(self, path):
        """Set the current path and update breadcrumbs"""
        self.current_path = str(path)
        self.update_breadcrumbs()
    
    def update_breadcrumbs(self):
        """Update breadcrumb buttons based on current path"""
        # Clear existing buttons
        while self.breadcrumb_layout.count() > 1:  # Keep the stretch
            item = self.breadcrumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not self.current_path:
            return
        
        # Split path into segments
        path_obj = Path(self.current_path)
        parts = path_obj.parts
        
        # Create button for each segment
        for i, part in enumerate(parts):
            # Create breadcrumb button
            btn = QPushButton(part)
            btn.setFlat(True)
            btn.setMaximumHeight(24)
            btn.setStyleSheet(f"""
                QPushButton {{
                    border: none;
                    padding: 2px 6px;
                    background: transparent;
                    text-align: left;
                    font-size: 12px;
                    font-family: {UI_FONT};
                    color: #e0e0e0;
                }}
                QPushButton:hover {{
                    background: rgba(100, 150, 255, 80);
                    border-radius: 2px;
                    color: #ffffff;
                }}
                QPushButton:pressed {{
                    background: rgba(100, 150, 255, 120);
                }}
            """)
            
            # Build path up to this segment
            segment_path = str(Path(*parts[:i+1]))
            # Use lambda with explicit checked parameter (even though we don't use it)
            btn.clicked.connect(lambda checked=False, p=segment_path: self.path_clicked.emit(p))
            
            # Insert button at the END (before stretch)
            self.breadcrumb_layout.insertWidget(self.breadcrumb_layout.count() - 1, btn)
            
            # Add separator (except for last item)
            if i < len(parts) - 1:
                separator = QLabel("›")
                separator.setStyleSheet(f"color: #999999; padding: 0 2px; font-size: 12px; font-family: {UI_FONT};")
                # Insert separator at the END (before stretch)
                self.breadcrumb_layout.insertWidget(self.breadcrumb_layout.count() - 1, separator)
    
    def enter_edit_mode(self):
        """Switch to manual path edit mode"""
        self.scroll_area.hide()
        self.path_edit.setText(self.current_path)
        self.path_edit.show()
        self.path_edit.setFocus()
        self.path_edit.selectAll()
        # Force layout update
        self.updateGeometry()
        self.layout.update()
    
    def exit_edit_mode(self):
        """Exit manual edit mode and emit path if valid"""
        new_path = self.path_edit.text().strip()
        
        # Switch back to breadcrumb mode
        self.path_edit.hide()
        self.scroll_area.show()
        
        # Force layout update
        self.updateGeometry()
        self.layout.update()
        
        # Only emit path if valid and different
        if new_path and Path(new_path).exists() and new_path != self.current_path:
            self.path_clicked.emit(new_path)
    
    def cancel_edit_mode(self):
        """Cancel edit mode without applying changes"""
        # Only cancel if path_edit is still visible (not already processed by returnPressed)
        if self.path_edit.isVisible():
            self.path_edit.hide()
            self.scroll_area.show()
            # Force layout update
            self.updateGeometry()
            self.layout.update()
    
    def set_collection_mode(self, collection_name):
        """Set breadcrumb to collection mode - shows collection name instead of path"""
        # Clear existing buttons
        while self.breadcrumb_layout.count() > 1:  # Keep the stretch
            item = self.breadcrumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Create collection icon + name button (using gray triangle icon)
        collection_btn = QPushButton(f"▸ {collection_name}")
        collection_btn.setFlat(True)
        collection_btn.setMaximumHeight(24)
        collection_btn.setStyleSheet(f"""
            QPushButton {{
                border: none;
                padding: 2px 8px;
                background: transparent;
                text-align: left;
                font-size: 12px;
                font-family: {UI_FONT};
                color: #b0b0b0;
                font-weight: bold;
            }}
        """)
        collection_btn.setEnabled(False)  # Not clickable
        
        # Insert at the END (before stretch)
        self.breadcrumb_layout.insertWidget(self.breadcrumb_layout.count() - 1, collection_btn)
        
        # Apply blue background style
        self.breadcrumb_container.setStyleSheet("""
            QWidget {
                background-color: #2a4a6a;
                border-radius: 3px;
            }
        """)
    
    def clear_collection_mode(self):
        """Clear collection mode and restore normal path breadcrumb"""
        # Reset background style
        self.breadcrumb_container.setStyleSheet("QWidget { background-color: #3c3c3c; }")
        
        # Restore normal breadcrumbs
        self.update_breadcrumbs()


class EnhancedSearchBar(QWidget):
    """Enhanced search bar with case-sensitive and regex toggles"""
    
    textChanged = Signal(str)  # Emitted when search text changes (real-time when subfolders OFF)
    optionsChanged = Signal()  # Emitted when case/regex toggles change
    searchRequested = Signal()  # Emitted when search button is clicked (subfolder search)
    searchCleared = Signal()  # Emitted when clear button is clicked
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.match_count = 0
        self.total_count = 0
        self.setup_ui()
    
    def setup_ui(self):
        """Setup search bar UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(5)
        
        # Search input field (no icon before it)
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search files... (Ctrl+F)")
        self.search_input.setMinimumWidth(300)
        self.search_input.setStyleSheet(f"font-size: 12px; font-family: {UI_FONT}; padding: 4px;")
        self.search_input.textChanged.connect(self._on_text_changed)
        self.search_input.returnPressed.connect(self._on_return_pressed)  # Enter key support
        layout.addWidget(self.search_input)
        
        # Search button (enabled only when Subfolders is checked)
        self.search_btn = QPushButton("🔍")
        self.search_btn.setMaximumWidth(35)
        self.search_btn.setMinimumHeight(28)
        self.search_btn.setMaximumHeight(28)
        self.search_btn.setToolTip("Search in Subfolders (Enter)")
        self.search_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px;
                background-color: #2a2a2a;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #4b7daa;
                border-color: #5a8db8;
            }
            QPushButton:pressed {
                background-color: #3a6d9a;
            }
            QPushButton:disabled {
                background-color: transparent;
                border-color: transparent;
                opacity: 0.3;
            }
        """)
        self.search_btn.clicked.connect(self._on_search_clicked)
        self.search_btn.setEnabled(False)  # Initially disabled (not hidden)
        layout.addWidget(self.search_btn)
        
        # Case-sensitive toggle button
        self.case_btn = QPushButton("Aa")
        self.case_btn.setCheckable(True)
        self.case_btn.setToolTip("Case Sensitive Search")
        self.case_btn.setMaximumWidth(35)
        self.case_btn.setMinimumHeight(28)
        self.case_btn.setMaximumHeight(28)
        self.case_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px;
                background-color: #2a2a2a;
            }
            QPushButton:checked {
                background-color: #4b7daa;
                border-color: #5a8db8;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
        """)
        self.case_btn.clicked.connect(self._on_options_changed)
        layout.addWidget(self.case_btn)
        
        # Regex toggle button
        self.regex_btn = QPushButton(".*")
        self.regex_btn.setCheckable(True)
        self.regex_btn.setToolTip("Regular Expression Search")
        self.regex_btn.setMaximumWidth(35)
        self.regex_btn.setMinimumHeight(28)
        self.regex_btn.setMaximumHeight(28)
        self.regex_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px;
                background-color: #2a2a2a;
                font-family: 'Courier New', monospace;
            }
            QPushButton:checked {
                background-color: #4b7daa;
                border-color: #5a8db8;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
        """)
        self.regex_btn.clicked.connect(self._on_options_changed)
        layout.addWidget(self.regex_btn)
        
        # Subfolders checkbox - search in subfolders when enabled
        self.subfolders_checkbox = QCheckBox("Subfolders")
        self.subfolders_checkbox.setToolTip("Search in subfolders (manual trigger with search button)")
        self.subfolders_checkbox.setChecked(False)
        # Use default checkbox style (same as Thumbnails and Sequences checkboxes)
        self.subfolders_checkbox.stateChanged.connect(self._on_subfolders_toggled)
        layout.addWidget(self.subfolders_checkbox)
        
        # Clear button (only visible when text present)
        self.clear_btn = QPushButton("❌")
        self.clear_btn.setMaximumWidth(30)
        self.clear_btn.setToolTip("Clear Search")
        self.clear_btn.clicked.connect(self.clear_search)
        self.clear_btn.setVisible(False)
        layout.addWidget(self.clear_btn)
        
        # Match count label
        self.match_label = QLabel("")
        self.match_label.setStyleSheet(f"color: #888; font-size: 12px; font-family: {UI_FONT}; font-weight: bold;")
        self.match_label.setMinimumWidth(90)
        layout.addWidget(self.match_label)
        
        # Search progress label (visible during subfolder search)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: #f39c12; font-size: 11px; font-family: {UI_FONT}; font-style: italic;")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)
        
        layout.addStretch()
    
    def _on_text_changed(self, text):
        """Handle text change"""
        self.clear_btn.setVisible(bool(text))
        # Only emit textChanged if subfolders is OFF (real-time search)
        # If subfolders is ON, search is triggered manually with button
        if not self.subfolders_checkbox.isChecked():
            self.textChanged.emit(text)
    
    def _on_return_pressed(self):
        """Handle Enter key press in search field"""
        if self.subfolders_checkbox.isChecked():
            # If subfolders mode, trigger search
            self._on_search_clicked()
        # If not in subfolders mode, real-time search already handled by textChanged
    
    def _on_search_clicked(self):
        """Handle search button click (subfolder search)"""
        self.searchRequested.emit()
    
    def _on_subfolders_toggled(self):
        """Handle subfolders checkbox toggle"""
        is_checked = self.subfolders_checkbox.isChecked()
        # Enable/disable search button based on subfolders state (not hide/show)
        self.search_btn.setEnabled(is_checked)
        # Notify options changed
        self.optionsChanged.emit()
    
    def _on_options_changed(self):
        """Handle case/regex toggle change"""
        self.optionsChanged.emit()
    
    def clear_search(self):
        """Clear search text"""
        self.search_input.clear()
        # Emit cleared signal so browser can reset state (even when subfolders is ON)
        self.searchCleared.emit()
    
    def set_match_count(self, matches, total):
        """Update match count display"""
        self.match_count = matches
        self.total_count = total
        if matches > 0:
            self.match_label.setText(f"{matches} match{'es' if matches != 1 else ''}")
            self.match_label.setStyleSheet(f"color: #5dade2; font-size: 12px; font-family: {UI_FONT}; font-weight: bold;")  # Maya cyan
        elif self.search_input.text():
            self.match_label.setText("No matches")
            self.match_label.setStyleSheet(f"color: #e74c3c; font-size: 12px; font-family: {UI_FONT}; font-weight: bold;")  # Brighter red
        else:
            self.match_label.setText("")
    
    def is_case_sensitive(self):
        """Check if case-sensitive search is enabled"""
        return self.case_btn.isChecked()
    
    def is_regex_enabled(self):
        """Check if regex search is enabled"""
        return self.regex_btn.isChecked()
    
    def is_subfolders_enabled(self):
        """Check if subfolder search is enabled"""
        return self.subfolders_checkbox.isChecked()
    
    def get_text(self):
        """Get current search text"""
        return self.search_input.text()
    
    def set_case_sensitive(self, enabled):
        """Set case-sensitive mode"""
        self.case_btn.setChecked(enabled)
    
    def set_regex_enabled(self, enabled):
        """Set regex mode"""
        self.regex_btn.setChecked(enabled)
    
    def set_subfolders_enabled(self, enabled):
        """Set subfolders search mode"""
        self.subfolders_checkbox.setChecked(enabled)
    
    def set_search_progress(self, scanned, matches):
        """Show search progress (files scanned and matches found)"""
        if scanned > 0:
            self.progress_label.setText(f"⏳ Scanning... {scanned} files | {matches} matches")
            self.progress_label.setVisible(True)
            # Hide match count while searching
            self.match_label.setVisible(False)
        else:
            self.progress_label.setVisible(False)
            self.match_label.setVisible(True)
    
    def clear_search_progress(self):
        """Clear search progress display"""
        self.progress_label.setVisible(False)
        self.match_label.setVisible(True)


class FilterPanel(QWidget):
    """Advanced filter panel widget"""
    
    filtersChanged = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup filter panel UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)
        
        # Header with toggle button
        header_layout = QHBoxLayout()
        self.toggle_btn = QPushButton("▼ Filters")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False)
        self.toggle_btn.setMaximumWidth(100)
        header_layout.addWidget(self.toggle_btn)
        
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.setMaximumWidth(80)
        header_layout.addWidget(self.clear_btn)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # Filter content (collapsible) - COMPACT HORIZONTAL LAYOUT
        self.filter_content = QWidget()
        self.filter_content.setMaximumHeight(120)  # Taller for 3 rows
        content_layout = QHBoxLayout(self.filter_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        
        # === COLUMN 1: File Types (Compact 2-row grid) ===
        self.type_group = QGroupBox("File Types")
        type_grid = QtWidgets.QGridLayout(self.type_group)
        type_grid.setSpacing(3)
        type_grid.setContentsMargins(5, 8, 5, 5)
        
        self.type_checkboxes = {}
        
        # Get file types from central registry
        from .utils import get_simple_filter_types
        file_types = get_simple_filter_types()
        
        # Calculate grid layout (3 columns, auto rows)
        cols = 3
        for idx, (ext, label) in enumerate(file_types):
            row = idx // cols
            col = idx % cols
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.stateChanged.connect(self.on_filter_changed)
            self.type_checkboxes[ext] = cb
            type_grid.addWidget(cb, row, col)
        
        self.type_group.setMaximumWidth(220)  # Wider for more items
        self.type_group.setMaximumHeight(140)  # Taller for more rows
        content_layout.addWidget(self.type_group)
        
        # === COLUMN 2: Size Filter (Compact) ===
        size_group = QGroupBox("File Size")
        size_layout = QFormLayout(size_group)
        size_layout.setSpacing(2)
        size_layout.setContentsMargins(5, 8, 5, 5)
        
        self.size_min_spin = QSpinBox()
        self.size_min_spin.setRange(0, 10000)
        self.size_min_spin.setSuffix(" MB")
        self.size_min_spin.setMaximumWidth(80)
        self.size_min_spin.valueChanged.connect(self.on_filter_changed)
        
        self.size_max_spin = QSpinBox()
        self.size_max_spin.setRange(0, 10000)
        self.size_max_spin.setSuffix(" MB")
        self.size_max_spin.setMaximumWidth(80)
        self.size_max_spin.valueChanged.connect(self.on_filter_changed)
        
        size_layout.addRow("Min:", self.size_min_spin)
        size_layout.addRow("Max:", self.size_max_spin)
        
        size_group.setMaximumWidth(150)
        size_group.setMaximumHeight(90)
        content_layout.addWidget(size_group)
        
        # === COLUMN 3: Date Filter (Compact) ===
        date_group = QGroupBox("Modified Date")
        date_layout = QHBoxLayout(date_group)
        date_layout.setSpacing(3)
        date_layout.setContentsMargins(5, 8, 5, 5)
        
        # Quick filter buttons
        self.date_today_btn = QPushButton("Today")
        self.date_week_btn = QPushButton("Week")
        self.date_month_btn = QPushButton("Month")
        self.date_today_btn.setMaximumWidth(55)
        self.date_week_btn.setMaximumWidth(50)
        self.date_month_btn.setMaximumWidth(55)
        
        self.date_today_btn.clicked.connect(lambda: self.set_date_range("today"))
        self.date_week_btn.clicked.connect(lambda: self.set_date_range("week"))
        self.date_month_btn.clicked.connect(lambda: self.set_date_range("month"))
        
        date_layout.addWidget(self.date_today_btn)
        date_layout.addWidget(self.date_week_btn)
        date_layout.addWidget(self.date_month_btn)
        
        # Custom range button (opens date picker dialog)
        self.date_custom_btn = QPushButton("...")
        self.date_custom_btn.setMaximumWidth(30)
        self.date_custom_btn.setToolTip("Custom Date Range")
        self.date_custom_btn.clicked.connect(self.open_custom_date_dialog)
        date_layout.addWidget(self.date_custom_btn)
        
        # Clear date filter button
        self.date_clear_btn = QPushButton("✕")
        self.date_clear_btn.setMaximumWidth(25)
        self.date_clear_btn.setToolTip("Clear Date Filter")
        self.date_clear_btn.clicked.connect(self.clear_date_filter)
        date_layout.addWidget(self.date_clear_btn)
        
        # Store date range internally
        self.date_from = None
        self.date_to = None
        
        date_group.setMaximumWidth(250)
        date_group.setMaximumHeight(90)
        content_layout.addWidget(date_group)
        
        # === COLUMN 4: Options (Compact) ===
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        options_layout.setSpacing(2)
        options_layout.setContentsMargins(5, 8, 5, 5)
        
        self.show_folders_check = QCheckBox("Show Folders")
        self.show_folders_check.setChecked(True)
        self.show_folders_check.stateChanged.connect(self.on_filter_changed)
        options_layout.addWidget(self.show_folders_check)
        
        self.show_images_check = QCheckBox("Show Images")
        self.show_images_check.setChecked(True)
        self.show_images_check.setToolTip("Show image files (TIF, JPG, PNG, HDR, EXR, TGA)")
        self.show_images_check.stateChanged.connect(self.on_filter_changed)
        options_layout.addWidget(self.show_images_check)
        
        self.show_scripts_check = QCheckBox("Show Scripts")
        self.show_scripts_check.setChecked(True)
        self.show_scripts_check.setToolTip("Show script files (MEL, Python)")
        self.show_scripts_check.stateChanged.connect(self.on_filter_changed)
        options_layout.addWidget(self.show_scripts_check)
        
        options_group.setMaximumWidth(120)
        options_group.setMaximumHeight(120)
        content_layout.addWidget(options_group)
        
        content_layout.addStretch()
        
        layout.addWidget(self.filter_content)
        self.filter_content.hide()  # Initially collapsed
        
        # Connections
        self.toggle_btn.toggled.connect(self.toggle_filters)
        self.clear_btn.clicked.connect(self.clear_all_filters)
    
    def toggle_filters(self, checked):
        """Toggle filter panel visibility"""
        if checked:
            self.toggle_btn.setText("▲ Filters")
            self.filter_content.show()
        else:
            self.toggle_btn.setText("▼ Filters")
            self.filter_content.hide()
    
    def on_filter_changed(self):
        """Emit signal when any filter changes"""
        self.filtersChanged.emit()
    
    def open_custom_date_dialog(self):
        """Open dialog to select custom date range"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Custom Date Range")
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        
        # From date
        from_label = QLabel("From Date:")
        from_edit = QDateEdit()
        from_edit.setCalendarPopup(True)
        from_edit.setDisplayFormat("yyyy-MM-dd")
        from_edit.setDate(QDate.currentDate().addDays(-7))
        
        layout.addWidget(from_label)
        layout.addWidget(from_edit)
        
        # To date
        to_label = QLabel("To Date:")
        to_edit = QDateEdit()
        to_edit.setCalendarPopup(True)
        to_edit.setDisplayFormat("yyyy-MM-dd")
        to_edit.setDate(QDate.currentDate())
        
        layout.addWidget(to_label)
        layout.addWidget(to_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        if dialog.exec_() == QDialog.Accepted:
            # Convert QDate to datetime
            from_qdate = from_edit.date()
            to_qdate = to_edit.date()
            
            self.date_from = datetime(from_qdate.year(), from_qdate.month(), from_qdate.day())
            self.date_to = datetime(to_qdate.year(), to_qdate.month(), to_qdate.day(), 23, 59, 59)
            
            self.on_filter_changed()
    
    def clear_date_filter(self):
        """Clear date filter"""
        self.date_from = None
        self.date_to = None
        self.on_filter_changed()
    
    def set_date_range(self, range_type):
        """Set date range filter"""
        now = datetime.now()
        
        if range_type == "today":
            self.date_from = now.replace(hour=0, minute=0, second=0)
            self.date_to = now
        elif range_type == "week":
            self.date_from = now - timedelta(days=7)
            self.date_to = now
        elif range_type == "month":
            self.date_from = now - timedelta(days=30)
            self.date_to = now
        
        self.on_filter_changed()
    
    def get_selected_file_types(self):
        """Get list of selected file type extensions"""
        selected = []
        for ext, cb in self.type_checkboxes.items():
            if cb.isChecked():
                selected.append(ext)
        return selected
    
    def get_size_range(self):
        """Get size range in bytes (returns min, max)"""
        min_mb = self.size_min_spin.value()
        max_mb = self.size_max_spin.value()
        
        min_bytes = min_mb * 1024 * 1024 if min_mb > 0 else 0
        max_bytes = max_mb * 1024 * 1024 if max_mb > 0 else 0
        
        return min_bytes, max_bytes
    
    def get_date_range(self):
        """Get date range (returns from, to)"""
        # Return current date range if set
        return self.date_from, self.date_to
    
    def get_show_folders(self):
        """Get show folders option"""
        return self.show_folders_check.isChecked()
    
    def get_show_images(self):
        """Get show images option"""
        return self.show_images_check.isChecked()
    
    def get_show_scripts(self):
        """Get show scripts option"""
        return self.show_scripts_check.isChecked()
    
    def clear_all_filters(self):
        """Clear all filters to default state"""
        # Reset all file type checkboxes
        for cb in self.type_checkboxes.values():
            cb.setChecked(True)
        
        # Reset size filters
        self.size_min_spin.setValue(0)
        self.size_max_spin.setValue(0)
        
        # Reset date filter
        self.date_from = None
        self.date_to = None
        
        # Reset options
        self.show_folders_check.setChecked(True)
        self.show_images_check.setChecked(True)
        self.show_scripts_check.setChecked(True)
        
        self.on_filter_changed()
    
    def rebuild_type_filters(self):
        """Rebuild file type checkboxes from current config"""
        # Force reload config to get latest changes
        from .utils import reload_file_formats_config, get_simple_filter_types
        reload_file_formats_config()
        
        # Get current layout
        layout = self.type_group.layout()
        
        # Clear existing checkboxes
        for cb in self.type_checkboxes.values():
            layout.removeWidget(cb)
            cb.deleteLater()
        self.type_checkboxes.clear()
        
        # Get updated file types from config
        file_types = get_simple_filter_types()
        
        # Rebuild grid
        cols = 3
        for idx, (ext, label) in enumerate(file_types):
            row = idx // cols
            col = idx % cols
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.stateChanged.connect(self.on_filter_changed)
            self.type_checkboxes[ext] = cb
            layout.addWidget(cb, row, col)


def load_hdr_exr_raw(file_path, max_size=2048):
    """
    Load raw HDR/EXR float data (NO tone mapping) for fast exposure adjustment
    
    Args:
        file_path: Path to HDR/EXR file
        max_size: Maximum width/height for preview (default 2048)
        
    Returns:
        tuple: (rgb_float_array, width, height, resolution_str) or (None, None, None, None) on failure
    """
    file_path_str = str(file_path)
    file_ext = file_path_str.lower()
    
    # Use OpenCV for .hdr (Radiance RGBE) files if available (best option!)
    if file_ext.endswith('.hdr') and OPENCV_AVAILABLE and NUMPY_AVAILABLE:
        try:
            # print(f"🔍 Attempting to load HDR with OpenCV: {file_path_str}")
            # Read HDR with OpenCV (cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR for float32)
            rgb = cv2.imread(file_path_str, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR)
            
            if rgb is None:
                raise Exception("OpenCV returned None - file may be corrupted or unsupported")
            
            # OpenCV loads as BGR, convert to RGB
            rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
            
            # print(f"✅ OpenCV loaded HDR: shape={rgb.shape}, dtype={rgb.dtype}, min={rgb.min():.3f}, max={rgb.max():.3f}")
            
            height, width = rgb.shape[:2]
            resolution_str = f"{width} x {height}"
            
            # Scale if needed
            if width > max_size or height > max_size:
                scale = min(max_size / width, max_size / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                
                # Use OpenCV resize (high quality)
                rgb = cv2.resize(rgb, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                width, height = new_width, new_height
            
            # print(f"✅ HDR ready for tone mapping: {width}x{height}")
            # Return RAW float data (no tone mapping!)
            return rgb, width, height, resolution_str
            
        except Exception as e:
            print(f"❌ OpenCV HDR loading failed: {e}")
            import traceback
            print(f"❌ OpenCV HDR loading failed: {e}")
            import traceback
            traceback.print_exc()
            return None, None, None, None
    
    # Use OpenEXR for .exr files if available
    if file_ext.endswith('.exr') and OPENEXR_AVAILABLE and NUMPY_AVAILABLE:
        try:
            # Open EXR file
            with OpenEXR.File(file_path_str) as exr_file:
                # Get header info
                header = exr_file.header()
                dw = header['dataWindow']
                width = dw[1][0] - dw[0][0] + 1
                height = dw[1][1] - dw[0][1] + 1
                resolution_str = f"{width} x {height}"
                
                # Read RGB channels
                channels = exr_file.channels()
                rgb = None
                
                # Try standard interleaved RGB or RGBA
                if "RGB" in channels:
                    rgb = np.array(channels["RGB"].pixels, dtype=np.float32).reshape(height, width, 3)
                elif "RGBA" in channels:
                    rgba = np.array(channels["RGBA"].pixels, dtype=np.float32).reshape(height, width, 4)
                    rgb = rgba[:, :, :3]  # Drop alpha
                elif all(c in channels for c in ["R", "G", "B"]):
                    r = np.array(channels["R"].pixels, dtype=np.float32).reshape(height, width)
                    g = np.array(channels["G"].pixels, dtype=np.float32).reshape(height, width)
                    b = np.array(channels["B"].pixels, dtype=np.float32).reshape(height, width)
                    rgb = np.stack([r, g, b], axis=2)
                
                if rgb is None:
                    return None, None, None, None
                
                # Scale if needed
                if width > max_size or height > max_size:
                    scale = min(max_size / width, max_size / height)
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    
                    # Simple nearest-neighbor resize (fast)
                    indices_h = np.linspace(0, height-1, new_height, dtype=int)
                    indices_w = np.linspace(0, width-1, new_width, dtype=int)
                    rgb = rgb[np.ix_(indices_h, indices_w)]
                    
                    width, height = new_width, new_height
                
                # Return RAW float data (no tone mapping!)
                return rgb, width, height, resolution_str
                
        except Exception as e:
            error_msg = str(e)
            # Deep/volumetric EXR files are not supported
            if "non-numeric dtype" in error_msg or "object" in error_msg:
                print(f"ℹ️  Deep/volumetric EXR not supported for preview: {Path(file_path_str).name}")
            else:
                print(f"OpenEXR raw loading failed: {e}")
            return None, None, None, None
    
    # If neither imageio nor OpenEXR available
    return None, None, None, None


def load_hdr_exr_image(file_path, max_size=3840, exposure=0.0, return_raw=False, metadata_manager=None):
    """
    Load HDR/EXR image with proper float HDR handling and ACES color management support
    
    Args:
        file_path: Path to HDR/EXR file
        max_size: Maximum width/height for preview (default 3840 for 4K quality)
        exposure: Exposure compensation in stops (0.0 = neutral, +1.0 = 2x brighter, -1.0 = half)
                 Like Arnold/Maya lighting exposure
        return_raw: If True, also return raw float RGB array (for caching)
        metadata_manager: Optional metadata manager for tag-based color management
        
    Returns:
        If return_raw=False: tuple (QPixmap, resolution_string) or (None, None) on failure
        If return_raw=True: tuple (QPixmap, resolution_string, rgb_raw_array) or (None, None, None) on failure
    """
    file_path_str = str(file_path)
    file_ext = file_path_str.lower()
    
    # FAST CHECK: Check if EXR is tagged as deep data (skip file check)
    if file_ext.endswith('.exr') and metadata_manager:
        try:
            from pathlib import Path
            file_metadata = metadata_manager.get_file_metadata(str(file_path))
            file_tags = file_metadata.get('tags', [])
            tag_names_lower = [tag['name'].lower() for tag in file_tags]
            
            if "deepdata" in tag_names_lower:
                # Deep EXR - return immediately without loading
                if return_raw:
                    return None, "Deep EXR - No Preview", None
                else:
                    return None, "Deep EXR - No Preview"
        except:
            pass
    
    # Use OpenCV for .hdr (Radiance RGBE) files if available
    if file_ext.endswith('.hdr') and OPENCV_AVAILABLE and NUMPY_AVAILABLE:
        try:
            # Read HDR with OpenCV
            rgb = cv2.imread(file_path_str, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR)
            
            if rgb is None:
                raise Exception("OpenCV returned None")
            
            # OpenCV loads as BGR, convert to RGB
            rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
            
            if rgb.ndim == 2:
                # Grayscale - convert to RGB
                rgb = np.stack([rgb, rgb, rgb], axis=2)
            elif rgb.shape[2] == 4:
                # RGBA - drop alpha
                rgb = rgb[:, :, :3]
            
            height, width = rgb.shape[:2]
            resolution_str = f"{width} x {height}"
            
            # Scale if needed
            if width > max_size or height > max_size:
                scale = min(max_size / width, max_size / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                
                # Use OpenCV resize
                rgb = cv2.resize(rgb, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                width, height = new_width, new_height
            
            # Check for ACES color management via tags
            use_aces = False
            if file_path_str.lower().endswith('.exr') and metadata_manager:
                try:
                    from pathlib import Path
                    file_metadata = metadata_manager.get_file_metadata(str(file_path))
                    file_tags = file_metadata.get('tags', [])
                    tag_names_lower = [tag['name'].lower() for tag in file_tags]
                    
                    if "acescg" in tag_names_lower or "srgb(aces)" in tag_names_lower:
                        use_aces = True
                except:
                    pass
            
            # Apply exposure compensation with -1 stop offset (match Nuke/Maya)
            compensated_exposure = exposure - 1.0
            
            if use_aces:
                # Use ACES view transform
                from .aces_color import apply_aces_view_transform
                rgb_display = apply_aces_view_transform(rgb, exposure=compensated_exposure)
            else:
                # Standard tone mapping
                exposure_multiplier = pow(2.0, compensated_exposure)
                rgb = rgb * exposure_multiplier
                
                # ACES Filmic tone mapping
                a = 2.51
                b = 0.03
                c = 2.43
                d = 0.59
                e = 0.14
                rgb_tonemapped = np.clip((rgb * (a * rgb + b)) / (rgb * (c * rgb + d) + e), 0, 1)
                
                # Gamma correction (2.2 for sRGB)
                gamma = 1.0 / 2.2
                rgb_display = np.power(rgb_tonemapped, gamma)
            
            # Convert to 8-bit
            rgb_8bit = (rgb_display * 255).astype(np.uint8)
            
            # Create QImage
            bytes_per_line = width * 3
            q_image = QImage(rgb_8bit.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
            q_image = q_image.copy()
            
            # Convert to QPixmap
            pixmap = QPixmap.fromImage(q_image)
            return pixmap, resolution_str
            
        except Exception as e:
            print(f"OpenCV HDR loading failed: {e}")
            import traceback
            traceback.print_exc()
            # Fall through to Maya MImage fallback
    
    # Use OpenEXR for .exr files if available
    if file_ext.endswith('.exr') and OPENEXR_AVAILABLE and NUMPY_AVAILABLE:
        try:
            # Open EXR file
            with OpenEXR.File(file_path_str) as exr_file:
                # Get header info
                header = exr_file.header()
                dw = header['dataWindow']
                width = dw[1][0] - dw[0][0] + 1
                height = dw[1][1] - dw[0][1] + 1
                resolution_str = f"{width} x {height}"
                
                # Read RGB channels as interleaved array
                channels = exr_file.channels()
                
                # Get RGB data (returns numpy array directly!)
                # Try multiple naming conventions for RGB channels
                rgb = None
                
                # 1. Try standard interleaved RGB or RGBA
                if "RGB" in channels:
                    rgb_data = channels["RGB"].pixels  # Shape: (height, width, 3)
                    if rgb_data is not None:
                        rgb = rgb_data
                elif "RGBA" in channels:
                    rgba_data = channels["RGBA"].pixels  # Shape: (height, width, 4)
                    if rgba_data is not None:
                        rgb = rgba_data[:, :, :3]  # Drop alpha, keep RGB only
                
                # 2. Try separate R, G, B channels
                elif all(c in channels for c in ["R", "G", "B"]):
                    r = channels["R"].pixels
                    g = channels["G"].pixels
                    b = channels["B"].pixels
                    if r is not None and g is not None and b is not None:
                        rgb = np.stack([r, g, b], axis=2)  # Shape: (height, width, 3)
                
                # 3. Try Beauty pass (common in render layers)
                elif all(c in channels for c in ["Beauty.R", "Beauty.G", "Beauty.B"]):
                    r = channels["Beauty.R"].pixels
                    g = channels["Beauty.G"].pixels
                    b = channels["Beauty.B"].pixels
                    if r is not None and g is not None and b is not None:
                        rgb = np.stack([r, g, b], axis=2)
                
                # 4. Try first layer with .R .G .B (generic multi-layer)
                else:
                    # Find first layer that has RGB channels
                    channel_names = list(channels.keys())
                    layer_prefixes = set()
                    for name in channel_names:
                        if '.' in name:
                            prefix = name.rsplit('.', 1)[0]
                            layer_prefixes.add(prefix)
                    
                    # Try each layer prefix
                    for prefix in sorted(layer_prefixes):
                        r_name = f"{prefix}.R"
                        g_name = f"{prefix}.G"
                        b_name = f"{prefix}.B"
                        if all(c in channels for c in [r_name, g_name, b_name]):
                            r = channels[r_name].pixels
                            g = channels[g_name].pixels
                            b = channels[b_name].pixels
                            if r is not None and g is not None and b is not None:
                                rgb = np.stack([r, g, b], axis=2)
                                break
                
                # 5. If still no RGB, try single channel (grayscale)
                if rgb is None:
                    # Try common single-channel names first
                    single_channels = ["Y", "Z", "depth", "A", "alpha", "luminance"]
                    for ch_name in single_channels:
                        if ch_name in channels:
                            gray = channels[ch_name].pixels
                            if gray is not None:
                                # Convert to RGB by repeating channel
                                if gray.ndim == 2:
                                    rgb = np.stack([gray, gray, gray], axis=2)
                                else:
                                    # Already 3D, just use it
                                    rgb = gray
                                break
                
                # 6. Last resort: use ANY available channel as grayscale
                if rgb is None and len(channels) > 0:
                    # Take the first available channel
                    first_channel_name = list(channels.keys())[0]
                    gray = channels[first_channel_name].pixels
                    
                    if gray is not None:
                        # Convert to RGB by repeating channel
                        if gray.ndim == 2:
                            rgb = np.stack([gray, gray, gray], axis=2)
                        elif gray.ndim == 3 and gray.shape[2] == 1:
                            # Single channel as 3D array
                            rgb = np.concatenate([gray, gray, gray], axis=2)
                        else:
                            rgb = gray
                
                # If still nothing, list available channels and give up
                if rgb is None:
                    available = ", ".join(sorted(channels.keys())[:10])  # Show first 10
                    raise Exception(f"No usable channels found. Available: {available}")
                
                # Final safety check: verify rgb is valid numpy array with data
                if rgb is None or not isinstance(rgb, np.ndarray) or rgb.size == 0:
                    raise Exception(f"RGB data is invalid or empty after channel processing")
                
                # Check if dtype is numeric (not object or other non-numeric types)
                # Deep EXR channels can return object arrays which we can't process
                if rgb.dtype == np.object_ or not np.issubdtype(rgb.dtype, np.number):
                    raise Exception(f"RGB data has non-numeric dtype: {rgb.dtype} (deep/volumetric EXR not supported)")
                
                # Scale if needed
                if width > max_size or height > max_size:
                    scale = min(max_size / width, max_size / height)
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    
                    # Simple nearest-neighbor resize (fast)
                    indices_h = np.linspace(0, height-1, new_height, dtype=int)
                    indices_w = np.linspace(0, width-1, new_width, dtype=int)
                    rgb = rgb[np.ix_(indices_h, indices_w)]
                    
                    width, height = new_width, new_height
                
                # Check for ACES color management via tags
                use_aces = False
                if metadata_manager:
                    try:
                        from pathlib import Path
                        file_metadata = metadata_manager.get_file_metadata(str(file_path))
                        file_tags = file_metadata.get('tags', [])
                        tag_names_lower = [tag['name'].lower() for tag in file_tags]
                        
                        if "acescg" in tag_names_lower or "srgb(aces)" in tag_names_lower:
                            use_aces = True
                    except:
                        pass
                
                # Apply exposure compensation with -1 stop offset (match Nuke/Maya)
                compensated_exposure = exposure - 1.0
                
                if use_aces:
                    # Use ACES view transform
                    from .aces_color import apply_aces_view_transform
                    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
                        rgb_display = apply_aces_view_transform(rgb, exposure=compensated_exposure)
                else:
                    # Standard tone mapping
                    exposure_multiplier = pow(2.0, compensated_exposure)
                    rgb = rgb * exposure_multiplier
                    
                    # ACES Filmic tone mapping
                    a = 2.51
                    b = 0.03
                    c = 2.43
                    d = 0.59
                    e = 0.14
                    
                    # Suppress numpy warnings for HDR tonemapping
                    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
                        rgb_tonemapped = np.clip((rgb * (a * rgb + b)) / (rgb * (c * rgb + d) + e), 0, 1)
                    
                    # Gamma correction (2.2 for sRGB)
                    gamma = 1.0 / 2.2
                    rgb_display = np.power(rgb_tonemapped, gamma)
                
                # Convert to 8-bit
                with np.errstate(invalid='ignore'):
                    rgb_8bit = (rgb_display * 255).astype(np.uint8)
                
                # Create QImage
                bytes_per_line = width * 3
                q_image = QImage(rgb_8bit.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                q_image = q_image.copy()
                
                # Convert to QPixmap
                pixmap = QPixmap.fromImage(q_image)
                return pixmap, resolution_str
                
        except Exception as e:
            error_msg = str(e)
            # Deep/volumetric EXR files are not supported
            if "non-numeric dtype" in error_msg or "deep/volumetric" in error_msg.lower():
                print(f"ℹ️  Deep/volumetric EXR not supported for preview: {Path(file_path_str).name}")
            else:
                print(f"OpenEXR loading failed: {e}")
            # Fall through to Maya MImage fallback
    
    # Fallback: Use Maya MImage for HDR or if OpenEXR not available
    # Only available if Maya API is present
    if not MAYA_API_AVAILABLE or om is None:
        # No Maya API - return error
        return None, -1, f"HDR/EXR loading requires Maya API (not available in standalone mode)"
    
    try:
        # Use Maya's MImage to read HDR/EXR
        m_image = om.MImage()
        m_image.readFromFile(str(file_path))
        
        # Get image dimensions using getSize()
        size = m_image.getSize()
        width = size[0]
        height = size[1]
        resolution_str = f"{width} x {height}"
        
        # Calculate scaled size if needed
        if width > max_size or height > max_size:
            if width > height:
                scaled_width = max_size
                scaled_height = int(max_size * height / width)
            else:
                scaled_height = max_size
                scaled_width = int(max_size * width / height)
            
            # Resize the MImage
            m_image.resize(scaled_width, scaled_height, True)
            
            # Update dimensions after resize
            size = m_image.getSize()
            width = size[0]
            height = size[1]
        
        # Try to get HDR pixels if numpy is available
        if NUMPY_AVAILABLE:
            try:
                # Maya MImage doesn't reliably expose float pixels via API
                # Better approach: write to temp file in HDR format, then read with proper library
                
                # Try IFF format (Maya native, preserves more data than PNG)
                import tempfile
                import os
                
                # Write as IFF (Maya's format, better than PNG for HDR)
                temp_path = tempfile.mktemp(suffix='.iff')
                m_image.writeToFile(temp_path, 'iff')
                
                # Read back with Maya and get pixels
                m_image2 = om.MImage()
                m_image2.readFromFile(temp_path)
                m_image2.setRGBA(True)
                
                # Get 8-bit pixels (but from IFF which preserves more range)
                pixel_ptr = m_image2.pixels()
                
                if pixel_ptr:
                    import ctypes
                    pixel_count = width * height * 4  # RGBA bytes
                    
                    # Create numpy array from 8-bit pixel data
                    ByteArray = ctypes.POINTER(ctypes.c_ubyte * pixel_count)
                    byte_array = ctypes.cast(pixel_ptr, ByteArray).contents
                    pixel_array = np.frombuffer(byte_array, dtype=np.uint8).copy()
                    pixel_array = pixel_array.reshape((height, width, 4))
                    
                    # Extract RGB
                    rgb = pixel_array[:, :, :3].astype(np.float32) / 255.0
                    
                    # Apply exposure compensation in stops (even on 8-bit, it helps)
                    exposure_multiplier = pow(2.0, exposure)
                    rgb = np.clip(rgb * exposure_multiplier, 0, 1)
                    
                    # Gamma correction
                    gamma = 1.0 / 2.2
                    rgb = np.power(rgb, gamma)
                    
                    # Convert back to 8-bit
                    rgb_8bit = (rgb * 255).astype(np.uint8)
                    
                    # Clean up temp file
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                    
                    # Create QImage
                    bytes_per_line = width * 3
                    q_image = QImage(rgb_8bit.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                    q_image = q_image.copy()
                    
                    # Convert to QPixmap
                    pixmap = QPixmap.fromImage(q_image)
                    return pixmap, resolution_str
                
                # Clean up if we got here
                try:
                    os.remove(temp_path)
                except:
                    pass
                    
            except Exception as numpy_error:
                print(f"NumPy HDR processing failed: {numpy_error}")
                import traceback
                traceback.print_exc()
                # Fall through to PNG fallback
        
        # Fallback: PNG export + simple exposure (no proper tone mapping)
            import tempfile
            import os
        # Fallback: PNG export + simple exposure (no proper tone mapping)
        print("Using PNG fallback for HDR (NumPy not available - install for better quality)")
        import tempfile
        import os
        
        temp_path = tempfile.mktemp(suffix='.png')
        m_image.writeToFile(temp_path, 'png')
        q_image = QImage(temp_path)
        
        try:
            os.remove(temp_path)
        except:
            pass
        
        if q_image.isNull():
            return None, None
        
        q_image = q_image.convertToFormat(QImage.Format_RGB888)
        
        # Simple 8-bit exposure (not proper HDR)
        bits = q_image.bits()
        bytes_per_line = q_image.bytesPerLine()
        
        if PYSIDE_VERSION == 6:
            pixel_data = bits.tobytes()
        else:
            bits.setsize(q_image.height() * bytes_per_line)
            pixel_data = bytes(bits)
        
        pixel_array = bytearray(pixel_data)
        # Apply exposure in stops (2^exposure)
        exposure_multiplier = pow(2.0, exposure)
        for i in range(0, len(pixel_array), 3):
            pixel_array[i] = min(int(pixel_array[i] * exposure_multiplier), 255)
            pixel_array[i+1] = min(int(pixel_array[i+1] * exposure_multiplier), 255)
            pixel_array[i+2] = min(int(pixel_array[i+2] * exposure_multiplier), 255)
        
        q_image = QImage(bytes(pixel_array), q_image.width(), q_image.height(), bytes_per_line, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(q_image)
        return pixmap, resolution_str
        
    except Exception as e:
        print(f"Error loading HDR/EXR: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def load_pdf_page(file_path, page_number=0, max_size=1024):
    """
    Load PDF page as QPixmap for preview
    
    Args:
        file_path: Path to PDF file
        page_number: Page number to load (0-indexed)
        max_size: Maximum width/height for preview (default 1024)
        
    Returns:
        tuple: (QPixmap, page_count, resolution_str) or (None, 0, None) on failure
               Returns (None, -1, "encrypted") if PDF is password protected
    """
    if not PYMUPDF_AVAILABLE:
        print("PyMuPDF not available - cannot load PDF")
        return None, 0, None
    
    try:
        # Open PDF document
        doc = fitz.open(str(file_path))
        
        # Check if document is encrypted
        if doc.is_encrypted:
            print(f"[PDF] Password protected, skipping thumbnail generation: {Path(file_path).name}")
            doc.close()
            return None, -1, "encrypted"  # Special return value for encrypted PDFs
        
        page_count = len(doc)
        
        # Validate page number
        if page_number < 0 or page_number >= page_count:
            page_number = 0
        
        # Get page
        try:
            page = doc[page_number]
        except (ValueError, RuntimeError) as e:
            print(f"Error accessing PDF page {page_number}: {e}")
            doc.close()
            return None, 0, None
        
        # Get page dimensions
        rect = page.rect
        width = int(rect.width)
        height = int(rect.height)
        resolution_str = f"{width} x {height}"
        
        # Calculate zoom to fit max_size
        zoom = min(max_size / width, max_size / height, 2.0)  # Max 2x zoom for quality
        mat = fitz.Matrix(zoom, zoom)
        
        # Render page to pixmap
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # Convert to QImage
        img_format = QImage.Format_RGB888 if pix.n == 3 else QImage.Format_RGBA8888
        q_image = QImage(pix.samples, pix.width, pix.height, pix.stride, img_format)
        q_image = q_image.copy()  # Make a deep copy
        
        # Convert to QPixmap
        pixmap = QPixmap.fromImage(q_image)
        
        # Close document
        doc.close()
        
        return pixmap, page_count, resolution_str
        
    except Exception as e:
        print(f"Error loading PDF: {e}")
        import traceback
        traceback.print_exc()
        return None, 0, None


def get_pdf_max_page_size(file_path):
    """
    Get maximum page dimensions across all pages in a PDF
    This is used for consistent layout when pages have different sizes
    
    Args:
        file_path: Path to PDF file
        
    Returns:
        tuple: (max_width, max_height, page_count) or (None, None, 0) on failure
    """
    if not PYMUPDF_AVAILABLE:
        return None, None, 0
    
    try:
        doc = fitz.open(str(file_path))
        
        # Check if encrypted
        if doc.is_encrypted:
            doc.close()
            return None, None, 0
        
        page_count = len(doc)
        max_width = 0
        max_height = 0
        
        # Scan all pages for maximum dimensions
        for page_num in range(page_count):
            try:
                page = doc[page_num]
                rect = page.rect
                max_width = max(max_width, int(rect.width))
                max_height = max(max_height, int(rect.height))
            except Exception as e:
                print(f"[PDF] Error reading page {page_num}: {e}")
                continue
        
        doc.close()
        
        return max_width, max_height, page_count
        
    except Exception as e:
        print(f"[PDF] Error scanning page sizes: {e}")
        return None, None, 0


def load_pdf_page_normalized(file_path, page_number=0, max_size=1024, canvas_size=None):
    """
    Load PDF page with normalized/centered layout for consistent sizing
    
    Args:
        file_path: Path to PDF file
        page_number: Page number to load (0-indexed)
        max_size: Maximum width/height for preview (default 1024)
        canvas_size: Optional tuple (width, height) to use as canvas size
                     If None, will auto-detect max page size in document
        
    Returns:
        tuple: (QPixmap, page_count, resolution_str, (canvas_w, canvas_h)) or (None, 0, None, None) on failure
    """
    if not PYMUPDF_AVAILABLE:
        print("PyMuPDF not available - cannot load PDF")
        return None, 0, None, None
    
    try:
        # Open PDF document
        doc = fitz.open(str(file_path))
        
        # Check if encrypted
        if doc.is_encrypted:
            print(f"[PDF] Password protected: {Path(file_path).name}")
            doc.close()
            return None, -1, "encrypted", None
        
        page_count = len(doc)
        
        # Validate page number
        if page_number < 0 or page_number >= page_count:
            page_number = 0
        
        # Get canvas size (either provided or auto-detect max size)
        if canvas_size is None:
            # Scan all pages for max dimensions
            max_width = 0
            max_height = 0
            for i in range(page_count):
                try:
                    p = doc[i]
                    r = p.rect
                    max_width = max(max_width, int(r.width))
                    max_height = max(max_height, int(r.height))
                except:
                    continue
            canvas_width = max_width
            canvas_height = max_height
        else:
            canvas_width, canvas_height = canvas_size
        
        # Get current page
        try:
            page = doc[page_number]
        except (ValueError, RuntimeError) as e:
            print(f"Error accessing PDF page {page_number}: {e}")
            doc.close()
            return None, 0, None, None
        
        # Get page dimensions
        rect = page.rect
        page_width = int(rect.width)
        page_height = int(rect.height)
        resolution_str = f"{page_width} x {page_height}"
        
        # Calculate zoom to fit max_size based on CANVAS size (not page size)
        zoom = min(max_size / canvas_width, max_size / canvas_height, 2.0)
        mat = fitz.Matrix(zoom, zoom)
        
        # Render page
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # Convert to QImage
        img_format = QImage.Format_RGB888 if pix.n == 3 else QImage.Format_RGBA8888
        q_image = QImage(pix.samples, pix.width, pix.height, pix.stride, img_format)
        q_image = q_image.copy()
        
        # Create canvas pixmap at normalized size
        canvas_scaled_width = int(canvas_width * zoom)
        canvas_scaled_height = int(canvas_height * zoom)
        canvas = QPixmap(canvas_scaled_width, canvas_scaled_height)
        canvas.fill(QColor(42, 42, 42))  # Match Quick View background (#2a2a2a)
        
        # Center the page image on canvas
        page_pixmap = QPixmap.fromImage(q_image)
        offset_x = (canvas_scaled_width - page_pixmap.width()) // 2
        offset_y = (canvas_scaled_height - page_pixmap.height()) // 2
        
        from PySide6.QtGui import QPainter
        painter = QPainter(canvas)
        painter.drawPixmap(offset_x, offset_y, page_pixmap)
        painter.end()
        
        doc.close()
        
        return canvas, page_count, resolution_str, (canvas_width, canvas_height)
        
    except Exception as e:
        print(f"Error loading PDF with normalization: {e}")
        import traceback
        traceback.print_exc()
        return None, 0, None, None


class MayaStyleListView(QListView):
    """
    Custom QListView with dual drag-and-drop modes:
    
    LEFT BUTTON (default):
    - Box selection (rubber band drag)
    - Drag a rectangle to select multiple items
    - ExtendedSelection mode: Ctrl+Click, Shift+Click for multi-select
    
    ALT + LEFT BUTTON:
    - Standard Windows/Maya drag-and-drop (file URLs)
    - Maya automatically imports files when dropped on viewport
    - Hold Alt while dragging to enable file drag
    
    MIDDLE BUTTON:
    - Batch import dialog (custom handling)
    - Drag to Collections panel to add files
    - Drag outside browser to show import options dialog
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.middle_button_pressed = False
        self.drag_start_position = None
        self.drag_started = False
        self.drag_to_collection = False  # Flag to distinguish drag-to-collection from batch import
        # Scroll speed reduction factor (lower = slower scrolling)
        self.scroll_speed_factor = 3.0  # 30% of normal speed
    
    def wheelEvent(self, event):
        """Handle mouse wheel with reduced scroll speed"""
        # Get the scroll delta
        delta = event.angleDelta().y()
        
        # Reduce the scroll amount
        reduced_delta = int(delta * self.scroll_speed_factor)
        
        # Get the scrollbar
        scrollbar = self.verticalScrollBar()
        
        # Apply the reduced scroll
        new_value = scrollbar.value() - reduced_delta // 8  # Divide by 8 for pixel conversion
        scrollbar.setValue(new_value)
        
        # Accept the event to prevent default handling
        event.accept()
    
    def mousePressEvent(self, event):
        """Handle mouse press - Middle button for batch import, Left button for selection/drag"""
        if event.button() == Qt.MiddleButton:
            # Middle button: Batch import or add to collection
            # Get item at click position
            index = self.indexAt(event.pos())
            
            # If clicked on valid item, ensure it's selected
            if index.isValid():
                # If not already selected, select it (single selection)
                if not self.selectionModel().isSelected(index):
                    self.setCurrentIndex(index)
            
            self.middle_button_pressed = True
            self.drag_start_position = event.pos()
            self.drag_started = False
            event.accept()
            return
        elif event.button() == Qt.LeftButton:
            # Left button: Box selection by default, file drag with Alt
            self.middle_button_pressed = False
            
            # Check if Alt is pressed for FILE DRAG
            # WITHOUT Alt = rubber band (disable drag)
            # WITH Alt = file drag (enable drag)
            if event.modifiers() & Qt.AltModifier:
                # Alt pressed: Enable file drag
                self._temp_drag_disabled = False
                self.setDragEnabled(True)
            else:
                # No Alt: Disable drag to allow rubber band selection
                self._temp_drag_disabled = True
                self.setDragEnabled(False)
            
            super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move - Start drag manually when over collections"""
        if self.middle_button_pressed and self.drag_start_position:
            if not self.drag_started:
                # Check if we've moved enough to start drag
                distance = (event.pos() - self.drag_start_position).manhattanLength()
                if distance >= 5:
                    self.drag_started = True
                    self.setCursor(Qt.ClosedHandCursor)
            
            if self.drag_started:
                # Continuously check position to see if we're over collections
                global_pos = self.mapToGlobal(event.pos())
                widget_at_cursor = QApplication.widgetAt(global_pos)
                
                # Check if cursor is over DragDropCollectionListWidget
                is_over_collections = False
                collections_widget = None
                check_widget = widget_at_cursor
                while check_widget:
                    if isinstance(check_widget, DragDropCollectionListWidget):
                        is_over_collections = True
                        collections_widget = check_widget
                        break
                    check_widget = check_widget.parent()
                
                # If over collections, check if cursor is over a valid collection item
                is_over_valid_collection = False
                if is_over_collections and collections_widget:
                    # Map global position to collections widget local coordinates
                    local_pos = collections_widget.mapFromGlobal(global_pos)
                    item = collections_widget.itemAt(local_pos)
                    if item and item.data(Qt.UserRole):  # Has collection name
                        is_over_valid_collection = True
                
                # Update cursor and start drag if over valid collection
                if is_over_valid_collection:
                    if not self.drag_to_collection:
                        self.drag_to_collection = True
                        # Start Qt drag operation (BLOCKING call)
                        self.startDrag(Qt.CopyAction)
                        
                        # After drag completes, check if we should do batch import
                        if not self.drag_to_collection:
                            # Check if mouse was released outside the browser window
                            global_pos = QCursor.pos()
                            widget_at_cursor = QApplication.widgetAt(global_pos)
                            
                            is_over_browser = False
                            check_widget = widget_at_cursor
                            while check_widget:
                                if hasattr(check_widget, 'windowTitle') and 'DD Content Browser' in str(check_widget.windowTitle()):
                                    is_over_browser = True
                                    break
                                if check_widget.__class__.__name__ == 'DDContentBrowser':
                                    is_over_browser = True
                                    break
                                check_widget = check_widget.parent() if check_widget else None
                            
                            # If not over browser, do batch import
                            if not is_over_browser:
                                indexes = self.selectedIndexes()
                                if indexes:
                                    print(f"[mouseMoveEvent] Batch importing {len(indexes)} files after drag...")
                                    count = len(indexes)
                                    browser = self.parent()
                                    while browser and not hasattr(browser, 'status_bar'):
                                        browser = browser.parent()
                                    if browser and hasattr(browser, 'status_bar'):
                                        try:
                                            browser.status_bar.showMessage(f"Batch importing {count} file{'s' if count != 1 else ''}...", 2000)
                                        except RuntimeError:
                                            pass
                                    self.batch_import_files(indexes)
                        
                        # Reset flags after drag completes
                        self.middle_button_pressed = False
                        self.drag_start_position = None
                        self.drag_started = False
                        self.drag_to_collection = False
                        self.setCursor(Qt.ArrowCursor)
                        self.unsetCursor()
                        return
                else:
                    if self.drag_to_collection:
                        # Left valid collection area
                        self.drag_to_collection = False
                        self.setCursor(Qt.ClosedHandCursor)
        
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        if event.button() == Qt.LeftButton:
            # Re-disable drag after Alt+drag completes (return to default rubber band mode)
            if not getattr(self, '_temp_drag_disabled', True):
                self.setDragEnabled(False)
                self._temp_drag_disabled = True
        
        if event.button() == Qt.MiddleButton:
            # Check if we're still over the ddContentBrowser window
            global_pos = self.mapToGlobal(event.pos())
            widget_at_cursor = QApplication.widgetAt(global_pos)
            
            # Find the top-level browser window
            is_over_browser = False
            check_widget = widget_at_cursor
            while check_widget:
                if hasattr(check_widget, 'windowTitle') and 'DD Content Browser' in str(check_widget.windowTitle()):
                    is_over_browser = True
                    break
                if check_widget.__class__.__name__ == 'DDContentBrowser':
                    is_over_browser = True
                    break
                check_widget = check_widget.parent()
            
            # Only do batch import if:
            # 1. Drag was started
            # 2. NOT dragging to collections
            # 3. Mouse is NOT over browser window (must be outside, e.g., Maya viewport)
            if self.drag_started and not self.drag_to_collection and not is_over_browser:
                indexes = self.selectedIndexes()
                if indexes:
                    print(f"[mouseReleaseEvent] Batch importing {len(indexes)} files...")
                    count = len(indexes)
                    browser = self.parent()
                    while browser and not hasattr(browser, 'status_bar'):
                        browser = browser.parent()
                    if browser and hasattr(browser, 'status_bar'):
                        try:
                            browser.status_bar.showMessage(f"Batch importing {count} file{'s' if count != 1 else ''}...", 2000)
                        except RuntimeError:
                            pass
                    self.batch_import_files(indexes)
            
            # Reset all flags
            self.middle_button_pressed = False
            self.drag_start_position = None
            self.drag_started = False
            self.drag_to_collection = False
            self.setCursor(Qt.ArrowCursor)
            self.unsetCursor()
            event.accept()
            return
        
        super().mouseReleaseEvent(event)
    
    def leaveEvent(self, event):
        """Reset cursor when leaving"""
        if self.drag_started or self.middle_button_pressed:
            self.setCursor(Qt.ArrowCursor)
            self.unsetCursor()
        super().leaveEvent(event)
    
    def keyPressEvent(self, event):
        """Handle ESC to cancel drag"""
        if event.key() == Qt.Key_Escape:
            if self.drag_started or self.middle_button_pressed:
                # Reset all drag state
                self.setCursor(Qt.ArrowCursor)
                self.unsetCursor()
                self.middle_button_pressed = False
                self.drag_start_position = None
                self.drag_started = False
                self.drag_to_collection = False
                
                browser = self.parent()
                while browser and not hasattr(browser, 'status_bar'):
                    browser = browser.parent()
                if browser and hasattr(browser, 'status_bar'):
                    try:
                        browser.status_bar.showMessage("Drag cancelled", 1500)
                    except RuntimeError:
                        pass  # Widget already deleted
                event.accept()
                return
        
        super().keyPressEvent(event)
    
    def startDrag(self, supportedActions):
        """Start drag operation - handle both ALT+left (file URLs) and middle button (collections only)"""
        try:
            from PySide6.QtCore import QMimeData, QUrl
            from PySide6.QtGui import QDrag
        except ImportError:
            from PySide2.QtCore import QMimeData, QUrl
            from PySide2.QtGui import QDrag
        
        # Remember if this is a middle button drag
        is_middle_button = self.middle_button_pressed
        
        # Create drag object
        drag = QDrag(self)
        mime_data = QMimeData()
        
        # Get selected files
        indexes = self.selectedIndexes()
        file_paths = []
        urls = []
        
        for index in indexes:
            if index.isValid():
                asset = self.model().data(index, Qt.UserRole)
                if asset and not asset.is_folder:
                    file_path = str(asset.file_path)
                    file_paths.append(file_path)
                    urls.append(QUrl.fromLocalFile(file_path))
        
        if not urls:
            # No files to drag - reset state if middle button
            if is_middle_button:
                self.middle_button_pressed = False
                self.drag_start_position = None
                self.drag_started = False
                self.setCursor(Qt.ArrowCursor)
                self.unsetCursor()
            return
        
        # Set mime data based on drag type
        if is_middle_button:
            # Middle button: Only text marker for collections drop handler
            # NO file URLs - prevents accidental drops to other apps
            mime_data.setText("drag_from_file_list")
        else:
            # ALT+Left button: Standard file URLs for Windows/Maya drag
            mime_data.setUrls(urls)
            mime_data.setText("alt_left_drag")
        
        drag.setMimeData(mime_data)
        
        # Execute drag (blocking call)
        drag.exec_(supportedActions)
    
    def batch_import_files(self, indexes):
        """Batch import files"""
        if not MAYA_AVAILABLE:
            return
        
        paths = []
        for index in indexes:
            if index.isValid():
                asset = self.model().data(index, Qt.UserRole)
                if asset and not asset.is_folder:
                    paths.append(str(asset.file_path))
        
        if not paths:
            return
        
        try:
            from ddContentBrowser.utils import get_extensions_by_category
            from pathlib import Path
            
            imported_count = 0
            failed_count = 0
            
            # Get image extensions from config
            image_exts = get_extensions_by_category('images')
            
            for file_path in paths:
                try:
                    file_ext = Path(file_path).suffix.lower()
                    is_image = file_ext in image_exts
                    
                    if is_image:
                        # Create texture node
                        file_node = cmds.shadingNode('file', asTexture=True, isColorManaged=True)
                        cmds.setAttr(f"{file_node}.fileTextureName", file_path, type="string")
                        
                        # Create place2dTexture
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
                        # Import 3D file
                        from ddContentBrowser.utils import get_maya_import_type
                        
                        # Get extension
                        file_ext = Path(file_path).suffix.lower()
                        
                        # Get Maya import type from config
                        file_type = get_maya_import_type(file_ext)
                        
                        if file_type:
                            # Import with type specification
                            cmds.file(file_path, i=True, type=file_type, ignoreVersion=True,
                                     mergeNamespacesOnClash=False, namespace=':',
                                     options='v=0', preserveReferences=True)
                            imported_count += 1
                        else:
                            # Unknown format or no import type - try auto-detect
                            try:
                                cmds.file(file_path, i=True, ignoreVersion=True,
                                         mergeNamespacesOnClash=False, namespace=':',
                                         preserveReferences=True)
                                imported_count += 1
                            except:
                                # Skip unsupported file types
                                failed_count += 1
                                continue
                    
                except Exception as e:
                    failed_count += 1
            
            # Update status bar
            browser = self.parent()
            while browser and not hasattr(browser, 'status_bar'):
                browser = browser.parent()
            if browser and hasattr(browser, 'status_bar'):
                try:
                    if imported_count > 0:
                        msg = f"Imported {imported_count} file{'s' if imported_count != 1 else ''}"
                        if failed_count > 0:
                            msg += f" ({failed_count} failed)"
                        browser.status_bar.showMessage(msg, 3000)
                    else:
                        browser.status_bar.showMessage("No files imported", 2000)
                except RuntimeError:
                    pass  # Widget already deleted
        
        except Exception as e:
            print(f"Batch import error: {e}")
            # Show error in status bar
            browser = self.parent()
            while browser and not hasattr(browser, 'status_bar'):
                browser = browser.parent()
            if browser and hasattr(browser, 'status_bar'):
                try:
                    browser.status_bar.showMessage(f"Batch import error: {e}", 3000)
                except RuntimeError:
                    pass  # Widget already deleted


class DragDropCollectionListWidget(QListWidget):
    """Custom QListWidget that accepts middle-button drag from file list"""
    
    # Signal emitted when files are dropped onto a collection
    files_dropped_on_collection = Signal(str, list)  # collection_name, file_paths
    
    # Signal emitted when drag leaves the collection area
    drag_left_collection = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.drop_indicator_item = None
    
    def dragEnterEvent(self, event):
        """Handle drag enter - check if it's coming from our file list"""
        # Accept drops from within our application
        if event.source() and isinstance(event.source(), MayaStyleListView):
            event.acceptProposedAction()
            return
        
        event.ignore()
    
    def dragMoveEvent(self, event):
        """Handle drag move - highlight collection under cursor"""
        if event.source() and isinstance(event.source(), MayaStyleListView):
            # Get item under cursor
            item = self.itemAt(event.pos())
            
            # Clear previous highlight
            if self.drop_indicator_item:
                font = self.drop_indicator_item.font()
                font.setBold(False)
                self.drop_indicator_item.setFont(font)
            
            # Highlight current item
            if item and item.data(Qt.UserRole):  # Has collection name
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                self.drop_indicator_item = item
                event.acceptProposedAction()
            else:
                self.drop_indicator_item = None
                event.ignore()
            
            return
        
        event.ignore()
    
    def dragLeaveEvent(self, event):
        """Handle drag leave - clear highlight and emit signal"""
        if self.drop_indicator_item:
            font = self.drop_indicator_item.font()
            font.setBold(False)
            self.drop_indicator_item.setFont(font)
            self.drop_indicator_item = None
        
        # Emit signal to notify that drag left the collection area
        self.drag_left_collection.emit()
    
    def dropEvent(self, event):
        """Handle drop - add files to collection"""
        # Clear highlight
        if self.drop_indicator_item:
            font = self.drop_indicator_item.font()
            font.setBold(False)
            self.drop_indicator_item.setFont(font)
            self.drop_indicator_item = None
        
        # Check if dropped on valid collection item
        item = self.itemAt(event.pos())
        if not item:
            event.ignore()
            return
        
        collection_name = item.data(Qt.UserRole)
        if not collection_name:
            event.ignore()
            return
        
        # Get file paths from source
        source = event.source()
        if not isinstance(source, MayaStyleListView):
            event.ignore()
            return
        
        # Get selected assets from file list
        indexes = source.selectedIndexes()
        file_paths = []
        
        for index in indexes:
            if index.isValid():
                asset = source.model().data(index, Qt.UserRole)
                if asset and not asset.is_folder:
                    file_paths.append(str(asset.file_path))
        
        if file_paths:
            # Emit signal with collection name and file paths
            self.files_dropped_on_collection.emit(collection_name, file_paths)
            event.acceptProposedAction()
        else:
            event.ignore()


def load_oiio_image_array(file_path, max_size=2048, mip_level=0):
    """
    Load image using OpenImageIO and return as numpy array (worker thread safe).
    Simpler version of load_oiio_image that returns raw array instead of QPixmap.
    
    Args:
        file_path: Path to image file
        max_size: Maximum width/height for thumbnail
        mip_level: Mipmap level to load (0 = full res, 1 = half res, etc.)
        
    Returns:
        numpy array (RGB, uint8) or None on failure
    """
    try:
        import sys
        import os
        external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
        if external_libs not in sys.path:
            sys.path.insert(0, external_libs)
        
        from OpenImageIO import ImageInput
        import numpy as np
        
        file_path_str = str(file_path)
        
        # Open image
        inp = ImageInput.open(file_path_str)
        if not inp:
            return None
        
        # Get image spec
        spec = inp.spec()
        width = spec.width
        height = spec.height
        
        # If mipmap requested and available
        if mip_level > 0 and spec.get_int_attribute('miplevels', 1) > mip_level:
            inp.seek_subimage(0, mip_level)
            spec = inp.spec()
            width = spec.width
            height = spec.height
        
        # Check valid dimensions
        if width <= 0 or height <= 0:
            return None
        
        # Read pixels
        pixels = inp.read_image()
        inp.close()
        
        if pixels is None:
            return None
        
        # Convert to numpy array
        img = np.array(pixels, dtype=np.float32)
        
        if img.size == 0:
            return None
        
        # Handle different channel counts
        if img.ndim == 2:
            # Grayscale -> RGB
            img = np.stack([img, img, img], axis=2)
        elif img.ndim == 3:
            actual_channels = img.shape[2]
            if actual_channels == 1:
                img = np.concatenate([img, img, img], axis=2)
            elif actual_channels == 2:
                img = np.concatenate([img[:,:,0:1], img[:,:,0:1], img[:,:,0:1]], axis=2)
            elif actual_channels == 4:
                # RGBA -> RGB
                img = img[:, :, :3]
            elif actual_channels > 4:
                # Take first 3 channels
                img = img[:, :, :3]
        
        # Resize if needed
        if width > max_size or height > max_size:
            scale = min(max_size / width, max_size / height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            
            if new_width < 1 or new_height < 1:
                return None
            
            import cv2
            img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
        
        # Return as float32 [0-inf] - caller will handle tone mapping
        # This allows HDR/ACEScg color management in the worker thread
        return img
        
    except Exception as e:
        return None


def load_oiio_image(file_path, max_size=2048, mip_level=0, exposure=0.0, metadata_manager=None):
    """
    Load image using OpenImageIO (supports .tx, .exr, .hdr, and many other formats)
    with ACES color management support
    
    Args:
        file_path: Path to image file
        max_size: Maximum width/height for preview
        mip_level: Mipmap level to load (0 = full res, 1 = half res, etc.)
        exposure: Exposure compensation in stops (0.0 = neutral)
        metadata_manager: Optional metadata manager for tag-based color management
        
    Returns:
        tuple: (QPixmap, resolution_string, metadata_dict) or (None, None, None) on failure
    """
    try:
        import sys
        import os
        external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
        if external_libs not in sys.path:
            sys.path.insert(0, external_libs)
        
        from OpenImageIO import ImageInput, ImageBuf, ImageSpec
        import numpy as np
        
        file_path_str = str(file_path)
        
        # Debug output for .tx files (disabled for production)
        # from pathlib import Path
        # if file_path_str.lower().endswith('.tx'):
        #     print(f"\n[OIIO] Loading .tx file: {Path(file_path_str).name}")
        
        # Open image
        inp = ImageInput.open(file_path_str)
        if not inp:
            return None, None, None
        
        # Get image spec (metadata)
        spec = inp.spec()
        width = spec.width
        height = spec.height
        channels = spec.nchannels
        
        # Get metadata
        metadata = {
            'width': width,
            'height': height,
            'channels': channels,
            'format': str(spec.format),  # TypeDesc needs str() conversion
            'compression': spec.get_string_attribute('compression', 'unknown'),
            'color_space': spec.get_string_attribute('oiio:ColorSpace', 'unknown'),
        }
        
        # Debug: Print metadata for .tx files (disabled for production)
        # if file_path_str.lower().endswith('.tx'):
        #     print(f"[OIIO]   Resolution: {width}x{height}, Channels: {channels}")
        #     print(f"[OIIO]   Format: {metadata['format']}, Compression: {metadata['compression']}")
        #     print(f"[OIIO]   Color Space: {metadata['color_space']}")
        
        # If mipmap requested and available
        if mip_level > 0 and spec.get_int_attribute('miplevels', 1) > mip_level:
            inp.seek_subimage(0, mip_level)
            spec = inp.spec()
            width = spec.width
            height = spec.height
        
        resolution_str = f"{width} x {height}"
        
        # Debug: Check for invalid dimensions
        if width <= 0 or height <= 0:
            return None, None, None
        
        # Read pixels
        pixels = inp.read_image()
        inp.close()
        
        if pixels is None:
            return None, None, None
        
        # Convert to numpy array
        img = np.array(pixels, dtype=np.float32)
        
        # Check if array is valid
        if img.size == 0:
            return None, None, None
        
        # Handle different channel counts (use actual img shape, not spec.channels!)
        # img can be 2D (grayscale) or 3D (multi-channel)
        if img.ndim == 2:
            # 2D grayscale -> RGB
            img = np.stack([img, img, img], axis=2)
        elif img.ndim == 3:
            actual_channels = img.shape[2]
            if actual_channels == 1:
                # 3D with 1 channel -> RGB
                img = np.concatenate([img, img, img], axis=2)
            elif actual_channels == 2:
                # 2 channels (grayscale + alpha) -> RGB
                img = np.concatenate([img[:,:,0:1], img[:,:,0:1], img[:,:,0:1]], axis=2)
            elif actual_channels == 4:
                # RGBA -> RGB (drop alpha)
                img = img[:, :, :3]
            elif actual_channels == 3:
                # RGB - keep as is
                pass
            else:
                # More than 4 channels - take first 3
                img = img[:, :, :3]
        
        # Scale if needed
        if width > max_size or height > max_size:
            scale = min(max_size / width, max_size / height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            
            # Safety check: ensure valid dimensions
            if new_width < 1 or new_height < 1:
                return None, None, None
            
            import cv2
            img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
            width, height = new_width, new_height
        
        # Detect ACES color space
        use_aces = False
        
        # Method 1: Check filename for ACEScg marker (RenderMan .tx convention)
        # Example: "texture_ACEScg.tx" or "env_scene-linear Rec.709-sRGB_ACEScg.hdr.tx"
        from pathlib import Path
        filename = Path(file_path_str).stem.lower()  # Get filename without extension
        
        # Debug: Show what we're checking (disabled for production)
        # if file_path_str.lower().endswith('.tx'):
        #     print(f"[OIIO] Checking filename stem: '{filename}'")
        
        if '_acescg' in filename or '-acescg' in filename or 'acescg' in filename:
            use_aces = True
            # print(f"[OIIO] ✓ Detected ACEScg from filename: {Path(file_path_str).name}")
        
        # Method 2: Check OIIO metadata color_space attribute
        if not use_aces and metadata.get('color_space', '').lower() in ['acescg', 'aces', 'aces_cg']:
            use_aces = True
            # print(f"[OIIO] Detected ACEScg from metadata: {metadata['color_space']}")
        
        # Method 3: Check tags (if metadata_manager provided)
        if not use_aces and metadata_manager:
            try:
                file_metadata = metadata_manager.get_file_metadata(str(file_path))
                file_tags = file_metadata.get('tags', [])
                tag_names_lower = [tag['name'].lower() for tag in file_tags]
                
                if "acescg" in tag_names_lower or "srgb(aces)" in tag_names_lower:
                    use_aces = True
                    # print(f"[OIIO] Detected ACEScg from tags: {[tag['name'] for tag in file_tags]}")
            except:
                pass
        
        # Debug: Print final color management decision (disabled for production)
        # if file_path_str.lower().endswith('.tx'):
        #     if use_aces:
        #         print(f"[OIIO] → Using ACES view transform")
        #     else:
        #         print(f"[OIIO] → Using standard filmic tone mapping")
        
        # Apply exposure compensation with -1 stop offset (match Nuke/Maya)
        compensated_exposure = exposure - 1.0
        
        # Apply color management and tone mapping
        if use_aces and img.max() > 1.0:
            # ACES view transform for HDR .tx files
            from .aces_color import apply_aces_view_transform
            img = apply_aces_view_transform(img, exposure=compensated_exposure)
        else:
            # Standard tone mapping
            if exposure != 0.0:
                exposure_multiplier = pow(2.0, compensated_exposure)
                img = img * exposure_multiplier
            
            # Tone mapping for HDR images (check if values > 1.0)
            if img.max() > 1.0:
                # ACES Filmic tone mapping
                a = 2.51
                b = 0.03
                c = 2.43
                d = 0.59
                e = 0.14
                img = np.clip((img * (a * img + b)) / (img * (c * img + d) + e), 0, 1)
            
            # Ensure values are in [0, 1]
            img = np.clip(img, 0, 1)
            
            # Gamma correction (2.2 for sRGB)
            gamma = 1.0 / 2.2
            img = np.power(img, gamma)
        
        # Convert to 8-bit
        img_8bit = (img * 255).astype(np.uint8)
        
        # Create QImage
        try:
            from PySide6.QtGui import QImage, QPixmap
        except ImportError:
            from PySide2.QtGui import QImage, QPixmap
        
        bytes_per_line = width * 3
        q_image = QImage(img_8bit.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
        q_image = q_image.copy()
        
        # Convert to QPixmap
        pixmap = QPixmap.fromImage(q_image)
        
        return pixmap, resolution_str, metadata
        
    except Exception as e:
        # Keep error logging for debugging critical failures
        print(f"[OIIO] Failed to load {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None




