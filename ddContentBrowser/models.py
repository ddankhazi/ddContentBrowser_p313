"""
DD Content Browser - Data Models
Asset representation and file system model

Author: ddankhazi
License: MIT
"""

import os
import re
import time
from pathlib import Path
from datetime import datetime

# UI Font - Default value (can be overridden by browser at runtime)
UI_FONT = "Segoe UI"

try:
    from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QMimeData, QUrl
    from PySide6 import QtCore
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtCore import QAbstractListModel, QModelIndex, Qt, QMimeData, QUrl
    from PySide2 import QtCore
    PYSIDE_VERSION = 2

# Import file type registry from utils
from .utils import (
    get_extension_category,
    is_extension_supported,
    get_importable_extensions,
    should_generate_thumbnail as utils_should_generate_thumbnail,
    FILE_TYPE_REGISTRY
)

# Debug flag - set to False to disable verbose logging
DEBUG_MODE = False  # Set to True for debugging


def natural_sort_key(text):
    """
    Generate a key for natural sorting (handles numbers correctly)
    Example: "file1.jpg", "file2.jpg", "file10.jpg" instead of "file1.jpg", "file10.jpg", "file2.jpg"
    """
    def convert(part):
        return int(part) if part.isdigit() else part.lower()
    
    return [convert(c) for c in re.split(r'(\d+)', text)]


# ============================================================================
# IMAGE SEQUENCE
# ============================================================================

class ImageSequence:
    """
    Represents an image sequence (e.g. render_0001.jpg, render_0002.jpg, ...)
    
    Attributes:
        base_name: Base name without frame number (e.g. 'render')
        pattern: Pattern string (e.g. 'render_####.jpg')
        first_frame: First frame number
        last_frame: Last frame number
        padding: Number of digits in frame number
        separator: Separator character ('_', '.', '#', '%')
        extension: File extension (e.g. '.jpg')
        files: List of Path objects (sorted by frame number)
        missing_frames: List of missing frame numbers
    """
    
    def __init__(self, pattern: str, files: list):
        """
        Initialize image sequence from pattern and file list.
        
        Args:
            pattern: Sequence pattern (e.g. 'render_####.jpg')
            files: List of Path objects belonging to this sequence
        """
        self.pattern = pattern
        self.files = sorted(files, key=lambda p: self._extract_frame(p.name))
        
        if not self.files:
            raise ValueError("ImageSequence requires at least one file")
        
        # Parse pattern to extract metadata
        from .utils import detect_sequence_pattern, get_sequence_frame_range
        
        first_file = self.files[0]
        pattern_info = detect_sequence_pattern(first_file.name)
        
        if pattern_info:
            self.base_name, _, self.padding, self.separator = pattern_info
        else:
            # Fallback for single files treated as sequences
            self.base_name = first_file.stem
            self.padding = 0
            self.separator = ''
        
        self.extension = first_file.suffix
        self.directory = first_file.parent
        
        # Calculate frame range
        self.first_frame, self.last_frame, self.missing_frames = get_sequence_frame_range(self.files)
        
        # Frame to file mapping for fast lookup
        self._frame_map = {}
        for file_path in self.files:
            frame_num = self._extract_frame(file_path.name)
            if frame_num is not None:
                self._frame_map[frame_num] = file_path
    
    def _extract_frame(self, filename: str) -> int:
        """Extract frame number from filename"""
        from .utils import extract_frame_number
        return extract_frame_number(filename)
    
    def get_frame_path(self, frame_number: int) -> Path:
        """
        Get file path for a specific frame number.
        Returns None if frame doesn't exist.
        """
        return self._frame_map.get(frame_number)
    
    def get_frame_index(self, frame_number: int) -> int:
        """
        Get list index for a frame number.
        Returns -1 if frame doesn't exist.
        """
        for i, file_path in enumerate(self.files):
            if self._extract_frame(file_path.name) == frame_number:
                return i
        return -1
    
    def get_middle_frame(self) -> Path:
        """Get the middle frame of the sequence (for thumbnails)"""
        if not self.files:
            return None
        middle_index = len(self.files) // 2
        return self.files[middle_index]
    
    def get_first_frame_path(self) -> Path:
        """Get the first frame file path"""
        return self.files[0] if self.files else None
    
    def get_last_frame_path(self) -> Path:
        """Get the last frame file path"""
        return self.files[-1] if self.files else None
    
    @property
    def frame_count(self) -> int:
        """Total number of frames in sequence"""
        return len(self.files)
    
    @property
    def is_continuous(self) -> bool:
        """Check if sequence has no missing frames"""
        return len(self.missing_frames) == 0
    
    @property
    def total_size(self) -> int:
        """Total size of all files in bytes"""
        total = 0
        for file_path in self.files:
            try:
                total += file_path.stat().st_size
            except:
                pass
        return total
    
    def __repr__(self):
        return f"ImageSequence('{self.pattern}', frames={self.frame_count}, range={self.first_frame}-{self.last_frame})"
    
    def __len__(self):
        return len(self.files)


