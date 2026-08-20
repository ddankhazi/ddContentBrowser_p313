"""
DD Content Browser - Utility Functions
Helper functions for Maya integration and common operations
"""

import os
import sys
import threading


def get_external_libs_dir():
    """
    Return the external_libs folder matching the running interpreter's ABI.

    The bundled binary wheels (numpy, Pillow, OpenEXR, scikit-image, scipy,
    psd-tools, aggdraw, ...) are compiled for a specific CPython version and
    won't import under a different one. external_libs/ is the default build
    (currently Python 3.13, for newer Maya); external_libs_py311/ is a
    Python 3.11 build (for Maya 2025/2026). Falls back to external_libs/ if
    no version-specific folder matches the running interpreter.
    """
    base = os.path.dirname(os.path.abspath(__file__))
    versioned = os.path.join(base, f'external_libs_py{sys.version_info.major}{sys.version_info.minor}')
    if os.path.isdir(versioned):
        return versioned
    return os.path.join(base, 'external_libs')


def get_mayapy_executable():
    """
    Locate mayapy.exe (Maya's standalone/headless Python interpreter) next
    to the currently running Maya executable.

    Used to spawn sequence-playback decode worker subprocesses (see
    sequence_decode_worker.py) as genuinely separate OS processes rather
    than threads within Maya's own process - confirmed necessary because
    calling OpenImageIO/OpenCV concurrently from ThreadPoolExecutor worker
    threads inside Maya's process crashed Maya outright (a native crash,
    no Python traceback, immediately after the first background decode
    requests were submitted).

    Falls back to sys.executable if mayapy.exe isn't found next to it -
    e.g. when testing standalone, where sys.executable already IS a plain
    python.exe capable of running the worker script directly.
    """
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    mayapy = os.path.join(exe_dir, 'mayapy.exe')
    if os.path.isfile(mayapy):
        return mayapy
    return sys.executable


_openexr_import_cache = {}
_openexr_import_lock = threading.Lock()


def import_openexr():
    """
    Import OpenEXR/Imath, preferring the bundled build in external_libs
    over any OpenEXR module Maya itself ships on its default sys.path.

    Maya (2026, and likely future versions too) bundles its own OpenEXR
    Python module for its own internal use, implementing only the legacy
    InputFile-style read API - not the newer .File API this codebase is
    written against. Since callers normally add external_libs to sys.path
    via append() (so Maya's own numpy/cv2/etc. still win, avoiding ABI
    conflicts between differently-built copies of those), Maya's own
    OpenEXR module wins that race too and gets imported instead of ours,
    producing errors like "module 'OpenEXR' has no attribute 'File'".

    This detects that case (bundled module found, but missing .File) and
    forces a reload from external_libs specifically for OpenEXR/Imath,
    without disturbing the general append-based priority used for
    everything else. Cached after the first call - the reload only ever
    needs to happen once per session.

    Returns (OpenEXR, Imath) modules, or (None, None) if unavailable.
    """
    if 'result' in _openexr_import_cache:
        return _openexr_import_cache['result']

    # Thumbnail generation runs on worker threads, so this can be called
    # concurrently on first use - the sys.modules/sys.path surgery below
    # isn't safe to run from two threads at once.
    with _openexr_import_lock:
        if 'result' in _openexr_import_cache:
            return _openexr_import_cache['result']

        try:
            import OpenEXR
            import Imath
        except ImportError:
            OpenEXR = None
            Imath = None

        if OpenEXR is not None and not hasattr(OpenEXR, 'File'):
            external_libs = get_external_libs_dir()
            if os.path.isdir(external_libs):
                sys.modules.pop('OpenEXR', None)
                sys.modules.pop('Imath', None)
                if external_libs in sys.path:
                    sys.path.remove(external_libs)
                sys.path.insert(0, external_libs)
                try:
                    import OpenEXR
                    import Imath
                except ImportError:
                    OpenEXR = None
                    Imath = None
                finally:
                    # Restore append-only priority for everything else
                    # that shares this folder (numpy, cv2, ...).
                    if external_libs in sys.path:
                        sys.path.remove(external_libs)
                    sys.path.append(external_libs)

        _openexr_import_cache['result'] = (OpenEXR, Imath)
        return OpenEXR, Imath


def group_oiio_exr_channels(channelnames):
    """
    Group a flat OpenImageIO channel-name list the same way OpenEXR's
    Python OpenEXR.File().channels() API groups them: channels sharing a
    dotted prefix (or no prefix) whose suffixes include R, G, B (and
    optionally A) collapse into one entry keyed by the prefix (or
    "RGB"/"RGBA" when there's no prefix, e.g. plain "R"/"G"/"B" channels
    group into "RGB", "diffuse.R"/"diffuse.G"/"diffuse.B" group into
    "diffuse"); every other channel (Z, N.X, N.Y, N.Z, ...) keeps its own
    full name as the key. Verified to match OpenEXR.File()'s real grouping
    exactly against both single-layer and multi-AOV EXRs.

    This lets code written against OpenEXR's grouped-dict API (see
    read_exr_via_oiio() below) be ported to OpenImageIO without changing
    the channel-name lookup/fallback logic itself - see
    cache.py's _generate_exr_thumbnail_optimized() and preview_panel.py's
    load_exr_channel() for both call sites.

    Returns an OrderedDict: group key -> list of member channel names (in
    R, G, B[, A] order for grouped entries; a single-item list otherwise),
    in first-seen order.
    """
    from collections import OrderedDict

    by_prefix = OrderedDict()
    for name in channelnames:
        if '.' in name:
            prefix, suffix = name.rsplit('.', 1)
        else:
            prefix, suffix = '', name
        by_prefix.setdefault(prefix, OrderedDict())[suffix] = name

    groups = OrderedDict()
    used = set()
    for prefix, suffix_map in by_prefix.items():
        if 'R' in suffix_map and 'G' in suffix_map and 'B' in suffix_map:
            has_alpha = 'A' in suffix_map
            key = prefix if prefix else ('RGBA' if has_alpha else 'RGB')
            members = [suffix_map['R'], suffix_map['G'], suffix_map['B']]
            if has_alpha:
                members.append(suffix_map['A'])
            groups[key] = members
            used.update(members)
    for name in channelnames:
        if name not in used:
            groups[name] = [name]
    return groups


def read_exr_via_oiio(file_path):
    """
    Read an EXR file's full pixel data via OpenImageIO - measured ~2-3x
    faster than the OpenEXR Python binding (OpenEXR.File()) for typical
    single-layer texture/HDRI EXRs, and still meaningfully faster on
    multi-AOV render EXRs, in testing during a thumbnail-generation
    performance investigation.

    Returns (width, height, channels) where channels is a dict of
    group-key -> numpy float32 array (2D for a single channel, 3D
    (H,W,3)/(H,W,4) for a grouped RGB/RGBA/layer entry) - grouped via
    group_oiio_exr_channels() so it has the same shape as iterating
    OpenEXR.File().channels().items() and reading each entry's .pixels
    (just without the .pixels attribute - index the dict value directly).

    Raises OSError/ValueError on failure (missing file, unreadable
    format, no pixel data, etc.) - callers should catch as part of their
    existing error handling, same as they would OpenEXR.File() raising.
    """
    import sys
    import numpy as np

    external_libs = get_external_libs_dir()
    if external_libs not in sys.path:
        sys.path.append(external_libs)
    from OpenImageIO import ImageInput

    inp = ImageInput.open(str(file_path))
    if not inp:
        raise OSError(f"OpenImageIO could not open {file_path}")
    spec = inp.spec()
    width, height = spec.width, spec.height
    pixels = inp.read_image()
    inp.close()
    if pixels is None:
        raise ValueError(f"OpenImageIO returned no pixel data for {file_path}")

    img = np.array(pixels, dtype=np.float32)
    name_to_idx = {name: i for i, name in enumerate(spec.channelnames)}
    grouped = group_oiio_exr_channels(spec.channelnames)

    channels = {}
    for key, members in grouped.items():
        idxs = [name_to_idx[m] for m in members]
        channels[key] = img[:, :, idxs] if len(idxs) > 1 else img[:, :, idxs[0]]

    return width, height, channels


# Maya imports
try:
    import maya.cmds as cmds
    import maya.mel as mel
    import maya.OpenMayaUI as omui
    MAYA_AVAILABLE = True
except ImportError:
    MAYA_AVAILABLE = False
    print("Maya not available - running in standalone mode")

# PySide imports
try:
    from PySide2 import QtWidgets
    from shiboken2 import wrapInstance
    PYSIDE_VERSION = 2
except ImportError:
    try:
        from PySide6 import QtWidgets
        from shiboken6 import wrapInstance
        PYSIDE_VERSION = 6
    except ImportError:
        print("Error: PySide2 or PySide6 required!")
        import sys
        sys.exit(1)


def get_maya_main_window():
    """Get Maya main window as QWidget"""
    if not MAYA_AVAILABLE:
        return None
    
    main_window_ptr = omui.MQtUtil.mainWindow()
    if main_window_ptr:
        return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)
    return None


# Default UI font - can be overridden by settings
_UI_FONT = "Segoe UI"

def get_ui_font():
    """Get the current UI font family"""
    return _UI_FONT

def set_ui_font(font_family):
    """Set the UI font family"""
    global _UI_FONT
    _UI_FONT = font_family


# ============================================================================
# FILE TYPE REGISTRY - Central definition of all supported file types
# ============================================================================

# Version of the registry - increment when adding/modifying default formats
# FILE_TYPE_REGISTRY version (increment to trigger config merge)
FILE_TYPE_REGISTRY_VERSION = "1.2"

