"""
DD Content Browser - Utility Functions
Helper functions for Maya integration and common operations
"""

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


def get_default_maya_import_type(extension):
    """Get default Maya import type for extension"""
    maya_import_types = {
        '.ma': 'mayaAscii',
        '.mb': 'mayaBinary',
        '.obj': 'OBJ',
        '.fbx': 'FBX',
        '.abc': 'Alembic',
        '.usd': 'USD Import',
        '.dae': 'DAE_FBX',
        '.stl': 'STL'
    }
    return maya_import_types.get(extension, None)


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
    
    # Final fallback: safe defaults
    return {
        "category": "unknown",
        "enabled": True,
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

