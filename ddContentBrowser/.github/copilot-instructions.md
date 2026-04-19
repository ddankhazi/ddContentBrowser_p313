# DD Content Browser - AI Coding Instructions

**Version:** 1.8.1 | **Target:** Maya 2025+ (Python 3.11+, PySide6)

## Project Overview

DD Content Browser is a high-performance asset browser for Autodesk Maya with standalone capabilities. It replaces Maya's built-in browser with advanced features: multithreaded thumbnail generation, SQLite-based metadata (tags/ratings), collections, Quick View, and smart material imports.

**Deployment Model:** Single-folder portable application with bundled dependencies in `external_libs/`

## Architecture Overview

### Core Components

**Browser ([browser.py](browser.py))** - Main window (4692 lines)
- `DDContentBrowser` class: Central coordinator between models, cache, widgets
- Dual-mode operation: Maya-integrated (parented to Maya main window) or standalone
- Navigation: Breadcrumb + favorites + recent paths + history (back/forward)
- View modes: Grid (scalable thumbnails) + List (sortable columns)

**Data Layer**
- `FileSystemModel` ([models.py](models.py)): QAbstractListModel with lazy metadata loading
- `AssetItem` data class: File path, size, mtime, extension, category, thumbnail state
- Directory cache: 5min TTL, max 20 dirs, complete AssetItem objects cached

**Cache System ([cache.py](cache.py))** - 3744 lines, critical performance component
- **Hybrid architecture:** ThreadPoolExecutor (3 workers) for CPU-intensive decode/resize → Main QThread for QPixmap conversion
- Memory cache: 200 items LRU
- Disk cache: 500MB JPEG thumbnails, MD5 keys = `hash(file_path + mtime)`
- Auto-refresh detection: Compares file mtime to cached thumbnail generation time
- Optimizations: OpenCV IMREAD_REDUCED_* flags (2-8× speedup), TurboJPEG for large files

**Metadata ([metadata.py](metadata.py))**
- SQLite database at `~/.ddContentBrowser/tags.db`
- Tables: `file_metadata` (ratings, color labels), `tags` (hierarchical with categories), `file_tags` (many-to-many)
- Default tags: 75+ production tags in 7 categories loaded from [default_tags.json](default_tags.json)

**Collections ([asset_collections.py](asset_collections.py))**
- Manual collections: User-curated file lists stored in `~/.ddContentBrowser/collections.json`
- Smart collections: Filter-based (roadmap - not yet implemented)
- Operations: Add via drag/drop, middle-mouse, context menu; Export to folder with conflict handling

**Configuration ([config.py](config.py))**
- JSON storage at `~/.ddContentBrowser/config.json`
- Session state: recent paths, favorites (with alias/color), window geometry, view mode
- Settings: Sort order, filters, thumbnail sizes, Quick View position

### Key Patterns & Conventions

**1. Version Management (CRITICAL)**
- **Single source of truth:** `__version__ = '1.8.1'` in [__init__.py](__init__.py) (line 11)
- MUST be defined BEFORE any imports to avoid circular dependencies
- Auto-imported by `browser.py`, `standalone_launcher_portable.py`
- See [VERSION_INFO.md](VERSION_INFO.md) for migration history

**2. External Dependencies (Portable Design)**
```python
# Standard pattern in every module needing external libs:
script_dir = Path(__file__).parent
external_libs_path = script_dir / "external_libs"
if str(external_libs_path) not in sys.path:
    sys.path.insert(0, str(external_libs_path))
```
- All dependencies bundled in `external_libs/`: numpy, opencv, PIL, pymupdf, openexr, psd_tools, scipy, skimage
- TurboJPEG DLL loaded from `external_libs/bin/turbojpeg.dll` (portable-first, fallback to system)

**3. Maya vs Standalone Detection**
```python
from .utils import MAYA_AVAILABLE, get_maya_main_window
# MAYA_AVAILABLE = True if maya.cmds importable
parent = get_maya_main_window() if MAYA_AVAILABLE else None
```
- Use `MAYA_AVAILABLE` flag before any Maya cmds/mel calls
- Standalone mode runs without Maya (PySide6 only)