FILE_TYPE_REGISTRY = {
    # Category: (extensions_list, display_label, filter_group_name)
    "maya": {
        "extensions": [".ma", ".mb"],
        "label": "Maya Files",
        "filter_label": "Maya Files (.ma/.mb)",
        "importable": True,
        "generate_thumbnail": False,  # Delegate draws gradient
        "is_3d": True
    },
    "3d_models": {
        "extensions": [".obj", ".fbx", ".abc", ".usd", ".vdb", ".dae", ".stl"],
        "label": "3D Models",
        "filter_label": "3D Models (.obj/.fbx/.abc/.usd/.vdb/ .dae/ .stl)",
        "importable": True,
        "generate_thumbnail": False,  # Delegate draws gradient
        "is_3d": True
    },
    "blender": {
        "extensions": [".blend"],
        "label": "Blender Files",
        "filter_label": "Blender (.blend)",
        "importable": False,  # Not directly importable to Maya
        "generate_thumbnail": False,  # Delegate draws gradient
        "is_3d": True
    },
    "houdini": {
        "extensions": [".hda"],
        "label": "Houdini Digital Assets",
        "filter_label": "Houdini HDA (.hda)",
        "importable": True,
        "generate_thumbnail": False,  # Delegate draws gradient
        "is_3d": True
    },
    "substance": {
        "extensions": [".sbsar"],
        "label": "Substance Archive",
        "filter_label": "Shaders (.sbsar)",
        "importable": True,
        "generate_thumbnail": False,  # Delegate draws gradient
        "is_3d": False
    },
    "images": {
        "extensions": [".tif", ".tiff", ".jpg", ".jpeg", ".png", ".hdr", ".exr", ".tga", ".psd", ".tx", ".gif"],
        "label": "Images",
        "filter_label": "Images (.tif/.jpg/.png/.hdr/.exr/.psd/.tx/.gif)",
        "importable": True,
        "generate_thumbnail": True,
        "is_3d": False
    },
    "pdf": {
        "extensions": [".pdf"],
        "label": "PDF Documents",
        "filter_label": "PDF (.pdf)",
        "importable": False,
        "generate_thumbnail": True,
        "is_3d": False
    },
    "scripts": {
        "extensions": [".mel", ".py"],
        "label": "Scripts",
        "filter_label": "Scripts (.mel/.py)",
        "importable": True,
        "generate_thumbnail": False,
        "is_3d": False
    },
    "text": {
        "extensions": [".txt"],
        "label": "Text Files",
        "filter_label": "Text (.txt)",
        "importable": False,
        "generate_thumbnail": False,
        "is_3d": False
    },
    "video": {
        "extensions": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv", ".wmv"],
        "label": "Video Files",
        "filter_label": "Video (.mp4/.mov/.avi/.mkv/.webm)",
        "importable": False,  # Not directly importable to Maya (could be image plane in future)
        "generate_thumbnail": True,  # Extract middle frame
        "is_3d": False
    },
    "other": {
        "extensions": [".abr"],
        "label": "Other Files",
        "filter_label": "Other (.abr)",
        "importable": False,
        "generate_thumbnail": False,
        "is_3d": False
    }
}

# The browser shows every file by default (see is_extension_supported()) so users
# don't have to register each format they care about. These extensions are pure
# filesystem/editor noise, so they default to disabled instead - still visible if
# the user explicitly re-enables them via Settings -> File Formats.
DEFAULT_DISABLED_EXTENSIONS = {
    ".tmp", ".bak", ".old", ".log", ".lock", ".swp", ".cache", ".pyc",
}


def get_all_supported_extensions():
    """Get list of all supported file extensions from config file"""
    config = ensure_file_formats_config()
    extensions = []
    for ext, ext_config in config.get('extensions', {}).items():
        # Only include enabled extensions
        if ext_config.get('enabled', True):
            extensions.append(ext)
    
    # Fallback to FILE_TYPE_REGISTRY if config is empty
    if not extensions:
        for category in FILE_TYPE_REGISTRY.values():
            extensions.extend(category["extensions"])
    
    return extensions


def get_extension_category(extension):
    """Get category name for a file extension from config file"""
    extension = extension.lower()
    config = ensure_file_formats_config()
    
    # Try config first (direct lookup to avoid recursion)
    if extension in config.get("extensions", {}):
        return config["extensions"][extension].get("category")
    
    # Fallback to FILE_TYPE_REGISTRY
    for category_name, category_data in FILE_TYPE_REGISTRY.items():
        if extension in category_data["extensions"]:
            return category_name
    
    return None


def is_extension_supported(extension):
    """Check if extension is supported in config file"""
    extension = extension.lower()
    
    # Try config first
    ext_config = get_extension_config(extension)
    if ext_config:
        return ext_config.get('enabled', True)
    
    # Fallback to FILE_TYPE_REGISTRY
    return get_extension_category(extension) is not None


def get_importable_extensions():
    """Get list of extensions that are importable to Maya from config file"""
    config = ensure_file_formats_config()
    extensions = []
    
    for ext, ext_config in config.get('extensions', {}).items():
        # Only include enabled extensions that have maya_import_type defined
        if ext_config.get('enabled', True) and ext_config.get('maya_import_type'):
            extensions.append(ext)
    
    # Fallback to FILE_TYPE_REGISTRY if config is empty
    if not extensions:
        for category in FILE_TYPE_REGISTRY.values():
            if category["importable"]:
                extensions.extend(category["extensions"])
    
    return extensions


def should_generate_thumbnail(extension):
    """Check if extension should generate thumbnails"""
    category = get_extension_category(extension)
    if category:
        return FILE_TYPE_REGISTRY[category]["generate_thumbnail"]
    return False


def get_filter_groups():
    """Get list of filter groups for UI (name, extensions) from config"""
    config = ensure_file_formats_config()
    categories = config.get('categories', {})
    
    groups = []
    for category_name, category_data in categories.items():
        filter_label = category_data.get('filter_label')
        if filter_label:
            # Get extensions for this category from config
            extensions = get_extensions_by_category(category_name)
            if extensions:  # Only add if category has extensions
                # Build dynamic label with actual extensions (max 5 shown, then "...")
                category_display_name = category_data.get('name', category_name)
                ext_preview = '/'.join(sorted(extensions)[:5])
                if len(extensions) > 5:
                    ext_preview += f"/... ({len(extensions)} total)"
                dynamic_label = f"{category_display_name} ({ext_preview})"
                
                groups.append((dynamic_label, extensions))
    
    return groups


def get_simple_filter_types():
    """Get file types for simple filter panel (extension, label) from config"""
    config = ensure_file_formats_config()
    extensions_dict = config.get('extensions', {})
    
    types = []
    for ext, ext_config in sorted(extensions_dict.items()):
        # Only include enabled extensions that should show in filters
        if ext_config.get('enabled', True) and ext_config.get('show_in_filters', True):
            # Create short label from extension (e.g., ".ma" -> "MA")
            label = ext[1:].upper()
            types.append((ext, label))
    
    return types


def get_extensions_by_category(category_name):
    """
    Get extensions for a specific category from config file.
    
    Args:
        category_name: Category key (e.g., 'images', 'scripts', 'maya')
    
    Returns:
        List of extensions for that category, or empty list if not found
    
    Example:
        >>> get_extensions_by_category('images')
        ['.tif', '.tiff', '.jpg', '.jpeg', '.png', '.hdr', '.exr', '.tga', '.psd']
    """
    config = ensure_file_formats_config()
    extensions = []
    
    # Get from config
    for ext, ext_config in config.get('extensions', {}).items():
        if ext_config.get('category') == category_name and ext_config.get('enabled', True):
            extensions.append(ext)
    
    # Fallback to FILE_TYPE_REGISTRY if config is empty
    if not extensions and category_name in FILE_TYPE_REGISTRY:
        return FILE_TYPE_REGISTRY[category_name]['extensions']
    
    return extensions


# ============================================================================
# METADATA DATABASE PATH
# ============================================================================

def get_metadata_db_path():
    """
    Get path to metadata SQLite database.
    Stored in user home directory: ~/.ddContentBrowser/tags.db
    
    Returns:
        Path: Path to tags.db file
    """
    from pathlib import Path
    
    db_dir = Path.home() / ".ddContentBrowser"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "tags.db"


def get_browser_data_dir():
    """
    Get path to browser data directory.
    Used for cache, database, and other user-specific data.
    
    Returns:
        Path: Path to ~/.ddContentBrowser/ directory
    """
    from pathlib import Path
    
    data_dir = Path.home() / ".ddContentBrowser"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


# ============================================================================
# FILE FORMATS CONFIG - JSON-based configuration system
# ============================================================================

# Cache for loaded config (avoid repeated file reads)
_file_formats_config_cache = None


def get_file_formats_config_path():
    """Get path to file_formats.json"""
    return get_browser_data_dir() / "file_formats.json"


