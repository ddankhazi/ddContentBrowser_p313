# -*- coding: utf-8 -*-
"""
Batch Rename Module for DD Content Browser - Multi-Rule System

Provides a rule-based batch rename dialog where users can add multiple
rename operations that are applied sequentially.
"""

import os
import re
from pathlib import Path

try:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
        QTableWidget, QTableWidgetItem, QHeaderView, QSpinBox,
        QGroupBox, QTextEdit, QProgressBar, QMessageBox, QScrollArea, QWidget, QSplitter
    )
    from PySide6.QtGui import QFont
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt, QTimer
    from PySide2.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
        QTableWidget, QTableWidgetItem, QHeaderView, QSpinBox,
        QGroupBox, QTextEdit, QProgressBar, QMessageBox, QScrollArea, QWidget, QSplitter
    )
    from PySide2.QtGui import QFont
    PYSIDE_VERSION = 2


class RenameRule(QWidget):
    """A single rename rule with type selector and options"""
    
    # Signals
    rule_changed = QtCore.Signal()
    remove_requested = QtCore.Signal(object)  # Pass self when remove clicked
    add_after_requested = QtCore.Signal(object)  # Pass self when add after clicked
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rule_widgets = {}  # Store widgets for current rule type
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the rule UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)  # Minimal margins
        layout.setSpacing(0)
        
        # Rule container with border - compact styling
        rule_container = QGroupBox()
        rule_container.setStyleSheet("""
            QGroupBox {
                border: 1px solid #555;
                border-radius: 3px;
                margin-top: 2px;
                padding: 5px;
                font-size: 11px;
            }
            QLabel {
                font-size: 11px;
            }
            QLineEdit, QSpinBox, QComboBox {
                font-size: 11px;
                padding: 2px;
            }
            QCheckBox {
                font-size: 11px;
                spacing: 3px;
            }
        """)
        container_layout = QVBoxLayout(rule_container)
        container_layout.setSpacing(3)
        container_layout.setContentsMargins(5, 5, 5, 5)
        
        # Top row: Type selector and Remove button
        top_layout = QHBoxLayout()
        top_layout.setSpacing(5)
        
        type_label = QLabel("Type:")
        top_layout.addWidget(type_label)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "Find & Replace",
            "New Name",
            "Add Prefix",
            "Add Suffix",
            "Numbering",
            "Case Change",
            "Regex Pattern"
        ])
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        top_layout.addWidget(self.type_combo, 1)
        
        # Add rule button (insert after this rule)
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(24, 24)
        self.add_btn.setToolTip("Add rule after this one")
        self.add_btn.setStyleSheet("font-weight: bold;")
        self.add_btn.clicked.connect(lambda: self.add_after_requested.emit(self))
        top_layout.addWidget(self.add_btn)
        
        # Remove button
        self.remove_btn = QPushButton("−")
        self.remove_btn.setFixedSize(24, 24)
        self.remove_btn.setToolTip("Remove this rule")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        top_layout.addWidget(self.remove_btn)
        
        container_layout.addLayout(top_layout)
        
        # Options area (dynamic based on rule type)
        self.options_widget = QWidget()
        self.options_layout = QVBoxLayout(self.options_widget)
        self.options_layout.setContentsMargins(0, 3, 0, 0)
        self.options_layout.setSpacing(3)  # Compact spacing
        container_layout.addWidget(self.options_widget)
        
        layout.addWidget(rule_container)
        
        # Initialize with first rule type
        self.on_type_changed(self.type_combo.currentText())
    
    def on_type_changed(self, rule_type):
        """Handle rule type change"""
        # Clear existing options
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())
        
        self.rule_widgets.clear()
        
        # Setup options based on type
        if rule_type == "Find & Replace":
            self.setup_find_replace()
        elif rule_type == "New Name":
            self.setup_new_name()
        elif rule_type == "Add Prefix":
            self.setup_prefix()
        elif rule_type == "Add Suffix":
            self.setup_suffix()
        elif rule_type == "Numbering":
            self.setup_numbering()
        elif rule_type == "Case Change":
            self.setup_case_change()
        elif rule_type == "Regex Pattern":
            self.setup_regex()
        
        self.rule_changed.emit()
    
    def clear_layout(self, layout):
        """Recursively clear a layout"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())
    
    def setup_find_replace(self):
        """Setup Find & Replace options"""
        # Find
        find_layout = QHBoxLayout()
        find_layout.addWidget(QLabel("Find:"))
        self.rule_widgets['find'] = QLineEdit()
        self.rule_widgets['find'].textChanged.connect(lambda: self.rule_changed.emit())
        find_layout.addWidget(self.rule_widgets['find'])
        self.options_layout.addLayout(find_layout)
        
        # Replace
        replace_layout = QHBoxLayout()
        replace_layout.addWidget(QLabel("Replace:"))
        self.rule_widgets['replace'] = QLineEdit()
        self.rule_widgets['replace'].textChanged.connect(lambda: self.rule_changed.emit())
        replace_layout.addWidget(self.rule_widgets['replace'])
        self.options_layout.addLayout(replace_layout)
        
        # Options
        self.rule_widgets['case_sensitive'] = QCheckBox("Case sensitive")
        self.rule_widgets['case_sensitive'].stateChanged.connect(lambda: self.rule_changed.emit())
        self.options_layout.addWidget(self.rule_widgets['case_sensitive'])
        
        self.rule_widgets['whole_name'] = QCheckBox("Replace whole name only")
        self.rule_widgets['whole_name'].stateChanged.connect(lambda: self.rule_changed.emit())
        self.options_layout.addWidget(self.rule_widgets['whole_name'])
    
    def setup_new_name(self):
        """Setup New Name options"""
        new_name_layout = QHBoxLayout()
        new_name_layout.addWidget(QLabel("New Name:"))
        self.rule_widgets['new_name'] = QLineEdit()
        self.rule_widgets['new_name'].setPlaceholderText("e.g., File_{num} or {original}_new")
        self.rule_widgets['new_name'].textChanged.connect(lambda: self.rule_changed.emit())
        new_name_layout.addWidget(self.rule_widgets['new_name'])
        self.options_layout.addLayout(new_name_layout)
        
        # Help text
        help_text = QLabel("Use {num} for numbering, {original} for original name")
        help_text.setStyleSheet("color: #888; font-size: 9px; padding: 2px 0;")
        help_text.setWordWrap(True)
        self.options_layout.addWidget(help_text)
    
    def setup_prefix(self):
        """Setup Add Prefix options"""
        prefix_layout = QHBoxLayout()
        prefix_layout.addWidget(QLabel("Prefix:"))
        self.rule_widgets['prefix'] = QLineEdit()
        self.rule_widgets['prefix'].textChanged.connect(lambda: self.rule_changed.emit())
        prefix_layout.addWidget(self.rule_widgets['prefix'])
        self.options_layout.addLayout(prefix_layout)
    
    def setup_suffix(self):
        """Setup Add Suffix options"""
        suffix_layout = QHBoxLayout()
        suffix_layout.addWidget(QLabel("Suffix:"))
        self.rule_widgets['suffix'] = QLineEdit()
        self.rule_widgets['suffix'].textChanged.connect(lambda: self.rule_changed.emit())
        suffix_layout.addWidget(self.rule_widgets['suffix'])
        self.options_layout.addLayout(suffix_layout)
    
    def setup_numbering(self):
        """Setup Numbering options"""
        # Start number
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("Start:"))
        self.rule_widgets['start'] = QSpinBox()
        self.rule_widgets['start'].setRange(0, 99999)
        self.rule_widgets['start'].setValue(1)
        self.rule_widgets['start'].valueChanged.connect(lambda: self.rule_changed.emit())
        start_layout.addWidget(self.rule_widgets['start'])
        self.options_layout.addLayout(start_layout)
        
        # Padding
        padding_layout = QHBoxLayout()
        padding_layout.addWidget(QLabel("Padding:"))
        self.rule_widgets['padding'] = QSpinBox()
        self.rule_widgets['padding'].setRange(1, 10)
        self.rule_widgets['padding'].setValue(3)
        self.rule_widgets['padding'].valueChanged.connect(lambda: self.rule_changed.emit())
        padding_layout.addWidget(self.rule_widgets['padding'])
        self.options_layout.addLayout(padding_layout)
        
        # Position
        position_layout = QHBoxLayout()
        position_layout.addWidget(QLabel("Position:"))
        self.rule_widgets['position'] = QComboBox()
        self.rule_widgets['position'].addItems(["End", "Start"])
        self.rule_widgets['position'].currentTextChanged.connect(lambda: self.rule_changed.emit())
        position_layout.addWidget(self.rule_widgets['position'])
        self.options_layout.addLayout(position_layout)
    
    def setup_case_change(self):
        """Setup Case Change options"""
        case_layout = QHBoxLayout()
        case_layout.addWidget(QLabel("Change to:"))
        self.rule_widgets['case_type'] = QComboBox()
        self.rule_widgets['case_type'].addItems([
            "UPPERCASE",
            "lowercase",
            "Title Case",
            "Sentence case"
        ])
        self.rule_widgets['case_type'].currentTextChanged.connect(lambda: self.rule_changed.emit())
        case_layout.addWidget(self.rule_widgets['case_type'])
        self.options_layout.addLayout(case_layout)
    
    def setup_regex(self):
        """Setup Regex Pattern options"""
        # Pattern
        pattern_layout = QHBoxLayout()
        pattern_layout.addWidget(QLabel("Pattern:"))
        self.rule_widgets['pattern'] = QLineEdit()
        self.rule_widgets['pattern'].textChanged.connect(lambda: self.rule_changed.emit())
        pattern_layout.addWidget(self.rule_widgets['pattern'])
        self.options_layout.addLayout(pattern_layout)
        
        # Replacement
        replacement_layout = QHBoxLayout()
        replacement_layout.addWidget(QLabel("Replace with:"))
        self.rule_widgets['replacement'] = QLineEdit()
        self.rule_widgets['replacement'].textChanged.connect(lambda: self.rule_changed.emit())
        replacement_layout.addWidget(self.rule_widgets['replacement'])
        self.options_layout.addLayout(replacement_layout)
        
        # Help
        help_text = QLabel("Regex example: (\\d+) → File_\\1 (captures numbers)")
        help_text.setStyleSheet("color: #888; font-size: 9px; padding: 2px 0;")
        help_text.setWordWrap(True)
        self.options_layout.addWidget(help_text)
    
    def get_rule_type(self):
        """Get the current rule type"""
        return self.type_combo.currentText()
    
    def apply_rule(self, name):
        """Apply this rule to a single filename and return the result"""
        rule_type = self.get_rule_type()
        
        try:
            if rule_type == "Find & Replace":
                return self.apply_find_replace(name)
            elif rule_type == "New Name":
                return self.apply_new_name(name)
            elif rule_type == "Add Prefix":
                return self.apply_prefix(name)
            elif rule_type == "Add Suffix":
                return self.apply_suffix(name)
            elif rule_type == "Numbering":
                return name  # Numbering requires index, handled separately
            elif rule_type == "Case Change":
                return self.apply_case_change(name)
            elif rule_type == "Regex Pattern":
                return self.apply_regex(name)
        except Exception as e:
            return f"ERROR: {str(e)}"
        
        return name
    
    def apply_find_replace(self, name):
        """Apply find & replace"""
        find_text = self.rule_widgets['find'].text()
        replace_text = self.rule_widgets['replace'].text()
        
        if not find_text:
            return name
        
        name_without_ext = Path(name).stem
        ext = Path(name).suffix
        
        if self.rule_widgets['whole_name'].isChecked():
            if self.rule_widgets['case_sensitive'].isChecked():
                if name_without_ext == find_text:
                    new_name = replace_text
                else:
                    new_name = name_without_ext
            else:
                if name_without_ext.lower() == find_text.lower():
                    new_name = replace_text
                else:
                    new_name = name_without_ext
        else:
            if self.rule_widgets['case_sensitive'].isChecked():
                new_name = name_without_ext.replace(find_text, replace_text)
            else:
                pattern = re.compile(re.escape(find_text), re.IGNORECASE)
                new_name = pattern.sub(replace_text, name_without_ext)
        
        return new_name + ext
    
    def apply_new_name(self, name):
        """Apply new name with placeholders"""
        template = self.rule_widgets['new_name'].text()
        if not template:
            return name
        
        name_without_ext = Path(name).stem
        ext = Path(name).suffix
        
        new_name = template.replace('{original}', name_without_ext)
        # {num} will be handled in batch processing
        
        return new_name + ext
    
    def apply_prefix(self, name):
        """Add prefix"""
        prefix = self.rule_widgets['prefix'].text()
        if not prefix:
            return name
        
        name_without_ext = Path(name).stem
        ext = Path(name).suffix
        
        return prefix + name_without_ext + ext
    
    def apply_suffix(self, name):
        """Add suffix"""
        suffix = self.rule_widgets['suffix'].text()
        if not suffix:
            return name
        
        name_without_ext = Path(name).stem
        ext = Path(name).suffix
        
        return name_without_ext + suffix + ext
    
    def apply_case_change(self, name):
        """Change case"""
        case_type = self.rule_widgets['case_type'].currentText()
        
        name_without_ext = Path(name).stem
        ext = Path(name).suffix
        
        if case_type == "UPPERCASE":
            new_name = name_without_ext.upper()
        elif case_type == "lowercase":
            new_name = name_without_ext.lower()
        elif case_type == "Title Case":
            new_name = name_without_ext.title()
        elif case_type == "Sentence case":
            new_name = name_without_ext[0].upper() + name_without_ext[1:].lower() if name_without_ext else ""
        else:
            new_name = name_without_ext
        
        return new_name + ext
    
    def apply_regex(self, name):
        """Apply regex pattern"""
        pattern = self.rule_widgets['pattern'].text()
        replacement = self.rule_widgets['replacement'].text()
        
        if not pattern:
            return name
        
        name_without_ext = Path(name).stem
        ext = Path(name).suffix
        
        try:
            compiled_pattern = re.compile(pattern)
            new_name = compiled_pattern.sub(replacement, name_without_ext)
        except re.error as e:
            raise Exception(f"Invalid regex: {e}")
        
        return new_name + ext


class BatchRenameDialog(QDialog):
    """Multi-rule batch rename dialog"""
    
    def __init__(self, file_paths, parent=None):
        super().__init__(parent)
        self.file_paths = [Path(p) for p in file_paths]
        self.original_names = [p.name for p in self.file_paths]
        self.preview_names = self.original_names.copy()
        self.rules = []  # List of RenameRule widgets
        
        self.setWindowTitle("Batch Rename Files")
        self.setMinimumSize(900, 700)
        
        # Enable maximize button and window resize
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        
        self.setup_ui()
        
        # Add first rule by default
        self.add_rule()
    
    def setup_ui(self):
        """Setup the main UI"""
        # Use splitter to allow resizing
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(5, 5, 5, 5)  # Add margin around the whole dialog
        
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Rules
        left_group = QGroupBox("Rename Rules")
        left_layout = QVBoxLayout(left_group)
        left_layout.setSpacing(5)
        left_layout.setContentsMargins(8, 8, 8, 8)  # Reduced top margin
        
        # Rules scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.rules_container = QWidget()
        self.rules_layout = QVBoxLayout(self.rules_container)
        self.rules_layout.setAlignment(Qt.AlignTop)
        self.rules_layout.setSpacing(4)  # Compact spacing between rules
        self.rules_layout.setContentsMargins(2, 2, 2, 2)
        
        scroll.setWidget(self.rules_container)
        left_layout.addWidget(scroll)
        
        splitter.addWidget(left_group)
        
        # Right side: Preview
        right_group = QGroupBox("Preview")
        right_layout = QVBoxLayout(right_group)
        right_layout.setContentsMargins(8, 8, 8, 8)  # Reduced top margin
        
        # Preview table
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(2)
        self.preview_table.setHorizontalHeaderLabels(["Original", "New Name"])
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.preview_table.setEditTriggers(QTableWidget.AllEditTriggers)  # Allow text selection
        self.preview_table.setSelectionMode(QTableWidget.ContiguousSelection)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectItems)
        
        # Compact styling: smaller font, less padding, tighter rows
        self.preview_table.setStyleSheet("""
            QTableWidget {
                font-size: 10px;
                gridline-color: #555;
            }
            QTableWidget::item {
                padding: 2px 5px;
            }
        """)
        self.preview_table.verticalHeader().setDefaultSectionSize(20)  # Smaller row height
        self.preview_table.setTextElideMode(Qt.ElideNone)
        self.preview_table.setWordWrap(False)
        
        right_layout.addWidget(self.preview_table)
        
        # Status label
        self.status_label = QLabel("0 files will be renamed")
        self.status_label.setStyleSheet("font-weight: bold; padding: 5px;")
        right_layout.addWidget(self.status_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        self.apply_btn = QPushButton("Apply Rename")
        self.apply_btn.clicked.connect(self.apply_rename)
        self.apply_btn.setStyleSheet("font-weight: bold;")
        button_layout.addWidget(self.apply_btn)
        
        right_layout.addLayout(button_layout)
        
        splitter.addWidget(right_group)
        
        # Set initial splitter sizes (40% left, 60% right)
        splitter.setSizes([400, 600])
        
        main_layout.addWidget(splitter)
        
        # Initialize preview
        self.update_preview()
    
    def add_rule(self, after_rule=None):
        """Add a new rule, optionally after a specific rule"""
        rule = RenameRule()
        rule.rule_changed.connect(self.update_preview)
        rule.remove_requested.connect(self.remove_rule)
        rule.add_after_requested.connect(self.add_rule_after)
        
        if after_rule and after_rule in self.rules:
            # Insert after specific rule
            index = self.rules.index(after_rule)
            self.rules.insert(index + 1, rule)
            self.rules_layout.insertWidget(index + 1, rule)
        else:
            # Add at end
            self.rules.append(rule)
            self.rules_layout.addWidget(rule)
        
        self.update_preview()
    
    def add_rule_after(self, after_rule):
        """Add a new rule after a specific rule"""
        self.add_rule(after_rule=after_rule)
    
    def remove_rule(self, rule):
        """Remove a rule"""
        if len(self.rules) <= 1:
            QMessageBox.warning(self, "Cannot Remove", "At least one rule must remain.")
            return
        
        self.rules.remove(rule)
        rule.deleteLater()
        
        self.update_preview()
    
    def update_preview(self):
        """Update the preview table"""
        # Apply all rules sequentially
        current_names = self.original_names.copy()
        
        for rule in self.rules:
            new_names = []
            for i, name in enumerate(current_names):
                if rule.get_rule_type() == "Numbering":
                    # Handle numbering specially
                    new_name = self.apply_numbering_rule(name, i, rule)
                elif rule.get_rule_type() == "New Name":
                    # Handle New Name with {num} placeholder
                    new_name = rule.apply_rule(name)
                    if '{num}' in new_name:
                        # Replace {num} with padded number
                        number = str(i + 1).zfill(3)  # Default 3-digit padding
                        new_name = new_name.replace('{num}', number)
                else:
                    new_name = rule.apply_rule(name)
                new_names.append(new_name)
            current_names = new_names
        
        self.preview_names = current_names
        
        # Update table
        self.preview_table.setRowCount(len(self.original_names))
        
        changes_count = 0
        for i, (original, new) in enumerate(zip(self.original_names, self.preview_names)):
            # Original
            original_item = QTableWidgetItem(original)
            original_item.setFlags(original_item.flags() | Qt.ItemIsSelectable)
            original_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.preview_table.setItem(i, 0, original_item)
            
            # New name
            new_item = QTableWidgetItem(new)
            new_item.setFlags(new_item.flags() | Qt.ItemIsSelectable)
            new_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
            if new != original and not new.startswith("ERROR:"):
                new_item.setBackground(QtGui.QColor(100, 200, 100, 50))
                changes_count += 1
            elif new.startswith("ERROR:"):
                new_item.setBackground(QtGui.QColor(200, 100, 100, 50))
            
            self.preview_table.setItem(i, 1, new_item)
        
        # Update status
        self.status_label.setText(f"{changes_count} file(s) will be renamed")
        self.apply_btn.setEnabled(changes_count > 0)
    
    def apply_numbering_rule(self, name, index, rule):
        """Apply numbering rule with index"""
        start = rule.rule_widgets['start'].value()
        padding = rule.rule_widgets['padding'].value()
        position = rule.rule_widgets['position'].currentText()
        
        name_without_ext = Path(name).stem
        ext = Path(name).suffix
        
        number = str(start + index).zfill(padding)
        
        if position == "Start":
            new_name = number + "_" + name_without_ext
        else:  # End
            new_name = name_without_ext + "_" + number
        
        return new_name + ext
    
    def apply_rename(self):
        """Apply the actual file renaming"""
        # Count actual changes
        changes = [(fp, new, orig) for fp, new, orig in 
                   zip(self.file_paths, self.preview_names, self.original_names)
                   if new != orig and not new.startswith("ERROR:")]
        
        if not changes:
            QMessageBox.information(self, "No Changes", "No files to rename.")
            return
        
        # Confirm
        reply = QMessageBox.question(
            self,
            "Confirm Rename",
            f"Are you sure you want to rename {len(changes)} file(s)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Apply renames
        errors = []
        success_count = 0
        
        for file_path, new_name, original_name in changes:
            try:
                new_path = file_path.parent / new_name
                file_path.rename(new_path)
                success_count += 1
            except Exception as e:
                errors.append(f"{original_name}: {str(e)}")
        
        # Show results
        if errors:
            error_msg = f"Renamed {success_count} file(s).\n\nErrors:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                error_msg += f"\n... and {len(errors) - 10} more errors"
            QMessageBox.warning(self, "Rename Complete with Errors", error_msg)
        else:
            QMessageBox.information(self, "Success", f"Successfully renamed {success_count} file(s)!")
        
        self.accept()