**4. PySide Version Compatibility**
```python
try:
    from PySide6 import QtCore, QtWidgets, QtGui
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2 import QtCore, QtWidgets, QtGui
    PYSIDE_VERSION = 2
```
- Support both PySide2 (Maya legacy) and PySide6 (standalone, modern)
- Check `PYSIDE_VERSION` for API differences

**5. UI Font Customization**
- Default: `UI_FONT = "Segoe UI"` (declared in cache.py, models.py, delegates.py)
- User-configurable via Settings dialog
- Applied via `set_ui_font()` in utils.py, propagated to all modules

**6. File Type Registry (Centralized)**
```python
from .utils import (
    get_extension_category,        # Returns: 'maya', 'images', 'videos', etc.
    is_extension_supported,         # Boolean check
    get_importable_extensions,      # Maya-specific importables
    FILE_TYPE_REGISTRY              # Full registry dict
)
```
- Single source in [utils.py](utils.py): `FILE_TYPE_REGISTRY`
- 9 categories with display names, extensions, colors, import/thumbnail flags
- User customizations preserved during config version updates

**7. Thumbnail State Machine**
```python
# AssetItem.thumbnail_state values:
'none'        # Not requested yet
'queued'      # Added to generation queue
'loading'     # Worker thread processing
'loaded'      # Pixmap in memory cache
'failed'      # Generation error
```

**8. Debug Mode Pattern**
```python
DEBUG_MODE = False  # Set True for verbose logging
if DEBUG_MODE:
    print(f"[Module] Debug message: {details}")
```
- Used in cache.py, browser.py, models.py, asset_collections.py
- Performance-critical: Set False for production

## Critical Workflows

### Thumbnail Generation Pipeline

1. **Request:** `browser.request_thumbnails_for_visible_items()` called on scroll/refresh
2. **Cache check:** Memory → Disk (with mtime validation via `needs_refresh()`)
3. **Queue:** If miss, add to `ThumbnailGenerator.queue` (priority queue, visible items first)
4. **Generation:** ThreadPoolExecutor workers decode/resize → numpy array
5. **Conversion:** Main QThread converts array → QPixmap, stores in caches
6. **Signal:** `thumbnail_generated` → `browser.on_thumbnail_ready()` → `model.dataChanged` → UI update

**Key files:** [cache.py](cache.py) (lines 100-3744), [browser.py](browser.py) `request_thumbnails_for_visible_items()`

### Launch Procedures

**From Maya:**
```python
from ddContentBrowser.launch_browser import launch_no_reload
launch_no_reload()  # No module reload (faster)
# OR
launch()  # Force reload all modules (development)
```

**Standalone:**
- Windows: `launch_standalone_portable.bat` (installs PySide6 if missing)
- Silent: `ddContentBrowser.pyw` (no console)
- Python: `python standalone_launcher_portable.py`

### Maya Import Operations

**Import file:**
```python
cmds.file(file_path, i=True, type="mayaAscii", 
          ignoreVersion=True, mergeNamespacesOnClash=False,
          namespace=':', options='v=0', preserveReferences=True)
```

**Reference file:**
```python
namespace = Path(file_path).stem  # Use filename as namespace
cmds.file(file_path, r=True, namespace=namespace)
```

**Drag & drop to viewport:** Uses MEL command with escaped paths (see [models.py](models.py) lines 1394-1420)

### Smart Material Generation (smart_imports/)

**Integration point:** [smart_imports/ddShaderNetworkGenerator.py](smart_imports/ddShaderNetworkGenerator.py)
- Pattern matching: `*_diffuse`, `*_albedo`, `*_normal`, `*_rough*`, `*_metal*`
- Configuration: JSON sidecar file (`ddShaderNetworkGenerator.json`)
- Supported shaders: `aiStandardSurface`, `openPBRSurface`
- UDIM detection: Regex `r"(?:[\._-])(1\d{3})(?=[\._-]|$)"`
- Channel priority: Configurable per-channel (displacement allows .exr, others exclude)