def get_default_icon_colors(extension):
    """
    Get default icon colors for an extension.
    Returns tuple of (primary_rgb_list, secondary_rgb_list)
    """
    # Default color schemes - migrated from cache.py
    color_schemes = {
        '.ma': ([70, 130, 220], [100, 170, 255]),   # Blue gradient
        '.mb': ([50, 100, 180], [80, 140, 220]),    # Dark blue gradient
        '.obj': ([150, 80, 150], [200, 130, 200]),  # Purple gradient
        '.fbx': ([200, 180, 60], [255, 220, 100]),  # Yellow gradient
        '.abc': ([80, 150, 80], [120, 200, 120]),   # Green gradient
        '.usd': ([200, 80, 80], [255, 120, 120]),   # Red gradient
        '.hda': ([180, 100, 60], [220, 140, 100]),  # Orange-brown (Houdini)
        '.blend': ([50, 120, 200], [80, 160, 240]), # Blue gradient (Blender)
        '.sbsar': ([220, 120, 40], [255, 160, 80]), # Orange gradient (Substance)
        '.dae': ([150, 80, 150], [200, 130, 200]),  # Purple gradient
        '.stl': ([150, 80, 150], [200, 130, 200]),  # Purple gradient
        '.vdb': ([80, 150, 80], [120, 200, 120]),   # Green gradient
        # Image formats (lighter, image-like colors)
        '.tif': ([100, 180, 220], [140, 210, 255]),  # Light blue (TIFF)
        '.tiff': ([100, 180, 220], [140, 210, 255]), # Light blue (TIFF)
        '.jpg': ([220, 180, 100], [255, 210, 140]),  # Light orange (JPEG)
        '.jpeg': ([220, 180, 100], [255, 210, 140]), # Light orange (JPEG)
        '.png': ([180, 220, 180], [210, 255, 210]),  # Light green (PNG)
        '.hdr': ([255, 200, 100], [255, 230, 150]),  # Golden (HDR)
        '.exr': ([220, 140, 220], [255, 180, 255]),  # Light magenta (EXR)
        '.tga': ([180, 180, 220], [210, 210, 255]),  # Light purple (TGA)
        '.psd': ([49, 168, 255], [89, 198, 255]),    # Photoshop blue
        '.tx': ([180, 100, 220], [210, 140, 255]),   # Purple-magenta (RenderMan)
        '.gif': ([100, 220, 180], [140, 255, 210]),  # Cyan-green (animated)
        # PDF files
        '.pdf': ([200, 50, 50], [255, 100, 100]),    # Red gradient (Adobe PDF)
        # Script/text files
        '.py': ([60, 120, 180], [100, 160, 220]),    # Python blue
        '.mel': ([70, 160, 100], [100, 200, 140]),   # Maya green (Maya native)
        '.txt': ([160, 160, 160], [200, 200, 200]),  # Gray (plain text)
        # Video files
        '.mp4': ([200, 80, 120], [255, 120, 160]),   # Pink-red gradient (video)
        '.mov': ([180, 100, 200], [220, 140, 240]),  # Purple gradient (QuickTime)
        '.avi': ([80, 120, 200], [120, 160, 240]),   # Blue gradient (AVI)
        '.mkv': ([100, 200, 120], [140, 240, 160]),  # Green gradient (Matroska)
        '.webm': ([220, 140, 80], [255, 180, 120]),  # Orange gradient (WebM)
        '.m4v': ([200, 80, 120], [255, 120, 160]),   # Pink-red (like MP4)
        '.flv': ([200, 120, 80], [240, 160, 120]),   # Orange-brown (Flash)
        '.wmv': ([100, 140, 200], [140, 180, 240]),  # Light blue (Windows Media)
    }
    
    return color_schemes.get(extension, ([100, 100, 100], [150, 150, 150]))


# Extension -> Maya import type string. Single source of truth, also used by
# the Settings -> File Formats editor to build its "Maya Import Type" dropdown
# (so the two never drift apart again).
MAYA_IMPORT_TYPES = {
    '.ma': 'mayaAscii',
    '.mb': 'mayaBinary',
    '.obj': 'OBJ',
    '.fbx': 'FBX',
    '.abc': 'Alembic',
    '.usd': 'USD Import',
    '.dae': 'DAE_FBX',
    '.stl': 'STL'
}


def get_default_maya_import_type(extension):
    """Get default Maya import type for extension"""
    return MAYA_IMPORT_TYPES.get(extension, None)


def get_default_thumbnail_method(extension):
    """Get default thumbnail generation method for extension"""
    if extension in ['.jpg', '.jpeg', '.png']:
        return 'qimage_optimized'
    elif extension in ['.tif', '.tiff']:
        return 'opencv_optimized'
    elif extension in ['.hdr', '.tga']:
        return 'opencv'
    elif extension == '.exr':
        return 'openexr'
    elif extension == '.pdf':
        return 'pymupdf'
    elif extension == '.psd':
        return 'opencv'  # Falls back to psd-tools automatically
    elif extension == '.tx':
        return 'openimageio'
    elif extension == '.gif':
        return 'qimage_optimized'
    elif extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.flv', '.wmv']:
        return 'video'
    else:
        return 'none'


def generate_default_file_formats_config():
    """
    Generate default file_formats.json from FILE_TYPE_REGISTRY.
    This provides backwards compatibility - creates config on first run.
    """
    config = {
        "version": "1.0",
        "extensions": {},
        "categories": {}
    }
    
    # Build categories
    for category_key, category_data in FILE_TYPE_REGISTRY.items():
        config["categories"][category_key] = {
            "name": category_data["label"],
            "filter_label": category_data["filter_label"],
            "is_3d": category_data.get("is_3d", False),
            "importable": category_data.get("importable", False)
        }
        
        # Build extensions
        for ext in category_data["extensions"]:
            colors = get_default_icon_colors(ext)
            thumbnail_method = get_default_thumbnail_method(ext)
            maya_import_type = get_default_maya_import_type(ext)
            
            config["extensions"][ext] = {
                "category": category_key,
                "enabled": True,
                "show_in_filters": True,
                "icon_color_primary": colors[0],
                "icon_color_secondary": colors[1],
                "thumbnail": {
                    "generate": category_data["generate_thumbnail"],
                    "method": thumbnail_method,
                    "max_size_mb": 50 if thumbnail_method == "qimage_optimized" else None
                },
                "maya_import_type": maya_import_type
            }
    
    return config


def load_file_formats_config():
    """Load file_formats.json with error handling"""
    import json
    
    config_path = get_file_formats_config_path()
    try:
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[File Formats] Error loading config: {e}")
    
    # Fallback to default
    return generate_default_file_formats_config()


def save_file_formats_config(config):
    """Save file_formats.json"""
    import json
    
    # Auto-create missing categories referenced in extensions
    if 'extensions' in config and 'categories' in config:
        # Collect all categories used by extensions
        used_categories = set()
        for ext_config in config['extensions'].values():
            category = ext_config.get('category')
            if category:
                used_categories.add(category)
        
        # Ensure all used categories exist in categories section
        for category in used_categories:
            if category not in config['categories']:
                # Auto-create missing category from FILE_TYPE_REGISTRY
                if category in FILE_TYPE_REGISTRY:
                    registry_cat = FILE_TYPE_REGISTRY[category]
                    config['categories'][category] = {
                        "name": registry_cat.get("label", category.title()),
                        "filter_label": registry_cat.get("filter_label", category.title()),
                        "is_3d": registry_cat.get("is_3d", False)
                    }
                    print(f"[File Formats] Auto-created missing category: {category}")
    
    config_path = get_file_formats_config_path()
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"[File Formats] Config saved to {config_path}")
        
        # Invalidate cache
        global _file_formats_config_cache
        _file_formats_config_cache = None
        
        return True
    except Exception as e:
        print(f"[File Formats] Error saving config: {e}")
        return False


def merge_registry_updates(user_config):
    """
    Merge & UPDATE formats from FILE_TYPE_REGISTRY into user config.
    
    Strategy:
    1. STANDARD extension (exists in registry) → OVERRIDE with default (fresh config!)
    2. CUSTOM extension (user-only) → PRESERVE (user added it)
    3. NEW category → add
    
    This ensures all standard formats always use the latest configuration!
    """
    default_config = generate_default_file_formats_config()
    
    # Ensure extensions and categories dicts exist
    if "extensions" not in user_config:
        user_config["extensions"] = {}
    if "categories" not in user_config:
        user_config["categories"] = {}
    
    # Merge categories - add new categories
    for cat_key, cat_data in default_config["categories"].items():
        if cat_key not in user_config["categories"]:
            user_config["categories"][cat_key] = cat_data
            print(f"  + Added category: {cat_key}")
    
    # Merge extensions
    updated_count = 0
    added_count = 0
    custom_count = 0
    
    # 1. Update/Add all standard extensions from registry
    for ext, ext_config in default_config["extensions"].items():
        if ext in user_config["extensions"]:
            # OVERRIDE - registry version is always newer
            user_config["extensions"][ext] = ext_config
            print(f"  ↻ Updated standard extension: {ext}")
            updated_count += 1
        else:
            # New extension
            user_config["extensions"][ext] = ext_config
            print(f"  + Added extension: {ext}")
            added_count += 1
    
    # 2. Count custom extensions (user added, not in registry)
    for ext in list(user_config["extensions"].keys()):
        if ext not in default_config["extensions"]:
            custom_count += 1
            print(f"  ✓ Preserved custom extension: {ext}")
    
    print(f"[File Formats] Updated {updated_count}, Added {added_count}, Preserved {custom_count} custom")
    return user_config


def ensure_file_formats_config():
    """
    Ensure file_formats.json exists and return loaded config.
    Auto-generates from FILE_TYPE_REGISTRY on first run.
    Auto-merges new formats when registry version changes.
    Uses cache to avoid repeated file reads.
    """
    global _file_formats_config_cache
    
    # Return cached config if available
    if _file_formats_config_cache is not None:
        return _file_formats_config_cache
    
    config_path = get_file_formats_config_path()
    
    if not config_path.exists():
        # First run or upgrade - generate default
        print("[File Formats] No config found, generating default...")
        config = generate_default_file_formats_config()
        config["registry_version"] = FILE_TYPE_REGISTRY_VERSION
        save_file_formats_config(config)
    else:
        # Load existing config
        config = load_file_formats_config()
        
        # Check if registry was updated - merge new formats
        if config.get("registry_version") != FILE_TYPE_REGISTRY_VERSION:
            print(f"[File Formats] Registry updated ({config.get('registry_version', '0.0')} → {FILE_TYPE_REGISTRY_VERSION}), merging changes...")
            config = merge_registry_updates(config)
            config["registry_version"] = FILE_TYPE_REGISTRY_VERSION
            save_file_formats_config(config)
    
    # Cache it
    _file_formats_config_cache = config
    return config


