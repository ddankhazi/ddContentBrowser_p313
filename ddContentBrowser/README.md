
# DD Content Browser v2.0.0

Content Browser for Maya by Denes Dankhazi
Modern Maya Asset Browser for Autodesk Maya 2025+ (PySide6, Python 3.11 & 3.13)

---

## ✨ Overview

DD Content Browser is a high-performance, feature-rich asset browser for Maya, designed for large production environments. It replaces the built-in browser with a fast, intuitive, and visually advanced interface with advanced features like video support, texture sets, collections, tags, Quick View, and more.

---

## 🔧 Maya & Python Compatibility

DD Content Browser auto-detects the running Python interpreter and loads the matching set of bundled binary libraries (numpy, Pillow, OpenEXR, OpenImageIO, scikit-image, scipy, psd-tools, aggdraw) — no manual setup needed:

- **Maya 2025 / 2026** (Python 3.11) → uses `external_libs_py311/`
- **Maya 2027+** (Python 3.13) → uses `external_libs/`

`get_external_libs_dir()` (in `utils.py`) picks the matching folder at import time based on `sys.version_info`. If a future Maya ships a different Python, add a new `external_libs_py3XX/` folder with matching wheels and it will be picked up automatically; otherwise it falls back to the default `external_libs/`.

---

## 🚀 How to Install and Launch

### Installation

1. Copy the full content into your Maya scripts folder:  
	 `C:/Users/%USERPROFILE%/Documents/maya/2026/scripts/ddContentBrowser`

### Launch from Maya (Python):

```python
from ddContentBrowser.launch_browser import launch_no_reload
launch_no_reload()
```

### Portable Launcher

