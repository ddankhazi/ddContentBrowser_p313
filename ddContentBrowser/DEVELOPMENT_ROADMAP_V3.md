# DD Content Browser - Development Roadmap v3.0

**Last Updated:** October 15, 2025

---

## 👥 Development Team

**Pair Programming Model:**
- **Production/Maya Expert (You)** - Domain knowledge, requirements, production testing, workflow design
- **AI Assistant - GitHub Copilot (Me)** - Code implementation, architecture, debugging, documentation

**Working Style:** 🤝
- Collaborative design sessions
- Iterative development
- Real-time testing in production environment
- Continuous documentation
- Code reviews and improvements

---

## 🎯 Vision for v3.0

Transform DD Content Browser from a **visual asset browser** into a **complete asset management system** with:
- Smart material generation
- Metadata organization (tags, ratings, colors)
- Virtual collections
- Batch operations

**Target:** Production-ready by Q1 2026

---

## 📅 Development Timeline

### **Phase 1: Smart Import Functions** 🧠
**Duration:** Week 1-2  
**Status:** 🔜 Next Up!

#### Tasks:
- [ ] **Shader Graph Integration**
  - Wire existing shader graph builder to browser
  - Add menu item: Right-click → "Auto-Generate Material"
  - Test integration with real production assets

- [ ] **Texture Pattern Detection**
  - Implement pattern matching for texture types
  - Support patterns: `*_diffuse`, `*_albedo`, `*_normal`, `*_rough*`, `*_metal*`
  - Add Settings panel for custom patterns
  - Group textures by base name

- [ ] **SkyDome Auto-Linker**
  - Drag HDR/EXR → detect aiSkyDomeLight
  - Update file path preserving exposure
  - Support batch SkyDome updates
  - Test with .hdr and .exr files

- [ ] **Smart Material Assignment**
  - Auto-assign generated material to selected objects
  - Support UDIM textures
  - Handle multiple material sets

- [ ] **Documentation**
  - User guide for Smart Import
  - Video tutorial
  - Pattern configuration guide

**Deliverable:** Smart Import working in production

---

### **Phase 2: Star/Color Rating System** ⭐
**Duration:** Week 3 (3-5 days)  
**Status:** 🔜 Coming Soon

#### Tasks:
- [ ] **Rating System**
  - 5-star rating (0-5 stars)
  - Keyboard shortcuts: `1-5` for rating
  - Visual star overlay on thumbnails
  - Sort by rating functionality

- [ ] **Color Label System**
  - 8 colors: Red, Orange, Yellow, Green, Blue, Purple, Gray, None
  - Keyboard shortcuts: `Ctrl+1-7` for colors
  - Colored border on thumbnails
  - Filter by color in filter panel

- [ ] **Data Storage**
  - JSON storage: `~/.ddContentBrowser/ratings.json`
  - File path as key
  - Schema:
    ```json
    {
      "C:/project/asset.ma": {
        "rating": 5,
        "color": "Red",
        "date_rated": "2025-10-15"
      }
    }
    ```

- [ ] **UI Integration**
  - Thumbnail overlay (stars + color border)
  - Filter panel: Rating slider + color checkboxes
  - Sort menu: "By Rating"
  - Bulk operations: Rate multiple files

- [ ] **Documentation**
  - Rating system guide
  - Keyboard shortcuts reference

**Deliverable:** Adobe Bridge-style rating system

---

### **Phase 3: Tag System** 🏷️
**Duration:** Week 4-5 (1-2 weeks)  
**Status:** � IN PROGRESS - Started October 17, 2025

#### Tasks:
- [ ] **Tag Editor Dialog**
  - Tag input with autocomplete
  - Tag list display
  - Add/remove tags
  - Tag color coding

- [ ] **Tag Hierarchy**
  - Category → Subcategory structure
  - Visual tree display
  - Collapsible categories

- [ ] **Data Storage**
  - SQLite or JSON backend (decide during implementation)
  - Schema:
    ```json
    {
      "C:/project/asset.ma": {
        "tags": ["Character", "Main", "Rigged"],
        "hierarchy": {
          "Project": ["Production"],
          "Type": ["Character"],
          "Status": ["Approved"]
        },
        "notes": "Final version",
        "artist": "Artist Name"
      }
    }
    ```