def reload_file_formats_config():
    """Force reload of file formats config (clears cache)"""
    global _file_formats_config_cache
    _file_formats_config_cache = None
    return ensure_file_formats_config()


# ============================================================================
# FILE FORMATS CONFIG - Helper functions
# ============================================================================

def get_extension_config(extension):
    """
    Get full config for an extension with fallback.
    
    Returns:
        dict: Extension config with all fields
    """
    extension = extension.lower()
    config = ensure_file_formats_config()
    
    # Try to get from config
    if extension in config.get("extensions", {}):
        return config["extensions"][extension]
    
    # Fallback: generate from registry
    category = get_extension_category(extension)
    if category and category in FILE_TYPE_REGISTRY:
        category_data = FILE_TYPE_REGISTRY[category]
        colors = get_default_icon_colors(extension)
        thumbnail_method = get_default_thumbnail_method(extension)
        maya_import_type = get_default_maya_import_type(extension)
        
        return {
            "category": category,
            "enabled": True,
            "show_in_filters": True,
            "icon_color_primary": colors[0],
            "icon_color_secondary": colors[1],
            "thumbnail": {
                "generate": category_data["generate_thumbnail"],
                "method": thumbnail_method,
                "max_size_mb": 50 if thumbnail_method == "qimage_optimized" else None
            },
            "maya_import_type": maya_import_type
        }
    
    # Final fallback: unknown extensions are shown by default (opt-out model),
    # except for known filesystem/editor noise (see DEFAULT_DISABLED_EXTENSIONS).
    return {
        "category": "unknown",
        "enabled": extension not in DEFAULT_DISABLED_EXTENSIONS,
        "show_in_filters": True,
        "icon_color_primary": [100, 100, 100],
        "icon_color_secondary": [150, 150, 150],
        "thumbnail": {
            "generate": False,
            "method": "none",
            "max_size_mb": None
        },
        "maya_import_type": None
    }


def get_icon_colors(extension):
    """
    Get icon colors for extension.
    
    Returns:
        tuple: (primary_rgb_list, secondary_rgb_list)
    """
    ext_config = get_extension_config(extension)
    return (
        ext_config.get("icon_color_primary", [100, 100, 100]),
        ext_config.get("icon_color_secondary", [150, 150, 150])
    )


def get_thumbnail_method(extension):
    """
    Get thumbnail generation method for extension.
    
    Returns:
        str: 'none', 'qimage', 'qimage_optimized', 'opencv', 'opencv_optimized', 'openexr', 'pymupdf'
    """
    ext_config = get_extension_config(extension)
    thumbnail_config = ext_config.get("thumbnail", {})
    
    if not thumbnail_config.get("generate", False):
        return "none"
    
    return thumbnail_config.get("method", "none")


def get_maya_import_type(extension):
    """
    Get Maya import type string for extension.
    
    Returns:
        str or None: Maya import type ('OBJ', 'FBX', etc.) or None
    """
    ext_config = get_extension_config(extension)
    return ext_config.get("maya_import_type", None)


def get_extensions_for_thumbnail_method(method):
    """
    Get all extensions that use a specific thumbnail method.
    
    Args:
        method: Thumbnail method ('qimage_optimized', 'opencv', etc.)
    
    Returns:
        list: List of extensions
    """
    config = ensure_file_formats_config()
    extensions = []
    
    for ext, ext_config in config.get("extensions", {}).items():
        thumbnail_config = ext_config.get("thumbnail", {})
        if thumbnail_config.get("method") == method:
            extensions.append(ext)
    
    return extensions


# ============================================================================
# IMAGE SEQUENCE DETECTION
# ============================================================================

import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def detect_sequence_pattern(filename):
    """
    Detect if a filename contains a frame number pattern.
    
    Supported patterns:
    - Underscore separator: render_0001.jpg, shot_####.exr
    - Dot separator: render.0001.jpg, shot.####.exr
    - Printf style: render%04d.jpg
    - Mixed: shot_v001_0001.jpg (version + frame)
    
    Returns:
        tuple: (base_name, frame_number, padding, separator) or None if no pattern
        
    Examples:
        'render_0001.jpg' -> ('render', 1, 4, '_')
        'shot.0123.exr' -> ('shot', 123, 4, '.')
        'anim####.png' -> ('anim', None, 4, '')
        'frame%04d.tif' -> ('frame', None, 4, '%')
    """
    stem = Path(filename).stem
    
    # Pattern 1: name_0001 or name.0001 (most common)
    match = re.match(r'^(.+?)[_.](\d+)$', stem)
    if match:
        base_name = match.group(1)
        frame_str = match.group(2)
        separator = stem[len(base_name)]  # Get actual separator
        return (base_name, int(frame_str), len(frame_str), separator)
    
    # Pattern 2: name#### (hash padding)
    match = re.match(r'^(.+?)(#+)$', stem)
    if match:
        base_name = match.group(1).rstrip('_.')  # Remove trailing separator if any
        padding = len(match.group(2))
        return (base_name, None, padding, '#')
    
    # Pattern 3: name%04d (printf style)
    match = re.match(r'^(.+?)%0?(\d+)d$', stem)
    if match:
        base_name = match.group(1).rstrip('_.')
        padding = int(match.group(2)) if match.group(2) else 1
        return (base_name, None, padding, '%')
    
    return None


def group_image_sequences(file_paths: List[Path]) -> Dict[str, List[Path]]:
    """
    Group image files into sequences.
    
    Args:
        file_paths: List of Path objects (images only)
        
    Returns:
        Dict with keys as sequence patterns and values as sorted file lists
        
    Example:
        Input: [render_0001.jpg, render_0002.jpg, other.png]
        Output: {
            'render_####.jpg': [render_0001.jpg, render_0002.jpg],
            'other.png': [other.png]  # Single file
        }
    """
    sequences = {}
    single_files = {}
    
    for path in file_paths:
        pattern_info = detect_sequence_pattern(path.name)
        
        if pattern_info:
            base_name, frame_num, padding, separator = pattern_info
            ext = path.suffix
            
            # Create sequence key
            if separator == '#':
                # Already has hash padding
                seq_key = f"{base_name}{'#' * padding}{ext}"
            elif separator == '%':
                # Printf style
                seq_key = f"{base_name}%0{padding}d{ext}"
            else:
                # Underscore or dot separator with numeric padding
                seq_key = f"{base_name}{separator}{'#' * padding}{ext}"
            
            if seq_key not in sequences:
                sequences[seq_key] = []
            sequences[seq_key].append(path)
        else:
            # Not a sequence - treat as single file
            single_files[path.name] = [path]
    
    # Sort each sequence by frame number
    for seq_key, files in sequences.items():
        sequences[seq_key] = sorted(files, key=lambda p: extract_frame_number(p.name))
    
    # Filter out single-file "sequences" - move them to single_files
    actual_sequences = {}
    for seq_key, files in sequences.items():
        if len(files) > 1:
            actual_sequences[seq_key] = files
        else:
            # Only one file - not really a sequence
            single_files[files[0].name] = files
    
    # Merge sequences and single files
    return {**actual_sequences, **single_files}


def extract_frame_number(filename: str) -> int:
    """
    Extract frame number from a filename.
    Returns 0 if no frame number found.
    """
    pattern_info = detect_sequence_pattern(filename)
    if pattern_info and pattern_info[1] is not None:
        return pattern_info[1]
    return 0


def get_sequence_frame_range(file_paths: List[Path]) -> Tuple[int, int, List[int]]:
    """
    Get frame range from a list of sequence files.
    
    Returns:
        tuple: (first_frame, last_frame, missing_frames)
        
    Example:
        [render_0001.jpg, render_0003.jpg] -> (1, 3, [2])
    """
    if not file_paths:
        return (0, 0, [])
    
    frame_numbers = []
    for path in file_paths:
        pattern_info = detect_sequence_pattern(path.name)
        if pattern_info and pattern_info[1] is not None:
            frame_numbers.append(pattern_info[1])
    
    if not frame_numbers:
        return (0, 0, [])
    
    frame_numbers.sort()
    first_frame = frame_numbers[0]
    last_frame = frame_numbers[-1]
    
    # Find missing frames
    expected_frames = set(range(first_frame, last_frame + 1))
    actual_frames = set(frame_numbers)
    missing_frames = sorted(expected_frames - actual_frames)
    
    return (first_frame, last_frame, missing_frames)


def format_sequence_pattern(base_name: str, padding: int, separator: str, extension: str) -> str:
    """
    Format a sequence pattern string.
    
    Examples:
        ('render', 4, '_', '.jpg') -> 'render_####.jpg'
        ('shot', 4, '.', '.exr') -> 'shot.####.exr'
    """
    if separator == '#':
        return f"{base_name}{'#' * padding}{extension}"
    elif separator == '%':
        return f"{base_name}%0{padding}d{extension}"
    else:
        return f"{base_name}{separator}{'#' * padding}{extension}"


# ============================================================
# Texture Set detection (PBR channels grouped by shared base name)
# ============================================================

