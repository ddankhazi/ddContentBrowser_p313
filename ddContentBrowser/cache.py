"""
DD Content Browser - Cache Module
Thumbnail caching system with memory and disk storage

OPTIMIZATIONS (2025-12):
- OpenCV IMREAD_REDUCED_* with smart size checking (2-8× speedup)
- Dynamic reduction based on original image dimensions (min 256px output)
- Small images (<512px) loaded at full resolution (no quality loss)
- Smart routing: Large files (>50MB) → OpenCV, others → QImageReader
- Optimized scaling logic: Load at 8-16× thumbnail size for quality/speed balance

Author: ddankhazi
License: MIT
"""

__all__ = [
    'ThumbnailCache',
    'ThumbnailDiskCache', 
    'ThumbnailGenerator',
    'apply_exif_orientation'
]

# UI Font - Default value (matches Windows/Maya UI)
UI_FONT = "Segoe UI"

# Debug flag - set to True to enable verbose logging
DEBUG_MODE = False

import os
import sys
import time
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, Future
from queue import Queue
import threading

# IMPORTANT: Disable ffmpeg report file generation BEFORE any imageio_ffmpeg import
# This prevents the creation of ffmpeg-*.log files in the working directory
os.environ.pop('FFREPORT', None)
from pathlib import Path
from datetime import datetime

# Suppress OpenCV/FFmpeg verbose output
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "loglevel;quiet"
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
os.environ["OPENCV_VIDEOIO_PRIORITY_FFMPEG"] = "0"
os.environ["FFMPEG_LOG_LEVEL"] = "quiet"

# TurboJPEG support (optional, faster JPEG decoding)
TURBOJPEG_AVAILABLE = False
TURBOJPEG_INSTANCE = None
try:
    # Add external_libs to path
    script_dir = Path(__file__).parent
    external_libs_path = script_dir / "external_libs"
    if str(external_libs_path) not in sys.path:
        sys.path.insert(0, str(external_libs_path))
    
    from turbojpeg import TurboJPEG
    
    # Try to load DLL from multiple locations (portable-first)
    dll_paths = [
        # 1. Tool directory (portable)
        os.path.join(os.path.dirname(__file__), 'external_libs', 'bin', 'turbojpeg.dll'),
        # 2. System installation
        r'C:\libjpeg-turbo64\bin\turbojpeg.dll',
    ]
    
    TURBOJPEG_INSTANCE = None
    for dll_path in dll_paths:
        if os.path.exists(dll_path):
            try:
                TURBOJPEG_INSTANCE = TurboJPEG(dll_path)
                TURBOJPEG_AVAILABLE = True
                if DEBUG_MODE:
                    print(f"[TURBOJPEG] ✓ Initialized: {dll_path}")
                break
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[TURBOJPEG] ✗ Failed to load {dll_path}: {e}")
                continue
    
    if TURBOJPEG_INSTANCE is None:
        # Last resort: try auto-detect
        try:
            TURBOJPEG_INSTANCE = TurboJPEG()
            TURBOJPEG_AVAILABLE = True
            if DEBUG_MODE:
                print(f"[TURBOJPEG] ✓ Initialized (auto-detected)")
        except Exception as e:
            if DEBUG_MODE:
                print(f"[TURBOJPEG] ✗ Not available: {e}")
            TURBOJPEG_AVAILABLE = False
            TURBOJPEG_INSTANCE = None
except Exception as e:
    if DEBUG_MODE:
        print(f"[TURBOJPEG] ✗ Import failed: {e}")
    TURBOJPEG_AVAILABLE = False
    TURBOJPEG_INSTANCE = None

try:
    from PySide6.QtCore import QThread, Signal, Qt
    from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QLinearGradient, QBrush, QTransform
    from PySide6.QtCore import QRect
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtCore import QThread, Signal, Qt
    from PySide2.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QLinearGradient, QBrush, QTransform
    from PySide2.QtCore import QRect
    PYSIDE_VERSION = 2



def apply_exif_orientation(pixmap, file_path):
    """
    Apply EXIF orientation to pixmap (auto-rotate based on camera orientation)
    FOR PREVIEW AND ZOOM MODE (+90° adjustment)
    
    NOTE: This function is now DEPRECATED - use QImageReader.setAutoTransform(True) instead!
    Kept for backward compatibility only.
    
    Args:
        pixmap: QPixmap to transform
        file_path: Path to image file (to read EXIF)
    
    Returns:
        Original pixmap unchanged (EXIF handling now done by QImageReader)
    """
    # QImageReader.setAutoTransform(True) handles EXIF orientation automatically
    # This function is no longer needed but kept for compatibility
    return pixmap


def apply_exif_orientation_thumbnail(pixmap, file_path):
    """
    Apply EXIF orientation to pixmap (auto-rotate based on camera orientation)
    FOR THUMBNAILS ONLY (no extra rotation)
    
    Args:
        pixmap: QPixmap to transform
        file_path: Path to image file (to read EXIF)
    
    Returns:
        Transformed QPixmap or original if no rotation needed
    """
    try:
        from PIL import Image
        
        # Open image and get EXIF orientation
        img = Image.open(str(file_path))
        exif = img._getexif()
        
        if not exif or 274 not in exif:
            return pixmap  # No orientation tag
        
        orientation = exif[274]
        
        if orientation == 1:
            return pixmap  # Normal, no rotation needed
        
        if orientation == 2:
            # Flip horizontal
            pixmap = pixmap.transformed(QTransform().scale(-1, 1), Qt.SmoothTransformation)
        elif orientation == 3:
            # Rotate 180°
            pixmap = pixmap.transformed(QTransform().rotate(180), Qt.SmoothTransformation)
        elif orientation == 4:
            # Flip vertical
            pixmap = pixmap.transformed(QTransform().scale(1, -1), Qt.SmoothTransformation)
        elif orientation == 5:
            # Flip horizontal (no extra rotation)
            pixmap = pixmap.transformed(QTransform().scale(-1, 1), Qt.SmoothTransformation)
        elif orientation == 6:
            # No rotation - most common for portrait photos
            pass
        elif orientation == 7:
            # Flip horizontal only
            pixmap = pixmap.transformed(QTransform().scale(-1, 1), Qt.SmoothTransformation)
        elif orientation == 8:
            # Rotate 180°
            pixmap = pixmap.transformed(QTransform().rotate(180), Qt.SmoothTransformation)
        
        return pixmap
        
    except Exception as e:
        # If PIL not available or any error, return original
        return pixmap


class ThumbnailCache:
    """In-memory thumbnail cache manager"""
    
    def __init__(self, max_size=1000):
        self.cache = {}
        self.max_size = max_size
        self.access_times = {}
    
    def get(self, file_path):
        """Get thumbnail from cache"""
        if file_path in self.cache:
            self.access_times[file_path] = time.time()
            return self.cache[file_path]
        return None
    
    def set(self, file_path, thumbnail):
        """Set thumbnail in cache"""
        if len(self.cache) >= self.max_size:
            self._cleanup()
        
        self.cache[file_path] = thumbnail
        self.access_times[file_path] = time.time()
    
    def clear(self):
        """Clear all cached thumbnails"""
        self.cache.clear()
        self.access_times.clear()
    
    def remove(self, file_path):
        """Remove specific thumbnail from cache"""
        if file_path in self.cache:
            del self.cache[file_path]
        if file_path in self.access_times:
            del self.access_times[file_path]
    
    def _cleanup(self):
        """LRU cache cleanup"""
        # Remove oldest accessed items
        sorted_items = sorted(self.access_times.items(), key=lambda x: x[1])
        items_to_remove = len(sorted_items) // 4  # Remove 25%
        
        for file_path, _ in sorted_items[:items_to_remove]:
            if file_path in self.cache:
                del self.cache[file_path]
            if file_path in self.access_times:
                del self.access_times[file_path]