class AssetItem:
    """Asset item representation with lazy stat loading"""
    
    def __init__(self, file_path, lazy_load=False):
        self.file_path = Path(file_path)
        self.name = self.file_path.name
        self.is_folder = self.file_path.is_dir()
        self.extension = "" if self.is_folder else self.file_path.suffix.lower()
        
        # Image sequence support
        self.is_sequence = False
        self.sequence = None  # ImageSequence object if is_sequence=True
        
        # Lazy loading - csak akkor töltjük be a stat infót, ha kell
        self._stat_loaded = False
        self._size = None
        self._modified_time = None
        self._modified = None
        
        # Ha nem lazy load, azonnal betöltjük (backward compatibility)
        if not lazy_load:
            self._load_stat()
        
        # Get category from registry
        self.category = get_extension_category(self.extension) if not self.is_folder else None
        
        # Fájltípus attribútumok - using registry
        self.is_maya_file = self.category == "maya"
        self.is_image_file = self.category == "images"
        self.is_script_file = self.category in ["scripts", "text"]
        self.is_pdf_file = self.category == "pdf"
        self.is_hda_file = self.category == "houdini"
        self.is_blend_file = self.category == "blender"
        self.is_sbsar_file = self.category == "substance"
        self.is_video_file = self.category == "video"
        
        # Thumbnail generation - using registry
        self.should_generate_thumbnail = not self.is_folder and utils_should_generate_thumbnail(self.extension)
    
    def _load_stat(self):
        """Load file stat info (size, modified time) - called on demand"""
        if self._stat_loaded:
            return
        
        try:
            if self.file_path.exists():
                stat_info = self.file_path.stat()
                self._size = 0 if self.is_folder else stat_info.st_size
                self._modified_time = stat_info.st_mtime
                # Convert to datetime for filtering
                self._modified = datetime.fromtimestamp(stat_info.st_mtime)
            else:
                self._size = 0
                self._modified_time = 0
                self._modified = datetime.fromtimestamp(0)
        except Exception as e:
            # Hálózati hiba esetén alapértékek
            self._size = 0
            self._modified_time = 0
            self._modified = datetime.fromtimestamp(0)
        
        self._stat_loaded = True
    
    @property
    def size(self):
        """Lazy load size on first access"""
        if not self._stat_loaded:
            self._load_stat()
        return self._size
    
    @property
    def modified_time(self):
        """Lazy load modified_time on first access"""
        if not self._stat_loaded:
            self._load_stat()
        return self._modified_time
    
    @property
    def modified(self):
        """Lazy load modified datetime on first access"""
        if not self._stat_loaded:
            self._load_stat()
        return self._modified
    
    def refresh_modified_time(self):
        """
        Refresh file modification time by re-reading stat info.
        Used for automatic thumbnail refresh detection.
        """
        try:
            if self.file_path.exists():
                stat_info = self.file_path.stat()
                self._modified_time = stat_info.st_mtime
                self._modified = datetime.fromtimestamp(stat_info.st_mtime)
            else:
                self._modified_time = 0
                self._modified = datetime.fromtimestamp(0)
        except Exception as e:
            # Hálózati hiba esetén ne módosítsd az értékeket
            pass
    
    def get_display_name(self):
        """Get display name"""
        if self.is_sequence and self.sequence:
            # Show sequence pattern instead of individual file
            return self.sequence.pattern
        return self.name
    
    def get_size_string(self):
        """Get size as formatted string"""
        if self.is_folder:
            return "Folder"
        
        if self.is_sequence and self.sequence:
            # Show total sequence size
            total_size = self.sequence.total_size
            if total_size < 1024:
                return f"{total_size} B"
            elif total_size < 1024 * 1024:
                return f"{total_size / 1024:.1f} KB"
            else:
                return f"{total_size / (1024 * 1024):.1f} MB"
        
        # Single file
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        else:
            return f"{self.size / (1024 * 1024):.1f} MB"
    
    def get_modified_string(self):
        """Get modification date as formatted string"""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.modified_time))