# Canonical channel -> filename suffix aliases. Kept aligned with
# smart_imports/ddShaderNetworkGenerator.json so grouping and shader
# building agree on which suffix maps to which material channel.
TEXTURE_CHANNEL_ALIASES = {
    "baseColor":    ["basecolor", "base_color", "albedo", "diffuse", "diffuse_color", "diff", "color", "col", "clr"],
    "roughness":    ["roughness", "rough", "glossiness", "gloss", "rgh"],
    "metalness":    ["metalness", "metallic", "metal", "met"],
    "normal":       ["normal", "normalmap", "normal_gl", "normal_dx", "normalgl", "normaldx",
                      "nor_gl", "nor_dx", "norgl", "nordx", "nrm", "nor", "norm", "n"],
    # High-poly-only normal variant (baked bump-into-normal for the "High" LOD).
    # Two unrelated naming conventions map to the same channel: the compound
    # "NormalBump"/"BumpNormal", and a plain "Normal" with an "_HF" (High
    # Frequency) suffix - both are used the same way, only for High geo.
    "normalHigh":   ["normalbump", "bumpnormal", "normal_hf", "normalhf"],
    "bump":         ["bump", "bumpmap"],
    "height":       ["height", "heightmap", "bumpheight", "heightpn"],
    "displacement": ["displacement", "disp", "displ", "displace"],
    "emission":     ["emission", "emissive", "emit"],
    "opacity":      ["opacity", "alpha", "cutout", "cutoutopacity", "mask", "geometrymask", "geometry_mask"],
    "transmission": ["transmission", "refraction", "refract"],
    # Diffuse/subsurface-style transmission (e.g. leaves, paper) - distinct
    # from "transmission" above, which is specular/refractive (glass-like,
    # IOR-based). Not the same shader input, so not merged into that channel.
    "translucency": ["translucency", "translucent"],
    "ao":           ["ao", "ambientocclusion", "ambient_occlusion", "occlusion", "occ"],
    "cavity":       ["cavity"],
    "specular":     ["specular", "spec"],
}

# Channels that are recognized/grouped for organization but are never wired
# into a shader network by the material builder (not valid PBR inputs for an
# Albedo/Metalness/Roughness workflow, and not needed for Arnold renders).
TEXTURE_CHANNELS_NEVER_WIRED = {"ao", "cavity", "specular"}

# Real image extensions that can appear as a "fake" embedded extension in a
# .tx filename (RenderMan's txmake often keeps the source format before the
# real .tx, e.g. "Albedo_sRGB_ACEScg.jpg.tx"). Used only for .tx parsing.
_TX_SOURCE_FORMAT_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.exr', '.hdr', '.tga', '.psd', '.gif',
}


def _build_texture_alias_lookup():
    """Flatten aliases into (alias, channel) pairs sorted by alias length desc."""
    pairs = []
    for channel, aliases in TEXTURE_CHANNEL_ALIASES.items():
        for alias in aliases:
            pairs.append((alias.lower(), channel))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


_TEXTURE_ALIAS_LOOKUP = _build_texture_alias_lookup()


def _match_channel_suffix(s):
    """Match the longest known channel alias as a trailing token of s.
    Returns (base, channel, alias), or (None, None, None) if nothing matches."""
    low = s.lower()
    for alias, channel in _TEXTURE_ALIAS_LOOKUP:
        for sep in ('_', '-', '.'):
            token = sep + alias
            if low.endswith(token):
                base = s[:len(s) - len(token)]
                if base:
                    return base, channel, alias
    return None, None, None


_LOD_REGEX = re.compile(r'[._-]lod(\d+)$', re.IGNORECASE)


def _strip_trailing_lod(s):
    """Strip a trailing _LODn tag. Returns (remaining, lod) - lod is 'LODn', or None if absent."""
    m = _LOD_REGEX.search(s)
    if m:
        return s[:m.start()], f"LOD{m.group(1)}"
    return s, None


def parse_texture_filename(stem: str, extension: str = None):
    """
    Parse a texture filename stem into (set_base, channel, udim, lod, alias).

    Strips a trailing UDIM (1xxx) token, then a trailing LOD tag (e.g.
    "_LOD0", "_LOD5" - a mesh-resolution-specific override, common in
    Megascans-style libraries where most channels are shared across LODs but
    e.g. normal maps have per-LOD variants), then matches the longest channel
    alias as a trailing token separated by _ . or -.

    The LOD tag can sit in either of two positions, both handled here:
        base_channel_LODn   (Megascans style, e.g. "Wall_Normal_LOD0")
        base_LODn_channel   (textures.com style, e.g. "..._LOD0_height")
    The first is caught by the trailing-LOD strip below (before channel
    matching); the second only becomes visible after the channel suffix is
    removed, so it's re-checked on the leftover base.

    A trailing resolution tag (e.g. "_4k", common on textures.com/Poliigon
    exports: "Lantern_01_brass_diff_4k") sits after the channel suffix, so
    it's stripped before channel matching too - but re-attached to the
    returned base afterwards, since find_texture_set_for_geo() relies on
    the set's display name still carrying it to prefer a 4K set over a 2K
    one for the same asset.

    .tx files (pass extension='.tx') can use one of two naming styles:
        Albedo.tx                    - plain
        Albedo_sRGB_ACEScg.jpg.tx    - annotated: colorspace tokens + the
                                        "fake" source format before the real
                                        .tx extension
    Both resolve to the same (base, channel). The fake source-format
    extension is stripped first, then up to 2 trailing "_token" segments are
    stripped one at a time (retrying the channel match after each) - this
    doesn't hardcode actual colorspace names (sRGB, ACEScg, Raw, ...) since
    those vary widely across pipelines; it just tries "channel name plus 0,
    1, or 2 extra tokens after it".

    Returns:
        (set_base, channel_key, udim, lod, alias) if a channel suffix was
        found, otherwise (stem, None, None, None, None). lod is a string
        like "LOD0", or None if the filename has no LOD tag. alias is the
        specific matched suffix (e.g. "heightpn" vs "height") - some
        channels have multiple aliases that aren't interchangeable quality-
        wise (see _ALIAS_PRIORITY_OVERRIDES), so the caller needs to know
        exactly which one matched, not just the resolved channel.
    """
    s = stem
    udim = None
    m = re.search(r'[._-](1\d{3})$', s)
    if m:
        udim = m.group(1)
        s = s[:m.start()]

    s, lod = _strip_trailing_lod(s)
    s, res_tag = _strip_resolution_tag(s)

    if extension and extension.lower() == '.tx':
        fake_ext = Path(s).suffix.lower()
        if fake_ext in _TX_SOURCE_FORMAT_EXTENSIONS:
            s = s[:-len(fake_ext)]

        for attempt in range(3):  # 0, 1, then 2 trailing tokens stripped
            base, channel, alias = _match_channel_suffix(s)
            if channel:
                if lod is None:
                    base, lod = _strip_trailing_lod(base)
                if res_tag:
                    base = f"{base}_{res_tag}"
                return base, channel, udim, lod, alias
            if attempt == 2 or '_' not in s:
                break
            s = s.rsplit('_', 1)[0]
        return stem, None, None, None, None

    base, channel, alias = _match_channel_suffix(s)
    if channel:
        if lod is None:
            base, lod = _strip_trailing_lod(base)
        if res_tag:
            base = f"{base}_{res_tag}"
        return base, channel, udim, lod, alias
    return stem, None, None, None, None


# When the same (base name, channel, UDIM) exists in more than one file format
# (e.g. Wall_baseColor.png AND Wall_baseColor.exr), only the highest-priority
# extension is kept as part of the set; the rest are demoted to loose files.
# Lower index = higher priority. .psd isn't typically wired directly into a
# shader network, and .gif isn't a production texture format, so both sink to
# the bottom; unrecognized extensions rank even lower than those. .tx is not
# in this list - it never competes here, see group_texture_sets() below.
_TEXTURE_EXTENSION_PRIORITY = [
    '.exr', '.hdr', '.tif', '.tiff', '.png', '.jpg', '.jpeg', '.tga', '.psd', '.gif',
]


def _texture_extension_rank(path: Path) -> int:
    """Lower = higher priority. Extensions outside the known list rank last."""
    try:
        return _TEXTURE_EXTENSION_PRIORITY.index(path.suffix.lower())
    except ValueError:
        return len(_TEXTURE_EXTENSION_PRIORITY)


# Some channels have multiple aliases that resolve to the same channel key
# but aren't equally good - e.g. a "_heightPN" export should win the channel
# slot over a plain "_height" of the same UDIM/LOD, not just be a same-
# quality alternate spelling. Lower = higher priority; an alias not listed
# here (or a channel not listed at all) ranks 1 (same as the average case),
# so this only kicks in for channels that actually need it.
_ALIAS_PRIORITY_OVERRIDES = {
    "height": {"heightpn": 0},
}


def _alias_rank(channel, alias):
    return _ALIAS_PRIORITY_OVERRIDES.get(channel, {}).get(alias, 1)