- [ ] **Integration**
  - Filter panel: Tag search/filter
  - Thumbnail display: Tag badges
  - Context menu: "Edit Tags"
  - Bulk tag operations

- [ ] **Import/Export**
  - Export tag database
  - Import tags from other projects
  - Share between team members

- [ ] **Decision Point:** 
  - **Option A:** Merge with Star/Color into unified metadata system
  - **Option B:** Keep separate (ratings.json + tags.json)
  - Decide based on Phase 2 experience

**Deliverable:** Advanced tag management system

---

### **Phase 4: Quixel Megascans Importer** 🎨
**Duration:** Week 6 (1 week)  
**Status:** 🔮 Future (After Tag System)

#### Background & Expertise:
**Based on years of production experience!** 💪
- Multiple custom Quixel Bridge export/import scripts written
- Octane Render engine integration (custom exporter/importer)
- First correct Blender 3 exporter/importer (fixed material ID order)
- Houdini version implementation
- Regular updates for Redshift/V-Ray/Arnold
- **Maya 2025/PySide6 Quixel Bridge fix** (March 2024)
- Years of daily Megascans usage in production
- Digic Pictures VFX experience
- Portfolio & Blog: [ddankhazi.com](https://ddankhazi.com)

**This isn't a new experiment - it's integrating proven, battle-tested workflows into the browser!**

#### Why This Feature:
Quixel Megascans has specific texture naming conventions and requirements that need special handling:
- Standardized texture naming (Albedo, Normal, Roughness, Displacement, etc.)
- UDIM texture support
- High-res texture sets (8K+)
- LOD variants
- Metadata from Bridge (resolution, tags, category)

#### Tasks:
- [ ] **Megascans Pattern Detection**
  - Recognize Megascans naming convention
  - Patterns: `*_Albedo`, `*_Normal_LOD0`, `*_Roughness`, `*_Displacement`
  - Support UDIM format: `texture_1001.jpg`, `texture_1002.jpg`
  - Detect LOD variants (LOD0, LOD1, LOD2)
  - Handle resolution indicators (2K, 4K, 8K)
  - **Leverage existing pattern knowledge from previous implementations**

- [ ] **Smart Material Generation**
  - Auto-detect Megascans texture set
  - Generate optimized shader network:
    - **Arnold:** aiStandardSurface with proven settings
    - **V-Ray:** VRayMtl optimization (from previous experience)
    - **Redshift:** RedshiftMaterial setup (from updates)
    - Normal map with bump2d setup (correct material ID order!)
    - Displacement with proper bounds
    - Proper UDIM tiling
  - LOD switching setup (optional)
  - Resolution-based texture selection
  - **Port proven workflows from Octane/Blender/Houdini versions**

- [ ] **Advanced Material ID Handling**
  - **Critical:** Correct material ID order (learned from Blender 3 fix!)
  - Handle multi-material Megascans assets
  - Preserve material assignment
  - Support for complex material setups

- [ ] **Metadata Import**
  - Parse Megascans metadata (if available)
  - Import asset name, category, tags
  - Store original resolution info
  - Import artist notes/description

- [ ] **UI Integration**
  - Right-click menu: "Import as Megascans Asset"
  - Detect Megascans folder structure
  - Auto-group textures by asset
  - Preview shader before import
  - Options dialog:
    - Select LOD level
    - Choose resolution (2K/4K/8K)
    - Enable/disable displacement
    - UDIM handling options

- [ ] **Advanced Features**
  - Batch import multiple Megascans assets
  - Auto-organize in Maya outliner
  - Generate proxy geometry (optional)
  - Material presets (Standard/High Quality/Performance)
  - Export material preset for reuse

- [ ] **Settings Integration**
  - Add "Megascans" tab in Settings
  - Custom naming patterns
  - Default shader settings per render engine
  - Auto-apply on import
  - Library path configuration
  - **Import proven settings from previous implementations**
  - Render engine presets (Arnold/V-Ray/Redshift)

- [ ] **Code Reuse & Integration**
  - Review existing Quixel Bridge scripts
  - Port proven logic from Octane version
  - Adapt Blender 3 material ID fix
  - Integrate Houdini workflow patterns
  - Merge Arnold/V-Ray/Redshift updates
  - Refactor for browser integration

**Technical Notes:**

```python
# Based on years of production experience:

# Material ID fix (from Blender 3 work):
def fix_material_id_order(mesh_node, material_slots):
    """
    Ensure material IDs are assigned in correct order
    Critical for multi-material Megascans assets!
    """
    # Proven fix from Blender 3 implementation
    pass

# Render engine abstraction (from multi-engine experience):
class MegascansImporter:
    def __init__(self, render_engine='arnold'):
        self.engine = render_engine
        # Load engine-specific presets
        self.presets = self.load_engine_presets(render_engine)
    
    def create_material(self, textures):
        if self.engine == 'arnold':
            return self.create_arnold_material(textures)
        elif self.engine == 'vray':
            return self.create_vray_material(textures)
        elif self.engine == 'redshift':
            return self.create_redshift_material(textures)
        # Octane, etc.
    
    def create_arnold_material(self, textures):
        """Proven Arnold setup from years of updates"""
        pass
    
    def create_vray_material(self, textures):
        """V-Ray optimization from experience"""
        pass
    
    def create_redshift_material(self, textures):
        """Redshift setup from regular updates"""
        pass

```python
# Megascans naming examples:
# - vcslfdpga_2K_Albedo.jpg
# - vcslfdpga_2K_Normal.jpg  
# - vcslfdpga_2K_Roughness.jpg
# - vcslfdpga_2K_Displacement.exr
# - vcslfdpga_4K_Albedo_1001.jpg (UDIM)

MEGASCANS_PATTERNS = {
    'albedo': [r'.*_Albedo.*', r'.*_BaseColor.*'],
    'normal': [r'.*_Normal.*'],
    'roughness': [r'.*_Roughness.*'],
    'metallic': [r'.*_Metallic.*'],
    'displacement': [r'.*_Displacement.*', r'.*_Height.*'],
    'ao': [r'.*_AO.*', r'.*_AmbientOcclusion.*'],
    'opacity': [r'.*_Opacity.*', r'.*_Alpha.*']
}

def detect_megascans_asset(files):
    """Detect if files are from Megascans"""
    # Check for Megascans naming pattern
    # Group by asset name
    # Detect resolution and LOD
    # Return structured info
    pass

def create_megascans_material(textures, options):
    """Create optimized Megascans material"""
    # Create aiStandardSurface
    # Setup all maps with correct settings
    # Handle displacement
    # Setup UDIMs if present
    # Apply presets based on options
    pass
```

**Deliverable:** One-click Megascans asset import with optimized shaders

---

### **Phase 5: Collection System** 📁
**Duration:** Week 7-8 (1-2 weeks)  
**Status:** ✅ **COMPLETE!** - October 18, 2025

#### Tasks:
- [ ] **UI Design**
  - Collection sidebar panel
  - Tree view for collection hierarchy
  - Drag & drop support

- [ ] **Smart Collections**
  - Rule-based collections
  - Auto-update based on rules
  - Example rules:
    - "All FBX files tagged 'Character' with rating ≥ 4"
    - "HDR files modified in last 7 days"
  - Rule editor dialog

- [ ] **Manual Collections**
  - Drag & drop files to collection
  - Add/remove files manually
  - Support nesting

- [ ] **Data Storage**
  - JSON storage: `~/.ddContentBrowser/collections.json`
  - Schema:
    ```json
    {
      "Hero_Assets": {
        "type": "smart",
        "rules": {
          "file_types": [".ma", ".mb"],
          "tags": ["Character", "Main"],
          "min_rating": 4,
          "colors": ["Red", "Orange"]
        },
        "auto_update": true
      },
      "Current_Project": {
        "type": "manual",
        "files": ["C:/path/file1.ma", "C:/path/file2.ma"]
      }
    }
    ```

- [ ] **Features**
  - Collection filtering
  - Export/import collections
  - Share collections between artists
  - Batch operations on collection items

**Deliverable:** Virtual folder system with smart collections ✅

---

### **Phase 5.5: Quick View System** ⚡🔍
**Duration:** Week 8-9 (3-5 days)  
**Status:** 🔜 **NEXT!** - macOS-style Quick Look

#### Concept:
macOS-style Quick Look for Maya - press **Space** to instantly preview files in a floating, non-modal window. Browse underneath while keeping the preview visible!

#### Core Features:
- **⌨️ Keyboard Activation:**
  - **Space** - Toggle Quick View on/off
  - **ESC** - Close Quick View
  - **Arrow Left/Right** - Navigate through files (when focused)
  - **Arrow Up/Down** - Navigate through files (when focused)

- **🪟 Floating Window:**
  - Non-modal window (browse underneath stays active)
  - Always on top (Qt.WindowStaysOnTopHint)
  - Draggable anywhere (even to second monitor)
  - Auto-resize based on content
  - Frameless or minimal titlebar

- **👁️ Preview Types:**
  - Images: Full preview with zoom/pan
  - HDR/EXR: Exposure control slider
  - PDF: Page navigation
  - Text files: Syntax highlighting
  - 3D files: Gradient icon (mesh preview later?)
  - Maya files: Metadata display (poly count later?)

- **📊 Multi-File Support:**
  - **1 file** → Large preview (800x600px default)
  - **2-4 files** → 2x2 grid layout
  - **5+ files** → Scrollable grid (2-3 columns)
  - Visual indicator for multiple files

- **📌 Pin Feature (Advanced):**
  - Pin button (📌) in titlebar
  - Pinned: Preview doesn't update when selecting new files
  - Useful for:
    - Keeping reference image visible
    - Comparing current file with pinned reference
    - Lock HDR/texture while browsing others
  - Multiple pin modes:
    - Pin entire preview (all files locked)
    - Pin individual items in grid (partial lock)
  - Visual indicator: Pinned items have pin icon overlay

#### Tasks:
- [ ] **QuickViewWindow Class**
  - QDialog with Qt.Tool | Qt.WindowStaysOnTopHint
  - Non-modal (Qt.NonModal)
  - Draggable custom titlebar
  - Auto-resize based on content/file count
  - Remember position/size in config.json

- [ ] **Preview Rendering**
  - Reuse PreviewPanel rendering code
  - Image preview with zoom/pan
  - HDR/EXR with exposure slider
  - PDF with page navigation
  - Text with syntax highlighting
  - Multi-file grid layout

- [ ] **Keyboard Shortcuts**
  - Global Space key handler in browser
  - ESC to close
  - Arrow keys for navigation (when window focused)
  - Number keys (1-9) for quick file selection in grid

- [ ] **Navigation Integration**
  - Connect to browser's file selection
  - Auto-update preview when selection changes (unless pinned)
  - Selection changes underneath while Quick View is open
  - Previous/Next file cycling

- [ ] **Multi-File Grid Layout**
  - Detect file count and choose layout:
    - 1 file: Full screen (800x600)
    - 2 files: 1x2 horizontal
    - 3-4 files: 2x2 grid
    - 5+ files: 2-3 column scrollable grid
  - Thumbnail size adapts to grid
  - Hover highlights in grid
  - Click to focus single file (zoom mode)

- [ ] **Pin Feature (Advanced)**
  - Pin button (📌) in titlebar
  - Toggle pin state
  - When pinned:
    - Store current asset(s)
    - Ignore selection changes
    - Visual indicator (pin icon overlay)
  - Modes:
    - **Full Pin** - Lock entire preview
    - **Partial Pin** (grid mode) - Pin specific items
  - Right-click individual grid items to pin/unpin
  - Status: "Pinned: filename.ma" in titlebar

- [ ] **Quick Actions (Future)**
  - Import button (when available)
  - Reference button (Maya files)
  - Open button (all files)
  - Copy path button
  - Minimize buttons in corner

- [ ] **Window State Persistence**
  - Save position/size to config.json
  - Remember last used size
  - Multi-monitor support
  - Restore on next activation

#### Technical Implementation:

```python
# quick_view.py (~400-600 lines)

class QuickViewWindow(QDialog):
    """macOS-style Quick Look window"""
    
    def __init__(self, browser):
        super().__init__(browser.parent())
        self.browser = browser
        self.pinned = False
        self.pinned_assets = []
        
        # Non-modal, always on top
        self.setModal(False)
        self.setWindowFlags(
            Qt.Tool | 
            Qt.WindowStaysOnTopHint | 
            Qt.FramelessWindowHint
        )
        
        # Setup UI
        self.setup_ui()
        
        # Load state
        self.restore_state()
    
    def setup_ui(self):
        """Setup Quick View UI"""
        layout = QVBoxLayout(self)
        
        # Custom titlebar
        titlebar = self.create_titlebar()
        layout.addWidget(titlebar)
        
        # Preview area (adapts to file count)
        self.preview_container = QStackedWidget()
        
        # Single file preview
        self.single_preview = self.create_single_preview()
        self.preview_container.addWidget(self.single_preview)
        
        # Grid preview (2x2, 3x3, etc.)
        self.grid_preview = self.create_grid_preview()
        self.preview_container.addWidget(self.grid_preview)
        
        layout.addWidget(self.preview_container)
        
        # Status bar
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
    
    def create_titlebar(self):
        """Custom draggable titlebar with pin button"""
        titlebar = QWidget()
        layout = QHBoxLayout(titlebar)
        
        # Title
        self.title_label = QLabel("Quick View")
        layout.addWidget(self.title_label)
        
        layout.addStretch()
        
        # Pin button
        self.pin_btn = QPushButton("📌")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("Pin preview (keeps current files visible)")
        self.pin_btn.clicked.connect(self.toggle_pin)
        layout.addWidget(self.pin_btn)
        
        # Close button
        close_btn = QPushButton("✕")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        # Make draggable
        titlebar.mousePressEvent = self.titlebar_press
        titlebar.mouseMoveEvent = self.titlebar_move
        
        return titlebar
    
    def show_preview(self, assets):
        """Show preview for selected assets"""
        if self.pinned:
            return  # Ignore if pinned
        
        if not assets:
            return
        
        # Single or multiple files?
        if len(assets) == 1:
            self.show_single_file(assets[0])
            self.preview_container.setCurrentWidget(self.single_preview)
        else:
            self.show_grid(assets)
            self.preview_container.setCurrentWidget(self.grid_preview)
        
        # Update title
        if len(assets) == 1:
            self.title_label.setText(f"Quick View - {assets[0].name}")
        else:
            self.title_label.setText(f"Quick View - {len(assets)} files")
    
    def toggle_pin(self):
        """Toggle pin state"""
        self.pinned = self.pin_btn.isChecked()
        
        if self.pinned:
            # Store current assets
            self.pinned_assets = self.current_assets.copy()
            self.status_label.setText("📌 Pinned")
        else:
            # Clear pin
            self.pinned_assets = []
            self.status_label.setText("")
            # Refresh with current selection
            self.show_preview(self.browser.get_selected_assets())
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Space:
            self.close()
        elif event.key() == Qt.Key_Left:
            self.navigate_previous()
        elif event.key() == Qt.Key_Right:
            self.navigate_next()
        else:
            super().keyPressEvent(event)


# Integration in browser.py:

def setup_quick_view(self):
    """Setup Quick View system"""
    self.quick_view_window = None
    
    # Install global Space key filter
    self.file_list.installEventFilter(self)

def eventFilter(self, obj, event):
    """Catch Space key for Quick View"""
    if obj == self.file_list:
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Space:
                self.toggle_quick_view()
                return True
    return super().eventFilter(obj, event)

def toggle_quick_view(self):
    """Toggle Quick View window"""
    if self.quick_view_window is None:
        self.quick_view_window = QuickViewWindow(self)
    
    if self.quick_view_window.isVisible():
        self.quick_view_window.close()
    else:
        # Get selected assets
        assets = self.get_selected_assets()
        if assets:
            self.quick_view_window.show_preview(assets)
            self.quick_view_window.show()
```

#### Future Enhancements:
- **Slideshow Mode** - Auto-advance through images (configurable interval)
- **Compare Mode** - Side-by-side pinned comparison (split view)
- **Quick Actions** - Import/Reference/Open buttons in preview
- **Mesh Preview** - Real 3D preview for Maya files (safe playblast)
- **Video Preview** - Play video files (.mp4, .mov)
- **Audio Preview** - Waveform display for audio files

**Deliverable:** macOS Quick Look-style floating preview with pin functionality

---

### **Phase 5.6: Floating Preview Window** 🪟
**Duration:** Week 8 (3-5 days)  
**Status:** 🔮 Future (After Collections)

#### Concept:
Duplicate preview window into a floating, movable window that can be:
- 📌 **Locked** - Content doesn't change when browsing other files
- 📍 **Always on Top** - Stays above all other windows/applications
- 🖼️ **Full Preview Features** - Zoom, pan, HDR exposure, PDF navigation

#### Use Cases:
- Compare current file with a locked reference image
- Keep an HDR visible while browsing textures
- Review PDF documentation while working
- Works with Collections system for side-by-side comparison

#### Tasks:
- [ ] **FloatingPreviewWindow Class**
  - QMainWindow or QDialog with Qt.Window flag
  - Reuse preview rendering code from PreviewPanel
  - Support all preview types: images, HDR/EXR, PDF, text
  - Share cache with main preview (memory optimization)

- [ ] **Preview Features**
  - Image zoom/pan (same as main preview)
  - HDR/EXR exposure control slider
  - PDF page navigation
  - Resolution display
  - File info overlay

- [ ] **Control Panel**
  - 📌 **Lock Content** checkbox
    - When locked: preview doesn't update on file selection
    - Stores current asset reference
  - 📍 **Always on Top** checkbox
    - Toggle `Qt.WindowStaysOnTopHint` flag
    - Keeps window above all applications
  - ❌ **Close** button

- [ ] **UI Integration**
  - "🪟 Pop Out Preview" button in PreviewPanel title bar
  - Or context menu: Right-click preview → "Open in Floating Window"
  - Or keyboard shortcut: `Ctrl+Shift+P`

- [ ] **Single Instance**
  - Only one floating window at a time (simplicity)
  - Opening new one closes previous (or reuses window)
  - Future: Multiple windows for Collections comparison

- [ ] **Memory Management**
  - Share texture cache with main preview
  - Unload floating preview cache when closed
  - Monitor memory usage

- [ ] **Window State Persistence**
  - Save window position/size in config.json
  - Restore on next open
  - Remember "Always on Top" state

#### Technical Implementation:

```python
class FloatingPreviewWindow(QMainWindow):
    """Floating preview window with lock and always-on-top features"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview - Floating")
        self.locked = False
        self.always_on_top = False
        self.current_asset = None
        
        # Setup UI
        self.setup_ui()
        
        # Load window state from config
        self.restore_window_state()
    
    def setup_ui(self):
        """Setup floating window UI"""
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        
        # Control panel
        controls = QHBoxLayout()
        self.lock_btn = QCheckBox("📌 Lock Content")
        self.lock_btn.toggled.connect(self.toggle_lock)
        
        self.top_btn = QCheckBox("📍 Always on Top")
        self.top_btn.toggled.connect(self.toggle_always_on_top)
        
        controls.addWidget(self.lock_btn)
        controls.addWidget(self.top_btn)
        controls.addStretch()
        
        layout.addLayout(controls)
        
        # Preview area (reuse PreviewPanel rendering logic)
        self.preview_area = QLabel()
        self.preview_area.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.preview_area)
        
        self.setCentralWidget(central_widget)
    
    def toggle_lock(self, checked):
        """Toggle content lock"""
        self.locked = checked
        if checked:
            # Store current asset
            pass
    
    def toggle_always_on_top(self, checked):
        """Toggle always on top"""
        self.always_on_top = checked
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        self.show()  # Re-show after flag change
    
    def update_preview(self, asset):
        """Update preview (only if not locked)"""
        if not self.locked:
            self.current_asset = asset
            # Load and display preview
            pass
```

#### Future Extensions (Collections Integration):
- Multiple floating windows for comparing collection items
- Sync floating windows with collection filters
- Grid layout of floating previews (2x2, 3x3)
- Compare mode: side-by-side locked previews

**Deliverable:** Floating preview window with lock and always-on-top features

---

### **Phase 6: Texture Converter** 🎨
**Duration:** Week 9-10 (Q1 2026)  
**Status:** 🔮 Future

#### Tasks:
- [ ] **Research Phase**
  - Test OpenImageIO (ships with Maya!)
  - Compare with OpenCV (already in external_libs)
  - Test Pillow as fallback
  - Document pros/cons

- [ ] **Core Converter**
  - Format conversion: JPEG ↔ PNG ↔ TGA ↔ TIFF ↔ EXR ↔ HDR
  - Resolution scaling (50%, 25%, custom)
  - Color space conversion (sRGB ↔ Linear ↔ ACEScg)
  - Compression quality control

- [ ] **UI Dialog**
  - Source files list
  - Output format selector
  - Resolution options
  - Color space selector
  - Quality slider
  - Output naming template
  - Progress bar

- [ ] **Challenges to Solve**
  - ⚠️ Color space preservation
  - ⚠️ 16/32-bit data handling
  - ⚠️ Metadata preservation (EXIF, color profile)
  - ⚠️ Multi-channel EXR support
  - Apply lessons from previous attempts!

- [ ] **Testing**
  - Test with various formats
  - Validate color spaces
  - Check file integrity
  - Performance testing with large batches

**Deliverable:** Professional texture batch converter

---

### **Phase 7: Polish & Finalization** ✨
**Duration:** Week 11-12 (Q1 2026)  
**Status:** 🔮 Future

#### Tasks:
- [ ] Bug fixes and optimization
- [ ] Performance profiling
- [ ] Memory leak checks
- [ ] User testing in production
- [ ] Documentation updates
- [ ] Video tutorials
- [ ] Code cleanup
- [ ] Final testing
- [ ] Prepare for public release (?)

---

## 🛠️ Technical Notes

### **Smart Import - Pattern Detection:**

```python
# Example texture pattern matcher
TEXTURE_PATTERNS = {
    'diffuse': [
        r'.*diffuse.*',
        r'.*albedo.*',
        r'.*base.*color.*',
        r'.*color.*',
        r'.*diff.*'
    ],
    'normal': [
        r'.*normal.*',
        r'.*nrm.*',
        r'.*norm.*'
    ],
    'roughness': [
        r'.*rough.*',
        r'.*rgh.*'
    ],
    'metallic': [
        r'.*metal.*',
        r'.*mtl.*'
    ],
    'ao': [
        r'.*ao.*',
        r'.*ambient.*occlusion.*'
    ],
    'displacement': [
        r'.*disp.*',
        r'.*height.*',
        r'.*bump.*'
    ]
}

def detect_texture_type(filename):
    """Match filename against patterns"""
    name_lower = filename.lower()
    for tex_type, patterns in TEXTURE_PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, name_lower):
                return tex_type
    return None
```

### **SkyDome Auto-Linker:**

```python
def update_skydome_with_hdr(hdr_path):
    """Update aiSkyDomeLight with new HDR/EXR"""
    import maya.cmds as cmds
    
    # Find or create SkyDome
    skydomes = cmds.ls(type='aiSkyDomeLight')
    if not skydomes:
        transform = cmds.shadingNode('aiSkyDomeLight', asLight=True)
        skydome = cmds.listRelatives(transform, shapes=True)[0]
    else:
        skydome = skydomes[0]
    
    # Get/create file node
    connections = cmds.listConnections(f"{skydome}.color")
    if connections:
        file_node = connections[0]
    else:
        file_node = cmds.shadingNode('file', asTexture=True)
        cmds.connectAttr(f"{file_node}.outColor", f"{skydome}.color")
    
    # Update path (preserve exposure)
    cmds.setAttr(f"{file_node}.fileTextureName", hdr_path, type="string")
    
    return skydome
```

---

## 📊 Success Metrics

### **Phase 1 Success:**
- ✅ Shader generation works with 90% of texture sets
- ✅ SkyDome update is one-click operation
- ✅ Pattern detection is configurable
- ✅ Production artists can use it without training

### **Phase 2 Success:**
- ✅ Rating/color operations are instant (<100ms)
- ✅ Visual feedback is clear and intuitive
- ✅ Filtering by rating/color is fast
- ✅ Artists use it daily

### **Phase 3 Success:**
- ✅ Tag autocomplete is responsive
- ✅ Tag search returns results in <500ms
- ✅ Tag import/export works cross-project
- ✅ Artists organize 100+ assets easily

### **Phase 4 Success:**
- ✅ Megascans assets detected automatically
- ✅ Shader generation is optimized for PBR
- ✅ UDIM textures work correctly
- ✅ LOD switching is seamless
- ✅ Import is faster than manual setup

### **Phase 5 Success:**
- ✅ Smart collections update in <1 second
- ✅ Collections handle 1000+ assets
- ✅ Drag & drop is smooth
- ✅ Artists create custom workflows

### **Phase 6 Success:**
- ✅ Converter handles 100+ textures
- ✅ Color spaces are preserved correctly
- ✅ No quality loss in conversions
- ✅ Batch conversion is faster than manual

---

## 💡 Development Philosophy

1. **Production First** - Build for real artists, not demos
2. **Performance Matters** - Sub-second operations always
3. **Error Handling** - Graceful failures, helpful messages
4. **Documentation** - Every feature documented
5. **Testing** - Test with real production assets
6. **Iteration** - Release early, improve based on feedback

---

## 🎊 Final Goal: v3.0

**DD Content Browser v3.0** will be:
- 🚀 **The fastest** asset browser for Maya
- 🎨 **The most visual** with ratings/colors/tags
- 🧠 **The smartest** with auto-material generation
- 🎨 **Megascans-ready** with one-click import
- 📁 **The most organized** with collections
- 🪟 **The most flexible** with floating preview windows
- 🎯 **Production-ready** for professional studios

**Key Features:**
1. ✅ Smart Import - Auto-generate materials from any texture set
2. ⭐ Star/Color System - Adobe Bridge-style organization
3. 🏷️ Tag System - Advanced metadata management
4. 🎨 Quixel Megascans - Optimized importer with UDIM/LOD support
5. 📁 Collections - Smart and manual collections
6. 🪟 Floating Preview - Lockable, always-on-top reference window
7. 🔄 Texture Converter - Professional batch conversion

**ETA:** Q1 2026

---

## 👨‍💻 About the Developer

**Denes Dankhazi** - VFX Artist & Technical Director

### Professional Background:
- **Digic Pictures** - VFX production experience
- Daily production work with Maya, Houdini, Unreal Engine, Substance Painter
- Specialized in pipeline tools and workflow optimization

### Expertise Areas:
- **Maya Scripting** - Python/MEL tools for production
- **Quixel Bridge Integration** - Years of custom import/export scripts
- **Render Engines** - Arnold, V-Ray, Redshift, Octane
- **Color Management** - ACEScg workflow implementation
- **Cross-DCC Tools** - Maya ↔ Houdini ↔ Unreal ↔ Blender ↔ Substance

### Notable Achievements:
- ✅ Fixed Maya 2025/PySide6 Quixel Bridge compatibility (March 2024)
- ✅ First correct Blender 3 Megascans importer (material ID fix)
- ✅ Custom Octane render engine Megascans integration
- ✅ Houdini Megascans workflow tools
- ✅ Regular Arnold/V-Ray/Redshift Megascans updates
- ✅ Multiple production pipeline tools (Split Geometry, Paint Effects Panel, Curve Cable, etc.)

### Blog & Portfolio:
**[ddankhazi.com](https://ddankhazi.com)** - Technical blog about Maya, Houdini, Unreal, and VFX pipelines

### This Project:
**DD Content Browser** is the culmination of years of production experience, combining:
- Asset management best practices
- Proven Megascans integration workflows
- Daily production needs
- Artist-friendly UX design

---

*Let's build something amazing together!* 🤝✨