class FileSystemModel(QAbstractListModel):
    """File system model for list view"""
    
    # Signals for progress updates
    if PYSIDE_VERSION == 6:
        from PySide6.QtCore import Signal
        searchProgress = Signal(int, int)  # (scanned_files, matched_files) - for search in subfolders
        loadProgress = Signal(int, int)    # (loaded_files, total_scanned) - for include subfolders loading
        limitReached = Signal(int, int)    # (loaded_count, total_scanned) - when max files limit is hit
    else:
        from PySide2.QtCore import Signal
        searchProgress = Signal(int, int)  # (scanned_files, matched_files) - for search in subfolders
        loadProgress = Signal(int, int)    # (loaded_files, total_scanned) - for include subfolders loading
        limitReached = Signal(int, int)    # (loaded_count, total_scanned) - when max files limit is hit
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.assets = []
        self._file_path_to_row = {}  # Fast lookup: file_path_str -> row_index
        self.current_path = None
        self.filter_text = ""
        
        # Base supported formats - from central FILE_TYPE_REGISTRY
        from .utils import get_all_supported_extensions, get_extensions_by_category
        self.base_formats = get_all_supported_extensions()
        self.supported_formats = self.base_formats.copy()
        self.custom_extensions = []  # User-defined custom extensions
        
        # Get specific format categories from registry
        self.image_formats = get_extensions_by_category('images')
        self.script_formats = get_extensions_by_category('scripts') + get_extensions_by_category('text')
        
        # Search options
        self.case_sensitive_search = False
        self.regex_search = False
        self.search_in_subfolders = False  # Search in subfolders when search text is present
        
        # Advanced filters
        self.filter_file_types = []  # Empty = all types
        self.filter_min_size = 0  # Bytes
        self.filter_max_size = 0  # 0 = no limit
        self.filter_date_from = None  # datetime or None
        self.filter_date_to = None  # datetime or None
        self.show_folders = True
        self.show_images = True  # Show image files by default
        self.show_scripts = True  # Show script files by default
        self.collection_filter = []  # Collection filter (list of file paths)
        
        # Collection mode - when active, show collection files instead of directory
        self.collection_mode = False
        self.collection_files = []  # List of file paths to display in collection mode
        
        # Sorting
        self.sort_column = "name"  # "name", "size", "date", "type"
        self.sort_ascending = True
        
        # Sequence grouping
        self.sequence_mode = False  # When True, group image sequences into single items
        self._ungrouped_assets = []  # Store ungrouped assets for quick sequence mode toggle
        
        # Recursive subfolder browsing
        self.include_subfolders = False
        self.max_recursive_files = 10000  # Limit for "Include Subfolders" (shows all files)
        self.max_search_files = 100000  # Higher limit for "Search Subfolders" (filtered results)
        
        # Search interrupt flag
        self._interrupt_search = False
        
        # Image sequence grouping
        self.sequence_mode = False  # When True, group image sequences into single items
        
        # Limit warning flag
        self.limit_reached = False  # Set to True when max_recursive_files limit is reached
        
        # Incremental loading state (for load_more functionality)
        self._all_scanned_paths = []  # All file paths found during last recursive scan
        self._current_display_limit = 0  # How many files are currently displayed
        
        # Directory cache system - cache AssetItem objects instead of Path objects
        self._dir_cache = {}  # {path_str: {'assets': [AssetItem], 'timestamp': float, 'mtime': float}}
        self._cache_max_size = 20  # Maximum number of cached directories
        self._cache_ttl = 300  # Cache time-to-live in seconds (5 minutes)
        self._cache_enabled = True
    
    def _rebuild_path_index(self):
        """Rebuild the file path to row index mapping (O(n) operation)"""
        self._file_path_to_row = {}
        for row, asset in enumerate(self.assets):
            self._file_path_to_row[str(asset.file_path)] = row
    
    def get_row_for_path(self, file_path):
        """Get row index for a file path (O(1) lookup)
        
        Args:
            file_path: File path as string
            
        Returns:
            Row index (int) or None if not found
        """
        return self._file_path_to_row.get(str(file_path))
    
    def endResetModel(self):
        """Override to rebuild path index after model reset"""
        super().endResetModel()
        self._rebuild_path_index()
    
    def set_custom_extensions(self, extensions):
        """Set custom file extensions to support
        Args:
            extensions: List of extension strings (e.g. ['.gltf', '.blend'])
        """
        self.custom_extensions = [ext.lower() for ext in extensions if ext.startswith('.')]
        # Rebuild supported formats with base + custom
        self.supported_formats = self.base_formats + self.custom_extensions
        print(f"[FileSystemModel] Custom extensions added: {self.custom_extensions}")
        print(f"[FileSystemModel] Total supported formats: {len(self.supported_formats)}")
    
    def _get_dir_mtime(self, path):
        """Get directory modification time"""
        try:
            return path.stat().st_mtime
        except:
            return 0
    
    def _is_cache_valid(self, path_str, current_mtime):
        """Check if cached data is still valid"""
        if not self._cache_enabled or path_str not in self._dir_cache:
            return False
        
        cache_entry = self._dir_cache[path_str]
        cache_age = time.time() - cache_entry['timestamp']
        
        # Check if cache expired or directory was modified
        if cache_age > self._cache_ttl:
            return False
        if cache_entry['mtime'] != current_mtime:
            return False
        
        return True
    
    def _add_to_cache(self, path_str, assets, mtime):
        """Add directory listing to cache (stores AssetItem objects)"""
        if not self._cache_enabled:
            return
        
        # Remove oldest entry if cache is full
        if len(self._dir_cache) >= self._cache_max_size:
            oldest_key = min(self._dir_cache.keys(), 
                           key=lambda k: self._dir_cache[k]['timestamp'])
            del self._dir_cache[oldest_key]
            if DEBUG_MODE:
                print(f"[CACHE] Removed oldest cache entry: {oldest_key}")
        
        self._dir_cache[path_str] = {
            'assets': assets.copy(),  # Cache the AssetItem objects
            'timestamp': time.time(),
            'mtime': mtime
        }
        if DEBUG_MODE:
            print(f"[CACHE] Added to cache: {path_str} ({len(assets)} assets)")
    
    def _get_from_cache(self, path_str):
        """Get cached AssetItem objects"""
        if path_str in self._dir_cache:
            return self._dir_cache[path_str]['assets'].copy()
        return None
    
    def clear_cache(self):
        """Clear all cached directory data"""
        self._dir_cache.clear()
        if DEBUG_MODE:
            print("[CACHE] Cache cleared")
    
    def set_cache_enabled(self, enabled):
        """Enable or disable caching"""
        self._cache_enabled = enabled
        if not enabled:
            self.clear_cache()
        if DEBUG_MODE:
            print(f"[CACHE] Caching {'enabled' if enabled else 'disabled'}")
    
    def setPath(self, path):
        """Set current path"""
        self.beginResetModel()
        self.current_path = Path(path)
        self.refresh()
        self.endResetModel()
    
    def interrupt_search(self):
        """Interrupt an ongoing search operation"""
        self._interrupt_search = True
    
    def refresh(self, force=False):
        """Refresh file list
        Args:
            force: If True, bypass cache and reload from filesystem
        """
        import time
        start_time = time.time()
        
        # Reset interrupt flag at start of refresh
        self._interrupt_search = False
        
        if DEBUG_MODE:
            print(f"[Model] refresh() called - force={force}, filter_text='{self.filter_text}', "
                  f"search_in_subfolders={self.search_in_subfolders}, collection_mode={self.collection_mode}, "
                  f"current_path={self.current_path}")
        
        # Collection mode - load files from collection list instead of directory
        if self.collection_mode:
            self._load_collection_files()
            return
        
        if not self.current_path or not self.current_path.exists():
            self.assets = []
            return
        
        # Check cache first (only for non-recursive mode and when not forcing)
        # IMPORTANT: Cache is ONLY used when include_subfolders is OFF
        # When toggling include_subfolders, force refresh to avoid showing stale data
        path_str = str(self.current_path)
        current_mtime = self._get_dir_mtime(self.current_path)
        
        cached_assets = None
        # Only use cache if:
        # 1. Not forcing refresh (force=False)
        # 2. NOT in subfolder mode (include_subfolders=False)
        # 3. NOT in search subfolder mode with active search (search_in_subfolders=False OR no search text)
        # 4. NOT filtering by search text (filter_text is empty)
        # 5. Cache is valid (not expired and directory not modified)
        use_subfolders = self.include_subfolders or (self.search_in_subfolders and self.filter_text)
        has_search_filter = bool(self.filter_text)
        if not force and not use_subfolders and not has_search_filter and self._is_cache_valid(path_str, current_mtime):
            cached_assets = self._get_from_cache(path_str)
        
        try:
            all_items = []
            
            # Reset limit flag
            self.limit_reached = False
            
            # Determine if we should search recursively
            # Use recursive search if:
            # 1. include_subfolders is ON (always show all files), OR
            # 2. search_in_subfolders is ON AND there's search text present
            should_search_recursively = self.include_subfolders or (self.search_in_subfolders and self.filter_text)
            
            if DEBUG_MODE:
                print(f"[Model] should_search_recursively={should_search_recursively} "
                      f"(include_subfolders={self.include_subfolders}, "
                      f"search_in_subfolders={self.search_in_subfolders}, "
                      f"filter_text='{self.filter_text}')")
            
            if should_search_recursively:
                # Recursive mode - collect files from all subfolders
                file_count = 0
                match_count = 0
                loaded_count = 0
                
                # Determine which limit to use
                is_search_mode = self.search_in_subfolders and self.filter_text
                max_files = self.max_search_files if is_search_mode else self.max_recursive_files
                
                # Collect file paths as strings (memory efficient)
                collected_paths = []
                
                for root, dirs, files in os.walk(self.current_path):
                    # Check for interrupt
                    if self._interrupt_search:
                        print(f"⚠️ [FileSystemModel] Loading interrupted by user")
                        break
                    
                    root_path = Path(root)
                    
                    # Add folders if enabled (only direct subfolders in current dir)
                    if self.show_folders and root == str(self.current_path):
                        for dir_name in dirs:
                            if not dir_name.startswith('.'):
                                if self.filter_text:
                                    if self._matches_search(dir_name, self.filter_text):
                                        collected_paths.append(str(root_path / dir_name))
                                        loaded_count += 1
                                else:
                                    collected_paths.append(str(root_path / dir_name))
                                    loaded_count += 1
                    
                    # Add files
                    for file_name in files:
                        ext = os.path.splitext(file_name)[1].lower()
                        if ext in self.supported_formats:
                            if self.filter_file_types and ext not in self.filter_file_types:
                                continue
                            
                            file_count += 1
                            
                            # Apply search filter if in search mode
                            if is_search_mode:
                                if self._matches_search(file_name, self.filter_text):
                                    collected_paths.append(str(root_path / file_name))
                                    match_count += 1
                                    loaded_count += 1
                                
                                if file_count % 100 == 0:
                                    self.searchProgress.emit(file_count, match_count)
                                    try:
                                        if PYSIDE_VERSION == 6:
                                            from PySide6.QtWidgets import QApplication
                                        else:
                                            from PySide2.QtWidgets import QApplication
                                        QApplication.processEvents()
                                    except:
                                        pass
                            else:
                                # No search filter - add all files
                                collected_paths.append(str(root_path / file_name))
                                loaded_count += 1
                                
                                if file_count % 100 == 0:
                                    self.loadProgress.emit(loaded_count, file_count)
                                    try:
                                        if PYSIDE_VERSION == 6:
                                            from PySide6.QtWidgets import QApplication
                                        else:
                                            from PySide2.QtWidgets import QApplication
                                        QApplication.processEvents()
                                    except:
                                        pass
                            
                            # Safety limit - stop scanning when we have enough
                            if file_count >= max_files:
                                self.limit_reached = True
                                self.limitReached.emit(loaded_count, file_count)
                                break
                    
                    if file_count >= max_files:
                        break
                
                # Store results for potential load_more
                self._all_scanned_paths = collected_paths
                self._current_display_limit = len(collected_paths)
                
                # Convert collected string paths to Path objects (lazy conversion)
                all_items = [Path(p) for p in collected_paths]
                
                # Emit final progress
                if is_search_mode:
                    self.searchProgress.emit(file_count, match_count)
                else:
                    self.loadProgress.emit(loaded_count, file_count)
                
                # Final UI update
                try:
                    if PYSIDE_VERSION == 6:
                        from PySide6.QtWidgets import QApplication
                    else:
                        from PySide2.QtWidgets import QApplication
                    QApplication.processEvents()
                except:
                    pass
            else:
                # Normal mode - only current folder
                
                # Check if we have cached AssetItem objects
                if cached_assets is not None:
                    # Use cached AssetItem objects but still apply ALL filters!
                    
                    # Check if we need stat info for size/date filtering
                    needs_stat_for_filter = (
                        self.filter_min_size > 0 or 
                        self.filter_max_size > 0 or 
                        self.filter_date_from is not None or 
                        self.filter_date_to is not None
                    )
                    
                    # Load stat info if needed
                    if needs_stat_for_filter:
                        for asset in cached_assets:
                            if not asset.is_folder:
                                asset._load_stat()
                    
                    filtered_assets = []
                    for asset in cached_assets:
                        # Apply folder visibility filter
                        if asset.is_folder:
                            if not self.show_folders:
                                continue
                            # Apply search filter to folders too
                            if self.filter_text:
                                if not self._matches_search(asset.name, self.filter_text):
                                    continue
                            filtered_assets.append(asset)
                            continue
                        
                        # Apply file type filter
                        ext = asset.extension
                        if self.filter_file_types:
                            # Only specific types
                            if ext not in self.filter_file_types:
                                continue
                            if ext not in self.supported_formats:
                                continue
                        else:
                            # All supported types
                            if ext not in self.supported_formats:
                                continue
                        
                        # Apply show_images filter
                        if asset.is_image_file and not self.show_images:
                            continue
                        
                        # Apply show_scripts filter
                        if asset.is_script_file and not self.show_scripts:
                            continue
                        
                        # Apply size filter
                        if self.filter_min_size > 0 or self.filter_max_size > 0:
                            size = asset.size
                            if self.filter_min_size > 0 and size < self.filter_min_size:
                                continue
                            if self.filter_max_size > 0 and size > self.filter_max_size:
                                continue
                        
                        # Apply date filter
                        if self.filter_date_from or self.filter_date_to:
                            mod_time = asset.modified
                            if self.filter_date_from and mod_time < self.filter_date_from:
                                continue
                            if self.filter_date_to and mod_time > self.filter_date_to:
                                continue
                        
                        # Apply search filter
                        if self.filter_text:
                            if not self._matches_search(asset.name, self.filter_text):
                                continue
                        
                        filtered_assets.append(asset)
                    
                    self.assets = filtered_assets
                else:
                    # No cache - load from filesystem using os.scandir() for maximum performance
                    # scandir() returns DirEntry objects with cached stat info (1 filesystem call!)
                    all_items = []
                    
                    # Use os.scandir() - much faster than iterdir() + glob()
                    # DirEntry.is_dir() uses cached data from the initial scandir() call
                    for entry in os.scandir(self.current_path):
                        # Skip hidden files/folders (starting with .)
                        if entry.name.startswith('.'):
                            continue
                        
                        # Check if it's a directory
                        try:
                            is_directory = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            # Handle permission errors or broken symlinks
                            continue
                        
                        if is_directory:
                            # Add folder if folders are enabled
                            if self.show_folders:
                                all_items.append(Path(entry.path))
                        else:
                            # Check file extension
                            ext = Path(entry.name).suffix.lower()
                            
                            # Apply file type filters
                            if self.filter_file_types:
                                # Only specific types
                                if ext in self.filter_file_types and ext in self.supported_formats:
                                    all_items.append(Path(entry.path))
                            else:
                                # All supported types
                                if ext in self.supported_formats:
                                    all_items.append(Path(entry.path))
            
            # Only process if we didn't use cache
            if cached_assets is None:
                if DEBUG_MODE:
                    print(f"[Model] No cache - loaded {len(all_items)} items from filesystem")
                
                # Filter based on search text (applies to both folders and files)
                if self.filter_text:
                    all_items = [f for f in all_items if self._matches_search(f.name, self.filter_text)]
                    if DEBUG_MODE:
                        print(f"[Model] After search filter: {len(all_items)} items")
                
                # Convert to AssetItem objects with LAZY LOADING
                self.assets = [AssetItem(f, lazy_load=True) for f in all_items]
                
                if DEBUG_MODE:
                    print(f"[Model] Created {len(self.assets)} AssetItem objects")
                
                # Apply advanced filters
                # Ellenőrizzük, hogy kell-e stat info (méret/dátum szűrés)
                needs_stat_for_filter = (
                    self.filter_min_size > 0 or 
                    self.filter_max_size > 0 or 
                    self.filter_date_from is not None or 
                    self.filter_date_to is not None
                )
                
                # Ha kell stat info szűréshez, batch-ben töltjük be
                if needs_stat_for_filter:
                    for asset in self.assets:
                        if not asset.is_folder:  # Csak fájlokhoz kell
                            asset._load_stat()
                
                filtered_assets = []
                for asset in self.assets:
                    # Check if folders should be shown
                    if asset.is_folder:
                        if self.show_folders:
                            filtered_assets.append(asset)
                        continue
                    
                    # Check if images should be shown
                    if asset.is_image_file and not self.show_images:
                        continue
                    
                    # Check if scripts should be shown
                    if asset.is_script_file and not self.show_scripts:
                        continue
                    
                    # Size filter (for files only) - már be van töltve ha kell
                    if self.filter_min_size > 0 and asset.size < self.filter_min_size:
                        continue
                    if self.filter_max_size > 0 and asset.size > self.filter_max_size:
                        continue
                    
                    # Date filter (for files only) - már be van töltve ha kell
                    if self.filter_date_from and asset.modified < self.filter_date_from:
                        continue
                    if self.filter_date_to and asset.modified > self.filter_date_to:
                        continue
                    
                    filtered_assets.append(asset)
                
                self.assets = filtered_assets
            
            # Store ungrouped assets BEFORE sequence grouping for quick toggle
            self._ungrouped_assets = self.assets.copy()
            
            # Group image sequences if sequence mode is enabled
            if self.sequence_mode:
                try:
                    # print(f"[DEBUG] Grouping sequences for {len(self.assets)} assets...")
                    self._group_sequences()
                    # print(f"[DEBUG] After grouping: {len(self.assets)} assets")
                except Exception as e:
                    import traceback
                    print(f"[ERROR] Sequence grouping failed: {e}")
                    traceback.print_exc()
                    # Don't crash, just skip grouping
            
            # Apply sorting
            try:
                self._sort_assets()
            except Exception as e:
                import traceback
                print(f"[ERROR] Sorting failed: {e}")
                traceback.print_exc()
            
            # Add to cache AFTER filtering and sorting (only if we loaded from filesystem)
            # BUT: Don't cache if we have search filter or other filters applied
            # because cache should only store the raw directory contents
            if cached_assets is None and not self.filter_text:
                self._add_to_cache(path_str, self.assets, current_mtime)
            
        except Exception as e:
            print(f"File loading error: {e}")
            self.assets = []
    
    def _sort_assets(self):
        """Sort assets based on current sort settings"""
        # Batch load stat info if sorting by size or date (FILES ONLY - folders don't need stat)
        if self.sort_column in ["size", "date"]:
            for asset in self.assets:
                if not asset.is_folder:
                    asset._load_stat()
        
        if self.sort_column == "name":
            # Natural sorting: 1, 2, 10 instead of 1, 10, 2
            self.assets.sort(key=lambda x: (not x.is_folder, natural_sort_key(x.name)), reverse=not self.sort_ascending)
        elif self.sort_column == "size":
            # Folders first, then files by size (folders get 0 size without loading stat)
            self.assets.sort(key=lambda x: (not x.is_folder, x.size if not x.is_folder else 0), reverse=not self.sort_ascending)
        elif self.sort_column == "date":
            # Folders first, then files by date (folders get epoch 0 without loading stat)
            self.assets.sort(key=lambda x: (not x.is_folder, x.modified if not x.is_folder else datetime.fromtimestamp(0)), reverse=not self.sort_ascending)
        elif self.sort_column == "type":
            self.assets.sort(key=lambda x: (not x.is_folder, x.extension.lower()), reverse=not self.sort_ascending)
    
    def _group_sequences(self):
        """
        Group image files into sequences.
        Modifies self.assets in-place to replace sequence files with single sequence items.
        Groups sequences PER FOLDER to avoid memory issues with subfolders.
        """
        from .utils import group_image_sequences
        from collections import defaultdict
        
        if DEBUG_MODE:
            print(f"[Model] _group_sequences called with {len(self.assets)} assets")
        
        # Separate folders and files
        folders = [asset for asset in self.assets if asset.is_folder]
        files = [asset for asset in self.assets if not asset.is_folder]
        
        if DEBUG_MODE:
            print(f"[Model] Separated: {len(folders)} folders, {len(files)} files")
        
        # Separate image files from other files
        image_files = []
        other_files = []
        
        for asset in files:
            if asset.is_image_file:
                image_files.append(asset)
            else:
                other_files.append(asset)
        
        if DEBUG_MODE:
            print(f"[Model] Found {len(image_files)} image files, {len(other_files)} other files")
        
        # Group image sequences PER FOLDER
        if image_files:
            # Group image files by their parent directory
            files_by_folder = defaultdict(list)
            for asset in image_files:
                folder = asset.file_path.parent
                files_by_folder[folder].append(asset)
            
            if DEBUG_MODE:
                print(f"[Model] Grouping {len(image_files)} images across {len(files_by_folder)} folders")
            
            # Process each folder separately
            sequence_assets = []
            total_sequences = 0
            for folder, folder_assets in files_by_folder.items():
                # Convert AssetItems to Path objects for this folder only
                image_paths = [asset.file_path for asset in folder_assets]
                
                # Group into sequences (only within this folder)
                sequences_dict = group_image_sequences(image_paths)
                
                sequences_in_folder = sum(1 for files in sequences_dict.values() if len(files) > 1)
                if DEBUG_MODE and sequences_in_folder > 0:
                    print(f"[Model] Folder {folder.name}: {sequences_in_folder} sequences from {len(folder_assets)} images")
                    total_sequences += sequences_in_folder
                
                # Create AssetItems for sequences and single files
                for pattern, file_list in sequences_dict.items():
                    if len(file_list) > 1:
                        # This is a sequence - create a sequence AssetItem
                        sequence = ImageSequence(pattern, file_list)
                        
                        # Use first file as the base AssetItem
                        first_file = file_list[0]
                        asset = AssetItem(first_file, lazy_load=True)
                        
                        # Mark as sequence and attach sequence object
                        asset.is_sequence = True
                        asset.sequence = sequence
                        asset.name = pattern  # Display pattern instead of filename
                        
                        # Ensure thumbnail generation is enabled for sequences
                        asset.should_generate_thumbnail = True
                        
                        sequence_assets.append(asset)
                    else:
                        # Single file - keep original AssetItem
                        # Find original asset
                        file_path = file_list[0]
                        for original_asset in folder_assets:
                            if original_asset.file_path == file_path:
                                sequence_assets.append(original_asset)
                                break
            
            # Replace assets list: folders + sequences + other files
            self.assets = folders + sequence_assets + other_files
        else:
            # No image files to group
            self.assets = folders + other_files
    
    def _matches_search(self, filename, search_text):
        """
        Check if filename matches search text
        Supports case-sensitive and regex search based on settings
        """
        if self.regex_search:
            # Regex search
            try:
                import re
                flags = 0 if self.case_sensitive_search else re.IGNORECASE
                return bool(re.search(search_text, filename, flags))
            except re.error:
                # Invalid regex - fall back to plain text search
                pass
        
        # Plain text search
        if self.case_sensitive_search:
            return search_text in filename
        else:
            return search_text.lower() in filename.lower()
    
    def setSortOrder(self, column, ascending=True):
        """Set sort order"""
        self.beginResetModel()
        self.sort_column = column
        self.sort_ascending = ascending
        self._sort_assets()
        self.endResetModel()
    
    def setFilterText(self, text):
        """Set filter text"""
        if self.filter_text != text:
            self.beginResetModel()
            self.filter_text = text
            # When clearing search (text is empty), force refresh to ensure 
            # we get current directory state (not cached subfolder results)
            if text == "":
                force_refresh = True
            else:
                force_refresh = False
            self.refresh(force=force_refresh)
            self.endResetModel()
    
    def setFilterFileTypes(self, types):
        """Set file type filter - list of extensions like ['.ma', '.mb']"""
        self.beginResetModel()
        self.filter_file_types = types
        self.refresh()  # Filters are now properly applied to cached assets
        self.endResetModel()
    
    def setFilterSize(self, min_size=0, max_size=0):
        """Set size filter in bytes"""
        self.beginResetModel()
        self.filter_min_size = min_size
        self.filter_max_size = max_size
        self.refresh()  # Filters are now properly applied to cached assets
        self.endResetModel()
    
    def setFilterDate(self, date_from=None, date_to=None):
        """Set date filter - datetime objects"""
        self.beginResetModel()
        self.filter_date_from = date_from
        self.filter_date_to = date_to
        self.refresh()  # Filters are now properly applied to cached assets
        self.endResetModel()
    
    def setShowFolders(self, show):
        """Toggle folder visibility"""
        self.beginResetModel()
        self.show_folders = show
        self.refresh()  # Filters are now properly applied to cached assets
        self.endResetModel()
    
    def setShowImages(self, show):
        """Toggle image file visibility"""
        self.beginResetModel()
        self.show_images = show
        self.refresh()  # Filters are now properly applied to cached assets
        self.endResetModel()
    
    def setShowScripts(self, show):
        """Toggle script file visibility"""
        self.beginResetModel()
        self.show_scripts = show
        self.refresh()  # Filters are now properly applied to cached assets
        self.endResetModel()
    
    def clearFilters(self):
        """Clear all advanced filters"""
        self.beginResetModel()
        self.filter_file_types = []
        self.filter_min_size = 0
        self.filter_max_size = 0
        self.filter_date_from = None
        self.filter_date_to = None
        self.show_folders = True
        self.show_images = True
        self.show_scripts = True
        self.refresh()  # Filters are now properly applied to cached assets
        self.endResetModel()
    
    def setCollectionFilter(self, file_paths):
        """Switch to collection mode and show only collection files"""
        self.beginResetModel()
        self.collection_mode = True
        self.collection_files = [str(Path(p).resolve()) for p in file_paths]
        self.refresh()
        self.endResetModel()
    
    def clearCollectionFilter(self):
        """Exit collection mode and return to normal directory browsing"""
        self.beginResetModel()
        self.collection_mode = False
        self.collection_files = []
        # Force refresh to ensure we get current directory state, not cached search results
        self.refresh(force=True)
        self.endResetModel()
    
    def reapplySequenceGrouping(self):
        """
        Reapply sequence grouping and sorting to current assets WITHOUT reloading from filesystem.
        This is much faster than a full refresh and should be used when only sequence mode changes.
        Uses the stored ungrouped assets list to avoid rescanning directories.
        """
        if DEBUG_MODE:
            print(f"[Model] reapplySequenceGrouping called - have {len(self._ungrouped_assets)} ungrouped assets, sequence_mode={self.sequence_mode}")
        
        if not self._ungrouped_assets:
            # No ungrouped assets stored - need full refresh
            if DEBUG_MODE:
                print("[Model] No ungrouped assets available - performing full refresh")
            self.refresh(force=True)
            return
        
        # Restore ungrouped assets
        self.assets = self._ungrouped_assets.copy()
        if DEBUG_MODE:
            print(f"[Model] Restored {len(self.assets)} assets from ungrouped")
        
        # Apply sequence grouping if enabled
        if self.sequence_mode:
            if DEBUG_MODE:
                print(f"[Model] Sequence mode is ON - grouping sequences...")
            try:
                self._group_sequences()
                if DEBUG_MODE:
                    print(f"[Model] After grouping: {len(self.assets)} assets")
            except Exception as e:
                import traceback
                print(f"[ERROR] Sequence grouping failed: {e}")
                traceback.print_exc()
        else:
            if DEBUG_MODE:
                print(f"[Model] Sequence mode is OFF - not grouping")
        
        # Apply sorting
        try:
            self._sort_assets()
        except Exception as e:
            import traceback
            print(f"[ERROR] Sorting failed: {e}")
            traceback.print_exc()
    
    def _load_collection_files(self):
        """Load files and folders from collection list (collection mode)"""
        try:
            all_assets = []
            
            # Load each file/folder from collection
            for file_path_str in self.collection_files:
                file_path = Path(file_path_str)
                
                # Check if file/folder exists
                if not file_path.exists():
                    continue
                
                # Handle folders
                if file_path.is_dir():
                    # Always show the folder itself if show_folders is enabled
                    if self.show_folders:
                        try:
                            asset = AssetItem(file_path, lazy_load=False)
                            all_assets.append(asset)
                        except Exception as e:
                            if DEBUG_MODE:
                                print(f"[Collection] Error loading folder {file_path}: {e}")
                    
                    # If include_subfolders is enabled, also load all files from this folder recursively
                    if self.include_subfolders:
                        # OPTIMIZED: Use os.walk instead of rglob for better memory efficiency
                        for root, dirs, files in os.walk(str(file_path)):
                            root_path = Path(root)
                            for file_name in files:
                                item_path = root_path / file_name
                                
                                # Check if extension is supported
                                ext = item_path.suffix.lower()
                                if ext not in self.supported_formats:
                                    continue
                                
                                # Check file type filters
                                if self.filter_file_types and ext not in self.filter_file_types:
                                    continue
                                
                                # Create AssetItem with LAZY LOADING
                                try:
                                    asset = AssetItem(item_path, lazy_load=True)
                                    
                                    # Apply size filter
                                    if self.filter_min_size > 0 and asset.size < self.filter_min_size:
                                        continue
                                    if self.filter_max_size > 0 and asset.size > self.filter_max_size:
                                        continue
                                    
                                    # Apply date filter
                                    if self.filter_date_from and asset.modified < self.filter_date_from:
                                        continue
                                    if self.filter_date_to and asset.modified > self.filter_date_to:
                                        continue
                                    
                                    all_assets.append(asset)
                                    
                                except Exception as e:
                                    if DEBUG_MODE:
                                        print(f"[Collection] Error loading file {item_path}: {e}")
                                    continue
                    continue
                
                # Handle files
                if not file_path.is_file():
                    continue
                
                # Check if extension is supported
                ext = file_path.suffix.lower()
                if ext not in self.supported_formats:
                    continue
                
                # Check file type filters
                if self.filter_file_types and ext not in self.filter_file_types:
                    continue
                
                # Create AssetItem
                try:
                    asset = AssetItem(file_path, lazy_load=False)
                    
                    # Apply size filter
                    if self.filter_min_size > 0 and asset.size < self.filter_min_size:
                        continue
                    if self.filter_max_size > 0 and asset.size > self.filter_max_size:
                        continue
                    
                    # Apply date filter
                    if self.filter_date_from and asset.modified < self.filter_date_from:
                        continue
                    if self.filter_date_to and asset.modified > self.filter_date_to:
                        continue
                    
                    all_assets.append(asset)
                    
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[Collection] Error loading file {file_path}: {e}")
                    continue
            
            # Apply search filter (applies to both folders and files)
            if self.filter_text:
                self.assets = [asset for asset in all_assets if self._matches_search(asset.name, self.filter_text)]
            else:
                self.assets = all_assets
            
            # Apply sorting
            self._sort_assets()
        
        except Exception as e:
            print(f"[Collection] Load error: {e}")
            import traceback
            traceback.print_exc()
            self.assets = []
    
    def rowCount(self, parent=QModelIndex()):
        return len(self.assets)
    
    def columnCount(self, parent=QModelIndex()):
        """Return number of columns: Name, Size, Date, Type"""
        return 4
    
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        """Return header labels for columns"""
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            headers = ["Name", "Size", "Date Modified", "Type"]
            if section < len(headers):
                return headers[section]
        return None
    
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.assets):
            return None
        
        asset = self.assets[index.row()]
        column = index.column()
        
        if role == Qt.DisplayRole:
            if column == 0:  # Name
                return asset.get_display_name()
            elif column == 1:  # Size
                return asset.get_size_string()
            elif column == 2:  # Date Modified
                return asset.get_modified_string()
            elif column == 3:  # Type
                if asset.is_folder:
                    return "Folder"
                elif asset.extension:
                    return asset.extension.upper()[1:]  # Remove dot, uppercase
                else:
                    return ""
        elif role == Qt.ToolTipRole and column == 0:
            # Rich HTML tooltip with dark theme
            icon = "📁" if asset.is_folder else "📄"
            
            # Type and color
            if asset.is_folder:
                file_type = "Folder"
                color = "#FFA726"  # Orange
            elif asset.is_maya_file:
                file_type = f"{asset.extension.upper()[1:]} Maya Scene"
                color = "#42A5F5"  # Light Blue
            else:
                file_type = f"{asset.extension.upper()[1:]} File" if asset.extension else "Unknown"
                color = "#aaa"  # Light Gray
            
            # Truncate path if too long
            path_str = str(asset.file_path.parent)
            if len(path_str) > 50:
                path_str = "..." + path_str[-47:]
            
            # Build HTML tooltip for dark background - single line layout
            html = f"""
            <div style="font-family: '{UI_FONT}', Arial, sans-serif; white-space: nowrap;">
                <p style="margin: 0 0 8px 0; font-size: 13px; font-weight: bold; color: {color};">
                    {icon} {asset.name}
                </p>
                <div style="border-top: 1px solid #555; padding-top: 6px;">
                    <div style="margin: 2px 0;"><span style="color: #999;">📍 Path:</span> <span style="color: #ddd;">{path_str}</span></div>
                    <div style="margin: 2px 0;"><span style="color: #999;">📦 Type:</span> <span style="color: {color}; font-weight: bold;">{file_type}</span></div>
                    <div style="margin: 2px 0;"><span style="color: #999;">📊 Size:</span> <span style="color: #ddd; font-weight: bold;">{asset.get_size_string()}</span></div>
                    <div style="margin: 2px 0;"><span style="color: #999;">📅 Modified:</span> <span style="color: #ddd; font-weight: bold;">{asset.get_modified_string()}</span></div>
                </div>
            </div>
            """
            return html.strip()
        elif role == Qt.UserRole:
            return asset
        
        return None
    
    def flags(self, index):
        """Return item flags for drag & drop support"""
        default_flags = super().flags(index)
        if index.isValid():
            return default_flags | Qt.ItemIsDragEnabled
        return default_flags | Qt.ItemIsDropEnabled
    
    def supportedDragActions(self):
        """Return supported drag actions"""
        return Qt.CopyAction | Qt.MoveAction
    
    def supportedDropActions(self):
        """Return supported drop actions"""
        return Qt.CopyAction | Qt.MoveAction
    
    def mimeTypes(self):
        """Return supported MIME types"""
        return ['text/plain', 'text/uri-list']
    
    def mimeData(self, indexes):
        """Create MIME data for drag operation with MEL batch import command"""
        mime_data = QMimeData()
        urls = []
        paths = []
        assets = []
        
        for index in indexes:
            if index.isValid():
                asset = self.data(index, Qt.UserRole)
                if asset and not asset.is_folder:
                    url = QUrl.fromLocalFile(str(asset.file_path))
                    urls.append(url)
                    paths.append(str(asset.file_path))
                    assets.append(asset)
        
        if paths:
            # For Maya: Generate MEL/Python command for batch import
            if len(paths) == 1:
                # Single file - generate appropriate command based on file type
                asset = assets[0]
                escaped_path = paths[0].replace('\\', '/')
                
                if asset.is_sbsar_file:
                    # Substance Archive - create substance texture node
                    mel_cmd = f'python("import maya.cmds as cmds; '
                    mel_cmd += f'try:\\n'
                    mel_cmd += f'    if not cmds.pluginInfo(\'substance\', query=True, loaded=True): cmds.loadPlugin(\'substance\')\\n'
                    mel_cmd += f'except: pass\\n'
                    mel_cmd += f'substance_node = cmds.shadingNode(\'substance\', asTexture=True)\\n'
                    mel_cmd += f'cmds.setAttr(substance_node + \'.filePath\', r\'{escaped_path}\', type=\'string\')\\n'
                    mel_cmd += f'print(\'Substance texture created: \' + substance_node)");'
                else:
                    # Regular Maya file import
                    mel_cmd = f'file -import -type "mayaAscii" -ignoreVersion -mergeNamespacesOnClash false -namespace ":" -options "v=0;" -preserveReferences "{escaped_path}";'
            else:
                # Multiple files - generate Python code for batch import
                mel_cmd = "python(\"import maya.cmds as cmds\\n"
                for i, path in enumerate(paths):
                    asset = assets[i]
                    escaped_path = path.replace('\\', '/').replace('"', '\\"')
                    
                    if asset.is_sbsar_file:
                        # Substance files
                        mel_cmd += f"try:\\n"
                        mel_cmd += f"    if not cmds.pluginInfo('substance', query=True, loaded=True): cmds.loadPlugin('substance')\\n"
                        mel_cmd += f"except: pass\\n"
                        mel_cmd += f"substance_node = cmds.shadingNode('substance', asTexture=True)\\n"
                        mel_cmd += f"cmds.setAttr(substance_node + '.filePath', r'{escaped_path}', type='string')\\n"
                    else:
                        # Regular files
                        mel_cmd += f"cmds.file(r'{escaped_path}', i=True, ignoreVersion=True, mergeNamespacesOnClash=False, namespace=':', options='v=0', preserveReferences=True)\\n"
                mel_cmd += "\");"
            
            # Set as plain text (Maya Script Editor and viewport accept this)
            mime_data.setText(mel_cmd)
            
            # Also set URLs for compatibility
            mime_data.setUrls(urls)
        
        return mime_data
    
    def canDropMimeData(self, data, action, row, column, parent):
        """Check if we can accept the drop"""
        if not data.hasUrls():
            return False
        return True
    
    def dropMimeData(self, data, action, row, column, parent):
        """Handle drop event - navigate to folder if a folder is dropped"""
        if not data.hasUrls():
            return False
        
        # Get first URL
        urls = data.urls()
        if urls:
            file_path = Path(urls[0].toLocalFile())
            
            # If it's a folder, navigate to it
            if file_path.exists() and file_path.is_dir():
                self.setPath(file_path)
                return True
            # If it's a file, navigate to its parent folder
            elif file_path.exists() and file_path.is_file():
                self.setPath(file_path.parent)
                return True
        
        return False
    
    def load_more(self, increment=10000):
        """Load more files when limit was reached.
        On first call, performs full scan to find all files.
        On subsequent calls, uses cached results.
        
        Args:
            increment: How many more files to display (default 10000)
        """
        import time
        
        if not self.limit_reached:
            return
        
        load_start = time.time()
        previous_count = len(self.assets)
        
        # If no cached scan exists, perform FULL scan now
        if not self._all_scanned_paths or len(self._all_scanned_paths) == self._current_display_limit:
            print(f"📂 [FileSystemModel] Performing full scan to find all files...")
            scan_start = time.time()
            
            # Do a complete scan without limit
            all_paths = []
            is_search_mode = self.search_in_subfolders and self.filter_text
            
            for root, dirs, files in os.walk(self.current_path):
                if self._interrupt_search:
                    break
                
                root_path = Path(root)
                
                # Add folders
                if self.show_folders and root == str(self.current_path):
                    for dir_name in dirs:
                        if not dir_name.startswith('.'):
                            if self.filter_text:
                                if self._matches_search(dir_name, self.filter_text):
                                    all_paths.append(str(root_path / dir_name))
                            else:
                                all_paths.append(str(root_path / dir_name))
                
                # Add files
                for file_name in files:
                    ext = os.path.splitext(file_name)[1].lower()
                    if ext in self.supported_formats:
                        if self.filter_file_types and ext not in self.filter_file_types:
                            continue
                        
                        if is_search_mode:
                            if self._matches_search(file_name, self.filter_text):
                                all_paths.append(str(root_path / file_name))
                        else:
                            all_paths.append(str(root_path / file_name))
            
            self._all_scanned_paths = all_paths
            scan_time = time.time() - scan_start
            print(f"   Full scan completed in {scan_time:.2f}s - found {len(all_paths)} total files")
        
        # Calculate new display limit
        old_limit = self._current_display_limit
        new_limit = min(old_limit + increment, len(self._all_scanned_paths))
        
        print(f"📂 [FileSystemModel] Loading {new_limit - old_limit} more files ({old_limit} → {new_limit} out of {len(self._all_scanned_paths)} total)...")
        
        # Get the additional paths to display
        additional_paths = self._all_scanned_paths[old_limit:new_limit]
        
        # Convert to Path objects and create AssetItems
        print(f"   Creating AssetItem objects...")
        creation_start = time.time()
        additional_items = [Path(p) for p in additional_paths]
        additional_assets = [AssetItem(f, lazy_load=True) for f in additional_items]
        creation_time = time.time() - creation_start
        print(f"   AssetItem creation took {creation_time:.2f}s")
        
        # Add to existing assets
        self.beginResetModel()
        self.assets.extend(additional_assets)
        self._current_display_limit = new_limit
        
        # Check if we reached the end
        if new_limit >= len(self._all_scanned_paths):
            self.limit_reached = False
            print(f"✓ [FileSystemModel] All files loaded ({len(self.assets)} total)")
        else:
            self.limit_reached = True
            print(f"⚠️ [FileSystemModel] {len(self._all_scanned_paths) - new_limit} more files available")
        
        self.endResetModel()
        
        elapsed = time.time() - load_start
        added = len(self.assets) - previous_count
        print(f"✓ [FileSystemModel] Loaded {added} additional files (total: {len(self.assets)}) in {elapsed:.2f}s")


        return False
