"""
DD Content Browser - Utility Functions
Helper functions for Maya integration and common operations
"""

import os
import sys
import threading
import time


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


_cv2_import_cache = {}
_cv2_import_lock = threading.Lock()


def _cv2_works(cv2):
    """Smoke test: can this cv2 build actually accept the loaded numpy's arrays?"""
    try:
        import numpy as np
        cv2.resize(np.zeros((4, 4, 3), np.float32), (2, 2), interpolation=cv2.INTER_AREA)
        return True
    except Exception:
        return False


def import_cv2():
    """
    Import cv2, falling back to the bundled build in external_libs when the
    one found first on sys.path can't work with the numpy already loaded.

    Only one numpy can live in a process, and Maya sessions often have it
    pulled in by another tool (e.g. numpy 2.x) while the studio site-packages
    cv2 (4.9) was compiled against numpy 1.x. That cv2 imports fine but then
    rejects every array ("src is not a numpy array, neither a scalar").

    This smoke-tests the first cv2 found; if it fails, swaps in the bundled
    cv2 (numpy 2 compatible) via sys.modules, so every later `import cv2` in
    this package gets the working one. Cached after the first call.

    Returns the cv2 module, or None if no working cv2 is available.
    """
    if 'result' in _cv2_import_cache:
        return _cv2_import_cache['result']

    with _cv2_import_lock:
        if 'result' in _cv2_import_cache:
            return _cv2_import_cache['result']

        try:
            import cv2
        except ImportError:
            cv2 = None

        if cv2 is None or not _cv2_works(cv2):
            external_libs = get_external_libs_dir()
            if os.path.isdir(os.path.join(external_libs, 'cv2')):
                saved = {k: v for k, v in sys.modules.items() if k == 'cv2' or k.startswith('cv2.')}
                for k in saved:
                    sys.modules.pop(k, None)
                # A failed cv2 import (e.g. "_ARRAY_API not found") leaves its
                # recursion guard and binary folder behind, which would make the
                # bundled import die with "recursion is detected"
                if hasattr(sys, 'OpenCV_LOADER'):
                    delattr(sys, 'OpenCV_LOADER')
                wanted = os.path.normcase(external_libs)
                for entry in list(sys.path):
                    if (os.path.basename(os.path.normpath(entry)).lower() == 'cv2'
                            and not os.path.normcase(entry).startswith(wanted)):
                        sys.path.remove(entry)
                if external_libs in sys.path:
                    sys.path.remove(external_libs)
                sys.path.insert(0, external_libs)
                bundled = None
                try:
                    import cv2 as bundled
                except Exception as e:
                    print(f"[ddContentBrowser] Bundled cv2 failed to import: {e}")
                finally:
                    # Restore append-only priority for everything else
                    if external_libs in sys.path:
                        sys.path.remove(external_libs)
                    sys.path.append(external_libs)

                if bundled is not None and _cv2_works(bundled):
                    print(f"[ddContentBrowser] Using bundled cv2 {bundled.__version__} "
                          f"(incompatible cv2 {getattr(cv2, '__version__', '?')} found first)")
                    cv2 = bundled
                else:
                    # Bundled one no better - put the original back untouched
                    for k in [k for k in sys.modules if k == 'cv2' or k.startswith('cv2.')]:
                        sys.modules.pop(k, None)
                    sys.modules.update(saved)
                    if cv2 is not None:
                        print(f"[ddContentBrowser] Warning: cv2 {cv2.__version__} is incompatible "
                              f"with the loaded numpy, and the bundled cv2 didn't help")

        _cv2_import_cache['result'] = cv2
        return cv2