def _group_texture_sets_single_pass(file_paths: List[Path]):
    """
    Core grouping pass, run separately per extension partition (see
    group_texture_sets). Groups files sharing a base name into sets covering
    >= 2 distinct (channel, UDIM, LOD) variants - e.g. baseColor+roughness,
    a single channel split across >= 2 UDIM tiles, or a channel with
    per-LOD overrides (e.g. Normal_LOD0 + Normal_LOD5). Files that share
    base name, channel, UDIM AND LOD (e.g. the same map exported as both
    .png and .exr, or a plain vs. "PN" height export) describe the same
    variant, not two: only the higher-priority one (alias priority first,
    see _ALIAS_PRIORITY_OVERRIDES, then file format, see
    _TEXTURE_EXTENSION_PRIORITY) is kept in the set, the other is demoted to
    a loose file - this is the whole point of the texture set view: an
    active set member is never also shown standalone, only the demoted
    loser is.
    """
    sets = {}
    singles = []

    for path in file_paths:
        base, channel, udim, lod, alias = parse_texture_filename(path.stem, path.suffix)
        if channel is None:
            singles.append(path)
            continue
        key = base.lower()
        if key not in sets:
            sets[key] = {'display': base, 'variants': {}, 'extra_formats': []}

        variant_key = (channel, udim, lod)
        variants = sets[key]['variants']
        existing = variants.get(variant_key)
        if existing is None:
            variants[variant_key] = (path, alias)
        else:
            existing_path, existing_alias = existing
            new_rank = (_alias_rank(channel, alias), _texture_extension_rank(path))
            existing_rank = (_alias_rank(channel, existing_alias), _texture_extension_rank(existing_path))
            if new_rank < existing_rank:
                # New file outranks the one we already picked - swap in,
                # demote the previous winner to a loose file, but remember it
                # belonged to this set (surfaced as a "+N" badge indicator).
                variants[variant_key] = (path, alias)
                sets[key]['extra_formats'].append(existing_path)
            else:
                sets[key]['extra_formats'].append(path)

    result_sets = {}
    for key, data in sets.items():
        variants = data['variants']
        # A real set needs >= 2 distinct (channel, UDIM, LOD) variants.
        if len(variants) >= 2:
            channels = {}
            files = []
            for (channel, _udim, _lod), (path, _alias) in variants.items():
                channels.setdefault(channel, []).append(path)
                files.append(path)
            result_sets[data['display']] = {
                'display': data['display'],
                'channels': channels,
                'files': files,
                'extra_formats': data['extra_formats'],
                # Raw (channel, UDIM, LOD) -> file lookup, for consumers that
                # need to pick a specific LOD/UDIM variant (e.g. a future
                # geo-import material builder). Not used by grouping/display
                # yet, kept here so that info isn't thrown away.
                'variant_map': {k: v[0] for k, v in variants.items()},
            }
            # extra_formats belong to this set (tracked for the "+N" badge/
            # tooltip) but must NOT also appear as standalone tiles - once a
            # file is part of a set, winner or demoted duplicate, it's never
            # shown separately. That's the whole point of the texture set view.
        else:
            singles.extend(path for path, _alias in variants.values())
            singles.extend(data['extra_formats'])

    return result_sets, singles


def _is_annotated_tx(path: Path) -> bool:
    """
    True if a .tx filename carries a "fake" source-format extension before
    the real .tx (e.g. "Albedo_sRGB_ACEScg.jpg.tx") - RenderMan txmake's
    colorspace-tagged naming style, as opposed to a plain "Albedo.tx" export.
    """
    return Path(path.stem).suffix.lower() in _TX_SOURCE_FORMAT_EXTENSIONS


def _merge_set_group(result_sets: dict, group_sets: dict, label: str):
    """Merge group_sets into result_sets, renaming on name collision using `label`."""
    for display_name, data in group_sets.items():
        name = display_name
        if name in result_sets:
            name = f"{display_name} ({label})"
            n = 2
            while name in result_sets:
                name = f"{display_name} ({label} {n})"
                n += 1
        data['display'] = name
        result_sets[name] = data


def group_texture_sets(file_paths: List[Path], group_tx_sets: bool = True):
    """
    Group texture files into texture sets by shared base name.

    Files are first split into three independent pools, each grouped on its
    own (never mixed/deduped across pools even if they'd share a base name):
      1. Non-.tx "source" files.
      2. Plain .tx exports (e.g. "Albedo.tx") - pre-baked, render-ready
         textures, a distinct build output from the source files.
      3. Colorspace-tagged .tx exports (e.g. "Albedo_sRGB_ACEScg.jpg.tx") -
         a separate .tx export batch from #2, identified by the "fake"
         source-format extension embedded before the real .tx. Even though a
         plain and a tagged .tx can resolve to the same (channel, UDIM), they
         come from different export batches and must stay separate sets, not
         collapse into one set with a "+1 alternate format".

    Args:
        file_paths: List of Path objects (images only)
        group_tx_sets: if False, pools 2 and 3 are skipped entirely - .tx
            files are never grouped into their own texture set (they're just
            loose files), regardless of how many would otherwise match. Not
            every workflow wants .tx-only sets listed; see the "Group
            TX-only texture sets" option in Texture Set Settings.

    Returns:
        (sets, singles) where:
            sets: dict[str set_base] -> {
                'display': str,
                'channels': dict[channel_key] -> list[Path],
                'files': list[Path],
                'extra_formats': list[Path]  # demoted same-variant duplicates, badge/tooltip only - never standalone tiles
            }
            singles: list[Path] that did not belong to any set
    """
    other_files = [p for p in file_paths if p.suffix.lower() != '.tx']
    other_sets, other_singles = _group_texture_sets_single_pass(other_files)

    if not group_tx_sets:
        tx_files = [p for p in file_paths if p.suffix.lower() == '.tx']
        return other_sets, other_singles + tx_files

    tx_plain_files = [p for p in file_paths if p.suffix.lower() == '.tx' and not _is_annotated_tx(p)]
    tx_annotated_files = [p for p in file_paths if p.suffix.lower() == '.tx' and _is_annotated_tx(p)]

    tx_plain_sets, tx_plain_singles = _group_texture_sets_single_pass(tx_plain_files)
    tx_annotated_sets, tx_annotated_singles = _group_texture_sets_single_pass(tx_annotated_files)

    result_sets = dict(other_sets)
    _merge_set_group(result_sets, tx_plain_sets, "TX")
    _merge_set_group(result_sets, tx_annotated_sets, "TX Annotated")

    singles = other_singles + tx_plain_singles + tx_annotated_singles
    return result_sets, singles


# Raster formats that can be converted to TIF - EXR (already lossless/HDR-
# capable) and .tx (pre-baked render-ready) are intentionally excluded.
_TIF_CONVERTIBLE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tga'}


def _convert_single_to_tif(path: Path) -> Path:
    """
    Convert one texture to a sibling .tif (LZW) next to it, if needed.

    Written next to the source (not a cache folder) so the result becomes a
    genuine texture set member - the existing extension-priority grouping
    (see _group_texture_sets_single_pass) already prefers .tif over
    .jpg/.png/.tga, so it's picked up automatically on the next scan without
    any special-case logic.

    Returns the .tif path (existing or freshly converted), or the original
    path unchanged if conversion isn't applicable/fails.
    """
    if path.suffix.lower() not in _TIF_CONVERTIBLE_EXTENSIONS:
        return path

    tif_path = path.with_suffix('.tif')
    try:
        if tif_path.exists() and tif_path.stat().st_mtime >= path.stat().st_mtime:
            return tif_path  # already converted and up to date
    except OSError:
        pass

    try:
        from PIL import Image
        with Image.open(path) as img:
            img.load()
            img.save(str(tif_path), format='TIFF', compression='tiff_lzw')
        return tif_path
    except Exception as e:
        print(f"[TIFConvert] Failed to convert {path} to TIF: {e}")
        return path


def _convert_paths_to_tif(paths, progress_callback=None) -> dict:
    """Convert an iterable of Paths (skipping non-convertible ones) to .tif
    in parallel. Returns {original_path: result_path} for the ones actually
    attempted (empty dict if nothing in `paths` was convertible).

    progress_callback, if given, is called as progress_callback(done, total)
    after each file finishes - in actual completion order (as_completed),
    not submission order, so it reflects real progress under parallelism."""
    to_convert = [p for p in paths if p.suffix.lower() in _TIF_CONVERTIBLE_EXTENSIONS]
    if not to_convert:
        return {}
    from concurrent.futures import ThreadPoolExecutor, as_completed
    total = len(to_convert)
    results = {}
    with ThreadPoolExecutor(max_workers=min(8, total)) as executor:
        futures = {executor.submit(_convert_single_to_tif, p): p for p in to_convert}
        done = 0
        for future in as_completed(futures):
            path = futures[future]
            try:
                results[path] = future.result()
            except Exception as e:
                print(f"[TIFConvert] Failed to convert {path} to TIF: {e}")
                results[path] = path
            done += 1
            if progress_callback:
                progress_callback(done, total)
    return results


def convert_channel_paths_to_tif(channels: dict, progress_callback=None) -> dict:
    """
    Convert a texture set's non-EXR raster channel files (.jpg/.jpeg/.png/
    .tga) to sibling .tif (LZW), for pipelines that prefer TIF for its
    Photoshop layer support. UDIM tiles are each converted individually
    (channels[key] already lists every tile as a separate Path - see
    _group_texture_sets_single_pass), not just the first/representative one.

    Conversions run in parallel (PIL releases the GIL during image codec
    work, so threading gives a real speedup) and are skipped per-file if an
    up-to-date .tif sibling already exists, so repeat builds are effectively
    free. progress_callback(done, total), if given, is called after each
    file finishes.

    Args:
        channels: dict[channel_key] -> list[Path], as produced by
            group_texture_sets()/TextureSet.channels.

    Returns:
        A new dict with the same shape; convertible paths are swapped to
        their .tif counterparts, everything else passes through unchanged.
    """
    results = _convert_paths_to_tif((p for files in channels.values() for p in files), progress_callback)
    if not results:
        return channels
    return {channel: [results.get(p, p) for p in files] for channel, files in channels.items()}


def convert_variant_map_to_tif(variant_map: dict, progress_callback=None) -> dict:
    """
    Same conversion as convert_channel_paths_to_tif(), but for the flat
    (channel, UDIM, LOD) -> Path shape used by find_texture_set_for_geo()/
    resolve_texture_set_channels() - resolve_texture_set_channels() already
    collapses to one file per channel (discarding the other UDIM tiles), so
    conversion has to happen here, on the full variant_map, first.
    """
    results = _convert_paths_to_tif(variant_map.values(), progress_callback)
    if not results:
        return variant_map
    return {key: results.get(p, p) for key, p in variant_map.items()}