- Install Python 3.11 if you don't have it yet.
- For the first launch use: `launch_standalone_portable.bat`  
	(This will install PySide6 if you don't have it.)
- After that you can use the silent launcher: `ddContentBrowser.pyw`

Cheers, D

---

## 📚 Main Features

### Navigation & Browsing
- **Breadcrumb navigation** with clickable segments, favorites panel
- **Recent folders dropdown** (🕒 button) - last 20 visited paths
- **Fast folder switching** - Manual path entry, browse dialog
- **Back/forward navigation** with history (Alt+Left/Right)
- **Multi-select favorites** - Batch add/remove, persistent storage
- **Include subfolders** - Recursive directory browsing

### File Operations
- **Import & Reference** - Maya file operations with drag & drop
- **Delete, Rename** - Single & batch operations with confirmation (Recycle Bin or permanent via Shift+Delete)
- **New Folder** - Create folders in place (Ctrl+Shift+N)
- **Cut / Copy / Paste** - Standard clipboard file operations (Ctrl+X/C/V)
- **Duplicate** - Copy selected files in place (Ctrl+D)
- **Copy path to clipboard** - Text path copy (Ctrl+Shift+C)
- **Batch Rename Dialog** - 7 rename rule types (Find/Replace, Prefix, Suffix, Numbering, Case, Regex, New Name)
- **Multi-rule chains** - Apply sequential rename operations
- **Open with default program** - Windows default app integration
- **Middle-button drag** - Batch import Maya-style
- **Drag & drop** - To Maya viewport, collections, or folders

### Search & Filtering
- **Quick search** - Real-time filename search with case-sensitive/regex options
- **Advanced Filters Panel** - Type, category, size, date, dimensions, aspect ratio, color mode, bit depth
- **Tag filtering** - OR logic within tags, AND across categories
- **File type filters** - MA, MB, OBJ, FBX, ABC, USD, images, videos, PDFs, scripts
- **Date range** - Today, Week, Month, Custom picker
- **Size range** - Min/max MB sliders
- **Show/Hide** - Folders, images, scripts toggles
- **Recursive limits** - Configurable max file count (100-100,000)

### View Modes
- **Grid View** - Scalable thumbnails (64-512px), **Ctrl+Scroll** zoom
- **List View** - Sortable columns (name, size, date, type) with click headers
- **Thumbnail size slider** - Snap points at standard sizes
- **Sort options** - Name, Size, Date, Type with ascending/descending toggle
- **Visual indicators** - ▲▼ sort direction arrows

### Texture Sets 🧩 ✨ **NEW!**
- **Automatic PBR grouping** - Detects texture channels (baseColor, roughness, metalness, normal, height, displacement, emission, opacity, transmission, ao) sharing a base filename and groups them into a single set item
- **UDIM-aware** - Multiple UDIM tiles per channel are counted and cached correctly
- **"Texture Sets" toggle** - Grouped-set view vs. individual files (mutually exclusive with Sequences mode)
- **"Show Only Sets" filter** - Hide loose/unmatched files, show only complete sets
- **Advanced Filters integration** - Filter by "Texture Set" category (Set member / Loose file)
- **Set badge & thumbnail** - File-count badge on the thumbnail, base-color image used as the set's preview
- **Rich tooltip & metadata panel** - Lists every channel and the file(s) filling it, plus total set size
- **Drag to build shader** - Drop a set into the Maya viewport to auto-generate a shader network (aiStandardSurface by default) wired to the set's channels
- **Collections support** - Dragging a set into a Collection (or "Add to Collection") adds every file in the set; Collection view re-groups sets when Texture Sets mode is on
- **Per-folder isolation** - Same-named sets in different folders stay fully separate (thumbnails, cache)

### Quick View System ✨ **NEW!**
- **Space to open** - macOS Quick Look-style floating preview
- **Frameless window** - Custom title bar with close button (Space/Escape)
- **Multi-file grid** - 2-100+ images in auto-layout (wide aspect preference)
- **Canvas controls** - Mouse-centered scroll zoom, left-drag pan
- **F key fit-to-view** - Reset zoom and center
- **Arrow key navigation** - Navigate browser thumbnails while preview active
- **State persistence** - Position/size saved
- **Always on top toggle** - Right-click context menu option

### Collections System ✨ **NEW!**
- **Manual Collections** - Drag & drop file management with SQLite backend
- **Virtual folder view** - Display files from multiple folders
- **Middle-button drag** - Maya-style file adding to collections
- **Texture set aware** - Dragging a texture set adds all its files; Collection view can re-group them back into sets
- **Collection mode** - Blue breadcrumb indicator, exit button
- **Context menus** - "Add to Collection >", "Remove from Collection"
- **Export to folder** - Copy files with conflict handling (overwrite/skip/rename)
- **File counts** - Display number of files per collection (e.g., "▸ MyAssets (23)")
- **Cleanup missing files** - Validate file existence
- **Persistent storage** - JSON at `~/.ddContentBrowser/collections.json`

### Tag System 🏷️ ✨ **NEW!**
- **SQLite backend** - Fast metadata storage at `~/.ddContentBrowser/tags.db`
- **Default tags** - 75+ production-ready tags in 7 categories
- **Tag autocomplete** - QCompleter with all available tags
- **Preview panel integration** - Add/remove tags from files
- **Tag chips** - Visual tag display with remove buttons
- **Advanced Filters integration** - Filter by tags with file counts
- **Tag categories** - Asset Type, Environment, Lighting, Source, Technical, Material, Status
- **Persistent tags** - Tags saved across sessions
- **Bulk operations** - Add tags to multiple files (context menu)

### Preview System
- **Preview panel** - Image (JPG, PNG, TIF, HDR, EXR, PSD), PDF (page navigation), text files
- **HDR/EXR support** - Exposure slider (-5 to +5 stops), ACES tone mapping
- **16/32-bit TIFF** - OpenCV integration with proper normalization
- **Video thumbnails** - Middle frame extraction for 8 formats (.mp4, .mov, .avi, .mkv, .webm, .m4v, .flv, .wmv)
- **Zoom mode** - Double-click for 1:1 pixel zoom, mouse-centered scroll zoom
- **Pan & scroll** - Drag to pan, scrollbars when zoomed
- **Background modes** - Dark, light, checkerboard
- **Password-protected PDFs** - User-friendly lock message
- **Multi-file summary** - Resolution, size, date display

### Batch Operations
- **Batch Import** - Middle mouse drag to Maya viewport
- **Batch Rename** - Multi-rule system with 7 rule types:
  - Find & Replace (case sensitive, whole name)
  - New Name (templates with {num}, {original})
  - Add Prefix/Suffix
  - Numbering (start, padding, position)
  - Case Change (UPPER, lower, Title, Sentence)
  - Regex Pattern (full regex with capture groups)
- **Live preview** - Real-time before/after comparison with highlighting
- **Rule management** - Add, remove, reorder with + and − buttons
- **Compact UI** - Space-efficient 11px font, resizable splitter

### Cache & Performance
- **Directory cache** - Complete AssetItem objects cached (5 min TTL, max 20 dirs)
- **Lazy loading** - Asset metadata (size/date) loaded only when needed
- **os.scandir() optimization** - 55x faster than iterdir/glob (2000 files: 12.5s → 0.007s cached)
- **Memory cache** - 200 items LRU
- **Disk cache** - 500MB JPEG compression, MD5 keys with mtime validation
- **Background thumbnail generation** - Non-blocking with progress signals
- **Smart invalidation** - Auto-refresh on directory changes (F5 force refresh)
- **Statistics tracking** - Cache hits, misses, generated counts

### Settings System ✨ **NEW!**
- **Multi-tab dialog** - General, Thumbnails, Preview, Filters (600x500px)
- **JSON persistence** - Auto-save to `~/.ddContentBrowser/settings.json`
- **General settings** - Startup dir, window size, UI font (5 fonts), confirm delete, auto-refresh
- **Thumbnail settings** - Discrete sizes [32-512px], quality presets (Low/Med/High), cache limit
- **Preview settings** - HDR resolution [512-4096px], cache size (1-20 files), default exposure
- **Filter settings** - Custom extensions, show hidden, case-sensitive search, recursive limits
- **Cache management** - Visual cache size display, one-click clear
- **Restore defaults** - Reset all settings button
- **Live updates** - settings_changed signal for component refresh

### File Type Registry ✨ **NEW!**
- **Centralized definitions** - Single source in FILE_TYPE_REGISTRY (utils.py)
- **11 categories** - maya, 3d_models, blender, houdini, substance, images, pdf, scripts, text, video, other
- **Config version system** - Automatic updates with user customization preservation
- **Video support** - 8 formats with custom color schemes
- **Helper functions** - get_extensions_by_category(), get_default_icon_colors()

### Supported Formats
- **Maya**: `.ma`, `.mb`
- **3D Models**: `.obj`, `.fbx`, `.abc`, `.usd`, `.vdb`, `.dae`, `.stl`
- **Blender**: `.blend`
- **Houdini**: `.hda`
- **Substance**: `.sbsar`
- **Images**: `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.tga`, `.exr`, `.hdr`, `.psd`, `.tx`, `.gif`
- **Videos** ✨ **NEW!**: `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v`, `.flv`, `.wmv`
- **Documents**: `.pdf`
- **Scripts**: `.py`, `.mel`
- **Text**: `.txt`
- **Other**: `.abr`

*(Central definition lives in `FILE_TYPE_REGISTRY`, `utils.py` — extend via Settings → Filters, no code changes needed.)*

### External Libraries
- **PySide6** - Qt for Python (UI framework)
- **Pillow** - Image processing (thumbnails, conversions)
- **OpenCV (cv2)** - Advanced image ops, 16/32-bit TIFF, video frames
- **PyMuPDF** - PDF rendering
- **OpenEXR** - HDR/EXR support with multi-channel
- **OpenImageIO** - `.tx` (RenderMan texture) loading, EXR fallback
- **NumPy** - Float processing
- **scikit-image** - Advanced image analysis
- **psd-tools** - Photoshop PSD file support
- **aggdraw** - Anti-aliased gradient icon rendering

*(Bundled per Python version - see "Maya & Python Compatibility" above.)*

---

## ⌨️ Keyboard Shortcuts

| Shortcut           | Action                                           |
|--------------------|--------------------------------------------------|
| **Space**          | Quick View (floating preview)                    |
| **F**              | Fit to view (in Quick View)                      |
| **F5**             | Refresh current folder (force cache bypass)      |
| **Delete**         | Delete selected files to Recycle Bin             |
| **Shift+Delete**   | Permanently delete selected files                |
| **F2**             | Rename selected file                             |
| **Ctrl+F**         | Focus search box                                 |
| **Ctrl+Shift+N**   | Create new folder                                |
| **Ctrl+C**         | Copy selected files to clipboard                 |
| **Ctrl+Shift+C**   | Copy path to clipboard                           |
| **Ctrl+X**         | Cut selected files to clipboard                  |
| **Ctrl+V**         | Paste files from clipboard                       |
| **Ctrl+D**         | Duplicate selected files                         |
| **Enter**          | Import selected file                             |
| **Backspace**      | Go to parent folder                              |
| **Ctrl+Scroll**    | Zoom thumbnails                                  |
| **Alt+Left/Right** | Back/Forward navigation                          |
| **Escape**         | Cancel path edit / Close Quick View              |
| **Arrow Keys**     | Navigation / Quick View file browsing            |
| **1-5**            | Star rating (future feature)                     |
| **Ctrl+1-7**       | Color labels (future feature)                    |

---

## 🖱️ Mouse Controls

| Control              | Action                                      |
|---------------------|---------------------------------------------|
| **LMB**             | Selection                                   |
| **LMB Drag**        | Box select (rubber band)                    |
| **Double-Click**    | Import file / Enter zoom mode (preview)     |
| **Alt+LMB Drag**    | File drag (Maya import)                     |
| **MMB Drag**        | Batch import / Add to collection            |
| **RMB**             | Context menu                                |
| **Ctrl+Scroll**     | Zoom thumbnails                             |
| **Scroll (Preview)**| Zoom (mouse-centered)                       |
| **Left-Drag (QV)**  | Pan image in Quick View                     |

---

## 🎨 Visual Features

- **Beautiful gradient icons** - Type-specific colors for each file format
- **Video format colors** - 8 video formats with custom gradients (.mp4 pink, .mov purple, .avi blue, etc.)
- **Maya/3D file thumbnails** - Blue/purple/yellow gradients for different formats
- **Image preview** - Actual image thumbnails with format detection
- **HDR/EXR tone-mapped** - Preview with exposure control
- **PDF first page** - Thumbnail of first page
- **Video middle frame** - Extracted frame for video preview
- **Collection indicators** - Blue breadcrumb background, ▸ icon
- **Tag chips** - Color-coded tag categories with remove buttons
- **Status info bar** - Selection count, file count, controls hint

---

## 🚀 Performance

**Directory Loading (os.scandir optimization):**
- 100 files: <100ms (first load), <1ms (cached)
- 1,000 files: ~500ms (first load), ~5ms (cached)
- 2,000 files (network): 2.5s (first load), 0.007s (cached) - **1785x faster!**
- 10,000 files: ~5s (background loading with progress)

**Cache Performance:**
- Memory cache hit: <1ms
- Disk cache hit: 5-10ms
- AssetItem cache: 353x faster on repeat visits
- Lazy loading: Only loads size/date when needed

**Thumbnail Generation:**
- Gradient icons: 100-500ms per file
- Image thumbnails: 50-200ms (with caching)
- Video thumbnails: 100-300ms (middle frame extraction)
- HDR/EXR: 100-200ms (1024px, first time), 35-45ms (exposure adjust from cache)

**UI Performance:**
- Frame time: ~16ms (60fps)
- Quick View zoom: ~16ms (60fps)
- Quick View pan: <5ms (instant)
- Filter update: <100ms (2000 files)

**Memory Usage:**
- Base: ~50MB
- +1MB per 100 thumbnails
- HDR cache: ~100-150MB (last 5 raw images)
- Disk cache: 500MB max (configurable)

**Optimizations:**
- Background thumbnail generation (non-blocking)
- LRU cache eviction (memory management)
- Deferred preview loading
- Smart cache invalidation (mtime checks)
- Batch stat loading (only when filtering/sorting)

---

## 📝 License

This tool is free for personal and studio use.
You may modify, copy, and integrate it into your workflow.
No warranty or liability is provided.
Commercial redistribution is not permitted without the author's permission.

---

## 🙏 Credits

**Author:** Denes Dankhazi (ddankhazi)  
**Version:** 2.0.0  
**Maya Version:** 2025+ (PySide6)  
**Python:** 3.11 (Maya 2025/2026) & 3.13 (Maya 2027+)  
**Blog & Portfolio:** [ddankhazi.com](https://ddankhazi.com)

---

## 🔮 Planned Features (Future)

*Smart Material Generator (auto-shader from texture sets) shipped in v2.0 — see "Texture Sets" above.*

### High Priority:
1. **Quixel Megascans Importer** - One-click optimized import with UDIM/LOD
2. **SkyDome Auto-Linker** - Drag HDR → update aiSkyDomeLight path
3. **Star/Color Rating** - Adobe Bridge-style organization (0-5 stars, 8 colors)
4. **Enhanced Tag System** - Tag hierarchies, bulk operations, import/export

### Medium Priority:
5. **Texture Converter** - Batch format conversion with color space management
6. **Real Maya Playblast** - Safe thumbnail generation (subprocess isolation)
7. **Asset Metadata** - Scene stats (poly count, shader info)
8. **Theme Support** - Dark/Light themes, custom colors
9. **Version Control** - Git/Perforce integration

---

**Happy browsing! 🚀✨**