def _ensure_pil_lambda_eval():
    """
    Give older Pillow versions the ImageMath.lambda_eval() psd_tools needs.

    psd_tools calls ImageMath.lambda_eval() in _remove_white_background(),
    which runs for every PSD whose preview has an alpha channel. That function
    only exists from Pillow 10.3; under Maya the studio Pillow 10.2 usually
    wins over the bundled one, so the call raises AttributeError and every
    PSD with alpha falls back to the slow layer compositing - or, before that
    fallback existed, to PIL's garbled output.

    The shim mirrors Pillow's own implementation and is only installed when
    the function is genuinely missing.
    """
    try:
        from PIL import ImageMath
    except ImportError:
        return

    if hasattr(ImageMath, "lambda_eval"):
        return
    if not hasattr(ImageMath, "_Operand") or not hasattr(ImageMath, "ops"):
        return  # unknown Pillow layout - better to leave it alone

    def lambda_eval(expression, options={}, **kw):
        args = ImageMath.ops.copy()
        args.update(options)
        args.update(kw)
        for key, value in args.items():
            if hasattr(value, "im"):
                args[key] = ImageMath._Operand(value)
        out = expression(args)
        try:
            return out.im
        except AttributeError:
            return out

    ImageMath.lambda_eval = lambda_eval
    print(f"[PSD] Pillow {getattr(ImageMath, '__version__', '')} lacks "
          f"ImageMath.lambda_eval - compatibility shim installed")


def _apply_icc_profile(image, icc_profile):
    """Convert an image to sRGB through its embedded ICC profile."""
    import io

    try:
        from PIL import ImageCms
    except ImportError:
        return image

    try:
        with io.BytesIO(icc_profile) as stream:
            in_profile = ImageCms.ImageCmsProfile(stream)
        out_profile = ImageCms.createProfile("sRGB")
        out_mode = image.mode if image.mode in ("L", "LA", "RGBA") else "RGB"
        converted = ImageCms.profileToProfile(
            image, in_profile, out_profile, outputMode=out_mode
        )
        return converted if converted is not None else image
    except Exception as exc:
        print(f"[PSD] Could not apply the embedded ICC profile: {exc}")
        return image


def load_psd_pil(file_path, max_size=None):
    """
    Load a PSD as a PIL Image, working around unreadable merged previews.

    psd_tools normally hands back the flattened preview Photoshop stored in
    the file, which is both fast and exactly what Photoshop shows. Some PSDs -
    seen with files carrying extra alpha channels - have a merged image
    section that neither psd_tools nor PIL can decode: psd_tools raises
    "Invalid RLE compression", while PIL silently returns a garbled, colour
    shifted image. The layer data in those files is intact, so re-compositing
    from the layers gives the correct picture; it is only used as a fallback
    because it is the slower of the two.

    :param max_size: longest edge the caller actually needs. The embedded ICC
        profile is applied after scaling down to it, which is where nearly all
        the time used to go: converting a 4000px composite to sRGB takes
        seconds, the same conversion on a 256px thumbnail is instant and
        indistinguishable.

    Returns a PIL Image (RGB or RGBA), or None if psd_tools is unavailable.
    """
    import sys

    external_libs = get_external_libs_dir()
    if external_libs not in sys.path:
        sys.path.append(external_libs)

    _ensure_pil_lambda_eval()

    try:
        from psd_tools import PSDImage
        from psd_tools.constants import Resource
    except ImportError:
        return None
    from PIL import Image

    psd = PSDImage.open(str(file_path))

    # apply_icc=False: the profile is applied below, on the scaled down image.
    image = None
    try:
        image = psd.composite(apply_icc=False)
    except Exception as exc:
        print(f"[PSD] Merged preview of {file_path} is unreadable ({exc}); "
              f"compositing from layers instead")

    if image is None:
        # ignore_preview re-renders the layer stack instead of reading the
        # unreadable merged image section.
        image = psd.composite(ignore_preview=True, apply_icc=False)

    if max_size and (image.width > max_size or image.height > max_size):
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

    try:
        has_profile = Resource.ICC_PROFILE in psd.image_resources
    except Exception:
        has_profile = False
    if has_profile:
        image = _apply_icc_profile(image, psd.image_resources.get_data(Resource.ICC_PROFILE))

    return image


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


def single_shot(msec, context, func):
    """
    QTimer.singleShot(msec, context, func) that works on every PySide build.

    The (msec, context, callable) overload - the callback is dropped if
    `context` is deleted first - only exists in newer PySide6. Maya's
    PySide6 6.5 and PySide2 reject it with a TypeError. Same behaviour here
    with a one-shot QTimer parented to `context`: it goes with `context`, so
    the callback never runs on a deleted object.
    """
    # The timer has to come from the same binding as its parent
    if any(c.__module__.startswith('PySide6') for c in type(context).__mro__):
        from PySide6.QtCore import QTimer
    else:
        from PySide2.QtCore import QTimer
    timer = QTimer(context)
    timer.setSingleShot(True)
    timer.timeout.connect(func)
    timer.timeout.connect(timer.deleteLater)
    timer.start(msec)


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