def convert_texture_sets_to_tif(channels_list, progress_callback=None):
    """
    Convert non-EXR raster textures across MULTIPLE texture sets in one
    combined pass, so progress_callback(done, total) reflects the whole
    batch (e.g. several sets dragged/dropped together) instead of resetting
    back to 0 for each set.

    Args:
        channels_list: list of dict[channel_key] -> list[Path], one per
            texture set (as produced by group_texture_sets()/TextureSet.channels).

    Returns:
        A new list of dicts, same shape/order as channels_list, with
        convertible paths swapped to their .tif counterparts.
    """
    all_paths = (p for channels in channels_list for files in channels.values() for p in files)
    results = _convert_paths_to_tif(all_paths, progress_callback)
    if not results:
        return channels_list
    return [
        {channel: [results.get(p, p) for p in files] for channel, files in channels.items()}
        for channels in channels_list
    ]


def channel_paths_from_channels(channels: dict) -> dict:
    """dict[channel]->list[Path] -> dict[channel]->str(first path). Mirrors
    TextureSet.channel_paths, for callers working with a converted (or
    otherwise transformed) channels dict rather than a live TextureSet."""
    return {channel: str(files[0]) for channel, files in channels.items() if files}


# Channel priority for choosing a texture set's representative (thumbnail) file.
_TEXTURE_SET_THUMBNAIL_PRIORITY = [
    "baseColor", "emission", "roughness", "metalness", "normal",
    "height", "displacement", "opacity", "transmission", "ao",
]


def get_texture_set_thumbnail_path(channels: dict):
    """Pick the representative file for a texture set (prefer baseColor)."""
    for channel in _TEXTURE_SET_THUMBNAIL_PRIORITY:
        files = channels.get(channel)
        if files:
            return files[0]
    # Fallback: any file
    for files in channels.values():
        if files:
            return files[0]
    return None


# ============================================================
# Folder preview thumbnails (a *preview.<ext> image inside a folder is
# shown as its thumbnail instead of the generic folder icon)
# ============================================================

# Sentinel distinguishing "not present in the batch cache lookup result"
# (never checked) from an actual cached value of None (checked, no preview).
_NOT_CACHED = object()


def find_folder_preview_file(folder_path) -> Optional[Path]:
    """
    Look for an image directly inside folder_path (non-recursive) whose
    filename (without extension) ends in "preview" - e.g. "AssetPreview.png"
    or "preview.jpg". Returns the first match, or None.
    """
    folder_path = Path(folder_path)
    try:
        for entry in os.scandir(folder_path):
            if not entry.is_file():
                continue
            p = Path(entry.path)
            if not p.stem.lower().endswith('preview'):
                continue
            if get_extension_category(p.suffix.lower()) == 'images':
                return p
    except OSError:
        pass
    return None


def resolve_folder_previews(folder_paths) -> dict:
    """
    Resolve which of the given folders have a *preview image inside them,
    using the metadata DB (folder_preview_cache table) so a folder already
    checked isn't re-scanned on every directory listing - only the first
    time it's seen, or after invalidate_folder_previews() clears it (F5,
    manual "regenerate thumbnail").

    Args:
        folder_paths: iterable of folder Path objects.

    Returns:
        dict[Path] -> Path: only folders that DO have a preview are present
        (absent, not None, for folders without one - use .get(folder)).
    """
    folder_paths = list(folder_paths)
    if not folder_paths:
        return {}

    try:
        from .metadata import get_metadata_manager
        mm = get_metadata_manager()
    except Exception:
        mm = None

    results = {}
    to_scan = folder_paths
    if mm is not None:
        # One batched lookup instead of one SELECT per folder - matters at
        # directory-listing scale (e.g. thousands of subfolders).
        cached = mm.get_folder_previews_batch(str(f) for f in folder_paths)
        to_scan = []
        for folder in folder_paths:
            cached_path = cached.get(str(folder), _NOT_CACHED)
            if cached_path is _NOT_CACHED:
                to_scan.append(folder)
            elif cached_path:
                results[folder] = Path(cached_path)

    if to_scan:
        # Independent, I/O-bound filesystem/network scans (only for folders
        # never checked before) - run in parallel instead of one at a time,
        # same reasoning as the TIF conversion's thread pool. Higher worker
        # count than that one since this is pure I/O wait (network latency),
        # not CPU-bound codec work.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(16, len(to_scan))) as executor:
            scanned = dict(zip(to_scan, executor.map(find_folder_preview_file, to_scan)))

        newly_checked = {}
        for folder, preview in scanned.items():
            newly_checked[str(folder)] = str(preview) if preview else None
            if preview:
                results[folder] = preview
        if mm is not None:
            mm.set_folder_previews_batch(newly_checked)

    return results


def invalidate_folder_previews(folder_paths):
    """Drop cached folder-preview entries so the next listing re-scans them
    (F5 / manual "regenerate thumbnail" on folders)."""
    try:
        from .metadata import get_metadata_manager
        get_metadata_manager().clear_folder_previews(str(p) for p in folder_paths)
    except Exception as e:
        print(f"[FolderPreview] Failed to invalidate cache: {e}")


# ============================================================
# Geo-import -> texture set matching (auto material build on import)
# ============================================================

_GEO_SUFFIX_REGEX = re.compile(r'_(High|LOD\d+)$', re.IGNORECASE)
_RESOLUTION_TAG_REGEX = re.compile(r'_(\d+K)$', re.IGNORECASE)
_TX_SET_SUFFIX_REGEX = re.compile(r' \(TX(?: Annotated)?(?: \d+)?\)$')
_VAR_FOLDER_REGEX = re.compile(r'^Var\d+$', re.IGNORECASE)


def strip_geo_suffix(name: str):
    """
    Strip a trailing mesh-resolution suffix from a geo file's base name.

    Returns (base, suffix) where suffix is 'high', 'LOD0', 'LOD5', etc.
    (normalized), or (name, None) if there's no such suffix.
    """
    m = _GEO_SUFFIX_REGEX.search(name)
    if not m:
        return name, None
    raw = m.group(1)
    base = name[:m.start()]
    if raw.lower() == 'high':
        return base, 'high'
    return base, 'LOD' + raw[3:]


def _strip_resolution_tag(name: str):
    """Strip a trailing _<N>K resolution tag. Returns (base, tag) where tag
    is like '4K' (normalized uppercase), or (name, None) if absent."""
    m = _RESOLUTION_TAG_REGEX.search(name)
    if not m:
        return name, None
    return name[:m.start()], m.group(1).upper()


def find_texture_set_for_geo(geo_path, preferred_resolution="4K"):
    """
    Find the texture set matching an imported geo file, for auto material
    building.

    Searches the geo's own folder first (priority), then its immediate
    subfolders, matching by base name once the geo's own LOD/High suffix and
    the texture set's resolution tag (_2K/_4K/...) are stripped from each
    side. When multiple candidates match (e.g. a 2K and a 4K set, or a
    source set and its .tx counterpart), non-.tx sets are preferred over
    .tx, and preferred_resolution (see the 'smart_import.preferred_resolution'
    setting - '1K'/'2K'/'4K'/'8K') is preferred over other resolutions,
    falling back to whichever resolution is actually available otherwise.

    Special case (Megascans "3D plant" layout): the geo can sit in a
    "VarN" folder (Var1, Var2, ...) whose own name carries no material info,
    with the shared texture set living in a sibling "Textures" folder one
    level up from VarN. If the normal search above finds nothing and the
    geo's parent folder is named "VarN", that Textures folder is searched
    for its texture set - name matching doesn't apply here since "Var1"
    isn't a material name, so instead all sets found must share the same
    base name once resolution/.tx tags are stripped (e.g. a "qheqG_2K" and
    "qheqG_4K" pair both resolve to "qheqG"), with the same non-.tx /
    preferred_resolution tie-break the named search above uses. Genuinely
    distinct base names (unrelated sets mixed together) still refuse to
    guess. Some assets ship
    both an "Atlas" set (for the VarN mesh) and a separate "Billboard" set
    (for a different, non-VarN impostor geo) side by side under Textures/ -
    when an "Atlas" subfolder exists, only it is searched (a VarN mesh
    always needs the Atlas set), otherwise the whole Textures tree is
    searched recursively.

    Args:
        geo_path: Path (or str) to the imported geo file.

    Returns:
        (texture_set_data, geo_suffix, is_var_match) - texture_set_data is
        the matched set's dict (as returned by group_texture_sets(),
        including 'variant_map'), or None if nothing matched. geo_suffix is
        the geo's own 'high'/'LODn'/None tag, needed to later pick the right
        channel variants via resolve_texture_set_channels(). is_var_match is
        True when the match came from the "VarN" fallback (Megascans 3D
        plants etc.), which typically don't need displacement - see the
        'smart_import.var_import_displacement' setting.
    """
    geo_path = Path(geo_path)
    geo_base, geo_suffix = strip_geo_suffix(geo_path.stem)
    target = geo_base.lower()

    def _images_in(directory, recursive=False):
        try:
            it = directory.rglob('*') if recursive else directory.iterdir()
            return [p for p in it if p.is_file() and get_extension_category(p.suffix.lower()) == 'images']
        except OSError:
            return []

    def _search(directory):
        candidates = _images_in(directory)
        if not candidates:
            return None

        sets, _ = group_texture_sets(candidates)

        matches = []
        for data in sets.values():
            clean = _TX_SET_SUFFIX_REGEX.sub('', data['display'])
            clean_base, res_tag = _strip_resolution_tag(clean)
            if clean_base.lower() == target:
                matches.append((data, res_tag))
        if not matches:
            return None

        # Prefer non-.tx over .tx, then the preferred resolution over others.
        matches.sort(key=lambda m: (' (TX' in m[0]['display'], m[1] != preferred_resolution))
        return matches[0][0]

    match = _search(geo_path.parent)
    if match:
        return match, geo_suffix, False

    try:
        subdirs = sorted((d for d in geo_path.parent.iterdir() if d.is_dir()), key=lambda d: d.name.lower())
    except OSError:
        subdirs = []
    for sub in subdirs:
        match = _search(sub)
        if match:
            return match, geo_suffix, False

    # "VarN" fallback: look for a sibling "Textures" folder one level up.
    if _VAR_FOLDER_REGEX.match(geo_path.parent.name):
        asset_root = geo_path.parent.parent
        textures_dir = None
        try:
            for d in asset_root.iterdir():
                if d.is_dir() and d.name.lower() == 'textures':
                    textures_dir = d
                    break
        except OSError:
            pass

        if textures_dir:
            # Some 3D-plant assets ship BOTH an "Atlas" set (full 3D mesh,
            # the VarN geo this fallback is for) and a "Billboard" set (a
            # separate impostor-plane geo, not a VarN mesh) side by side
            # under Textures/. Scanning the whole tree recursively would mix
            # both sets together and produce >1 result, so the old "exactly
            # one set found" check would fail and silently skip the match.
            # Prefer the Atlas subfolder alone when present - that's always
            # the one a VarN mesh needs; only fall back to scanning the
            # whole tree if there's no dedicated Atlas subfolder.
            atlas_dir = None
            try:
                for d in textures_dir.iterdir():
                    if d.is_dir() and d.name.lower() == 'atlas':
                        atlas_dir = d
                        break
            except OSError:
                pass

            search_dir = atlas_dir or textures_dir
            candidates = _images_in(search_dir, recursive=True)
            if candidates:
                sets, _ = group_texture_sets(candidates)
                # Multiple sets can land here purely from resolution/.tx
                # variants of the same material (e.g. "qheqG_2K" and
                # "qheqG_4K" grouped as separate sets) - collapse those with
                # the same non-.tx / preferred-resolution tie-break used by
                # the named search above, rather than requiring there be
                # only a single set. Genuinely distinct materials (e.g. an
                # Atlas set mixed with a Billboard set when there's no
                # dedicated Atlas subfolder) still refuse to guess.
                tagged = []
                for data in sets.values():
                    clean = _TX_SET_SUFFIX_REGEX.sub('', data['display'])
                    clean_base, res_tag = _strip_resolution_tag(clean)
                    tagged.append((data, clean_base.lower(), res_tag))
                if tagged and len({t[1] for t in tagged}) == 1:
                    tagged.sort(key=lambda t: (' (TX' in t[0]['display'], t[2] != preferred_resolution))
                    return tagged[0][0], geo_suffix, True

    return None, geo_suffix, False