class ThumbnailDiskCache:
    """Persistent disk-based thumbnail cache"""
    
    def __init__(self, cache_dir=None, max_size_mb=500):
        """
        Initialize disk cache.
        
        Args:
            cache_dir: Directory to store thumbnails (default: %LOCALAPPDATA%/ddContentBrowser/thumbnails)
            max_size_mb: Maximum cache size in megabytes (default: 500 MB)
        """
        if cache_dir is None:
            # Use AppData/Local on Windows, ~/.local/share on Linux/Mac
            import os
            if os.name == 'nt':  # Windows
                cache_root = Path(os.getenv('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
            else:  # Linux/Mac
                cache_root = Path.home() / '.local' / 'share'
            cache_dir = cache_root / "ddContentBrowser" / "thumbnails"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_size_mb = max_size_mb
        self.stats = {
            'hits': 0,
            'misses': 0,
            'generated': 0
        }
        
        # Load or create cache info
        self.info_file = self.cache_dir / "cache_info.json"
        self.load_info()
    
    def load_info(self):
        """Load cache information"""
        if self.info_file.exists():
            try:
                with open(self.info_file, 'r') as f:
                    self.stats = json.load(f)
            except:
                pass
    
    def save_info(self):
        """Save cache information"""
        try:
            with open(self.info_file, 'w') as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            print(f"Error saving cache info: {e}")
    
    def get_cache_key(self, file_path, file_mtime):
        """
        Generate unique cache key from file path and modification time
        
        Args:
            file_path: Path to the file
            file_mtime: File modification timestamp
            
        Returns:
            MD5 hash string
        """
        key_string = f"{file_path}_{file_mtime}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def get_thumbnail_path(self, file_path, file_mtime):
        """Get path to cached thumbnail file"""
        cache_key = self.get_cache_key(file_path, file_mtime)
        return self.cache_dir / f"{cache_key}.jpg"
    
    def get(self, file_path, file_mtime):
        """
        Get thumbnail from disk cache
        
        Args:
            file_path: Path to the source file
            file_mtime: File modification timestamp
            
        Returns:
            QPixmap if found, None otherwise
        """
        # Check our own cache
        thumb_path = self.get_thumbnail_path(file_path, file_mtime)
        
        if thumb_path.exists():
            try:
                pixmap = QPixmap(str(thumb_path))
                if not pixmap.isNull():
                    self.stats['hits'] += 1
                    return pixmap
            except Exception as e:
                print(f"Error loading thumbnail from {thumb_path}: {e}")
        
        self.stats['misses'] += 1
        return None
    
    def set(self, file_path, file_mtime, pixmap, quality=85):
        """
        Save thumbnail to disk cache
        
        Args:
            file_path: Path to the source file
            file_mtime: File modification timestamp
            pixmap: QPixmap to save
            quality: JPEG quality (0-100)
        """
        thumb_path = self.get_thumbnail_path(file_path, file_mtime)
        
        try:
            # Ensure parent directory exists
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert QPixmap to QImage for thread-safe saving
            # QPixmap.save() is NOT thread-safe, but QImage.save() IS
            image = pixmap.toImage()
            
            # Save as JPEG for smaller file size
            success = image.save(str(thumb_path), "JPEG", quality)
            
            if success:
                self.stats['generated'] += 1
                self.save_info()
                
                # Check if we need to cleanup old cache
                self._check_cache_size()
            
            return success
            
        except Exception as e:
            print(f"Error saving thumbnail to {thumb_path}: {e}")
            return False
    
    def clear(self):
        """Clear all cached thumbnails"""
        try:
            for thumb_file in self.cache_dir.glob("*.jpg"):
                thumb_file.unlink()
            
            self.stats = {'hits': 0, 'misses': 0, 'generated': 0}
            self.save_info()
            
            print(f"Cache cleared: {self.cache_dir}")
            
        except Exception as e:
            print(f"Error clearing cache: {e}")
    
    def needs_refresh(self, file_path, file_mtime):
        """
        Check if cached thumbnail needs to be refreshed.
        Returns True if:
        - File doesn't have a cached thumbnail
        - File was modified after the thumbnail was generated (newer mtime than cached version)
        
        Args:
            file_path: Path to the source file
            file_mtime: Current file modification timestamp
            
        Returns:
            bool: True if refresh is needed, False if cache is valid
        """
        try:
            file_path = Path(file_path)
            
            # Check if thumbnail with CURRENT mtime exists
            current_thumb_path = self.get_thumbnail_path(file_path, file_mtime)
            
            if current_thumb_path.exists():
                # Cache is up-to-date
                return False
            
            # Cache doesn't exist with current mtime - refresh needed
            # Also clean up any old cached versions (optional optimization)
            self._cleanup_old_thumbnails_for_file(file_path, file_mtime)
            
            return True
            
        except Exception as e:
            print(f"Error checking if refresh needed for {file_path}: {e}")
            return True  # On error, refresh to be safe
    
    def _cleanup_old_thumbnails_for_file(self, file_path, current_mtime):
        """
        Clean up old cached thumbnails for a file (with outdated mtime).
        This prevents cache bloat when files are frequently modified.
        
        Args:
            file_path: Path to the source file
            current_mtime: Current file modification timestamp
        """
        try:
            # We need to find old cache entries for this file
            # Since cache key = MD5(filepath + "_" + mtime), we can't directly search by filepath
            # Instead, we'll use a metadata file approach or just skip cleanup
            # (cleanup will happen naturally through LRU policy in _cleanup_old_cache)
            
            # For now, skip explicit cleanup - let LRU handle it
            # Future optimization: maintain a filepath -> cache_keys mapping
            pass
            
        except Exception as e:
            print(f"Error cleaning up old thumbnails for {file_path}: {e}")
    
    def clear_thumbnail(self, file_path):
        """
        Clear cached thumbnail for a specific file
        
        Args:
            file_path: Path to the source file
            
        Returns:
            bool: True if thumbnail was found and deleted, False otherwise
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                return False
            
            # Get file modification time
            file_mtime = file_path.stat().st_mtime
            
            # Get cache path
            thumb_path = self.get_thumbnail_path(file_path, file_mtime)
            
            if thumb_path.exists():
                thumb_path.unlink()
                print(f"Cleared thumbnail cache for: {file_path.name}")
                return True
            else:
                return False
                
        except Exception as e:
            print(f"Error clearing thumbnail for {file_path}: {e}")
            return False
    
    def get_cache_size(self):
        """Get current cache size in MB"""
        total_size = 0
        for thumb_file in self.cache_dir.glob("*.jpg"):
            total_size += thumb_file.stat().st_size
        
        return total_size / (1024 * 1024)  # Convert to MB
    
    def _check_cache_size(self):
        """Check cache size and cleanup if needed"""
        current_size = self.get_cache_size()
        
        if current_size > self.max_size_mb:
            print(f"Cache size {current_size:.1f}MB exceeds limit {self.max_size_mb}MB, cleaning up...")
            self._cleanup_old_cache()
    
    def _cleanup_old_cache(self):
        """Remove oldest thumbnails based on access time (LRU)"""
        try:
            # Get all thumbnail files with their stats
            thumbs = []
            for thumb_file in self.cache_dir.glob("*.jpg"):
                stat = thumb_file.stat()
                thumbs.append({
                    'path': thumb_file,
                    'size': stat.st_size,
                    'atime': stat.st_atime,  # Access time
                    'mtime': stat.st_mtime   # Modification time
                })
            
            if not thumbs:
                return
            
            # Sort by access time (least recently accessed first)
            thumbs.sort(key=lambda x: x['atime'])
            
            # Calculate target size (80% of max to leave headroom)
            target_size = self.max_size_mb * 0.8 * 1024 * 1024  # Convert to bytes
            current_size = sum(t['size'] for t in thumbs)
            
            # Remove files until we're under target
            removed_count = 0
            for thumb in thumbs:
                if current_size <= target_size:
                    break
                
                try:
                    thumb['path'].unlink()
                    current_size -= thumb['size']
                    removed_count += 1
                except Exception as e:
                    print(f"Error removing {thumb['path']}: {e}")
            
            print(f"Removed {removed_count} old thumbnails, cache now {current_size / (1024*1024):.1f}MB")
            
        except Exception as e:
            print(f"Error during cache cleanup: {e}")
    
    def get_stats(self):
        """Get cache statistics"""
        return {
            **self.stats,
            'cache_size_mb': self.get_cache_size(),
            'cache_dir': str(self.cache_dir),
            'file_count': len(list(self.cache_dir.glob("*.jpg")))
        }


class ThumbnailGenerator(QThread):
    """
    Hybrid multithreaded thumbnail generator
    
    Architecture:
    - ThreadPoolExecutor (2-4 workers): CPU-intensive work (decode, resize, color conversion)
    - Main QThread: QPixmap conversion and signal emission (thread-safe)
    - Thread-safe queue for worker results
    
    This ensures Qt objects are only created in the main thread while parallelizing
    the heavy computational work across multiple CPU cores.
    """
    
    # Signals
    thumbnail_ready = Signal(str, object)  # (file_path, pixmap)
    progress_update = Signal(int, int)     # (current, total)
    generation_failed = Signal(str, str)    # (file_path, error_message)
    cache_status = Signal(str)             # Status message: "cache" or "generating"
    
    def __init__(self, memory_cache, disk_cache, thumbnail_size=128, jpeg_quality=85, metadata_manager=None, max_workers=None):
        super().__init__()
        self.memory_cache = memory_cache
        self.disk_cache = disk_cache
        self.thumbnail_size = thumbnail_size
        self.jpeg_quality = jpeg_quality  # JPEG quality for disk cache (0-100)
        self.metadata_manager = metadata_manager  # For auto-tagging color spaces
        self.queue = []
        self.is_running = True
        self.current_file = None
        self.processed_count = 0  # Track how many we've processed
        self.total_count = 0      # Track total in current batch
        
        # Performance tracking
        self._last_stats_time = 0
        self._stats_interval = 5.0  # Print stats every 5 seconds (in debug mode)
        
        # ThreadPoolExecutor for parallel thumbnail generation
        # Auto-detect optimal worker count based on CPU cores (if not specified)
        if max_workers is None:
            import os
            cpu_count = os.cpu_count() or 4
            # Use CPU count but cap at 12 to avoid excessive threads
            max_workers = min(cpu_count, 12)
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ThumbWorker")
        
        # Thread-safe result queue for worker threads
        self.result_queue = Queue()
        
        # Track active futures to avoid processing duplicate files
        self.active_futures = {}  # file_path -> Future
        self.futures_lock = threading.Lock()
        
        # Clean up any ffmpeg log files generated by imageio_ffmpeg imports
        self._cleanup_ffmpeg_logs()
        
        # Increase Qt image allocation limit from 256MB to 1024MB (1GB)
        # This allows loading very large images (e.g., 8K textures)
        try:
            if PYSIDE_VERSION == 6:
                from PySide6.QtGui import QImageReader
            else:
                from PySide2.QtGui import QImageReader
            QImageReader.setAllocationLimit(1024)  # 1024 MB = 1 GB
        except Exception as e:
            print(f"[Cache] Could not set image allocation limit: {e}")
        
        # Always print initialization info (even if DEBUG_MODE is off)
        print(f"[ThumbnailGenerator] ✨ Initialized with {max_workers} worker threads")
        print(f"[ThumbnailGenerator]    Thumbnail size: {thumbnail_size}px")
        print(f"[ThumbnailGenerator]    JPEG quality: {jpeg_quality}")
        print(f"[ThumbnailGenerator]    Max in-flight jobs: {max_workers + 2}")
        if DEBUG_MODE:
            print(f"[ThumbnailGenerator]    Debug mode: ENABLED")
        
    def _cleanup_ffmpeg_logs(self):
        """Remove ffmpeg log files created by imageio_ffmpeg initialization"""
        try:
            import os
            import glob
            # Look for ffmpeg-*.log files in the current directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_pattern = os.path.join(script_dir, "ffmpeg-*.log")
            for log_file in glob.glob(log_pattern):
                try:
                    os.remove(log_file)
                except:
                    pass  # Silently ignore if we can't delete
        except:
            pass  # Don't let cleanup errors affect initialization
        
    def add_to_queue(self, file_path, file_mtime, priority=False, asset=None):
        """Add file to generation queue with optional priority and asset
        
        Args:
            file_path: Path to file
            file_mtime: File modification time
            priority: Priority flag (unused, kept for compatibility)
            asset: Optional AssetItem object (for sequence support)
        """
        # Check if already in queue
        for item in self.queue:
            if item[0] == file_path:
                return
        
        # Just append to queue - priority is handled by clearing old items
        # Items are added in visible order (top to bottom)
        self.queue.append((file_path, file_mtime, asset))
        self.total_count += 1  # Increment total when adding to queue
    
    def clear_queue(self):
        """Clear generation queue"""
        self.queue.clear()
        self.processed_count = 0
        self.total_count = 0
    
    def stop(self):
        """Stop the generator thread and worker pool gracefully"""
        self.is_running = False
        self.queue.clear()
        self.current_file = None  # Clear current processing file
        
        # Shutdown thread pool (wait for active tasks to complete)
        if hasattr(self, 'executor'):
            if DEBUG_MODE:
                print("[ThumbnailGenerator] Shutting down worker pool...")
            self.executor.shutdown(wait=True, cancel_futures=True)
            if DEBUG_MODE:
                print("[ThumbnailGenerator] Worker pool shut down")
    
    def run(self):
        """
        Main thread loop - dispatch work to thread pool and process results
        
        Balanced two-stage pipeline:
        1. Submit jobs to ThreadPoolExecutor (controlled rate)
        2. Process completed results (QPixmap conversion in main thread)
        """
        if DEBUG_MODE:
            print("[CACHE-THREAD] 🚀 Main loop started")
        
        while self.is_running:
            # Stage 1: Submit MULTIPLE new jobs if capacity available (fill the pool!)
            # Submit up to max_workers jobs per iteration to saturate CPU
            jobs_submitted = 0
            while self.queue and self.is_running and jobs_submitted < self.max_workers:
                # Check if we have capacity (don't overwhelm the pool)
                with self.futures_lock:
                    active_count = len(self.active_futures)
                
                # Limit in-flight jobs to avoid memory buildup
                # Max in-flight = max_workers + 2 (tight control)
                if active_count < self.max_workers + 2:
                    # Get next item from queue (pop from END for correct order)
                    queue_item = self.queue.pop()  # pop() = pop(-1) = last item
                    
                    # Extract components (backwards compatible with old tuple format)
                    if len(queue_item) == 3:
                        file_path, file_mtime, asset = queue_item
                    else:
                        file_path, file_mtime = queue_item
                        asset = None
                    
                    # Check if already processing this file
                    already_processing = False
                    with self.futures_lock:
                        if file_path in self.active_futures:
                            already_processing = True
                    
                    if not already_processing:
                        # For sequences, use pattern as cache key instead of file path
                        cache_key = file_path
                        is_sequence = asset and asset.is_sequence and asset.sequence
                        if is_sequence:
                            cache_key = str(asset.sequence.pattern)
                        
                        if DEBUG_MODE:
                            print(f"[CACHE-THREAD] Processing: {Path(file_path).name}")
                        
                        # Check memory cache first
                        cached = self.memory_cache.get(cache_key)
                        if cached:
                            if DEBUG_MODE:
                                print(f"[CACHE-THREAD] → Found in memory cache")
                            self.cache_status.emit("cache")
                            self.thumbnail_ready.emit(file_path, cached)
                            self.processed_count += 1
                            if self.total_count > 0:
                                self.progress_update.emit(self.processed_count, self.total_count)
                            # DON'T continue here - fall through to Stage 2
                        # Check disk cache (skip for sequences)
                        elif not is_sequence:
                            cached = self.disk_cache.get(file_path, file_mtime)
                            if cached and not cached.isNull():
                                if DEBUG_MODE:
                                    print(f"[CACHE-THREAD] → Found in disk cache")
                                self.cache_status.emit("cache")
                                self.memory_cache.set(file_path, cached)
                                self.thumbnail_ready.emit(file_path, cached)
                                self.processed_count += 1
                                if self.total_count > 0:
                                    self.progress_update.emit(self.processed_count, self.total_count)
                                # DON'T continue here - fall through to Stage 2
                            else:
                                # Need to generate - submit to worker pool
                                self._submit_worker_job(file_path, file_mtime, asset, cache_key, is_sequence)
                        else:
                            # Sequence - submit to worker pool
                            self._submit_worker_job(file_path, file_mtime, asset, cache_key, is_sequence)
                        
                        jobs_submitted += 1
                else:
                    # Pool is full, stop submitting
                    break
            
            # Stage 2: Process completed results from worker threads
            # Convert numpy arrays to QPixmap and emit signals
            # Process MULTIPLE results per iteration to keep up with workers
            results_processed = 0
            max_results_per_iteration = 5  # Process up to 5 results per loop
            
            while results_processed < max_results_per_iteration:
                try:
                    # Non-blocking check for results (timeout=0.01 seconds)
                    result = self.result_queue.get(timeout=0.01)
                    
                    if DEBUG_MODE:
                        print(f"[CACHE-THREAD] ← Received result from queue")
                    
                    file_path = result['file_path']
                    success = result['success']
                    
                    # Increment progress
                    self.processed_count += 1
                    if self.total_count > 0:
                        self.progress_update.emit(self.processed_count, self.total_count)
                    
                    if success:
                        # Convert numpy array to QPixmap (MUST be done in main thread)
                        img_data = result['data']
                        file_mtime = result['file_mtime']
                        cache_key = result['cache_key']
                        is_sequence = result['is_sequence']
                        
                        if DEBUG_MODE:
                            data_status = "DATA" if img_data is not None else "NULL"
                            print(f"[CACHE-THREAD] → Converting to QPixmap ({data_status})")
                        
                        if img_data is not None:
                            pixmap = self._numpy_to_pixmap(img_data)
                            
                            if pixmap and not pixmap.isNull():
                                if DEBUG_MODE:
                                    print(f"[CACHE-THREAD] ✓ QPixmap created: {pixmap.width()}×{pixmap.height()}")
                                
                                # Save to memory cache immediately (fast)
                                self.memory_cache.set(cache_key, pixmap)
                                
                                # Emit signal FIRST (UI updates immediately)
                                self.thumbnail_ready.emit(file_path, pixmap)
                                
                                # Save to disk cache ASYNC in worker pool (don't block UI)
                                # QImage.save() is thread-safe, so we can do this in background
                                if not is_sequence:
                                    self.executor.submit(
                                        self.disk_cache.set,
                                        file_path,
                                        file_mtime,
                                        pixmap,
                                        self.jpeg_quality
                                    )
                                
                                if DEBUG_MODE:
                                    print(f"[CACHE-THREAD] ✓ Thumbnail ready signal emitted: {Path(file_path).name}")
                            else:
                                if DEBUG_MODE:
                                    print(f"[CACHE-THREAD] Failed to convert to QPixmap: {Path(file_path).name}")
                                # Emit fail signal so delegate stops retrying
                                self.generation_failed.emit(file_path, "Failed to convert image data to QPixmap")
                        else:
                            # Worker returned NULL data (unsupported format or error)
                            if DEBUG_MODE:
                                print(f"[CACHE-THREAD] ⚠️ NULL data from worker: {Path(file_path).name}")
                            # Emit fail signal so delegate stops retrying
                            self.generation_failed.emit(file_path, "Unsupported format or generation failed")
                    else:
                        # Error occurred in worker
                        error_msg = result.get('error', 'Unknown error')
                        self.generation_failed.emit(file_path, error_msg)
                    
                    results_processed += 1
                        
                except:
                    # Queue empty or timeout - break inner loop
                    break
            
            # Small sleep if nothing to do
            if not self.queue and self.result_queue.empty():
                self.msleep(10)  # Shorter sleep for better responsiveness
            else:
                # Yield to other threads briefly
                self.msleep(1)
            
            # Debug stats (periodic)
            # Removed spammy STATS output - only log important events
            # if DEBUG_MODE:
            #     import time
            #     current_time = time.time()
            #     if current_time - self._last_stats_time > self._stats_interval:
            #         self._last_stats_time = current_time
            #         with self.futures_lock:
            #             active_count = len(self.active_futures)
            #         queue_size = len(self.queue)
            #         result_queue_size = self.result_queue.qsize()
            #         print(f"[STATS] Queue: {queue_size} | Active: {active_count} | Results: {result_queue_size} | Progress: {self.processed_count}/{self.total_count}")
    
    def _submit_worker_job(self, file_path, file_mtime, asset, cache_key, is_sequence):
        """Submit a job to the worker pool (extracted helper method)."""
        if DEBUG_MODE:
            print(f"[CACHE-THREAD] → Submitting to worker pool...")
            print(f"[CACHE-THREAD] → Executor state: {self.executor}")
        
        # Auto-tag color space BEFORE submitting to worker
        # This ensures tags are available when worker reads them
        if self.metadata_manager:
            try:
                # Auto-tag EXR and TX files for color space detection
                file_ext = str(file_path).lower()
                if file_ext.endswith('.exr') or file_ext.endswith('.tx'):
                    from .aces_color import auto_tag_file_colorspace
                    auto_tag_file_colorspace(file_path, self.metadata_manager)
                    if DEBUG_MODE:
                        print(f"[CACHE-THREAD] ✓ Auto-tagged: {Path(file_path).name}")
            except Exception as tag_error:
                if DEBUG_MODE:
                    print(f"[CACHE-THREAD] ⚠ Auto-tag failed: {tag_error}")
        
        self.cache_status.emit("generating")
        
        # Submit worker job (CPU-intensive work happens here in parallel)
        future = self.executor.submit(
            self._generate_thumbnail_data,
            file_path,
            asset
        )
        
        if DEBUG_MODE:
            print(f"[CACHE-THREAD] → Future created: {future}")
        
        # IMPORTANT: Store metadata FIRST, then add callback
        # This prevents race condition where callback fires before metadata exists
        with self.futures_lock:
            self.active_futures[file_path] = {
                'future': future,
                'file_path': file_path,
                'file_mtime': file_mtime,
                'asset': asset,
                'cache_key': cache_key,
                'is_sequence': is_sequence
            }
        
        # Add callback AFTER metadata is stored
        future.add_done_callback(
            lambda f, fp=file_path: self._worker_done_callback(f, fp)
        )
        
        if DEBUG_MODE:
            print(f"[CACHE-THREAD] → Callback registered")
            with self.futures_lock:
                active_count = len(self.active_futures)
            print(f"[CACHE-THREAD] ⚡ Worker job submitted (active jobs: {active_count})")

    def _worker_done_callback(self, future, file_path):
        """
        Callback when worker thread completes a job.
        Puts result in queue for main thread to process.
        Thread-safe - called by worker threads.
        """
        if DEBUG_MODE:
            import threading
            thread_name = threading.current_thread().name
            print(f"[{thread_name}] 📥 Callback triggered for: {Path(file_path).name}")
        
        import time
        
        # Try to get job info (with retry in case metadata not yet stored)
        job_info = None
        for retry in range(100):  # Try up to 100 times (100ms total)
            with self.futures_lock:
                job_info = self.active_futures.pop(file_path, None)
            
            if job_info:
                if DEBUG_MODE:
                    import threading
                    thread_name = threading.current_thread().name
                    print(f"[{thread_name}] ✓ Job info found (retry: {retry})")
                break
            
            # Metadata not yet stored, wait briefly and retry
            if DEBUG_MODE and retry == 0:
                import threading
                thread_name = threading.current_thread().name
                print(f"[{thread_name}] ⏳ Waiting for metadata to be stored...")
            time.sleep(0.001)  # 1ms wait
        
        if not job_info:
            if DEBUG_MODE:
                import threading
                thread_name = threading.current_thread().name
                print(f"[{thread_name}] ✗ No job info found after retries: {Path(file_path).name}")
            return
        
        try:
            # Get result from future
            result_data = future.result()
            
            if DEBUG_MODE:
                import threading
                thread_name = threading.current_thread().name
                result_type = "SUCCESS" if result_data is not None else "NULL"
                print(f"[{thread_name}] ✓ Worker completed: {Path(file_path).name} ({result_type})")
            
            # Put in result queue for main thread
            self.result_queue.put({
                'file_path': file_path,
                'file_mtime': job_info['file_mtime'],
                'cache_key': job_info['cache_key'],
                'is_sequence': job_info['is_sequence'],
                'success': True,
                'data': result_data
            })
            
            if DEBUG_MODE:
                import threading
                thread_name = threading.current_thread().name
                print(f"[{thread_name}] → Result queued for main thread")
            
        except Exception as e:
            # Worker encountered an error
            if DEBUG_MODE:
                print(f"[WORKER] Error generating thumbnail for {Path(file_path).name}: {e}")
            
            self.result_queue.put({
                'file_path': file_path,
                'file_mtime': job_info['file_mtime'],
                'cache_key': job_info['cache_key'],
                'is_sequence': job_info['is_sequence'],
                'success': False,
                'error': str(e)
            })
    
    def _numpy_to_pixmap(self, img_data):
        """
        Convert numpy array to QPixmap.
        MUST be called from main QThread (not worker threads).
        
        Args:
            img_data: dict with 'array', 'width', 'height', 'channels'
                      'is_rgb': True if already in RGB format (TurboJPEG), False if BGR (OpenCV)
        
        Returns:
            QPixmap or None
        """
        if img_data is None:
            return None
        
        try:
            import numpy as np
            import cv2
            
            img_array = img_data['array']
            width = img_data['width']
            height = img_data['height']
            channels = img_data['channels']
            is_rgb = img_data.get('is_rgb', False)  # Default: BGR (OpenCV)
            
            # Ensure uint8
            if img_array.dtype != np.uint8:
                img_array = img_array.astype(np.uint8)
            
            # Qt's Format_RGB888 expects RGB format
            # OpenCV outputs BGR, so we need to convert BGR→RGB
            # TurboJPEG/EXR/PIL output RGB, so no conversion needed
            
            if channels == 3:
                if is_rgb:
                    # Already RGB (from TurboJPEG) - no conversion
                    if DEBUG_MODE:
                        print(f"[PIXMAP] → RGB format (no conversion)")
                else:
                    # BGR from OpenCV - convert to RGB
                    if DEBUG_MODE:
                        print(f"[PIXMAP] → BGR format (converting to RGB)")
                    img_array = cv2.cvtColor(img_array, cv2.COLOR_BGR2RGB)
            elif channels == 4:
                if is_rgb:
                    # RGBA - no conversion
                    pass
                else:
                    # BGRA from OpenCV - convert to RGBA
                    img_array = cv2.cvtColor(img_array, cv2.COLOR_BGRA2RGBA)
            
            if PYSIDE_VERSION == 6:
                from PySide6.QtGui import QImage
            else:
                from PySide2.QtGui import QImage
            
            bytes_per_line = width * channels
            
            if channels == 3:
                q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
            elif channels == 4:
                q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGBA8888)
            elif channels == 1:
                q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_Grayscale8)
            else:
                if DEBUG_MODE:
                    print(f"[PIXMAP] Unsupported channel count: {channels}")
                return None
            
            pixmap = QPixmap.fromImage(q_image.copy())
            return pixmap
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[PIXMAP] Error converting to QPixmap: {e}")
            return None
    
    def _generate_thumbnail_data(self, file_path, asset=None):
        """
        Generate thumbnail data (numpy array) - runs in worker thread.
        This is the CPU-intensive part that can be parallelized.
        
        IMPORTANT: Does NOT create QPixmap (not thread-safe).
        Returns numpy array that will be converted to QPixmap in main thread.
        
        Args:
            file_path: Path to file
            asset: Optional AssetItem object
        
        Returns:
            dict with 'array', 'width', 'height', 'channels' or None
        """
        try:
            # Reuse existing _generate_thumbnail logic but return numpy array
            # instead of QPixmap
            from .utils import get_thumbnail_method
            
            # Check if this is a sequence - use middle frame for thumbnail
            if asset and asset.is_sequence and asset.sequence:
                middle_frame_path = asset.sequence.get_middle_frame()
                if middle_frame_path:
                    file_path = middle_frame_path
            
            extension = os.path.splitext(str(file_path))[1].lower()
            
            # Get thumbnail method from config
            thumbnail_method = get_thumbnail_method(extension)
            
            if thumbnail_method != 'none':
                # Generate actual thumbnail from file - returns numpy array data
                return self._generate_image_thumbnail_data(file_path)
            
            # 3D files and other types - return None (delegate will draw placeholder)
            return None
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[WORKER] Error in _generate_thumbnail_data: {e}")
            raise
    
    def _generate_image_thumbnail_data(self, file_path):
        """
        Worker-thread-safe version of _generate_image_thumbnail.
        Returns numpy array instead of QPixmap (for thread safety).
        
        This method does all CPU-intensive work (decode, resize, color conversion)
        and returns raw image data that will be converted to QPixmap in main thread.
        
        Args:
            file_path: Path to image file
            
        Returns:
            dict with 'array', 'width', 'height', 'channels' or None
        """
        try:
            import numpy as np
            extension = os.path.splitext(str(file_path))[1].lower()
            
            if DEBUG_MODE:
                import threading
                thread_name = threading.current_thread().name
                print(f"[{thread_name}] 🔧 Processing: {Path(file_path).name} ({extension})")
            
            # Special handling for video files - extract first frame
            if extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.flv', '.wmv']:
                try:
                    if DEBUG_MODE:
                        print(f"[{thread_name}] → Using OpenCV video capture for {extension}")
                    
                    return self._generate_video_thumbnail_data(file_path)
                except Exception as video_error:
                    if DEBUG_MODE:
                        print(f"[{thread_name}] ✗ Video thumbnail failed: {video_error}")
                    return None
            
            # For formats that need special handling, process them here
            # Most CPU-intensive formats (TIFF, HDR, EXR, PSD, TGA, etc.)
            
            if extension in ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.tif', '.tga', '.hdr']:
                # TurboJPEG for JPEG files (2-3x faster than OpenCV)
                if extension in ['.jpg', '.jpeg'] and TURBOJPEG_AVAILABLE:
                    try:
                        if DEBUG_MODE:
                            import threading
                            thread_name = threading.current_thread().name
                            print(f"[{thread_name}] → Using TurboJPEG for {extension}")
                        
                        # Read file into memory
                        with open(str(file_path), 'rb') as f:
                            jpeg_data = f.read()
                        
                        # Decode with TurboJPEG (fast!)
                        # scaling_factor: (1, 1)=full, (1, 2)=1/2, (1, 4)=1/4, (1, 8)=1/8
                        # For 256px thumbnails, use 1/8 scale for maximum speed
                        # IMPORTANT: Specify TJPF_RGB pixel format (default is BGR!)
                        from turbojpeg import TJPF_RGB
                        img = TURBOJPEG_INSTANCE.decode(jpeg_data, pixel_format=TJPF_RGB, scaling_factor=(1, 8))
                        
                        if DEBUG_MODE:
                            print(f"[{thread_name}] ✓ TurboJPEG loaded: {img.shape}")
                        
                        # TurboJPEG returns RGB format (not BGR like OpenCV!)
                        height, width = img.shape[:2]
                        channels = img.shape[2] if len(img.shape) == 3 else 1
                        
                        # Resize if still too large
                        if width > self.thumbnail_size or height > self.thumbnail_size:
                            import cv2
                            scale = min(self.thumbnail_size / width, self.thumbnail_size / height)
                            new_width = int(width * scale)
                            new_height = int(height * scale)
                            img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                            height, width = new_height, new_width
                        
                        if DEBUG_MODE:
                            print(f"[{thread_name}] → Returning: {width}×{height}, {channels} channels")
                        
                        return {
                            'array': img,
                            'width': width,
                            'height': height,
                            'channels': channels,
                            'is_rgb': True  # TurboJPEG outputs RGB
                        }
                    except Exception as turbo_error:
                        if DEBUG_MODE:
                            print(f"[{thread_name}] ✗ TurboJPEG failed: {turbo_error}, falling back to OpenCV")
                        # Fall through to OpenCV
                
                # Use OpenCV for fast decoding and resizing (thread-safe)
                import cv2
                cv2.setLogLevel(0)  # Silent
                
                if DEBUG_MODE:
                    import threading
                    thread_name = threading.current_thread().name
                    print(f"[{thread_name}] → Using OpenCV for {extension}")
                
                # Get optimized imread flags (pass file_path to check original dimensions)
                imread_flags = self._get_opencv_imread_flags(file_path=file_path)
                
                # Handle non-ASCII paths
                file_path_str = str(file_path)
                has_non_ascii = any(ord(c) > 127 for c in file_path_str)
                
                if DEBUG_MODE:
                    print(f"[{thread_name}] → Non-ASCII path: {has_non_ascii}")
                
                img = None
                if has_non_ascii:
                    # Buffer method for non-ASCII paths
                    if DEBUG_MODE:
                        print(f"[{thread_name}] → Loading via buffer...")
                    with open(file_path_str, 'rb') as f:
                        file_bytes = np.frombuffer(f.read(), np.uint8)
                    img = cv2.imdecode(file_bytes, imread_flags)
                else:
                    # Direct imread
                    if DEBUG_MODE:
                        print(f"[{thread_name}] → Loading via cv2.imread...")
                    img = cv2.imread(file_path_str, imread_flags)
                
                if img is None:
                    if DEBUG_MODE:
                        print(f"[{thread_name}] ✗ OpenCV failed to load image, trying PIL...")
                    # Fall through to PIL fallback below
                else:
                    if DEBUG_MODE:
                        print(f"[{thread_name}] ✓ OpenCV loaded: {img.shape}")
                    
                    # Keep in BGR format (will be converted to RGB in _numpy_to_pixmap)
                    if len(img.shape) == 3:
                        channels = img.shape[2]
                    else:
                        # Grayscale - convert to BGR for consistency
                        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                        channels = 3
                    
                    # Normalize bit depth
                    if img.dtype == np.uint16:
                        img = (img / 257).astype(np.uint8)
                    elif img.dtype in [np.float32, np.float64]:
                        img = np.clip(img, 0, 1)
                        img = (img * 255).astype(np.uint8)
                    
                    # Resize
                    height, width = img.shape[:2]
                    if width > self.thumbnail_size or height > self.thumbnail_size:
                        scale = min(self.thumbnail_size / width, self.thumbnail_size / height)
                        new_width = int(width * scale)
                        new_height = int(height * scale)
                        img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                        height, width = new_height, new_width
                    
                    if DEBUG_MODE:
                        import threading
                        thread_name = threading.current_thread().name
                        print(f"[{thread_name}] → Returning: {width}×{height}, {channels} channels")
                    
                    return {
                        'array': img,
                        'width': width,
                        'height': height,
                        'channels': channels,
                        'is_rgb': False  # OpenCV outputs BGR
                    }
            
            elif extension == '.tx':
                # TX: Use OpenImageIO loader
                return self._generate_tx_thumbnail_data(file_path)
            
            elif extension == '.pdf':
                # PDF: Use PyMuPDF loader
                return self._generate_pdf_thumbnail_data(file_path)
            
            elif extension == '.exr':
                # EXR: Use optimized loader but return numpy array
                return self._generate_exr_thumbnail_data(file_path)
            
            elif extension == '.psd':
                # PSD: Use PIL/psd-tools
                return self._generate_psd_thumbnail_data(file_path)
            
            # For other formats or if OpenCV fails, fall back to QPixmap method
            # NOTE: This is less optimal as it requires QPixmap creation in worker thread
            # But we'll do a workaround by using PIL/imageio for thread-safe loading
            
            if DEBUG_MODE:
                import threading
                thread_name = threading.current_thread().name
                print(f"[{thread_name}] → Trying PIL fallback...")
            
            try:
                from PIL import Image
                Image.MAX_IMAGE_PIXELS = None
                
                pil_img = Image.open(str(file_path))
                pil_img = pil_img.convert('RGB')
                pil_img.thumbnail((self.thumbnail_size, self.thumbnail_size), Image.Resampling.LANCZOS)
                
                img_array = np.array(pil_img)
                height, width = img_array.shape[:2]
                channels = 3
                
                if DEBUG_MODE:
                    print(f"[{thread_name}] ✓ PIL loaded: {width}×{height}")
                
                return {
                    'array': img_array,
                    'width': width,
                    'height': height,
                    'channels': channels,
                    'is_rgb': True  # PIL outputs RGB
                }
            except Exception as pil_error:
                if DEBUG_MODE:
                    print(f"[{thread_name}] ✗ PIL fallback failed: {pil_error}")
                return None
            
        except Exception as e:
            if DEBUG_MODE:
                import threading
                thread_name = threading.current_thread().name
                print(f"[{thread_name}] ✗ EXCEPTION in _generate_image_thumbnail_data: {e}")
                import traceback
                traceback.print_exc()
            raise
    
    def _generate_exr_thumbnail_data(self, file_path):
        """
        Generate EXR thumbnail as numpy array (worker thread safe).
        Returns dict with array data instead of QPixmap.
        
        Includes ACES color management if file is tagged appropriately.
        Supports all channel naming conventions (same as optimized loader).
        """
        try:
            import numpy as np
            import OpenEXR
            import Imath
            
            # Open EXR file
            exr_file = OpenEXR.InputFile(str(file_path))
            header = exr_file.header()
            
            dw = header['dataWindow']
            width = dw.max.x - dw.min.x + 1
            height = dw.max.y - dw.min.y + 1
            
            # Get channels
            channels_dict = header['channels']
            channel_names = list(channels_dict.keys())
            
            if DEBUG_MODE:
                import threading
                thread_name = threading.current_thread().name
                print(f"[{thread_name}] EXR channels: {', '.join(channel_names)}")
            
            FLOAT = Imath.PixelType(Imath.PixelType.FLOAT)
            
            # Try to find RGB channels (supports multiple naming conventions)
            rgb = None
            
            # 1. Try standard separate R, G, B channels
            if all(c in channels_dict for c in ['R', 'G', 'B']):
                if DEBUG_MODE:
                    import threading
                    thread_name = threading.current_thread().name
                    print(f"[{thread_name}] → Using R/G/B channels")
                r_str = exr_file.channel('R', FLOAT)
                g_str = exr_file.channel('G', FLOAT)
                b_str = exr_file.channel('B', FLOAT)
                
                r = np.frombuffer(r_str, dtype=np.float32).reshape(height, width)
                g = np.frombuffer(g_str, dtype=np.float32).reshape(height, width)
                b = np.frombuffer(b_str, dtype=np.float32).reshape(height, width)
                
                rgb = np.stack([r, g, b], axis=2)
            
            # 2. Try Beauty pass (common in render layers)
            elif all(c in channels_dict for c in ['Beauty.R', 'Beauty.G', 'Beauty.B']):
                if DEBUG_MODE:
                    import threading
                    thread_name = threading.current_thread().name
                    print(f"[{thread_name}] → Using Beauty.R/G/B channels")
                r_str = exr_file.channel('Beauty.R', FLOAT)
                g_str = exr_file.channel('Beauty.G', FLOAT)
                b_str = exr_file.channel('Beauty.B', FLOAT)
                
                r = np.frombuffer(r_str, dtype=np.float32).reshape(height, width)
                g = np.frombuffer(g_str, dtype=np.float32).reshape(height, width)
                b = np.frombuffer(b_str, dtype=np.float32).reshape(height, width)
                
                rgb = np.stack([r, g, b], axis=2)
            
            # 3. Try first layer with .R .G .B (generic multi-layer)
            if rgb is None:
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
                    if all(c in channels_dict for c in [r_name, g_name, b_name]):
                        if DEBUG_MODE:
                            import threading
                            thread_name = threading.current_thread().name
                            print(f"[{thread_name}] → Using layer: {prefix}")
                        r_str = exr_file.channel(r_name, FLOAT)
                        g_str = exr_file.channel(g_name, FLOAT)
                        b_str = exr_file.channel(b_name, FLOAT)
                        
                        r = np.frombuffer(r_str, dtype=np.float32).reshape(height, width)
                        g = np.frombuffer(g_str, dtype=np.float32).reshape(height, width)
                        b = np.frombuffer(b_str, dtype=np.float32).reshape(height, width)
                        
                        rgb = np.stack([r, g, b], axis=2)
                        break
            
            # 4. Try single channel (grayscale) - Y, Z, depth, A, alpha, luminance
            if rgb is None:
                single_channels = ["Y", "Z", "depth", "A", "alpha", "luminance"]
                for ch_name in single_channels:
                    if ch_name in channels_dict:
                        if DEBUG_MODE:
                            import threading
                            thread_name = threading.current_thread().name
                            print(f"[{thread_name}] → Using single channel: {ch_name}")
                        gray_str = exr_file.channel(ch_name, FLOAT)
                        gray = np.frombuffer(gray_str, dtype=np.float32).reshape(height, width)
                        # Convert to RGB by repeating channel
                        rgb = np.stack([gray, gray, gray], axis=2)
                        break
            
            # 5. Last resort: use ANY available channel as grayscale
            if rgb is None and len(channels_dict) > 0:
                first_channel_name = channel_names[0]
                if DEBUG_MODE:
                    import threading
                    thread_name = threading.current_thread().name
                    print(f"[{thread_name}] → Using first available: {first_channel_name}")
                gray_str = exr_file.channel(first_channel_name, FLOAT)
                gray = np.frombuffer(gray_str, dtype=np.float32).reshape(height, width)
                # Convert to RGB by repeating channel
                rgb = np.stack([gray, gray, gray], axis=2)
            
            if rgb is None:
                if DEBUG_MODE:
                    print(f"[EXR-DATA] No usable channels found")
                return None
            
            # Check if we should use ACES color management
            use_aces = False
            if self.metadata_manager:
                try:
                    file_metadata = self.metadata_manager.get_file_metadata(str(file_path))
                    file_tags = file_metadata.get('tags', [])
                    tag_names_lower = [tag['name'].lower() for tag in file_tags]
                    
                    # Check for ACEScg tag (case-insensitive)
                    if "acescg" in tag_names_lower or "srgb(aces)" in tag_names_lower:
                        use_aces = True
                        if DEBUG_MODE:
                            import threading
                            thread_name = threading.current_thread().name
                            print(f"[{thread_name}] → EXR: Using ACES view transform")
                except Exception as tag_error:
                    if DEBUG_MODE:
                        print(f"[EXR-DATA] Tag check failed: {tag_error}")
            
            # Apply tone mapping (ACES or standard)
            if use_aces:
                try:
                    from .aces_color import apply_aces_view_transform
                    # Apply ACES with -1 stop compensation
                    rgb_tonemapped = apply_aces_view_transform(rgb, exposure=-1.0)
                    if DEBUG_MODE:
                        import threading
                        thread_name = threading.current_thread().name
                        print(f"[{thread_name}] → EXR: Applied ACES RRT+ODT (exposure: -1.0)")
                except Exception as aces_error:
                    if DEBUG_MODE:
                        print(f"[EXR-DATA] ACES failed, using Reinhard: {aces_error}")
                    # Fallback to Reinhard
                    rgb = np.clip(rgb, 0, None)  # Clamp negatives FIRST
                    rgb_tonemapped = rgb / (1.0 + rgb)  # Reinhard
                    gamma = 1.0 / 2.2
                    rgb_tonemapped = np.power(rgb_tonemapped, gamma)
            else:
                # Standard Reinhard tone mapping for Linear sRGB
                rgb = np.clip(rgb, 0, None)  # Clamp negatives FIRST
                rgb_tonemapped = rgb / (1.0 + rgb)  # Reinhard
                
                # Gamma correction (2.2 for sRGB)
                gamma = 1.0 / 2.2
                rgb_tonemapped = np.power(rgb_tonemapped, gamma)
            
            # Convert to 8-bit
            rgb_8bit = (rgb_tonemapped * 255).astype(np.uint8)
            
            # Resize if needed
            if width > self.thumbnail_size or height > self.thumbnail_size:
                import cv2
                scale = min(self.thumbnail_size / width, self.thumbnail_size / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                rgb_8bit = cv2.resize(rgb_8bit, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                height, width = new_height, new_width
            
            return {
                'array': rgb_8bit,
                'width': width,
                'height': height,
                'channels': 3,
                'is_rgb': True  # EXR outputs RGB (not BGR)
            }
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[EXR-DATA] Error: {e}")
            raise
    
    def _generate_tx_thumbnail_data(self, file_path):
        """
        Generate TX (RenderMan texture) thumbnail as numpy array (worker thread safe).
        Returns dict with array data instead of QPixmap.
        
        Uses OpenImageIO to load .tx files with mip level support.
        Includes ACES color management if file is tagged appropriately.
        """
        try:
            import numpy as np
            
            # Load using OpenImageIO (returns float32 HDR data)
            from .widgets import load_oiio_image_array
            
            # Load mip level 1 for fast thumbnail (half resolution)
            rgb = load_oiio_image_array(file_path, max_size=self.thumbnail_size, mip_level=1)
            
            if rgb is None:
                return None
            
            height, width = rgb.shape[:2]
            channels = rgb.shape[2] if len(rgb.shape) == 3 else 1
            
            # Check if we should use ACES color management (same logic as EXR)
            use_aces = False
            if self.metadata_manager:
                try:
                    file_metadata = self.metadata_manager.get_file_metadata(str(file_path))
                    file_tags = file_metadata.get('tags', [])
                    tag_names_lower = [tag['name'].lower() for tag in file_tags]
                    
                    # Check for ACEScg tag (case-insensitive)
                    if "acescg" in tag_names_lower or "srgb(aces)" in tag_names_lower:
                        use_aces = True
                        if DEBUG_MODE:
                            import threading
                            thread_name = threading.current_thread().name
                            print(f"[{thread_name}] → TX: Using ACES view transform")
                except Exception as tag_error:
                    if DEBUG_MODE:
                        print(f"[TX-DATA] Tag check failed: {tag_error}")
            
            # Apply tone mapping (ACES or standard)
            if use_aces:
                try:
                    from .aces_color import apply_aces_view_transform
                    # Apply ACES with -1 stop compensation
                    rgb_tonemapped = apply_aces_view_transform(rgb, exposure=-1.0)
                    if DEBUG_MODE:
                        import threading
                        thread_name = threading.current_thread().name
                        print(f"[{thread_name}] → TX: Applied ACES RRT+ODT (exposure: -1.0)")
                except Exception as aces_error:
                    if DEBUG_MODE:
                        print(f"[TX-DATA] ACES failed, using Reinhard: {aces_error}")
                    # Fallback to Reinhard
                    rgb = np.clip(rgb, 0, None)  # Clamp negatives FIRST
                    rgb_tonemapped = rgb / (1.0 + rgb)  # Reinhard
                    gamma = 1.0 / 2.2
                    rgb_tonemapped = np.power(rgb_tonemapped, gamma)
            else:
                # Standard Reinhard tone mapping for Linear sRGB
                rgb = np.clip(rgb, 0, None)  # Clamp negatives FIRST
                rgb_tonemapped = rgb / (1.0 + rgb)  # Reinhard
                
                # Gamma correction (2.2 for sRGB)
                gamma = 1.0 / 2.2
                rgb_tonemapped = np.power(rgb_tonemapped, gamma)
            
            # Convert to 8-bit
            rgb_8bit = (rgb_tonemapped * 255).astype(np.uint8)
            
            return {
                'array': rgb_8bit,
                'width': width,
                'height': height,
                'channels': channels,
                'is_rgb': True  # OIIO outputs RGB
            }
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[TX-DATA] Error: {e}")
            raise
    
    def _generate_psd_thumbnail_data(self, file_path):
        """
        Generate PSD thumbnail as numpy array (worker thread safe).
        Returns dict with array data instead of QPixmap.
        """
        try:
            import numpy as np
            from PIL import Image
            
            # Try to load PSD composite first
            try:
                from psd_tools import PSDImage
                psd = PSDImage.open(str(file_path))
                pil_img = psd.composite()
                
                if pil_img:
                    pil_img = pil_img.convert('RGB')
                    pil_img.thumbnail((self.thumbnail_size, self.thumbnail_size), Image.Resampling.LANCZOS)
                    
                    img_array = np.array(pil_img)
                    height, width = img_array.shape[:2]
                    
                    return {
                        'array': img_array,
                        'width': width,
                        'height': height,
                        'channels': 3,
                        'is_rgb': True  # PIL/psd-tools output RGB
                    }
            except Exception as psd_error:
                if DEBUG_MODE:
                    print(f"[PSD-DATA] psd-tools failed: {psd_error}")
            
            # Fallback to PIL
            Image.MAX_IMAGE_PIXELS = None
            pil_img = Image.open(str(file_path))
            pil_img = pil_img.convert('RGB')
            pil_img.thumbnail((self.thumbnail_size, self.thumbnail_size), Image.Resampling.LANCZOS)
            
            img_array = np.array(pil_img)
            height, width = img_array.shape[:2]
            
            return {
                'array': img_array,
                'width': width,
                'height': height,
                'channels': 3,
                'is_rgb': True  # PIL outputs RGB
            }
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[PSD-DATA] Error: {e}")
            raise
    
    def _generate_pdf_thumbnail_data(self, file_path):
        """
        Generate PDF thumbnail as numpy array (worker thread safe).
        Returns dict with array data instead of QPixmap.
        
        Renders first page using PyMuPDF (fitz).
        """
        try:
            import numpy as np
            
            # Check if PyMuPDF is available
            try:
                import fitz  # PyMuPDF
            except ImportError:
                if DEBUG_MODE:
                    print(f"[PDF-DATA] PyMuPDF not available")
                return None
            
            # Open PDF document
            doc = fitz.open(str(file_path))
            
            # Check if encrypted
            if doc.is_encrypted:
                doc.close()
                return None
            
            page_count = len(doc)
            if page_count == 0:
                doc.close()
                return None
            
            # Get first page
            page = doc[0]
            
            # Get page dimensions
            rect = page.rect
            width = int(rect.width)
            height = int(rect.height)
            
            # Calculate zoom to fit thumbnail size
            zoom = min(self.thumbnail_size / width, self.thumbnail_size / height, 2.0)
            mat = fitz.Matrix(zoom, zoom)
            
            # Render page to pixmap
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # Convert to numpy array (RGB format)
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            
            # Close document
            doc.close()
            
            return {
                'array': img_array,
                'width': pix.width,
                'height': pix.height,
                'channels': pix.n,
                'is_rgb': True  # PyMuPDF outputs RGB
            }
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[PDF-DATA] Error: {e}")
            return None
    
    def _get_opencv_imread_flags(self, file_path=None):
        """
        Calculate optimal OpenCV imread flags based on thumbnail size AND original image dimensions.
        Uses IMREAD_REDUCED_* for faster decoding of large TIFF/HDR images.
        
        Optimized logic:
        - Min pre-downsampled size: 256px (max thumbnail size)
        - Only use IMREAD_REDUCED_* if original image > 512px (ensures 256px minimum after reduction)
        - Small images loaded at full resolution (fast anyway)
        
        Args:
            file_path: Path to image file (optional, for size checking)
        
        Returns:
            OpenCV imread flags (int)
        """
        import cv2
        # Suppress OpenCV/FFmpeg verbose output
        cv2.setLogLevel(0)  # 0 = Silent
        
        # If no file path provided, use default flags
        if file_path is None:
            if DEBUG_MODE:
                print(f"[OPENCV] No file path, using default IMREAD_COLOR")
            return cv2.IMREAD_COLOR | cv2.IMREAD_ANYDEPTH
        
        # Quick header read to get original image dimensions (PIL is very fast for this)
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                width, height = img.size
                min_dimension = min(width, height)
                
            if DEBUG_MODE:
                print(f"[OPENCV] Image size: {width}×{height}px (min={min_dimension}px)")
            
            # REDUCTION LOGIC (target: 256px minimum after reduction)
            # - < 512px     → Full resolution (360×360 stays 360×360)
            # - 512-1023px  → 1/2 reduction (512×512 → 256×256)
            # - 1024-2047px → 1/4 reduction (1024×1024 → 256×256)
            # - 2048px+     → 1/8 reduction (2048×2048 → 256×256)
            
            if min_dimension >= 2048:
                # 1/8 reduction: 2048×2048 → 256×256
                if DEBUG_MODE:
                    print(f"[OPENCV] 1/8 reduction (IMREAD_REDUCED_COLOR_8): {min_dimension}px → {min_dimension//8}px")
                return cv2.IMREAD_REDUCED_COLOR_8 | cv2.IMREAD_ANYDEPTH
            elif min_dimension >= 1024:
                # 1/4 reduction: 1024×1024 → 256×256
                if DEBUG_MODE:
                    print(f"[OPENCV] 1/4 reduction (IMREAD_REDUCED_COLOR_4): {min_dimension}px → {min_dimension//4}px")
                return cv2.IMREAD_REDUCED_COLOR_4 | cv2.IMREAD_ANYDEPTH
            elif min_dimension >= 512:
                # 1/2 reduction: 512×512 → 256×256
                if DEBUG_MODE:
                    print(f"[OPENCV] 1/2 reduction (IMREAD_REDUCED_COLOR_2): {min_dimension}px → {min_dimension//2}px")
                return cv2.IMREAD_REDUCED_COLOR_2 | cv2.IMREAD_ANYDEPTH
            else:
                # < 512px: Full resolution (360×360 stays 360×360, fast to load anyway)
                if DEBUG_MODE:
                    print(f"[OPENCV] Full resolution (no reduction): {min_dimension}px")
                return cv2.IMREAD_COLOR | cv2.IMREAD_ANYDEPTH
                
        except Exception as e:
            # If PIL fails, use conservative default (no reduction)
            if DEBUG_MODE:
                print(f"[OPENCV] PIL header read failed ({e}), using full resolution")
            return cv2.IMREAD_COLOR | cv2.IMREAD_ANYDEPTH
    
    @staticmethod
    def _load_psd_composite(file_path, max_size=None):
        """
        Load full PSD composite image using psd-tools library (STATIC METHOD)
        
        This loads the full-resolution flattened/composite image from a PSD file,
        including support for 32-bit PSDs that PIL cannot handle.
        
        Args:
            file_path: Path to PSD file
            max_size: Optional max dimension (for thumbnails/previews)
            
        Returns:
            QPixmap or None
        """
        import sys
        import os
        
        # Add external_libs to path
        external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
        if external_libs not in sys.path:
            sys.path.insert(0, external_libs)
        
        try:
            from psd_tools import PSDImage
            from PIL import Image
            
            if DEBUG_MODE:
                print(f"[PSD] Loading composite with psd-tools: {Path(file_path).name}")
            
            # Open PSD
            psd = PSDImage.open(str(file_path))
            
            if DEBUG_MODE:
                print(f"[PSD] PSD size: {psd.width}x{psd.height}, depth={psd.depth}-bit")
            
            # Get composite (flattened) image as PIL Image
            composite = psd.composite()
            
            if composite is None:
                if DEBUG_MODE:
                    print(f"[PSD] No composite available")
                return None
            
            # Preserve alpha channel if present
            if composite.mode in ('RGBA', 'LA', 'PA'):
                if DEBUG_MODE:
                    print(f"[PSD] Preserving transparency: {composite.mode} → RGBA")
                composite = composite.convert('RGBA')
            elif composite.mode == 'L':
                composite = composite.convert('RGB')
            elif composite.mode not in ('RGB', 'RGBA'):
                if DEBUG_MODE:
                    print(f"[PSD] Converting {composite.mode} → RGBA")
                composite = composite.convert('RGBA')
            
            # Resize if max_size specified
            if max_size:
                composite.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                if DEBUG_MODE:
                    print(f"[PSD] Resized to: {composite.size}")
            
            # Convert PIL Image to QPixmap with proper byte order handling
            import numpy as np
            
            if PYSIDE_VERSION == 6:
                from PySide6.QtGui import QImage
            else:
                from PySide2.QtGui import QImage
            
            # Handle RGBA with correct byte order for Qt
            if composite.mode == 'RGBA':
                # Convert PIL RGBA to Qt-compatible BGRA byte order
                data = composite.tobytes("raw", "BGRA")
                width, height = composite.size
                bytes_per_line = width * 4
                # Format_ARGB32 expects BGRA byte order on little-endian systems (Windows)
                q_image = QImage(data, width, height, bytes_per_line, QImage.Format_ARGB32)
            else:
                # RGB888 has correct byte order
                img_array = np.array(composite)
                height, width = img_array.shape[:2]
                bytes_per_line = width * 3
                q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
            
            if DEBUG_MODE:
                print(f"[PSD] ✓ Composite loaded: {width}x{height}, mode={composite.mode}")
            
            return QPixmap.fromImage(q_image.copy())
            
        except ImportError:
            if DEBUG_MODE:
                print(f"[PSD] psd-tools not available, falling back to thumbnail extraction")
            return None
        except Exception as e:
            if DEBUG_MODE:
                print(f"[PSD] Failed to load composite: {e}")
            return None
    
    @staticmethod
    def _extract_psd_thumbnail(file_path, thumbnail_size=256):
        """
        Extract embedded thumbnail from PSD file (STATIC METHOD)
        
        Many PSD files (especially 32-bit) contain embedded JPEG/PNG thumbnails
        that can be extracted without loading the full image data.
        
        Args:
            file_path: Path to PSD file
            thumbnail_size: Max dimension for the thumbnail
            
        Returns:
            QPixmap or None
        """
        import struct
        from io import BytesIO
        import sys
        import os
        
        # Add external_libs to path for PIL import
        external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
        if external_libs not in sys.path:
            sys.path.insert(0, external_libs)
        
        try:
            with open(str(file_path), 'rb') as f:
                # Read PSD header
                signature = f.read(4)
                if signature != b'8BPS':
                    return None
                
                version = struct.unpack('>H', f.read(2))[0]
                f.read(6)  # Reserved
                channels = struct.unpack('>H', f.read(2))[0]
                height = struct.unpack('>I', f.read(4))[0]
                width = struct.unpack('>I', f.read(4))[0]
                depth = struct.unpack('>H', f.read(2))[0]
                color_mode = struct.unpack('>H', f.read(2))[0]
                
                # Skip color mode data section
                color_mode_data_len = struct.unpack('>I', f.read(4))[0]
                f.read(color_mode_data_len)
                
                # Read image resources section (contains thumbnails)
                image_resources_len = struct.unpack('>I', f.read(4))[0]
                resources_start = f.tell()
                resources_end = resources_start + image_resources_len
                
                # Look for thumbnail resources
                # Resource ID 1033 = Thumbnail (Photoshop 5.0+, JPEG)
                # Resource ID 1036 = Thumbnail (Photoshop 4.0, RGB)
                while f.tell() < resources_end:
                    try:
                        # Read resource block
                        res_signature = f.read(4)
                        if res_signature != b'8BIM':
                            break
                        
                        res_id = struct.unpack('>H', f.read(2))[0]
                        
                        # Read pascal string name (padded to even length)
                        name_len = struct.unpack('B', f.read(1))[0]
                        if name_len > 0:
                            f.read(name_len)
                        if (name_len + 1) % 2 != 0:
                            f.read(1)  # Padding
                        
                        # Read resource data size
                        res_size = struct.unpack('>I', f.read(4))[0]
                        res_data_start = f.tell()
                        
                        # Check if this is a thumbnail resource
                        if res_id in [1033, 1036]:
                            if DEBUG_MODE:
                                print(f"[PSD] Found thumbnail resource ID {res_id}, size={res_size}")
                            
                            if res_id == 1033:
                                # JPEG thumbnail (Photoshop 5.0+)
                                # Skip format (4), width (4), height (4), widthbytes (4), 
                                # total size (4), compressed size (4), bpp (2), planes (2) = 28 bytes
                                f.read(28)
                                jpeg_data = f.read(res_size - 28)
                                
                                # Load JPEG thumbnail
                                from PIL import Image
                                thumb_img = Image.open(BytesIO(jpeg_data))
                                
                                # Resize to thumbnail size
                                thumb_img.thumbnail((thumbnail_size, thumbnail_size), Image.Resampling.LANCZOS)
                                
                                # Convert to QPixmap
                                import numpy as np
                                img_array = np.array(thumb_img.convert('RGB'))
                                height, width = img_array.shape[:2]
                                
                                if PYSIDE_VERSION == 6:
                                    from PySide6.QtGui import QImage
                                else:
                                    from PySide2.QtGui import QImage
                                
                                bytes_per_line = width * 3
                                q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                                return QPixmap.fromImage(q_image.copy())
                            
                            elif res_id == 1036:
                                # RGB thumbnail (Photoshop 4.0)
                                # Format: format (4), width (4), height (4), widthbytes (4), 
                                # total size (4), compressed size (4), bpp (2), planes (2) = 28 bytes
                                # Then raw RGB data OR JPEG data (check compressed_size)
                                if DEBUG_MODE:
                                    print(f"[PSD] Processing resource 1036 (Photoshop 4.0 RGB thumbnail)")
                                
                                thumb_format = struct.unpack('>I', f.read(4))[0]  # 1 = kRawRGB
                                thumb_width = struct.unpack('>I', f.read(4))[0]
                                thumb_height = struct.unpack('>I', f.read(4))[0]
                                widthbytes = struct.unpack('>I', f.read(4))[0]
                                total_size = struct.unpack('>I', f.read(4))[0]
                                compressed_size = struct.unpack('>I', f.read(4))[0]
                                bpp = struct.unpack('>H', f.read(2))[0]
                                planes = struct.unpack('>H', f.read(2))[0]
                                
                                if DEBUG_MODE:
                                    print(f"[PSD] Thumb size: {thumb_width}x{thumb_height}, format={thumb_format}, bpp={bpp}")
                                    print(f"[PSD] Total size: {total_size}, Compressed: {compressed_size}")
                                
                                # Read thumbnail data (remaining bytes after header)
                                rgb_data_size = res_size - 28
                                rgb_data = f.read(rgb_data_size)
                                
                                # Check if it's compressed (JPEG)
                                from PIL import Image
                                try:
                                    if compressed_size > 0 and compressed_size < total_size:
                                        # Compressed thumbnail (usually JPEG)
                                        if DEBUG_MODE:
                                            print(f"[PSD] Thumbnail is compressed (JPEG), size={compressed_size}")
                                        thumb_img = Image.open(BytesIO(rgb_data))
                                    else:
                                        # Uncompressed RGB data
                                        if DEBUG_MODE:
                                            print(f"[PSD] Thumbnail is raw RGB data")
                                        thumb_img = Image.frombytes('RGB', (thumb_width, thumb_height), rgb_data)
                                    
                                    # Resize to thumbnail size
                                    thumb_img.thumbnail((thumbnail_size, thumbnail_size), Image.Resampling.LANCZOS)
                                    
                                    # Convert to QPixmap
                                    import numpy as np
                                    img_array = np.array(thumb_img.convert('RGB'))
                                    height, width = img_array.shape[:2]
                                    
                                    if PYSIDE_VERSION == 6:
                                        from PySide6.QtGui import QImage
                                    else:
                                        from PySide2.QtGui import QImage
                                    
                                    bytes_per_line = width * 3
                                    q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                                    if DEBUG_MODE:
                                        print(f"[PSD] ✓ Resource 1036 thumbnail extracted: {width}x{height}")
                                    return QPixmap.fromImage(q_image.copy())
                                except Exception as rgb_error:
                                    if DEBUG_MODE:
                                        print(f"[PSD] Failed to decode RGB thumbnail: {rgb_error}")
                        
                        # Skip to next resource (data is padded to even length)
                        f.seek(res_data_start + res_size)
                        if res_size % 2 != 0:
                            f.read(1)  # Padding
                            
                    except struct.error:
                        break
                
        except Exception as e:
            if DEBUG_MODE:
                print(f"[PSD] Thumbnail extraction error: {e}")
            return None
        
        return None
    
    def _generate_thumbnail(self, file_path, asset=None):
        """
        Generate thumbnail from file
        
        For images/PDFs: Load and scale the actual image/first page
        For sequences: Load middle frame and add badge overlay
        For 3D files: Generate gradient icon (safe mode)
        
        Args:
            file_path: Path to file (or sequence pattern for sequences)
            asset: Optional AssetItem object (for sequence support)
            
        Returns:
            QPixmap or None
        """
        # Early exit if thread is stopping
        if not self.is_running:
            return None
        
        from .utils import get_thumbnail_method
        
        # Check if this is a sequence - use middle frame for thumbnail
        if asset and asset.is_sequence and asset.sequence:
            middle_frame_path = asset.sequence.get_middle_frame()
            if middle_frame_path:
                # Generate thumbnail from middle frame (WITHOUT badge - delegate will add it)
                pixmap = self._generate_image_thumbnail(middle_frame_path)
                
                # Don't add badge here - the delegate will draw it at the correct display size
                # if pixmap and not pixmap.isNull():
                #     pixmap = self._add_sequence_badge(pixmap, asset.sequence.frame_count)
                
                return pixmap
        
        extension = os.path.splitext(str(file_path))[1].lower()
        
        # Get thumbnail method from config
        thumbnail_method = get_thumbnail_method(extension)
        
        if thumbnail_method != 'none':
            # Generate actual thumbnail from file
            return self._generate_image_thumbnail(file_path)
        
        # 3D files and other types - don't generate placeholder in cache
        # The delegate will draw gradient placeholder directly (faster, no scaling)
        return None
    
    def _add_sequence_badge(self, pixmap, frame_count):
        """
        Add badge overlay to sequence thumbnail showing frame count
        
        Args:
            pixmap: Original thumbnail pixmap
            frame_count: Number of frames in sequence
            
        Returns:
            QPixmap with badge overlay
        """
        if PYSIDE_VERSION == 6:
            from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush
            from PySide6.QtCore import Qt, QRect
        else:
            from PySide2.QtGui import QPainter, QColor, QFont, QPen, QBrush
            from PySide2.QtCore import Qt, QRect
        
        # Create a copy to draw on
        result = pixmap.copy()
        
        # Setup painter
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Badge dimensions - scale with thumbnail size but keep readable minimum
        # For very small thumbnails, use aggressive scaling to remain visible
        thumb_size = result.height()
        
        if thumb_size <= 32:
            # Tiny thumbnails (list view): use 35% with higher minimum
            badge_height = max(20, int(thumb_size * 0.35))
        elif thumb_size < 64:
            # Small thumbnails: use 28% with higher minimum
            badge_height = max(18, int(thumb_size * 0.28))
        else:
            # Normal thumbnails: use 15% with standard minimum
            badge_height = max(16, int(thumb_size * 0.15))
        
        badge_margin = 2
        
        # Badge text
        badge_text = f"{frame_count} frames"
        
        # Setup font - larger minimum for small thumbnails
        font = QFont()
        if thumb_size <= 32:
            # Tiny thumbnails: much larger relative font (min 11px)
            font_size = max(11, int(badge_height * 0.65))
            font.setPixelSize(font_size)
        elif thumb_size < 64:
            # Small thumbnails: larger font (min 10px)
            font_size = max(10, int(badge_height * 0.62))
            font.setPixelSize(font_size)
        else:
            # Normal thumbnails: standard font (min 9px)
            font_size = max(9, int(badge_height * 0.6))
            font.setPixelSize(font_size)
        font.setBold(True)
        painter.setFont(font)
        
        # Calculate text size
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(badge_text)
        text_height = metrics.height()
        
        # Badge rectangle (bottom of thumbnail)
        badge_width = text_width + badge_margin * 4
        badge_rect = QRect(
            (result.width() - badge_width) // 2,  # Centered horizontally
            result.height() - badge_height - badge_margin,  # Bottom
            badge_width,
            badge_height
        )
        
        # Draw semi-transparent background
        painter.setPen(Qt.NoPen)
        bg_color = QColor(0, 0, 0, 180)  # Black with 70% opacity
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(badge_rect, 3, 3)
        
        # Draw text
        painter.setPen(QPen(QColor(255, 255, 255)))  # White text
        text_rect = QRect(
            badge_rect.x() + badge_margin * 2,
            badge_rect.y() + (badge_height - text_height) // 2,
            text_width,
            text_height
        )
        painter.drawText(text_rect, Qt.AlignCenter, badge_text)
        
        painter.end()
        
        return result
    
    def _generate_video_thumbnail_data(self, file_path):
        """
        Worker-thread-safe video thumbnail generation.
        Returns numpy array instead of QPixmap.
        
        Args:
            file_path: Path to video file
            
        Returns:
            dict with 'array', 'width', 'height', 'channels' or None
        """
        try:
            import cv2
            import numpy as np
            import threading
            
            thread_name = threading.current_thread().name if DEBUG_MODE else None
            
            # Suppress OpenCV/FFmpeg verbose output
            cv2.setLogLevel(0)
            
            # Open video file
            cap = cv2.VideoCapture(str(file_path))
            
            if not cap.isOpened():
                if DEBUG_MODE:
                    print(f"[{thread_name}] ✗ Failed to open video file")
                return None
            
            # Read first frame (faster than seeking to middle)
            ret, frame = cap.read()
            cap.release()
            
            if not ret or frame is None:
                if DEBUG_MODE:
                    print(f"[{thread_name}] ✗ Failed to read video frame")
                return None
            
            if DEBUG_MODE:
                print(f"[{thread_name}] ✓ Video frame captured: {frame.shape}")
            
            # Keep in BGR format (will be converted to RGB in _numpy_to_pixmap)
            height, width = frame.shape[:2]
            channels = 3
            
            # Resize if needed
            if width > self.thumbnail_size or height > self.thumbnail_size:
                scale = min(self.thumbnail_size / width, self.thumbnail_size / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                height, width = new_height, new_width
            
            if DEBUG_MODE:
                print(f"[{thread_name}] → Returning: {width}×{height}, {channels} channels")
            
            return {
                'array': frame,
                'width': width,
                'height': height,
                'channels': channels,
                'is_rgb': False  # OpenCV BGR format
            }
            
        except Exception as e:
            if DEBUG_MODE:
                import threading
                thread_name = threading.current_thread().name
                print(f"[{thread_name}] ✗ Video thumbnail exception: {e}")
            return None

    def _generate_video_thumbnail(self, file_path):
        """
        Generate thumbnail from video file by extracting middle frame
        
        Args:
            file_path: Path to video file
            
        Returns:
            QPixmap or None
        """
        import time
        start_time = time.time()
        
        try:
            file_name = Path(file_path).name
            file_ext = Path(file_path).suffix.lower()
            
            import cv2
            import numpy as np
            
            # Suppress OpenCV/FFmpeg verbose output
            cv2.setLogLevel(0)  # 0 = Silent
            
            if PYSIDE_VERSION == 6:
                from PySide6.QtGui import QImage, QPixmap
                from PySide6.QtCore import Qt
            else:
                from PySide2.QtGui import QImage, QPixmap
                from PySide2.QtCore import Qt
            
            # Open video file
            cap = cv2.VideoCapture(str(file_path))
            
            if not cap.isOpened():
                # Try imageio as fallback (better FLV support)
                if file_ext in ['.flv', '.wmv']:
                    try:
                        import imageio_ffmpeg
                        import numpy as np
                        import subprocess
                        import re
                        import os
                        
                        # Ensure FFREPORT is not set to prevent log file generation
                        env = os.environ.copy()
                        env.pop('FFREPORT', None)  # Remove FFREPORT if it exists
                        
                        # Windows: Hide console window for subprocess
                        import sys
                        startupinfo = None
                        if sys.platform.startswith('win'):
                            startupinfo = subprocess.STARTUPINFO()
                            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            startupinfo.wShowWindow = subprocess.SW_HIDE
                        
                        # Get video dimensions first
                        probe_cmd = [imageio_ffmpeg.get_ffmpeg_exe(), '-i', str(file_path)]
                        probe_result = subprocess.run(
                            probe_cmd, 
                            stderr=subprocess.PIPE, 
                            stdout=subprocess.DEVNULL, 
                            text=True, 
                            check=False, 
                            env=env,
                            startupinfo=startupinfo
                        )
                        
                        # Parse width and height from stderr
                        match = re.search(r'(\d{3,5})x(\d{3,5})', probe_result.stderr)
                        if not match:
                            raise Exception("Could not parse video dimensions")
                        
                        w, h = int(match.group(1)), int(match.group(2))
                        
                        # Extract first frame
                        cmd = [
                            imageio_ffmpeg.get_ffmpeg_exe(),
                            '-i', str(file_path),
                            '-vframes', '1',
                            '-f', 'image2pipe',
                            '-pix_fmt', 'rgb24',
                            '-vcodec', 'rawvideo',
                            '-'
                        ]
                        
                        result = subprocess.run(
                            cmd, 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.DEVNULL, 
                            check=False, 
                            env=env,
                            startupinfo=startupinfo
                        )
                        
                        if result.returncode == 0 and result.stdout:
                            # Convert raw bytes to numpy array
                            frame = np.frombuffer(result.stdout, dtype=np.uint8).reshape((h, w, 3))
                            
                            # Create QImage from numpy array
                            bytes_per_line = 3 * w
                            q_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                            
                            # Convert to pixmap and scale
                            pixmap = QPixmap.fromImage(q_image)
                            pixmap = pixmap.scaled(
                                self.thumbnail_size, 
                                self.thumbnail_size,
                                Qt.KeepAspectRatio,
                                Qt.SmoothTransformation
                            )
                            
                            return pixmap
                    except Exception as e:
                        pass  # Silently fail, return None below
                
                return None
            
            # Get video info
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            # Read first frame (seeking can be very slow for large videos)
            ret, frame = cap.read()
            cap.release()
            
            if not ret or frame is None:
                return None
            
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Get frame dimensions
            h, w = frame_rgb.shape[:2]
            
            # Create QImage from numpy array
            bytes_per_line = 3 * w
            q_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            # Convert to pixmap and scale to thumbnail size
            pixmap = QPixmap.fromImage(q_image)
            
            # Scale to thumbnail size maintaining aspect ratio
            pixmap = pixmap.scaled(
                self.thumbnail_size, 
                self.thumbnail_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            return pixmap
            
        except Exception as e:
            return None
    
    def _generate_image_thumbnail(self, file_path):
        """
        Generate thumbnail from image file (including PDF first page)
        Fast image loading and scaling
        
        Args:
            file_path: Path to image file or PDF
            
        Returns:
            QPixmap or None
        """
        try:
            extension = os.path.splitext(str(file_path))[1].lower()
            
            # Special handling for PDF files - render first page
            if extension == '.pdf':
                try:
                    from .widgets import load_pdf_page
                    pixmap, page_count, status = load_pdf_page(file_path, page_number=0, max_size=self.thumbnail_size)
                    
                    # Check if PDF is encrypted
                    if status == "encrypted":
                        # Password protected PDF - use default icon without extra error message
                        return self._get_default_icon(file_path)
                    
                    if pixmap and not pixmap.isNull():
                        return pixmap
                    else:
                        raise Exception("PDF loader returned null pixmap")
                except Exception as e:
                    # Only print error for non-encrypted PDFs
                    if "encrypted" not in str(e).lower():
                        print(f"[Cache] PDF loading failed: {e}, using default icon...")
                    return self._get_default_icon(file_path)
            
            # Special handling for .tx files - use OpenImageIO
            if extension == '.tx':
                # Auto-tag color space FIRST (before thumbnail generation)
                if self.metadata_manager:
                    try:
                        from .aces_color import auto_tag_file_colorspace
                        auto_tag_file_colorspace(file_path, self.metadata_manager)
                    except Exception as tag_error:
                        if DEBUG_MODE:
                            print(f"[Cache] Warning: Auto-tagging .tx failed: {tag_error}")
                
                try:
                    from .widgets import load_oiio_image
                    # Load mip level 1 for fast thumbnail (half resolution)
                    pixmap, _, _ = load_oiio_image(file_path, max_size=self.thumbnail_size, mip_level=1)
                    if pixmap and not pixmap.isNull():
                        return pixmap
                    else:
                        raise Exception("OIIO loader returned null pixmap")
                except Exception as e:
                    print(f"[Cache] OIIO .tx loading failed: {e}, using default icon...")
                    return self._get_default_icon(file_path)
            
            # Special handling for video files - extract first frame
            if extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.flv', '.wmv']:
                pixmap = self._generate_video_thumbnail(file_path)
                if pixmap and not pixmap.isNull():
                    return pixmap
                else:
                    # Video thumbnail failed, use default icon
                    return self._get_default_icon(file_path)
            
            # Special handling for EXR files - OPTIMIZED fast thumbnail generation
            if extension == '.exr':
                # Use optimized EXR thumbnail loader (much faster than full loader)
                try:
                    pixmap = self._generate_exr_thumbnail_optimized(file_path)
                    if pixmap and not pixmap.isNull():
                        return pixmap
                    else:
                        raise Exception("EXR loader returned null pixmap")
                except Exception as e:
                    error_msg = str(e)
                    # Deep/volumetric EXR files are not supported
                    if "deep/volumetric" in error_msg.lower() or "non-numeric dtype" in error_msg:
                        if DEBUG_MODE:
                            print(f"[Cache] Deep/volumetric EXR not supported: {Path(file_path).name}")
                        return self._get_default_icon(file_path)
                    else:
                        if DEBUG_MODE:
                            print(f"[Cache] EXR loading failed: {e}, trying QPixmap fallback...")
                    # Fall through to QPixmap method below
            
            # Special handling for HDR/TIFF/TGA/PSD files - use OpenCV or PIL for better format support
            elif extension in ['.hdr', '.tif', '.tiff', '.tga', '.psd']:
                file_path_obj = Path(file_path) if isinstance(file_path, str) else file_path
                if DEBUG_MODE:
                    print(f"[THUMB DEBUG] Loading {extension} file: {file_path_obj.name}")
                try:
                    print(f"  File size: {file_path_obj.stat().st_size / (1024*1024):.2f} MB")
                    print(f"  Modified time: {file_path_obj.stat().st_mtime}")
                except Exception as e:
                    print(f"  Could not get file stats: {e}")
                
                # OPTIMIZED: Use dedicated fast thumbnail generator for HDR files
                if extension == '.hdr':
                    try:
                        pixmap = self._generate_hdr_thumbnail_optimized(file_path)
                        if pixmap and not pixmap.isNull():
                            return pixmap
                        else:
                            if DEBUG_MODE:
                                print(f"[THUMB] HDR optimized loader failed, trying fallback...")
                    except Exception as e:
                        if DEBUG_MODE:
                            print(f"[THUMB] HDR optimized loader exception: {e}, trying fallback...")
                
                try:
                    # Try OpenCV first for 16-bit/32-bit TIFF and TGA support
                    import cv2
                    import numpy as np
                    
                    if DEBUG_MODE:
                        print(f"[THUMB DEBUG] Attempting OpenCV load...")
                    
                    # Suppress OpenCV/FFmpeg verbose output
                    cv2.setLogLevel(0)  # 0 = Silent
                    
                    # Get optimized imread flags (uses IMREAD_REDUCED_* for faster decoding)
                    # Pass file_path to check original dimensions
                    imread_flags = self._get_opencv_imread_flags(file_path=file_path)
                    print(f"  OpenCV flags: {imread_flags}")
                    
                    # OpenCV can't handle Unicode paths, check for non-ASCII first
                    file_path_str = str(file_path)
                    has_non_ascii = any(ord(c) > 127 for c in file_path_str)
                    print(f"  Non-ASCII path: {has_non_ascii}")
                    
                    img = None
                    if has_non_ascii:
                        # Use buffer method for non-ASCII paths (ékezetes karakterek)
                        try:
                            if DEBUG_MODE:
                                print(f"[THUMB] Using buffer method (non-ASCII path) with flags={imread_flags}")
                            with open(file_path_str, 'rb') as f:
                                file_bytes = np.frombuffer(f.read(), np.uint8)
                            img = cv2.imdecode(file_bytes, imread_flags)
                        except Exception as e:
                            if DEBUG_MODE:
                                print(f"[THUMB] Buffer decode failed: {e}")
                    else:
                        # ASCII-only path, use direct imread with optimized flags
                        try:
                            if DEBUG_MODE:
                                print(f"[THUMB] Using imread with optimized flags={imread_flags}")
                            img = cv2.imread(file_path_str, imread_flags)
                        except Exception as e:
                            if DEBUG_MODE:
                                print(f"[THUMB] OpenCV imread failed: {e}")
                    
                    if img is None:
                        if DEBUG_MODE:
                            print(f"[THUMB DEBUG] ❌ OpenCV failed to load image")
                        raise Exception("OpenCV could not load the image")
                    
                    if DEBUG_MODE:
                        print(f"[THUMB DEBUG] ✓ OpenCV loaded successfully")
                    
                    # Check channel count
                    if len(img.shape) == 3:
                        channels = img.shape[2]
                        print(f"  Image: {img.shape[1]}×{img.shape[0]}, {channels} channels, dtype={img.dtype}")
                        
                        # Handle unsupported channel counts (e.g., 5-channel TIFF)
                        if channels > 4:
                            if DEBUG_MODE:
                                print(f"[THUMB] Unsupported {channels} channels, extracting first 4...")
                            img = img[:, :, :4]  # Keep only first 4 channels
                    else:
                        if DEBUG_MODE:
                            print(f"[THUMB] Image loaded: {img.shape[1]}×{img.shape[0]}, grayscale, dtype={img.dtype}")
                    
                    # FIRST: Convert color space (BGR/BGRA → RGB) BEFORE normalization
                    if len(img.shape) == 2:
                        # Grayscale - convert to RGB
                        if DEBUG_MODE:
                            print(f"[THUMB] Converting grayscale to RGB")
                        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                    elif len(img.shape) == 3 and img.shape[2] == 4:
                        # RGBA - convert to RGB (keeping 16-bit if present)
                        if DEBUG_MODE:
                            print(f"[THUMB] Converting BGRA to RGB")
                        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
                    elif len(img.shape) == 3 and img.shape[2] == 3:
                        # BGR - convert to RGB
                        if DEBUG_MODE:
                            print(f"[THUMB] Converting BGR to RGB")
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    
                    # THEN: Normalize bit depth AFTER color conversion
                    if img.dtype == np.uint16:
                        # 16-bit image - normalize to 8-bit
                        # 16-bit range: 0-65535 → 8-bit range: 0-255
                        # Correct conversion: divide by 257 (65535/255), not 256
                        if DEBUG_MODE:
                            print(f"[THUMB] Normalizing 16-bit to 8-bit (÷257)")
                        img = (img / 257).astype(np.uint8)
                    elif img.dtype == np.float32 or img.dtype == np.float64:
                        # 32-bit float - normalize and apply simple tone mapping
                        if DEBUG_MODE:
                            print(f"[THUMB] Normalizing 32-bit float to 8-bit")
                        img = np.clip(img, 0, 1)  # Clip to 0-1 range
                        img = (img * 255).astype(np.uint8)
                    
                    if DEBUG_MODE:
                        print(f"[THUMB] Converted to RGB: {img.shape[1]}×{img.shape[0]}")
                    
                    # Resize for thumbnail
                    height, width = img.shape[:2]
                    if width > self.thumbnail_size or height > self.thumbnail_size:
                        scale = min(self.thumbnail_size / width, self.thumbnail_size / height)
                        new_width = int(width * scale)
                        new_height = int(height * scale)
                        img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                        if DEBUG_MODE:
                            print(f"[THUMB] Resized to: {new_width}×{new_height}")
                    
                    # Convert numpy array to QPixmap
                    height, width, channels = img.shape
                    bytes_per_line = width * channels
                    
                    if PYSIDE_VERSION == 6:
                        from PySide6.QtGui import QImage
                    else:
                        from PySide2.QtGui import QImage
                    
                    q_image = QImage(img.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                    pixmap = QPixmap.fromImage(q_image.copy())
                    
                    if not pixmap.isNull():
                        if DEBUG_MODE:
                            print(f"[THUMB] ✓ Successfully created thumbnail")
                        return pixmap
                    else:
                        raise Exception("Failed to convert to QPixmap")
                        
                except Exception as e:
                    # Try multiple fallback methods
                    if DEBUG_MODE:
                        print(f"[THUMB] OpenCV failed: {e}")
                    pixmap = None
                    
                    # For multi-channel images, always try PIL/Pillow as fallback
                    # (OpenCV prints errors to stderr, not in exception message)
                    if DEBUG_MODE:
                        print(f"[THUMB DEBUG] 🔄 Trying PIL/Pillow fallback...")
                    try:
                        from PIL import Image
                        # Disable decompression bomb warning for large images
                        Image.MAX_IMAGE_PIXELS = None
                        
                        if DEBUG_MODE:
                            print(f"[THUMB DEBUG] Opening file with PIL.Image.open()...")
                        
                        pil_image = Image.open(str(file_path))
                        
                        if DEBUG_MODE:
                            print(f"[THUMB DEBUG] ✓ PIL loaded successfully!")
                            print(f"  Image size: {pil_image.size}")
                            print(f"  Mode: {pil_image.mode}")
                            print(f"  Format: {pil_image.format}")
                            # Check for layers/pages
                            try:
                                n_frames = getattr(pil_image, 'n_frames', 1)
                                print(f"  Frames/Layers: {n_frames}")
                            except:
                                pass
                        
                        # Convert to RGB (discard extra channels)
                        if pil_image.mode not in ('RGB', 'L'):
                            if DEBUG_MODE:
                                print(f"[THUMB DEBUG] Converting {pil_image.mode} → RGB...")
                            pil_image = pil_image.convert('RGB')
                        elif pil_image.mode == 'L':
                            if DEBUG_MODE:
                                print(f"[THUMB DEBUG] Converting grayscale → RGB...")
                            pil_image = pil_image.convert('RGB')
                        
                        # Resize
                        if DEBUG_MODE:
                            print(f"[THUMB DEBUG] Resizing to {self.thumbnail_size}x{self.thumbnail_size}...")
                        pil_image.thumbnail((self.thumbnail_size, self.thumbnail_size), Image.Resampling.LANCZOS)
                        
                        # Convert to QPixmap
                        if DEBUG_MODE:
                            print(f"[THUMB DEBUG] Converting PIL → QPixmap via numpy...")
                        import numpy as np
                        img_array = np.array(pil_image)
                        height, width = img_array.shape[:2]
                        channels = img_array.shape[2] if len(img_array.shape) == 3 else 1
                        
                        if PYSIDE_VERSION == 6:
                            from PySide6.QtGui import QImage
                        else:
                            from PySide2.QtGui import QImage
                        
                        if channels == 3:
                            bytes_per_line = width * 3
                            q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                            pixmap = QPixmap.fromImage(q_image.copy())
                            if DEBUG_MODE:
                                print(f"[THUMB] ✓ PIL fallback successful: {width}×{height}")
                            if pixmap and not pixmap.isNull():
                                return pixmap
                        
                        if DEBUG_MODE:
                            print(f"[THUMB] PIL unexpected channels={channels}, falling through...")
                    except Exception as pil_error:
                        if DEBUG_MODE:
                            print(f"[THUMB] PIL fallback also failed: {pil_error}")
                        
                        # Try tifffile for special TIFF formats (Affinity, compressed, multi-layer)
                        if extension in ['.tif', '.tiff']:
                            if DEBUG_MODE:
                                print(f"[THUMB DEBUG] 🔄 Trying tifffile library for special TIFF...")
                            try:
                                import tifffile
                                import numpy as np
                                
                                if DEBUG_MODE:
                                    print(f"[THUMB DEBUG] Reading TIFF with tifffile.imread()...")
                                
                                # Read the TIFF - this handles Deflate/LZW compression, BigTIFF, etc.
                                img_array = tifffile.imread(str(file_path))
                                
                                if DEBUG_MODE:
                                    print(f"[THUMB DEBUG] ✓ tifffile loaded successfully!")
                                    print(f"  Array shape: {img_array.shape}")
                                    print(f"  Data type: {img_array.dtype}")
                                
                                # Handle different array shapes
                                if len(img_array.shape) == 3:
                                    # Multi-channel image (RGB, RGBA, etc.)
                                    height, width, channels = img_array.shape
                                    
                                    # Normalize to 8-bit if needed
                                    if img_array.dtype == np.uint32:
                                        if DEBUG_MODE:
                                            print(f"[THUMB DEBUG] Converting 32-bit → 8-bit...")
                                            print(f"  Value range: {img_array.min()} - {img_array.max()}")
                                        # Affinity Photo uses uint32 but only a subset of the range
                                        # Normalize based on actual min/max values
                                        img_min = img_array.min()
                                        img_max = img_array.max()
                                        if img_max > img_min:
                                            # Normalize to 0-255 range based on actual min/max
                                            img_array = ((img_array.astype(np.float64) - img_min) / (img_max - img_min) * 255).astype(np.uint8)
                                        else:
                                            img_array = np.zeros_like(img_array, dtype=np.uint8)
                                        if DEBUG_MODE:
                                            print(f"  Normalized + gamma corrected to: {img_array.min()} - {img_array.max()}")
                                    elif img_array.dtype == np.uint16:
                                        if DEBUG_MODE:
                                            print(f"[THUMB DEBUG] Converting 16-bit → 8-bit...")
                                        img_array = (img_array / 256).astype(np.uint8)
                                    elif img_array.dtype == np.float32 or img_array.dtype == np.float64:
                                        if DEBUG_MODE:
                                            print(f"[THUMB DEBUG] Converting float → 8-bit...")
                                        img_array = (img_array * 255).astype(np.uint8)
                                    
                                    # Keep only RGB channels if RGBA
                                    if channels > 3:
                                        if DEBUG_MODE:
                                            print(f"[THUMB DEBUG] Dropping alpha channel ({channels} → 3)...")
                                        img_array = img_array[:, :, :3]
                                        channels = 3
                                    
                                elif len(img_array.shape) == 2:
                                    # Grayscale
                                    if DEBUG_MODE:
                                        print(f"[THUMB DEBUG] Converting grayscale → RGB...")
                                    height, width = img_array.shape
                                    
                                    # Normalize to 8-bit
                                    if img_array.dtype == np.uint32:
                                        img_min = img_array.min()
                                        img_max = img_array.max()
                                        if img_max > img_min:
                                            img_array = ((img_array.astype(np.float64) - img_min) / (img_max - img_min) * 255).astype(np.uint8)
                                        else:
                                            img_array = np.zeros_like(img_array, dtype=np.uint8)
                                    elif img_array.dtype == np.uint16:
                                        img_array = (img_array / 256).astype(np.uint8)
                                    elif img_array.dtype == np.float32 or img_array.dtype == np.float64:
                                        img_array = (img_array * 255).astype(np.uint8)
                                    
                                    # Convert to RGB
                                    img_array = np.stack([img_array, img_array, img_array], axis=2)
                                    channels = 3
                                
                                # Resize using PIL
                                if DEBUG_MODE:
                                    print(f"[THUMB DEBUG] Resizing {width}×{height} → {self.thumbnail_size}...")
                                from PIL import Image
                                pil_image = Image.fromarray(img_array)
                                pil_image.thumbnail((self.thumbnail_size, self.thumbnail_size), Image.Resampling.LANCZOS)
                                
                                # Convert to QPixmap
                                img_array = np.array(pil_image)
                                height, width = img_array.shape[:2]
                                
                                if PYSIDE_VERSION == 6:
                                    from PySide6.QtGui import QImage
                                else:
                                    from PySide2.QtGui import QImage
                                
                                bytes_per_line = width * 3
                                q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                                pixmap = QPixmap.fromImage(q_image.copy())
                                
                                if DEBUG_MODE:
                                    print(f"[THUMB DEBUG] ✓ tifffile fallback successful: {width}×{height}")
                                
                                return pixmap
                                
                            except Exception as tifffile_error:
                                if DEBUG_MODE:
                                    print(f"[THUMB] tifffile also failed: {tifffile_error}")
                        
                        # Special handling for PSD files: try embedded thumbnail FIRST (fast), then psd-tools (slow)
                        if extension == '.psd':
                            try:
                                if DEBUG_MODE:
                                    print(f"[THUMB] Trying embedded PSD thumbnail (fast)...")
                                pixmap = ThumbnailGenerator._extract_psd_thumbnail(file_path, thumbnail_size=self.thumbnail_size)
                                if pixmap and not pixmap.isNull():
                                    if DEBUG_MODE:
                                        print(f"[THUMB] ✓ PSD embedded thumbnail loaded successfully")
                                    return pixmap
                                else:
                                    if DEBUG_MODE:
                                        print(f"[THUMB] No embedded thumbnail, trying psd-tools (slow)...")
                                    pixmap = ThumbnailGenerator._load_psd_composite(file_path, max_size=self.thumbnail_size)
                                    if pixmap and not pixmap.isNull():
                                        if DEBUG_MODE:
                                            print(f"[THUMB] ✓ PSD thumbnail extracted successfully")
                                        return pixmap
                            except Exception as thumb_error:
                                if DEBUG_MODE:
                                    print(f"[THUMB] PSD loading failed: {thumb_error}")
                        
                        # Check if it's an unsupported multi-channel TIFF
                        if "unknown pixel mode" in str(pil_error) or "KeyError" in str(pil_error):
                            if DEBUG_MODE:
                                print(f"[THUMB] → Unsupported TIFF format (5+ channels), skipping: {file_path.name}")
                    
                    # Method 1: Try QImageReader with explicit format and increased limit
                    try:
                        if PYSIDE_VERSION == 6:
                            from PySide6.QtGui import QImageReader, QImage
                        else:
                            from PySide2.QtGui import QImageReader, QImage
                        
                        reader = QImageReader(str(file_path))
                        
                        # Increase allocation limit for this reader (TGA files can be huge)
                        reader.setAllocationLimit(2048)  # 2 GB limit
                        
                        # Force format detection
                        if extension == '.tga':
                            reader.setFormat(b'tga')
                            if DEBUG_MODE:
                                print(f"[THUMB] QImageReader trying TGA with 2GB limit...")
                        elif extension in ['.tif', '.tiff']:
                            reader.setFormat(b'tiff')
                        
                        image = reader.read()
                        if not image.isNull():
                            pixmap = QPixmap.fromImage(image)
                            if DEBUG_MODE:
                                print(f"[THUMB] ✓ QImageReader successful")
                    except Exception as reader_error:
                        print(f"[THUMB] QImageReader failed: {reader_error}")
                    
                    # Method 2: Standard QPixmap
                    if pixmap is None or pixmap.isNull():
                        pixmap = QPixmap(str(file_path))
                    
                    # If we got a valid pixmap, resize it
                    if pixmap is not None and not pixmap.isNull():
                        pixmap = pixmap.scaled(
                            self.thumbnail_size,
                            self.thumbnail_size,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        )
                        return pixmap
                    # Fall through to default handling below
            
            # Standard image files - use QPixmap (for 8-bit JPEG, PNG, etc.)
            # For very large images (16K+), try OpenCV first for better memory handling
            try:
                # Check file size first - if over 50MB, use OpenCV
                file_size_mb = os.path.getsize(str(file_path)) / (1024 * 1024)
                
                if DEBUG_MODE:
                    print(f"[Cache] Standard image: {Path(file_path).name}, size={file_size_mb:.1f}MB, ext={extension}")
                    import sys
                    sys.stdout.flush()  # Force immediate print
                
                # OPTIMIZED: Only large files go to OpenCV (removed auto JPG routing)
                # Small/medium JPG/PNG work better with QImageReader (native DCT/progressive decode)
                # IMPORTANT: PNG files should ALWAYS use QImageReader (better 16-bit support)
                if file_size_mb > 50 and extension != '.png':
                    if DEBUG_MODE:
                        print(f"[Cache] → Large file, using OpenCV path")
                    # Try OpenCV for large files - better memory handling with optimized flags
                    import cv2
                    import numpy as np
                    
                    # Suppress OpenCV/FFmpeg verbose output
                    cv2.setLogLevel(0)  # 0 = Silent
                    
                    # Get optimized imread flags (uses IMREAD_REDUCED_* for faster decoding)
                    # Pass file_path to check original dimensions
                    imread_flags = self._get_opencv_imread_flags(file_path=file_path)
                    
                    # OpenCV can't handle Unicode paths, check for non-ASCII first
                    file_path_str = str(file_path)
                    has_non_ascii = any(ord(c) > 127 for c in file_path_str)
                    
                    img = None
                    if has_non_ascii:
                        # Use buffer method for non-ASCII paths (ékezetes karakterek)
                        try:
                            if DEBUG_MODE:
                                print(f"[Cache] Using buffer method (non-ASCII path) with flags={imread_flags}")
                            with open(file_path_str, 'rb') as f:
                                file_bytes = np.frombuffer(f.read(), np.uint8)
                            img = cv2.imdecode(file_bytes, imread_flags)
                        except Exception as e:
                            print(f"[Cache] Buffer decode failed: {e}")
                    else:
                        # ASCII-only path, use direct imread with optimized flags
                        try:
                            if DEBUG_MODE:
                                print(f"[Cache] Using imread with optimized flags={imread_flags}")
                            img = cv2.imread(file_path_str, imread_flags)
                        except:
                            pass
                    
                    if img is not None:
                        # Convert BGR to RGB
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        
                        # Calculate thumbnail size
                        h, w = img.shape[:2]
                        
                        # Only resize if still too large (IMREAD_REDUCED_* already downscaled)
                        if w > self.thumbnail_size or h > self.thumbnail_size:
                            scale = min(self.thumbnail_size / w, self.thumbnail_size / h)
                            new_w = int(w * scale)
                            new_h = int(h * scale)
                            
                            # Resize with OpenCV (faster for large images)
                            img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                            
                            if DEBUG_MODE:
                                print(f"[Cache] Resized from {w}×{h} to {new_w}×{new_h}")
                        else:
                            # Already at good size from IMREAD_REDUCED
                            img_resized = img
                            if DEBUG_MODE:
                                print(f"[Cache] No resize needed, already at {w}×{h}")
                        
                        # Convert to QPixmap
                        if PYSIDE_VERSION == 6:
                            from PySide6.QtGui import QImage
                        else:
                            from PySide2.QtGui import QImage
                        
                        height, width, channel = img_resized.shape
                        bytes_per_line = 3 * width
                        q_image = QImage(img_resized.data, width, height, bytes_per_line, QImage.Format_RGB888)
                        
                        pixmap = QPixmap.fromImage(q_image)
                        
                        return pixmap
            except Exception as e:
                print(f"[Cache] OpenCV loading failed for large JPG: {e}, trying QPixmap...")
            
            # OPTIMIZED: Use QImageReader with scaled size for fast thumbnail generation
            # This loads only the necessary data at thumbnail size, not the full image
            # Works best for: JPEG (uses DCT subsampling), PNG (progressive decode), standard 8-bit images
            # 
            # ULTRA-OPTIMIZED (2025-01): 10× speedup for JPG/PNG thumbnails
            # - JPEG/PNG: Use OpenCV with IMREAD_REDUCED_GRAYSCALE_2 for 4× faster decode
            # - OpenCV libjpeg-turbo is 2-3× faster than Qt's JPEG decoder
            # - Combined with reduced resolution: 8-10× total speedup
            try:
                # FAST PATH: Optimized JPG/PNG loading with QImageReader
                if extension in ['.jpg', '.jpeg', '.png']:
                    try:
                        # Use QImageReader with optimizations
                        if PYSIDE_VERSION == 6:
                            from PySide6.QtGui import QImageReader, QImage
                            from PySide6.QtCore import QSize
                        else:
                            from PySide2.QtGui import QImageReader, QImage
                            from PySide2.QtCore import QSize
                        
                        file_path_str = str(file_path)
                        
                        reader = QImageReader(file_path_str)
                        reader.setAutoTransform(True)  # Handle EXIF rotation
                        
                        # Get original size
                        original_size = reader.size()
                        
                        if original_size.isValid():
                            # Calculate target scaled size
                            scaled_size = original_size.scaled(
                                self.thumbnail_size,
                                self.thumbnail_size,
                                Qt.KeepAspectRatio
                            )
                            
                            # Tell reader to decode at smaller size
                            reader.setScaledSize(scaled_size)
                            
                            # Set quality to FAST (lower quality but faster decode)
                            # For thumbnails, 50 is good balance
                            reader.setQuality(50)
                            
                            # Decode the image
                            image = reader.read()
                            
                            if not image.isNull():
                                pixmap = QPixmap.fromImage(image)
                                if not pixmap.isNull():
                                    return pixmap
                        
                    except Exception as qimage_error:
                        if DEBUG_MODE:
                            print(f"[FAST JPG/PNG] QImageReader error: {qimage_error}")
                    
                    # FALLBACK: OpenCV with REDUCED_8
                    try:
                        import cv2
                        import numpy as np
                        
                        cv2.setLogLevel(0)  # Suppress verbose output
                        
                        # Use REDUCED_8 for maximum speed
                        imread_flag = cv2.IMREAD_REDUCED_COLOR_8
                        
                        file_path_str = str(file_path)
                        has_non_ascii = any(ord(c) > 127 for c in file_path_str)
                        
                        if has_non_ascii:
                            with open(file_path_str, 'rb') as f:
                                file_bytes = np.frombuffer(f.read(), np.uint8)
                            img = cv2.imdecode(file_bytes, imread_flag)
                        else:
                            img = cv2.imread(file_path_str, imread_flag)
                        
                        if img is not None:
                            # Convert BGR to RGB
                            if len(img.shape) == 3 and img.shape[2] == 3:
                                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                            elif len(img.shape) == 3 and img.shape[2] == 4:
                                img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
                            
                            # Resize if needed
                            h, w = img.shape[:2]
                            if w > self.thumbnail_size or h > self.thumbnail_size:
                                scale = min(self.thumbnail_size / w, self.thumbnail_size / h)
                                new_w = int(w * scale)
                                new_h = int(h * scale)
                                img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                            
                            # Convert to QPixmap
                            if PYSIDE_VERSION == 6:
                                from PySide6.QtGui import QImage
                            else:
                                from PySide2.QtGui import QImage
                            
                            height, width, channels = img.shape
                            bytes_per_line = width * channels
                            q_image = QImage(img.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                            pixmap = QPixmap.fromImage(q_image.copy())
                            
                            if not pixmap.isNull():
                                return pixmap
                    
                    except Exception as cv_error:
                        if DEBUG_MODE:
                            print(f"[FAST JPG/PNG] OpenCV error: {cv_error}")
                
                # STANDARD PATH: QImageReader for other formats (or OpenCV fallback)
                print(f"\n[QImageReader] Starting: {Path(file_path).name}, ext={extension}")
                start_qimage = time.perf_counter()
                
                if PYSIDE_VERSION == 6:
                    from PySide6.QtGui import QImageReader, QImage
                    from PySide6.QtCore import QSize
                else:
                    from PySide2.QtGui import QImageReader, QImage
                    from PySide2.QtCore import QSize
                
                t1 = time.perf_counter()
                reader = QImageReader(str(file_path))
                print(f"  → QImageReader init: {(time.perf_counter() - t1)*1000:.2f}ms")
                
                # Enable EXIF auto-rotation (CRITICAL for correct thumbnail orientation!)
                reader.setAutoTransform(True)
                
                # Get original size
                t2 = time.perf_counter()
                original_size = reader.size()
                print(f"  → Get size: {(time.perf_counter() - t2)*1000:.2f}ms")
                
                if original_size.isValid():
                    print(f"  → Original size: {original_size.width()}×{original_size.height()}")
                    
                    # Calculate scaled size maintaining aspect ratio
                    scaled_size = original_size.scaled(
                        self.thumbnail_size, 
                        self.thumbnail_size, 
                        Qt.KeepAspectRatio
                    )
                    print(f"  → Target scaled size: {scaled_size.width()}×{scaled_size.height()}")
                    
                    # Tell reader to decode at this smaller size (FAST!)
                    # For JPEG: uses DCT coefficient subsampling (4-6× faster)
                    # For PNG: progressive decode, only loads what's needed
                    reader.setScaledSize(scaled_size)
                
                # Read the already-scaled image (no separate scaling step needed!)
                t3 = time.perf_counter()
                image = reader.read()
                read_time = (time.perf_counter() - t3) * 1000
                print(f"  → reader.read(): {read_time:.2f}ms")
                
                if not image.isNull():
                    t4 = time.perf_counter()
                    pixmap = QPixmap.fromImage(image)
                    print(f"  → QPixmap.fromImage: {(time.perf_counter() - t4)*1000:.2f}ms")
                    
                    total_time = (time.perf_counter() - start_qimage) * 1000
                    if not pixmap.isNull():
                        print(f"[QImageReader] ✓ SUCCESS: {pixmap.width()}×{pixmap.height()} in {total_time:.2f}ms TOTAL\n")
                        return pixmap
                
                # If reader failed, print error and fall through to old method
                print(f"[QImageReader] ✗ FAILED: {reader.errorString()}, using QPixmap fallback...\n")
                
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[Cache] ✗ QImageReader exception: {e}, using fallback...")
            
            # Fallback to standard QPixmap loading (slower, but always works)
            if DEBUG_MODE:
                print(f"[Cache] → Using QPixmap fallback")
            
            pixmap = QPixmap(str(file_path))
            
            if pixmap.isNull():
                # Failed to load - check if it's a known unsupported format
                if extension == '.exr':
                    # Deep EXR already logged above, just return default icon quietly
                    if DEBUG_MODE:
                        print(f"[Cache] ✗ Using default icon for unsupported EXR: {Path(file_path).name}")
                else:
                    if DEBUG_MODE:
                        print(f"[Cache] ✗ QPixmap failed to load: {file_path}")
                return self._get_default_icon(file_path)
            
            if DEBUG_MODE:
                print(f"[Cache] → QPixmap loaded: {pixmap.width()}×{pixmap.height()}")
            
            # Scale to thumbnail size (keep aspect ratio)
            scaled = pixmap.scaled(
                self.thumbnail_size,
                self.thumbnail_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            if DEBUG_MODE:
                print(f"[Cache] ✓ Scaled to: {scaled.width()}×{scaled.height()}")
            
            return scaled
            
        except Exception as e:
            print(f"Error loading image thumbnail {file_path}: {e}")
            return self._get_default_icon(file_path)
    
    def _generate_exr_thumbnail_optimized(self, file_path):
        """
        OPTIMIZED: Fast EXR thumbnail generation for cache
        
        Much faster than full EXR loader used in preview panel because:
        1. Loads at reduced resolution (uses downsampling)
        2. Simplified tone mapping (no exposure control)
        3. Only loads RGB channels (no alpha/AOVs)
        
        Args:
            file_path: Path to EXR file
            
        Returns:
            QPixmap or None
        """
        # Check if this is a deep EXR - skip thumbnail generation and TAG it
        from .preview_panel import is_deep_exr
        if is_deep_exr(file_path):
            if DEBUG_MODE:
                print(f"[EXR-OPT] Deep EXR detected - skipping thumbnail and tagging: {Path(file_path).name}")
            
            # Tag as deep data for fast future checks
            if self.metadata_manager:
                try:
                    tag_id = self.metadata_manager.add_tag("deepdata", category=None, color=None)
                    self.metadata_manager.add_tag_to_file(str(file_path), tag_id)
                    if DEBUG_MODE:
                        print(f"[EXR-OPT] Tagged as 'deepdata' for fast future detection")
                except Exception as tag_error:
                    if DEBUG_MODE:
                        print(f"[EXR-OPT] Warning: Failed to tag deep EXR: {tag_error}")
            
            return None
        
        # Auto-tag color space (before thumbnail generation)
        # This ensures tags are available when preview panel loads the file
        if self.metadata_manager:
            try:
                from .aces_color import auto_tag_file_colorspace
                auto_tag_file_colorspace(file_path, self.metadata_manager)
            except Exception as tag_error:
                if DEBUG_MODE:
                    print(f"[EXR-OPT] Warning: Auto-tagging failed: {tag_error}")
        
        import sys
        import os
        
        # Add external_libs to path
        external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
        if external_libs not in sys.path:
            sys.path.insert(0, external_libs)
        
        try:
            import numpy as np
            
            # Try OpenEXR library first (fast, native)
            try:
                import OpenEXR
                
                if DEBUG_MODE:
                    print(f"[EXR-OPT] Loading EXR with OpenEXR library: {Path(file_path).name}")
                
                # Open EXR file
                with OpenEXR.File(str(file_path)) as exr_file:
                    # Get header info
                    header = exr_file.header()
                    dw = header['dataWindow']
                    width = dw[1][0] - dw[0][0] + 1
                    height = dw[1][1] - dw[0][1] + 1
                    
                    if DEBUG_MODE:
                        print(f"[EXR-OPT] Original size: {width}x{height}")
                    
                    # List all available channels (DEBUG)
                    channels = exr_file.channels()
                    if DEBUG_MODE:
                        channel_list = list(channels.keys())
                        print(f"[EXR-OPT] Available channels: {', '.join(channel_list)}")
                    
                    # Read RGB channels
                    channels = exr_file.channels()
                    rgb = None
                    
                    # Try multiple naming conventions (same as full loader)
                    # 1. Try standard interleaved RGB or RGBA
                    if "RGB" in channels:
                        if DEBUG_MODE:
                            print(f"[EXR-OPT] → Using interleaved RGB channel")
                        rgb_data = channels["RGB"].pixels
                        if rgb_data is not None:
                            # If RGBA, drop alpha channel
                            if rgb_data.ndim == 3 and rgb_data.shape[2] >= 3:
                                rgb = rgb_data[:, :, :3]
                            else:
                                rgb = rgb_data
                    elif "RGBA" in channels:
                        if DEBUG_MODE:
                            print(f"[EXR-OPT] → Using interleaved RGBA channel (dropping alpha)")
                        rgba_data = channels["RGBA"].pixels
                        if rgba_data is not None:
                            rgb = rgba_data[:, :, :3]  # Drop alpha, keep RGB only
                    
                    # 2. Try separate R, G, B channels
                    elif all(c in channels for c in ["R", "G", "B"]):
                        if DEBUG_MODE:
                            print(f"[EXR-OPT] → Using separate R, G, B channels")
                        r = channels["R"].pixels
                        g = channels["G"].pixels
                        b = channels["B"].pixels
                        if r is not None and g is not None and b is not None:
                            rgb = np.stack([r, g, b], axis=2)
                    
                    # 3. Try Beauty pass (common in render layers)
                    elif all(c in channels for c in ["Beauty.R", "Beauty.G", "Beauty.B"]):
                        if DEBUG_MODE:
                            print(f"[EXR-OPT] → Using Beauty.R/G/B channels")
                        r = channels["Beauty.R"].pixels
                        g = channels["Beauty.G"].pixels
                        b = channels["Beauty.B"].pixels
                        if r is not None and g is not None and b is not None:
                            rgb = np.stack([r, g, b], axis=2)
                    
                    # 4. Try first layer with .R .G .B (generic multi-layer)
                    if rgb is None:
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
                                    if DEBUG_MODE:
                                        print(f"[EXR-OPT] Using layer: {prefix}")
                                    break
                    
                    # 5. If still no RGB, try single channel (grayscale)
                    if rgb is None:
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
                                    if DEBUG_MODE:
                                        print(f"[EXR-OPT] Using single channel: {ch_name}")
                                    break
                    
                    # 6. Last resort: use ANY available channel as grayscale
                    if rgb is None and len(channels) > 0:
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
                            if DEBUG_MODE:
                                print(f"[EXR-OPT] Using first available channel: {first_channel_name}")
                    
                    if rgb is None:
                        raise Exception("No usable channels found")
                    
                    # Debug: Show what we loaded
                    if DEBUG_MODE:
                        print(f"[EXR-OPT] → Loaded data: shape={rgb.shape}, dtype={rgb.dtype}")
                    
                    # Check if dtype is numeric (deep EXR returns object arrays)
                    if rgb.dtype == np.object_ or not np.issubdtype(rgb.dtype, np.number):
                        raise Exception(f"Non-numeric dtype: {rgb.dtype} (deep/volumetric EXR not supported)")
                    
                    # Convert float16 to float32 (OpenCV resize needs float32)
                    if rgb.dtype == np.float16:
                        if DEBUG_MODE:
                            print(f"[EXR-OPT] → Converting float16 to float32 (OpenCV compatibility)")
                        rgb = rgb.astype(np.float32)
                    
                    # OPTIMIZATION 1: Downsample BEFORE tone mapping (much faster!)
                    # Use area interpolation for best quality at reduced size
                    import cv2
                    
                    # Suppress OpenCV/FFmpeg verbose output
                    cv2.setLogLevel(0)  # 0 = Silent
                    if width > self.thumbnail_size or height > self.thumbnail_size:
                        scale = min(self.thumbnail_size / width, self.thumbnail_size / height)
                        new_width = int(width * scale)
                        new_height = int(height * scale)
                        
                        if DEBUG_MODE:
                            print(f"[EXR-OPT] → Downsampling to {new_width}x{new_height} (scale={scale:.3f})")
                        
                        # Use INTER_AREA for downsampling (best quality, fast)
                        rgb = cv2.resize(rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
                        width, height = new_width, new_height
                    else:
                        if DEBUG_MODE:
                            print(f"[EXR-OPT] → No downsampling needed (already small)")
                    
                    # Check if we should use ACES color management
                    use_aces = False
                    if self.metadata_manager:
                        try:
                            file_metadata = self.metadata_manager.get_file_metadata(str(file_path))
                            file_tags = file_metadata.get('tags', [])
                            tag_names_lower = [tag['name'].lower() for tag in file_tags]
                            
                            # Check for ACEScg tag (case-insensitive)
                            if "acescg" in tag_names_lower or "srgb(aces)" in tag_names_lower:
                                use_aces = True
                                if DEBUG_MODE:
                                    print(f"[EXR-OPT] → Using ACES view transform for thumbnail")
                        except Exception as tag_error:
                            if DEBUG_MODE:
                                print(f"[EXR-OPT] → Tag check failed: {tag_error}")
                    
                    # Apply tone mapping (ACES or standard)
                    if use_aces:
                        # Use ACES RRT + ODT with -1 stop exposure compensation
                        try:
                            from .aces_color import apply_aces_view_transform
                            
                            if DEBUG_MODE:
                                min_val = np.min(rgb)
                                max_val = np.max(rgb)
                                print(f"[EXR-OPT] → HDR range before ACES: min={min_val:.3f}, max={max_val:.3f}")
                            
                            # Apply ACES with -1 stop compensation (matches preview)
                            rgb_tonemapped = apply_aces_view_transform(rgb, exposure=-1.0)
                            
                            if DEBUG_MODE:
                                print(f"[EXR-OPT] → Applied ACES RRT+ODT (exposure: -1.0)")
                        except Exception as aces_error:
                            if DEBUG_MODE:
                                print(f"[EXR-OPT] → ACES failed, falling back to Reinhard: {aces_error}")
                            # Fallback to Reinhard
                            rgb = np.clip(rgb, 0, None)
                            rgb_tonemapped = rgb / (1.0 + rgb)
                            gamma = 1.0 / 2.2
                            rgb_tonemapped = np.power(rgb_tonemapped, gamma)
                    else:
                        # Standard Reinhard tone mapping for Linear sRGB
                        if DEBUG_MODE:
                            min_val = np.min(rgb)
                            max_val = np.max(rgb)
                            mean_val = np.mean(rgb)
                            print(f"[EXR-OPT] → HDR range before tone mapping: min={min_val:.3f}, max={max_val:.3f}, mean={mean_val:.3f}")
                        
                        rgb = np.clip(rgb, 0, None)  # Clamp negatives
                        rgb_tonemapped = rgb / (1.0 + rgb)  # Reinhard
                        
                        if DEBUG_MODE:
                            print(f"[EXR-OPT] → Applied Reinhard tone mapping")
                        
                        # Gamma correction (2.2 for sRGB)
                        gamma = 1.0 / 2.2
                        rgb_tonemapped = np.power(rgb_tonemapped, gamma)
                        
                        if DEBUG_MODE:
                            print(f"[EXR-OPT] → Applied gamma correction (2.2)")
                    
                    # Convert to 8-bit
                    rgb_8bit = (rgb_tonemapped * 255).astype(np.uint8)
                    
                    # Create QImage
                    if PYSIDE_VERSION == 6:
                        from PySide6.QtGui import QImage
                    else:
                        from PySide2.QtGui import QImage
                    
                    bytes_per_line = width * 3
                    q_image = QImage(rgb_8bit.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                    q_image = q_image.copy()
                    
                    # Convert to QPixmap
                    pixmap = QPixmap.fromImage(q_image)
                    
                    if DEBUG_MODE:
                        print(f"[EXR-OPT] ✓ Thumbnail generated: {width}x{height}")
                    
                    return pixmap
                    
            except ImportError:
                if DEBUG_MODE:
                    print(f"[EXR-OPT] OpenEXR library not available, trying OpenImageIO...")
                # Fall through to OIIO method
            
            # Fallback: Try OpenImageIO (slower but more compatible)
            try:
                from .widgets import load_oiio_image
                
                if DEBUG_MODE:
                    print(f"[EXR-OPT] Loading EXR with OpenImageIO: {Path(file_path).name}")
                
                # Load with OIIO at reduced size
                pixmap, _, _ = load_oiio_image(file_path, max_size=self.thumbnail_size)
                if pixmap and not pixmap.isNull():
                    if DEBUG_MODE:
                        print(f"[EXR-OPT] ✓ OIIO thumbnail loaded")
                    return pixmap
                else:
                    raise Exception("OIIO loader returned null pixmap")
                    
            except Exception as oiio_error:
                if DEBUG_MODE:
                    print(f"[EXR-OPT] OIIO loading failed: {oiio_error}")
                return None
                
        except Exception as e:
            if DEBUG_MODE:
                print(f"[EXR-OPT] Failed to load EXR: {e}")
            return None
    
    def _generate_hdr_thumbnail_optimized(self, file_path):
        """
        OPTIMIZED: Fast HDR (Radiance RGBE) thumbnail generation for cache
        
        Much faster than full HDR loader because:
        1. Loads at reduced resolution (uses OpenCV downsampling)
        2. Simplified tone mapping (no exposure control)
        
        Args:
            file_path: Path to HDR file
            
        Returns:
            QPixmap or None
        """
        # Auto-tag color space FIRST (before thumbnail generation)
        # This ensures tags are available when preview panel loads the file
        if self.metadata_manager:
            try:
                from .aces_color import auto_tag_file_colorspace
                auto_tag_file_colorspace(file_path, self.metadata_manager)
            except Exception as tag_error:
                if DEBUG_MODE:
                    print(f"[HDR-OPT] Warning: Auto-tagging failed: {tag_error}")
        
        try:
            import cv2
            import numpy as np
            
            # Suppress OpenCV/FFmpeg verbose output
            cv2.setLogLevel(0)  # 0 = Silent
            
            if DEBUG_MODE:
                print(f"[HDR-OPT] Loading HDR with OpenCV: {Path(file_path).name}")
            
            # OPTIMIZATION: Use OpenCV imread with REDUCED flag for fast thumbnail
            # This loads the image at 1/2, 1/4, or 1/8 resolution during decode
            # Pass file_path to check original dimensions
            imread_flags = self._get_opencv_imread_flags(file_path=file_path)
            
            if DEBUG_MODE:
                print(f"[HDR-OPT] → Using imread flags: {imread_flags}")
            
            # OpenCV can't handle Unicode paths
            file_path_str = str(file_path)
            has_non_ascii = any(ord(c) > 127 for c in file_path_str)
            
            rgb = None
            if has_non_ascii:
                # Use buffer method for non-ASCII paths
                try:
                    if DEBUG_MODE:
                        print(f"[HDR-OPT] Using buffer method (non-ASCII path)")
                    with open(file_path_str, 'rb') as f:
                        file_bytes = np.frombuffer(f.read(), np.uint8)
                    rgb = cv2.imdecode(file_bytes, imread_flags)
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[HDR-OPT] Buffer decode failed: {e}")
            else:
                # ASCII-only path
                try:
                    if DEBUG_MODE:
                        print(f"[HDR-OPT] Using imread with flags={imread_flags}")
                    rgb = cv2.imread(file_path_str, imread_flags)
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[HDR-OPT] OpenCV imread failed: {e}")
            
            if rgb is None:
                raise Exception("OpenCV could not load HDR file")
            
            # Convert BGR to RGB
            rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
            
            if DEBUG_MODE:
                print(f"[HDR-OPT] → Loaded: {rgb.shape[1]}x{rgb.shape[0]}, dtype={rgb.dtype}")
            
            # Additional resize if still too large (imread_flags may not be enough)
            height, width = rgb.shape[:2]
            if width > self.thumbnail_size or height > self.thumbnail_size:
                scale = min(self.thumbnail_size / width, self.thumbnail_size / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                
                if DEBUG_MODE:
                    print(f"[HDR-OPT] → Additional resize to {new_width}x{new_height}")
                
                rgb = cv2.resize(rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
                width, height = new_width, new_height
            else:
                if DEBUG_MODE:
                    print(f"[HDR-OPT] → No additional resize needed")
            
            # Simplified tone mapping (Reinhard - fast for thumbnails)
            # HDR files are always Linear sRGB, no ACES needed
            if DEBUG_MODE:
                min_val = np.min(rgb)
                max_val = np.max(rgb)
                mean_val = np.mean(rgb)
                print(f"[HDR-OPT] → HDR range: min={min_val:.3f}, max={max_val:.3f}, mean={mean_val:.3f}")
            
            rgb = np.clip(rgb, 0, None)  # Clamp negatives
            rgb_tonemapped = rgb / (1.0 + rgb)
            
            if DEBUG_MODE:
                print(f"[HDR-OPT] → Applied Reinhard tone mapping")
            
            # Gamma correction (2.2 for sRGB)
            gamma = 1.0 / 2.2
            rgb_tonemapped = np.power(rgb_tonemapped, gamma)
            
            if DEBUG_MODE:
                print(f"[HDR-OPT] → Applied gamma correction (2.2)")
            
            # Convert to 8-bit
            rgb_8bit = (rgb_tonemapped * 255).astype(np.uint8)
            
            # Create QImage
            if PYSIDE_VERSION == 6:
                from PySide6.QtGui import QImage
            else:
                from PySide2.QtGui import QImage
            
            bytes_per_line = width * 3
            q_image = QImage(rgb_8bit.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
            q_image = q_image.copy()
            
            # Convert to QPixmap
            pixmap = QPixmap.fromImage(q_image)
            
            if DEBUG_MODE:
                print(f"[HDR-OPT] ✓ Thumbnail generated: {width}x{height}")
            
            return pixmap
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[HDR-OPT] Failed to load HDR: {e}")
            return None
    
    def _get_default_icon(self, file_path):
        """
        Get attractive default icon based on file type
        Creates gradient-based icon with file extension
        """
        from .utils import get_icon_colors
        
        extension = os.path.splitext(str(file_path))[1].lower()
        
        # Create pixmap
        pixmap = QPixmap(self.thumbnail_size, self.thumbnail_size)
        pixmap.fill(Qt.transparent)
        
        # Get colors from config
        color_primary, color_secondary = get_icon_colors(extension)
        colors = (
            QColor(*color_primary),   # Convert [R,G,B] to QColor
            QColor(*color_secondary)
        )
        
        # Create gradient background
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Gradient from top to bottom
        gradient = QLinearGradient(0, 0, 0, self.thumbnail_size)
        gradient.setColorAt(0, colors[0])
        gradient.setColorAt(1, colors[1])
        
        # Draw rounded rectangle
        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        rect = QRect(2, 2, self.thumbnail_size - 4, self.thumbnail_size - 4)
        painter.drawRoundedRect(rect, 8, 8)
        
        # Draw border
        painter.setPen(QPen(QColor(0, 0, 0, 60), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 8, 8)
        
        # Draw file extension text
        painter.setPen(QColor(255, 255, 255, 230))
        font = QFont(UI_FONT, max(12, self.thumbnail_size // 10), QFont.Bold)
        painter.setFont(font)
        
        text = extension[1:].upper() if len(extension) > 1 else "FILE"
        painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
        
        # Draw file icon (simple document shape)
        painter.setPen(QPen(QColor(255, 255, 255, 100), 2))
        icon_size = self.thumbnail_size // 4
        icon_x = self.thumbnail_size - icon_size - 8
        icon_y = 8
        painter.drawRect(icon_x, icon_y, icon_size, icon_size)
        
        painter.end()
        
        return pixmap