def get_local_cache_dir(*parts):
    """
    Machine-local folder for rebuildable caches (thumbnails, the Asset
    Library database), as opposed to get_browser_data_dir(), which holds
    the user's own data (settings, tags, collections).

    %LOCALAPPDATA%/ddContentBrowser on Windows (not roamed - caches can be
    large), ~/.local/share/ddContentBrowser elsewhere. `parts` are joined
    onto it (e.g. get_local_cache_dir("thumbnails")). Not created here.
    """
    from pathlib import Path

    if os.name == 'nt':
        root = Path(os.getenv('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
    else:
        root = Path.home() / '.local' / 'share'
    return root.joinpath('ddContentBrowser', *parts)


# ============================================================================
# UNC -> MAPPED DRIVE PATH NORMALIZATION
# ============================================================================
#
# Browsing a network location through its UNC name (a UNC favourite, a UNC
# library root, the Windows network tree, ...) makes every asset path come
# out as \\server\share\... Handing that straight to Maya bakes the UNC form
# into file nodes / references, which breaks for anyone whose pipeline is
# built around the mapped drive letter (and is unreadable in the Attribute
# Editor). Everything that hands a path to Maya goes through to_maya_path()
# below, which swaps a UNC prefix back for its mapped drive letter.

_unc_drive_map_cache = None
_unc_drive_map_built_at = 0.0
_unc_drive_map_lock = threading.Lock()
# Minimum seconds between re-queries after a UNC path fails to match.
_UNC_DRIVE_MAP_TTL = 30.0


def _build_unc_drive_map():
    """
    Query Windows for every mapped network drive and return
    {unc_root_lowercase: "X:"}, e.g. {"\\\\svsmb.digicpictures.local\\w": "W:"}.

    Empty dict on non-Windows, or if the lookup fails for any reason - in
    that case to_maya_path() simply passes paths through unchanged.
    """
    mapping = {}
    if os.name != 'nt':
        return mapping
    try:
        import ctypes
        from ctypes import wintypes

        mpr = ctypes.WinDLL('mpr', use_last_error=True)
        WNetGetConnectionW = mpr.WNetGetConnectionW
        WNetGetConnectionW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
                                       ctypes.POINTER(wintypes.DWORD)]
        WNetGetConnectionW.restype = wintypes.DWORD
        drive_bits = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception as e:
        print(f"[PathMap] Could not query mapped drives: {e}")
        return mapping

    for i in range(26):
        if not (drive_bits >> i) & 1:
            continue
        local = f"{chr(ord('A') + i)}:"
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        try:
            if WNetGetConnectionW(local, buf, ctypes.byref(size)) != 0:
                continue  # not a network drive
        except Exception:
            continue
        remote = (buf.value or '').rstrip('\\/')
        if remote.startswith('\\\\'):
            # Several letters can map to the same share - first (lowest)
            # letter wins, so the result is stable across sessions.
            mapping.setdefault(remote.lower(), local)
    return mapping


def get_unc_drive_map(refresh=False):
    """Cached _build_unc_drive_map(). Pass refresh=True to re-query (drives
    can be mapped/unmapped while the browser is open)."""
    global _unc_drive_map_cache, _unc_drive_map_built_at
    with _unc_drive_map_lock:
        if _unc_drive_map_cache is None or refresh:
            _unc_drive_map_cache = _build_unc_drive_map()
            _unc_drive_map_built_at = time.time()
        return _unc_drive_map_cache


def _refresh_unc_drive_map_if_stale():
    """
    Re-query the drive map, but at most once per _UNC_DRIVE_MAP_TTL seconds.
    Called by unc_to_drive() only after a UNC path failed to match, so a
    drive mapped mid-session starts working without re-querying Windows for
    every one of the hundreds of paths a texture-set import touches.

    Returns the fresh map, or None if the last query is still recent
    (in which case the caller has already tried it and should give up).
    """
    with _unc_drive_map_lock:
        if time.time() - _unc_drive_map_built_at < _UNC_DRIVE_MAP_TTL:
            return None
    return get_unc_drive_map(refresh=True)


def unc_to_drive(path):
    """
    Rewrite a UNC path to its mapped drive letter, if one exists:

        \\\\svsmb.digicpictures.local\\W\\library\\foo.tif  ->  W:\\library\\foo.tif

    Anything that isn't a UNC path, or whose share isn't mapped on this
    machine, is returned unchanged. The input's separator style is
    preserved (a //server/share/... path comes back as X:/...).
    """
    if not path:
        return path
    original = str(path)
    if not (original.startswith('\\\\') or original.startswith('//')):
        return original

    forward_slashed = '\\' not in original
    norm = original.replace('/', '\\')

    def _finish(result):
        if len(result) == 2:  # share root -> keep it a directory path ("W:\")
            result += '\\'
        return result.replace('\\', '/') if forward_slashed else result

    lowered = norm.lower()

    def _match(drive_map):
        """Drive path for `norm` against this map, or None if no share matches."""
        # Exact prefix match, longest first (a share can be mounted at
        # several depths, e.g. \\srv\lib and \\srv\lib\megascans).
        best = None
        for unc_root, drive in drive_map.items():
            if lowered == unc_root or lowered.startswith(unc_root + '\\'):
                if best is None or len(unc_root) > len(best[0]):
                    best = (unc_root, drive)
        if best:
            return _finish(best[1] + norm[len(best[0]):])

        # Hostname-alias fallback: the path may spell the server out as an
        # FQDN while the drive was mapped with the short name (or vice
        # versa), e.g. \\svsmb.digicpictures.local\W vs. a W: on \\svsmb\W.
        parts = norm[2:].split('\\', 2)
        if len(parts) >= 2:
            host_short = parts[0].split('.')[0].lower()
            share = parts[1].lower()
            rest = '\\' + parts[2] if len(parts) > 2 else ''
            for unc_root, drive in drive_map.items():
                mapped = unc_root[2:].split('\\')
                if len(mapped) >= 2 and mapped[1] == share and mapped[0].split('.')[0] == host_short:
                    return _finish(drive + rest)
        return None

    result = _match(get_unc_drive_map())
    if result is None:
        # A miss may just mean the drive was mapped after the cache was
        # built, so re-query once (rate-limited) before giving up.
        fresh = _refresh_unc_drive_map_if_stale()
        if fresh is not None:
            result = _match(fresh)
    return result if result is not None else original


def to_maya_path(path):
    """
    Normalize a path on its way into Maya (file nodes, imports, references,
    drag & drop MEL, ...). Currently that means UNC -> mapped drive letter;
    see unc_to_drive(). Always returns a str, so Path objects can be passed
    straight in.
    """
    return unc_to_drive(str(path)) if path is not None else path


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


def get_maya_import_options(file_type):
    """
    Get the cmds.file(options=...) string for a Maya import type.

    'v=0' is a mayaAscii/mayaBinary translator option only. Other translators
    parse the options string strictly (e.g. mayaUsd's "USD Import" fails with
    "Unknown flag 'v'"), so they get no options at all.

    Returns:
        str or None: Options string, or None to omit the flag
    """
    if file_type in ('mayaAscii', 'mayaBinary'):
        return 'v=0'
    return None


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
    "roughness":    ["roughness", "rough", "rgh"],
    # Gloss is the INVERSE of roughness (gloss = 1 - roughness), so it gets
    # its own channel rather than being aliased onto "roughness" - wiring a
    # gloss map straight into a roughness input renders everything backwards
    # (shiny where it should be matte). The shader builder inverts it on the
    # way into the roughness input; a set shipping both prefers roughness.
    "gloss":        ["glossiness", "gloss", "gls"],
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


def convert_variant_maps_to_tif(variant_maps, progress_callback=None):
    """
    convert_variant_map_to_tif() for several variant_maps in one combined
    pass - one running progress count for a whole batch import, and a file
    shared by several maps is only converted once.

    Returns a list of converted maps, same order as variant_maps.
    """
    results = _convert_paths_to_tif(dict.fromkeys(p for vm in variant_maps for p in vm.values()),
                                    progress_callback)
    if not results:
        return list(variant_maps)
    return [{key: results.get(p, p) for key, p in vm.items()} for vm in variant_maps]


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
    "baseColor", "emission", "roughness", "gloss", "metalness", "normal",
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
_MAYA_UNIQUIFIER_REGEX = re.compile(r'(?<=[^\d_])\d+$')
_FBX_ASCII_ESCAPE_REGEX = re.compile(r'FBXASC(\d{3})')


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


def _images_in_dir(directory, recursive=False):
    """Image files directly in `directory` (or anywhere below it, if recursive)."""
    try:
        it = directory.rglob('*') if recursive else directory.iterdir()
        return [p for p in it if p.is_file() and get_extension_category(p.suffix.lower()) == 'images']
    except OSError:
        return []


def _texture_sets_in_dir(directory, recursive=False, cache=None):
    """
    The texture sets (group_texture_sets() values) built from the images in
    `directory`. `cache` is an optional plain dict owned by the caller that
    memoizes this per directory - a batch import asks about the same few
    folders over and over (every geo, every imported material/object), and
    each scan + grouping would otherwise hit the disk/network again.
    """
    key = ('sets', os.path.normcase(str(directory)), recursive)
    if cache is not None and key in cache:
        return cache[key]
    images = _images_in_dir(directory, recursive)
    sets = list(group_texture_sets(images)[0].values()) if images else []
    if cache is not None:
        cache[key] = sets
    return sets


def _named_search_dirs(geo_path, cache=None):
    """The folders a geo's texture set is looked up in by name, in priority
    order: the geo's own folder, then its immediate subfolders (sorted)."""
    parent = geo_path.parent
    key = ('dirs', os.path.normcase(str(parent)))
    if cache is not None and key in cache:
        return cache[key]
    try:
        subdirs = sorted((d for d in parent.iterdir() if d.is_dir()), key=lambda d: d.name.lower())
    except OSError:
        subdirs = []
    dirs = [parent] + subdirs
    if cache is not None:
        cache[key] = dirs
    return dirs


def _var_textures_dir(geo_path, cache=None):
    """
    For a geo sitting in a Megascans-style "VarN" folder: the folder its
    shared texture set lives in - Textures/Atlas if present, else the whole
    Textures folder (searched recursively). None for any other geo.

    Some 3D-plant assets ship BOTH an "Atlas" set (full 3D mesh, the VarN
    geo) and a "Billboard" set (a separate impostor-plane geo, not a VarN
    mesh) side by side under Textures/. Scanning the whole tree would mix
    both together, so the Atlas subfolder alone is preferred when present -
    that's always the one a VarN mesh needs.
    """
    if not _VAR_FOLDER_REGEX.match(geo_path.parent.name):
        return None
    asset_root = geo_path.parent.parent
    key = ('var', os.path.normcase(str(asset_root)))
    if cache is not None and key in cache:
        return cache[key]

    def _child_dir(directory, name):
        try:
            for d in directory.iterdir():
                if d.is_dir() and d.name.lower() == name:
                    return d
        except OSError:
            pass
        return None

    textures_dir = _child_dir(asset_root, 'textures')
    search_dir = (_child_dir(textures_dir, 'atlas') or textures_dir) if textures_dir else None
    if cache is not None:
        cache[key] = search_dir
    return search_dir


def _best_texture_set(matches, preferred_resolution):
    """Pick one set from [(set_data, res_tag, rank), ...]: lowest rank first
    (how closely the name matched), then non-.tx over .tx, then the
    preferred resolution over others."""
    matches.sort(key=lambda m: (m[2], ' (TX' in m[0]['display'], m[1] != preferred_resolution))
    return matches[0][0]


def find_texture_set_for_geo(geo_path, preferred_resolution="4K", cache=None):
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
    guess. When an "Atlas" subfolder exists under Textures, only it is
    searched (see _var_textures_dir()).

    Args:
        geo_path: Path (or str) to the imported geo file.
        cache: optional dict reused across calls (see _texture_sets_in_dir()).

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

    for directory in _named_search_dirs(geo_path, cache):
        matches = []
        for data in _texture_sets_in_dir(directory, cache=cache):
            clean = _TX_SET_SUFFIX_REGEX.sub('', data['display'])
            clean_base, res_tag = _strip_resolution_tag(clean)
            if clean_base.lower() == target:
                matches.append((data, res_tag, 0))
        if matches:
            return _best_texture_set(matches, preferred_resolution), geo_suffix, False

    # "VarN" fallback: Multiple sets can land here purely from resolution/.tx
    # variants of the same material (e.g. "qheqG_2K" and "qheqG_4K" grouped
    # as separate sets) - collapse those with the same tie-break used above,
    # rather than requiring there be only a single set. Genuinely distinct
    # materials (e.g. an Atlas set mixed with a Billboard set when there's
    # no dedicated Atlas subfolder) still refuse to guess.
    var_dir = _var_textures_dir(geo_path, cache)
    if var_dir:
        tagged = []
        for data in _texture_sets_in_dir(var_dir, recursive=True, cache=cache):
            clean = _TX_SET_SUFFIX_REGEX.sub('', data['display'])
            clean_base, res_tag = _strip_resolution_tag(clean)
            tagged.append((data, clean_base.lower(), res_tag))
        if tagged and len({t[1] for t in tagged}) == 1:
            return _best_texture_set([(t[0], t[2], 0) for t in tagged], preferred_resolution), geo_suffix, True

    return None, geo_suffix, False


def strip_maya_uniquifier(name: str) -> str:
    """Drop a trailing number glued straight onto a node name - what Maya
    appends on a name clash (RockA_MAT -> RockA_MAT1). Numbers after an
    underscore (Rock_01) are left alone, those are usually meaningful."""
    return _MAYA_UNIQUIFIER_REGEX.sub('', name)


def _normalize_match_name(name: str) -> str:
    """Lowercase, with every run of non-alphanumerics folded to a single
    '_' - Maya node names can't hold the spaces/dashes texture file names
    can, so both sides are compared in this form."""
    return re.sub(r'[^0-9a-z]+', '_', name.lower()).strip('_')


def _name_match_keys(name, strip_patterns=()):
    """
    Candidate texture set base names for a Maya node name (an imported
    material or geo object), as up to two tiers, most exact first:
      1. the name itself, plus the name with the configured material
         suffixes (_MAT, _mtl, ...), the geo _High/_LODn tag and a _<N>K
         resolution tag stripped;
      2. the same after strip_maya_uniquifier() - only tried when tier 1
         found nothing anywhere, since a trailing number can be meaningful.
    FBX-escaped characters (FBXASC032 = space, ...) are decoded first.
    """
    name = name.split('|')[-1].split(':')[-1]
    name = _FBX_ASCII_ESCAPE_REGEX.sub(lambda m: chr(int(m.group(1))), name)

    def _variants(base):
        out = [base]
        for pat in strip_patterns:
            for b in list(out):
                stripped = re.sub(pat, '', b, flags=re.IGNORECASE)
                if stripped and stripped not in out:
                    out.append(stripped)
        for strip in (lambda s: strip_geo_suffix(s)[0], lambda s: _strip_resolution_tag(s)[0]):
            for b in list(out):
                stripped = strip(b)
                if stripped and stripped not in out:
                    out.append(stripped)
        return [k for k in dict.fromkeys(_normalize_match_name(v) for v in out) if k]

    tiers = [_variants(name)]
    unique_less = strip_maya_uniquifier(name)
    if unique_less and unique_less != name:
        tier2 = [k for k in _variants(unique_less) if k not in tiers[0]]
        if tier2:
            tiers.append(tier2)
    return [t for t in tiers if t]


def find_texture_set_by_name(name, geo_path, preferred_resolution="4K", strip_patterns=(), cache=None):
    """
    Find the texture set named after a node that came in with an imported
    geo file - one of its materials, or one of its geo objects - so a
    multi-object or per-face-assigned file can give each part its own
    texture set, instead of one set for the whole file.

    Looked up in the same places as find_texture_set_for_geo(), in the same
    priority: the geo file's own folder, then its immediate subfolders,
    then (for a geo in a "VarN" folder) the shared Textures/Atlas folder.
    Within a folder, the closest name variant wins (see _name_match_keys()),
    then the usual non-.tx / preferred_resolution tie-break.

    Args:
        name: the Maya node name to match (namespace/DAG path is ignored).
        geo_path: Path (or str) to the geo file the node was imported from.
        strip_patterns: regexes of material suffixes to also try without
            (the shader generator's 'material_suffixes_to_strip' config).
        cache: optional dict reused across calls (see _texture_sets_in_dir()).

    Returns:
        (texture_set_data, from_var_folder) - from_var_folder is True when
        the set was found in a "VarN" asset's shared Textures folder (the
        'smart_import.var_import_displacement' rule applies). (None, False)
        if nothing matched.
    """
    geo_path = Path(geo_path)
    search = [(d, False) for d in _named_search_dirs(geo_path, cache)]
    var_dir = _var_textures_dir(geo_path, cache)
    if var_dir:
        search.append((var_dir, True))

    for keys in _name_match_keys(name, strip_patterns):
        rank = {k: i for i, k in enumerate(keys)}
        for directory, is_var in search:
            matches = []
            for data in _texture_sets_in_dir(directory, recursive=is_var, cache=cache):
                clean = _TX_SET_SUFFIX_REGEX.sub('', data['display'])
                clean_base, res_tag = _strip_resolution_tag(clean)
                key = _normalize_match_name(clean_base)
                if key in rank:
                    matches.append((data, res_tag, rank[key]))
            if matches:
                return _best_texture_set(matches, preferred_resolution), is_var
    return None, False


_ASSET_GEO_FORMAT_PRIORITY = ('.fbx', '.abc', '.obj')


def find_asset_folder_geo(folder, level, importable_extensions):
    """
    The geo files to import for an asset folder at the requested detail
    level - for "Import Asset Folders" on Megascans-style libraries (any
    folder using the _High/_LODn naming works).

    Looks in the folder's "VarN" subfolders (Megascans 3D plants) and only
    if those hold no geo, in the folder itself (some older plants carry
    duplicate copies of the Var geo at the top level too) - never deeper,
    so selecting a whole category folder by mistake doesn't import hundreds
    of assets. Within a folder, files are grouped by base name
    (strip_geo_suffix()), one pick per base.

    Per base: 'high' takes High, else LOD0 (3D plants never ship a High);
    'LOD0' takes LOD0 - never High instead (much heavier). Untagged files
    are only picked in a folder with no High/LOD0 geo at all (next to
    tagged geo they're extras like _proxy or ZTool exports), and when some
    bases have a LOD chain (any _LODn file) and others don't, only the
    ones with a chain are the asset - the rest are extras (e.g. pieces).
    Formats rank FBX > ABC > OBJ > anything else importable: per file the
    best one is taken, and per folder only picks in the best format present
    are kept (Megascans' OBJs/ABCs are fallback copies or pieces).

    Args:
        folder: the asset folder (Path or str).
        level: 'high' or 'LOD0'.
        importable_extensions: iterable of importable extensions (with or
            without a leading '.').

    Returns:
        (paths, fell_back) - fell_back is how many picks used LOD0 because
        'high' was requested but the base has no High.
    """
    folder = Path(folder)
    exts = {('.' + e.lstrip('.')).lower() for e in importable_extensions}

    def _format_rank(path):
        ext = path.suffix.lower()
        return (_ASSET_GEO_FORMAT_PRIORITY.index(ext) if ext in _ASSET_GEO_FORMAT_PRIORITY
                else len(_ASSET_GEO_FORMAT_PRIORITY), ext)

    try:
        var_dirs = [d for d in folder.iterdir() if d.is_dir() and _VAR_FOLDER_REGEX.match(d.name)]
    except OSError:
        var_dirs = []
    var_dirs.sort(key=lambda d: int(d.name[3:]))  # Var2 before Var10

    order = ('high', 'LOD0', None) if level == 'high' else ('LOD0', None)

    def _picks(directory):
        try:
            files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in exts]
        except OSError:
            return []
        by_base = {}
        has_lod_chain = set()
        for p in files:
            base, suffix = strip_geo_suffix(p.stem)
            if suffix and suffix.startswith('LOD'):
                has_lod_chain.add(base.lower())
                if suffix != 'LOD0':
                    continue  # only High, LOD0 or untagged can be picked
            by_base.setdefault(base.lower(), {}).setdefault(suffix, []).append(p)
        # A VarN folder holding its own VarN_* geo: ignore strays from other
        # Vars (seen in real downloads: a Var4_LOD0 sitting in Var3)
        own = directory.name.lower()
        if own in by_base and _VAR_FOLDER_REGEX.match(directory.name):
            by_base = {own: by_base[own]}
        # Untagged files only count when the folder has no High/LOD0 at all -
        # next to tagged geo they're extras (_proxy, ZTool exports, ...)
        if any(set(v) - {None} for v in by_base.values()):
            by_base = {b: v for b, v in by_base.items() if set(v) - {None}}
        # Geo with a LOD chain is the asset; single-level files next to it are
        # extras (Debris_rb0gufa: a combined High+LOD6 FBX plus its pieces as
        # High-only OBJs)
        if any(b in has_lod_chain for b in by_base) and any(b not in has_lod_chain for b in by_base):
            by_base = {b: v for b, v in by_base.items() if b in has_lod_chain}
        picks = []
        for base in sorted(by_base):
            variants = by_base[base]
            for suffix in order:
                if suffix in variants:
                    picks.append((min(variants[suffix], key=_format_rank), suffix))
                    break
        # One folder, one format: Megascans ships the same asset as FBX and
        # as OBJ/ABC fallbacks (or as pieces in a fallback format), so only
        # the best format present is imported (Debris_rb0gufa: a combined
        # FBX plus its pieces as OBJs)
        if picks:
            best = min(_format_rank(p)[0] for p, _ in picks)
            picks = [pk for pk in picks if _format_rank(pk[0])[0] == best]
        return picks

    picks = [pick for d in var_dirs for pick in _picks(d)] or _picks(folder)
    fell_back = sum(1 for _, suffix in picks if level == 'high' and suffix == 'LOD0')
    return [p for p, _ in picks], fell_back