def find_lod_proxy_for_geo(geo_path, geo_suffix, importable_extensions):
    """
    Look for a lower-detail "LODN" proxy geo next to a just-imported geo
    file, for asset-library building where a lightweight stand-in is wanted
    alongside the full-res import (see the 'smart_import.import_lod_proxy'
    setting).

    Only meaningful when the source geo is "high" or has no LOD/High suffix
    at all - a geo that's itself already a LODN import doesn't need a
    proxy, so this returns None immediately for that case. Only the geo's
    own folder is searched (never subfolders): other importable 3D files
    there are matched by base name (once each side's own suffix is
    stripped via strip_geo_suffix()) and must carry a numbered "LODN" tag
    themselves. Among matches, the highest N wins, since LOD numbers
    increase with decreasing detail - that's the lightest proxy available.

    Args:
        geo_path: Path (or str) to the just-imported geo file.
        geo_suffix: the source geo's own suffix from strip_geo_suffix()
            ('high', 'LODn', or None).
        importable_extensions: iterable of importable extensions (with or
            without a leading '.') to consider as proxy candidates.

    Returns:
        Path to the chosen proxy file, or None if none matched.
    """
    if geo_suffix not in (None, 'high'):
        return None

    geo_path = Path(geo_path)
    geo_base, _ = strip_geo_suffix(geo_path.stem)
    target = geo_base.lower()
    exts = {('.' + e.lstrip('.')).lower() for e in importable_extensions}

    try:
        candidates = [p for p in geo_path.parent.iterdir() if p.is_file() and p.suffix.lower() in exts]
    except OSError:
        return None

    best_path, best_n = None, -1
    for p in sorted(candidates, key=lambda p: p.name.lower()):
        if p == geo_path:
            continue
        base, suffix = strip_geo_suffix(p.stem)
        if not suffix or not suffix.startswith('LOD') or base.lower() != target:
            continue
        try:
            n = int(suffix[3:])
        except ValueError:
            continue
        if n > best_n:
            best_n = n
            best_path = p

    return best_path


def resolve_texture_set_channels(variant_map: dict, geo_suffix, exclude_displacement=False):
    """
    Resolve a texture set's variant_map ((channel, UDIM, LOD) -> Path) down
    to a single winning file per channel, for a specific geo variant.

    Rules:
      - Channels in TEXTURE_CHANNELS_NEVER_WIRED (ao/cavity/specular) are
        excluded entirely.
      - For the "high" geo variant, the special normalHigh channel
        (NormalBump/BumpNormal/Normal_HF) is preferred as the normal input
        if present.
      - Otherwise (or if normalHigh is absent), normal - like every other
        channel - prefers a variant tagged with the geo's own LOD, falling
        back to LOD0, then to the untagged (no-LOD) variant if neither
        exists.
      - "High" geo never gets displacement/height (it's already the
        fully-detailed mesh). exclude_displacement additionally drops them
        for any geo variant - used for the "VarN" match case (Megascans
        plants etc.), where displacement is opt-in via the
        'smart_import.var_import_displacement' setting.

    Args:
        variant_map: dict[(channel, udim, lod)] -> Path, from a set built by
            group_texture_sets()/_group_texture_sets_single_pass().
        geo_suffix: 'high', 'LOD0'..'LODn', or None (from strip_geo_suffix).
        exclude_displacement: if True, drop displacement/height regardless
            of geo_suffix.

    Returns:
        dict[channel_key] -> str(path), ready for the shader network
        generator's build_from_texture_sets().
    """
    by_channel = {}
    for (channel, _udim, lod), path in variant_map.items():
        by_channel.setdefault(channel, {}).setdefault(lod, path)

    lod_order = []
    if geo_suffix and geo_suffix != 'high':
        lod_order.append(geo_suffix)
    if 'LOD0' not in lod_order:
        lod_order.append('LOD0')
    lod_order.append(None)

    def _pick(variants):
        for lod in lod_order:
            if lod in variants:
                return variants[lod]
        return None

    result = {}

    # Normal: "high" geo prefers the dedicated high-frequency channel.
    normal_high = by_channel.get('normalHigh')
    if geo_suffix == 'high' and normal_high:
        result['normal'] = str(next(iter(normal_high.values())))
    else:
        normal_variants = by_channel.get('normal')
        if normal_variants:
            picked = _pick(normal_variants)
            if picked:
                result['normal'] = str(picked)

    # "High" geo is already the fully-detailed mesh (no displacement/subdiv
    # needed at render time) - exclude displacement/height so the shader
    # builder's displacement chain (and its per-shape subdiv settings) never
    # gets built for it.
    skip_channels = {'normal', 'normalHigh'} | TEXTURE_CHANNELS_NEVER_WIRED
    if geo_suffix == 'high' or exclude_displacement:
        skip_channels |= {'displacement', 'height'}

    for channel, variants in by_channel.items():
        if channel in skip_channels:
            continue
        picked = _pick(variants)
        if picked:
            result[channel] = str(picked)

    return result


# ============================================================
# Fuzzy filename search (fzf/VSCode "Ctrl+P" style subsequence matching)
# ============================================================

_FUZZY_SEPARATORS = set('_-. /\\')


def fuzzy_match(query: str, text: str):
    """
    Subsequence fuzzy match: every character of `query` must appear in
    `text`, in order, but not necessarily consecutively (e.g. "rgh" matches
    "roughness" via r-o-u-**g**-**h**-ness). Case-insensitive - both
    strings are lowercased internally.

    This is a greedy scorer, not a full optimal-alignment algorithm (like
    fzf's own Smith-Waterman-style matcher) - it always takes the first
    valid position for each query character rather than searching every
    possible alignment for the best-scoring one. That's a deliberate
    simplicity/speed tradeoff: filenames are short, so a greedy pass is
    plenty good in practice and stays O(len(text)) per file, which matters
    when it runs against thousands of files per keystroke.

    Scoring bonuses (higher = better match), used to rank/sort results:
      - consecutive matched characters (a contiguous run scores much more
        than the same characters scattered around)
      - a match starting right at a word boundary (start of string, or
        right after _/-/./space/\\ - e.g. matching "wall" at the start of
        "Wall_baseColor" scores higher than matching it starting mid-word)
      - the match starting at position 0 of the whole string

    Args:
        query: the search text (as typed by the user).
        text: the filename (or other string) to test against.

    Returns:
        (score, matched_indices) if query is a subsequence of text -
        matched_indices is a list of the same length as query, giving the
        index in `text` each query character matched at (used for drawing
        the "which letters matched" highlight). Returns None if query is
        not a subsequence of text at all (no match).
    """
    if not query:
        return (0.0, [])

    q = query.lower()
    t = text.lower()

    indices = []
    score = 0.0
    search_from = 0
    consecutive_run = 0

    for qc in q:
        pos = t.find(qc, search_from)
        if pos == -1:
            return None

        if pos == search_from:
            consecutive_run += 1
            score += 15 + consecutive_run * 5  # escalating bonus for longer runs
        else:
            consecutive_run = 0
            score += 1

        if pos == 0 or t[pos - 1] in _FUZZY_SEPARATORS:
            score += 10  # word-boundary bonus

        indices.append(pos)
        search_from = pos + 1

    if indices[0] == 0:
        score += 5  # whole match starts at the very beginning of the string

    # Slight preference for shorter overall strings (less "noise" around
    # the match), so e.g. "Wall" ranks "Wall.png" above "Wall_Detail_04_Extra.png".
    score -= len(text) * 0.01

    return (score, indices)