**Future integration:** Context menu "Auto-Generate Material" (see [DEVELOPMENT_ROADMAP_V3.md](DEVELOPMENT_ROADMAP_V3.md) Phase 1)

## Coding Guidelines

### When Adding New Features

**DO:**
- Use `multi_replace_string_in_file` for multiple edits (efficiency)
- Add to appropriate module: widgets (UI), models (data), cache (thumbnails), metadata (tags/ratings)
- Follow lazy loading patterns (metadata loaded only when needed)
- Test both Maya and standalone modes
- Update `FILE_TYPE_REGISTRY` for new file format support
- Use natural sorting: `natural_sort_key()` from models.py
- Add settings to [settings.py](settings.py) with JSON persistence

**DON'T:**
- Create QPixmap/QImage in worker threads (Qt thread-safety violation)
- Hardcode file paths (use Path objects, resolve to absolute)
- Block main thread with I/O (use threading/QThreads)
- Add version strings outside `__init__.py`
- Import modules in `__init__.py` before `__version__` declaration

### Performance Considerations

**Thumbnail optimization checklist:**
- Use OpenCV for files >50MB (IMREAD_REDUCED flags)
- Load at 8-16× target size (quality/speed balance)
- Cache scaled pixmaps in delegates (avoid re-scaling on every paint)
- Limit worker threads to 3-4 (more = memory pressure + I/O contention)

**Directory scanning:**
- Use `os.scandir()` (55× faster than iterdir/glob)
- Cache full `AssetItem` objects (5min TTL)
- Lazy metadata loading (size/mtime only when visible)

### Error Handling Patterns

```python
try:
    from turbojpeg import TurboJPEG
    TURBOJPEG_AVAILABLE = True
except Exception as e:
    if DEBUG_MODE:
        print(f"[Module] Optional dependency unavailable: {e}")
    TURBOJPEG_AVAILABLE = False
```
- Graceful degradation for optional dependencies
- Print errors only in DEBUG_MODE unless critical

## Testing & Debugging

**Manual test scenarios:**
1. Large directories (1000+ files) - check cache performance
2. Mixed file types (Maya, images, videos, PDFs) - verify categorization
3. File modifications - auto-refresh detection
4. Drag & drop - Maya import, collection adding
5. Quick View - multi-file grid layout, zoom/pan controls
6. Settings changes - live updates without restart

**Debug tools:**
- Set `DEBUG_MODE = True` in target module
- Statistics panel: Cache hits/misses, generated count (browser status bar)
- Qt message handler suppression: TGA warnings globally filtered (browser.py line 41)

**Common issues:**
- **Circular imports:** Ensure `__version__` is first line in `__init__.py`
- **Thumbnail failures:** Check external_libs path, verify codec support
- **Maya integration:** Verify `MAYA_AVAILABLE` flag, test with Maya not running

## Deployment Notes

**Packaging:**
- External libs precompiled for Windows x64
- NumPy/SciPy wheels: Python 3.11 compatible
- OpenCV DLLs in `external_libs/` (no system install needed)

**User data locations:**
- Config: `~/.ddContentBrowser/config.json`
- Tags DB: `~/.ddContentBrowser/tags.db`
- Collections: `~/.ddContentBrowser/collections.json`
- Settings: `~/.ddContentBrowser/settings.json`
- Disk cache: `~/.ddContentBrowser/thumbnail_cache/`

## Active Development (Phase 1 - Q1 2026)

See [DEVELOPMENT_ROADMAP_V3.md](DEVELOPMENT_ROADMAP_V3.md) for full roadmap.

**Current focus:**
- Smart Import Functions integration
- Shader graph builder wiring (ddShaderNetworkGenerator)
- Texture pattern detection UI
- SkyDome auto-linker for HDR/EXR files

**Pair programming model:** Production expert + AI assistant (GitHub Copilot)