def _single_map_sets_in_dir(directory):
    """
    "Sets" of the texture maps in `directory` that group_texture_sets() leaves
    as loose files because there's only one map per base name - Megascans
    imperfections are a single Roughness map. Same shape as a texture set,
    same duplicate handling (one file per variant: alias priority, then file
    format - e.g. the .jpg/.tif pair of one map).
    """
    groups = {}
    for path in _images_in_dir(directory):
        base, channel, udim, lod, alias = parse_texture_filename(path.stem, path.suffix)
        if channel is None:
            continue
        group = groups.setdefault(base.lower(), {'display': base, 'variants': {}})
        key = (channel, udim, lod)
        rank = (_alias_rank(channel, alias), _texture_extension_rank(path))
        if key not in group['variants'] or rank < group['variants'][key][1]:
            group['variants'][key] = (path, rank)
    sets = []
    for group in groups.values():
        channels = {}
        for (channel, _udim, _lod), (path, _rank) in group['variants'].items():
            channels.setdefault(channel, []).append(path)
        sets.append({
            'display': group['display'],
            'channels': channels,
            'files': [p for p, _ in group['variants'].values()],
            'extra_formats': [],
            'variant_map': {k: v[0] for k, v in group['variants'].items()},
        })
    return sets


def find_asset_folder_texture_set(folder, preferred_resolution="4K", asset_id=None):
    """
    The texture set of a texture-only asset folder (a Megascans surface,
    decal, atlas, imperfection, displacement, ...) - for "Import Asset
    Folders". Built from the images directly in the folder, never its
    subfolders: Megascans' Thumbs/ only holds low-res copies, previews/
    renders.

    When the folder holds several sets, the one named after the asset (its
    id, else the folder name's last '_' part - "concrete_rough_xeokfboga"
    -> "xeokfboga") wins, then the one with more channels, then the usual
    non-.tx / preferred_resolution tie-break.

    Returns the set dict (see group_texture_sets()), or None.
    """
    folder = Path(folder)
    sets = _texture_sets_in_dir(folder)
    if not sets:
        sets = _single_map_sets_in_dir(folder)
    if not sets:
        return None
    ident = (asset_id or folder.name.rsplit('_', 1)[-1]).lower()
    matches = []
    for data in sets:
        clean = _TX_SET_SUFFIX_REGEX.sub('', data['display'])
        base, res_tag = _strip_resolution_tag(clean)
        matches.append((data, res_tag, 0 if ident and ident in base.lower() else 1))
    # More channels first; _best_texture_set's stable sort keeps that order
    # within its own ranking
    matches.sort(key=lambda m: -len(m[0]['channels']))
    return _best_texture_set(matches, preferred_resolution)


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


