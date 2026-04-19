"""
DD Content Browser - Sequence Frame Cache
LRU cache system for image sequence playback optimization

Features:
- LRU eviction policy (least recently used frames removed first)
- Configurable memory limit
- Preload frames ahead/behind current position
- Thread-safe access
- Cache key includes exposure value for HDR/EXR sequences

Author: ddankhazi
License: MIT
"""

from collections import OrderedDict
from pathlib import Path
import threading

try:
    from PySide6.QtGui import QPixmap
    from PySide6.QtCore import QThread, Signal
except ImportError:
    from PySide2.QtGui import QPixmap
    from PySide2.QtCore import QThread, Signal


class SequenceFrameCache:
    """
    LRU cache for sequence frames with memory management
    
    Cache key format: (sequence_pattern, frame_index, exposure_value)
    - sequence_pattern: unique identifier for the sequence (e.g., "render_####.exr")
    - frame_index: 0-based frame index in sequence.files list
    - exposure_value: exposure compensation for HDR/EXR (0.0 for standard images)
    
    Thread-safe: uses lock for all operations
    """
    
    def __init__(self, max_size_mb=512, max_frames=100):
        """
        Initialize sequence frame cache
        
        Args:
            max_size_mb: Maximum cache size in megabytes (default 512MB)
            max_frames: Maximum number of frames to cache (default 100)
        """
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.max_frames = max_frames
        
        # OrderedDict maintains insertion order for LRU tracking
        # Key: (sequence_pattern, frame_index, exposure_value)
        # Value: (QPixmap, size_bytes, resolution_str)
        self.cache = OrderedDict()
        
        self.current_size_bytes = 0
        self.lock = threading.Lock()
        
        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def get(self, sequence_pattern, frame_index, exposure=0.0):
        """
        Get frame from cache (marks as recently used)
        
        Args:
            sequence_pattern: Sequence identifier (e.g., "render_####.exr")
            frame_index: 0-based frame index
            exposure: Exposure value for HDR/EXR (default 0.0)
            
        Returns:
            tuple: (QPixmap, resolution_str) or (None, None) if not in cache
        """
        with self.lock:
            key = (sequence_pattern, frame_index, round(exposure, 2))
            
            if key in self.cache:
                # Move to end (mark as recently used)
                self.cache.move_to_end(key)
                pixmap, size_bytes, resolution_str = self.cache[key]
                self.hits += 1
                return pixmap, resolution_str
            else:
                self.misses += 1
                return None, None
    
    def put(self, sequence_pattern, frame_index, pixmap, resolution_str, exposure=0.0):
        """
        Add frame to cache (evicts old frames if needed)
        
        Args:
            sequence_pattern: Sequence identifier
            frame_index: 0-based frame index
            pixmap: QPixmap to cache
            resolution_str: Resolution string (e.g., "1920 x 1080")
            exposure: Exposure value for HDR/EXR (default 0.0)
        """
        if pixmap is None or pixmap.isNull():
            return
        
        with self.lock:
            key = (sequence_pattern, frame_index, round(exposure, 2))
            
            # Calculate pixmap size in bytes (width * height * 4 bytes per pixel for ARGB)
            size_bytes = pixmap.width() * pixmap.height() * 4
            
            # If this frame is already cached, remove old entry
            if key in self.cache:
                old_pixmap, old_size, old_res = self.cache[key]
                self.current_size_bytes -= old_size
                del self.cache[key]
            
            # Evict old frames if cache is full
            while (len(self.cache) >= self.max_frames or 
                   self.current_size_bytes + size_bytes > self.max_size_bytes):
                if not self.cache:
                    break
                # Remove oldest (first) item
                oldest_key, (oldest_pixmap, oldest_size, oldest_res) = self.cache.popitem(last=False)
                self.current_size_bytes -= oldest_size
                self.evictions += 1
            
            # Add new frame to cache (at end = most recently used)
            self.cache[key] = (pixmap, size_bytes, resolution_str)
            self.current_size_bytes += size_bytes
    
    def clear(self):
        """Clear entire cache"""
        with self.lock:
            self.cache.clear()
            self.current_size_bytes = 0
            self.evictions = 0
    
    def clear_sequence(self, sequence_pattern):
        """
        Clear all frames for a specific sequence
        
        Args:
            sequence_pattern: Sequence identifier to clear
        """
        with self.lock:
            keys_to_remove = [key for key in self.cache.keys() if key[0] == sequence_pattern]
            for key in keys_to_remove:
                pixmap, size_bytes, resolution_str = self.cache[key]
                self.current_size_bytes -= size_bytes
                del self.cache[key]
    
    def keep_only_range(self, sequence_pattern, start_index, end_index, exposure=0.0):
        """
        Remove all cached frames outside the specified range for a sequence
        
        Args:
            sequence_pattern: Sequence identifier
            start_index: First frame index to keep (inclusive)
            end_index: Last frame index to keep (inclusive)
            exposure: Exposure value for HDR/EXR (default 0.0)
        """
        with self.lock:
            keys_to_remove = []
            for key in self.cache.keys():
                pattern, frame_index, exp = key
                if pattern == sequence_pattern and round(exp, 2) == round(exposure, 2):
                    if frame_index < start_index or frame_index > end_index:
                        keys_to_remove.append(key)
            
            for key in keys_to_remove:
                pixmap, size_bytes, resolution_str = self.cache[key]
                self.current_size_bytes -= size_bytes
                del self.cache[key]
                # Don't count as eviction since this is intentional cleanup
    
    def get_stats(self):
        """
        Get cache statistics
        
        Returns:
            dict: Statistics dictionary
        """
        with self.lock:
            total_requests = self.hits + self.misses
            hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0.0
            
            return {
                'frames_cached': len(self.cache),
                'size_mb': self.current_size_bytes / (1024 * 1024),
                'max_size_mb': self.max_size_bytes / (1024 * 1024),
                'hits': self.hits,
                'misses': self.misses,
                'hit_rate': hit_rate,
                'evictions': self.evictions
            }
    
    def print_stats(self):
        """Print cache statistics to console"""
        stats = self.get_stats()
        print(f"\n[Sequence Cache Stats]")
        print(f"  Frames cached: {stats['frames_cached']}/{self.max_frames}")
        print(f"  Memory used: {stats['size_mb']:.1f}/{stats['max_size_mb']:.0f} MB")
        print(f"  Hit rate: {stats['hit_rate']:.1f}% ({stats['hits']} hits, {stats['misses']} misses)")
        print(f"  Evictions: {stats['evictions']}")


class SequencePreloader:
    """
    Background preloader for sequence frames
    
    Preloads frames with adaptive strategy:
    - Forward cache during playback (preload ahead only)
    - Centered buffer when stopped (preload ahead and behind)
    """
    
    def __init__(self, cache, preload_ahead=16, preload_behind=16):
        """
        Initialize preloader
        
        Args:
            cache: SequenceFrameCache instance
            preload_ahead: Number of frames to preload ahead (default 16)
            preload_behind: Number of frames to preload behind when stopped (default 16)
        """
        self.cache = cache
        self.preload_ahead = preload_ahead
        self.preload_behind = preload_behind
        self.is_playing = False  # Track playback state for adaptive strategy
    
    def set_playing_state(self, is_playing):
        """Update playback state for adaptive preloading"""
        self.is_playing = is_playing
    
    def preload_frames(self, sequence, current_index, load_frame_callback, exposure=0.0, batch_size=10):
        """
        Preload frames around current position (batched for smooth performance)
        
        Strategy:
        - If playing: Forward cache only (current to current+preload_ahead)
        - If stopped: Centered buffer (current-preload_behind to current+preload_ahead)
        
        Args:
            sequence: ImageSequence object
            current_index: Current frame index
            load_frame_callback: Function to load frame (frame_path) -> (pixmap, resolution_str)
            exposure: Exposure value for HDR/EXR
            batch_size: Number of frames to load per batch (default 10)
            
        Returns:
            tuple: (preloaded_count, more_remaining) where:
                - preloaded_count: Number of frames loaded in this batch
                - more_remaining: True if more uncached frames exist, False if cache is complete
        """
        if not sequence or not sequence.files:
            return
        
        frame_count = len(sequence.files)
        pattern = sequence.pattern
        
        # Adaptive preload range based on playback state
        if self.is_playing:
            # Forward cache during playback: only preload ahead
            # But keep past frames in cache (don't remove them, LRU will handle)
            start_index = current_index + 1  # Start from next frame (current already loaded)
            end_index = min(frame_count - 1, current_index + self.preload_ahead)
            print(f"[CACHE] PLAYING mode: preload {start_index} to {end_index} (current={current_index}, ahead={self.preload_ahead})")
        else:
            # Centered buffer when stopped: preload behind and ahead
            # Adjust range at edges (start/end of sequence)
            start_index = max(0, current_index - self.preload_behind)
            end_index = min(frame_count - 1, current_index + self.preload_ahead)
            
            # At edges, shift the buffer to use full cache capacity
            available_behind = current_index - start_index
            available_ahead = end_index - current_index
            
            # If can't go back enough, extend forward
            if available_behind < self.preload_behind and end_index < frame_count - 1:
                extra = self.preload_behind - available_behind
                end_index = min(frame_count - 1, end_index + extra)
            
            # If can't go forward enough, extend backward
            if available_ahead < self.preload_ahead and start_index > 0:
                extra = self.preload_ahead - available_ahead
                start_index = max(0, start_index - extra)
            
            print(f"[CACHE] STOPPED mode: preload {start_index} to {end_index} (current={current_index}, range={end_index-start_index+1} frames)")
        
        preloaded = 0
        uncached_remaining = 0  # Track how many frames still need loading
        
        for index in range(start_index, end_index + 1):
            # Skip current frame (already loaded)
            if index == current_index:
                continue
            
            # Check if already in cache
            cached_pixmap, _ = self.cache.get(pattern, index, exposure)
            if cached_pixmap is not None:
                continue
            
            # This frame needs loading
            uncached_remaining += 1
            
            # Stop after batch_size frames to avoid blocking
            if preloaded >= batch_size:
                continue  # Count remaining but don't load
            
            # Load and cache frame
            frame_path = sequence.files[index]
            pixmap, resolution_str = load_frame_callback(frame_path)
            
            if pixmap and not pixmap.isNull():
                self.cache.put(pattern, index, pixmap, resolution_str, exposure)
                preloaded += 1
        
        # Return number preloaded and whether more frames remain
        more_remaining = (uncached_remaining - preloaded) > 0
        return preloaded, more_remaining


class SequencePreloaderThread(QThread):
    """
    Background thread for preloading sequence frames without blocking UI
    
    Signals:
        frames_loaded: Emitted when a batch of frames has been loaded (count)
        preload_complete: Emitted when all requested frames are cached
    """
    
    frames_loaded = Signal(int)  # Number of frames loaded in this batch
    preload_complete = Signal()
    
    def __init__(self, cache, preloader, parent=None):
        super().__init__(parent)
        self.cache = cache
        self.preloader = preloader
        self.is_running = True
        self.current_job = None  # (sequence, current_index, load_callback, exposure)
        self.job_lock = threading.Lock()
    
    def request_preload(self, sequence, current_index, load_frame_callback, exposure=0.0):
        """Request a new preload job (replaces any existing job)"""
        with self.job_lock:
            self.current_job = (sequence, current_index, load_frame_callback, exposure)
    
    def clear_job(self):
        """Clear current job"""
        with self.job_lock:
            self.current_job = None
    
    def stop(self):
        """Stop the thread"""
        self.is_running = False
        self.clear_job()
    
    def run(self):
        """Main thread loop - process preload jobs"""
        try:
            while self.is_running:
                # Check if there's a job
                with self.job_lock:
                    job = self.current_job
                    if job is None:
                        self.msleep(50)  # Sleep 50ms if no job
                        continue
                
                # Check if still running (could have been stopped during sleep)
                if not self.is_running:
                    break
                
                # Unpack job
                sequence, current_index, load_frame_callback, exposure = job
                
                # Preload in small batches to allow job cancellation
                batch_size = 5  # Small batches for responsive cancellation
                
                try:
                    preloaded, more_remaining = self.preloader.preload_frames(
                        sequence, current_index, load_frame_callback, exposure, batch_size=batch_size
                    )
                    
                    # Emit signal if we loaded something (check still running)
                    if preloaded > 0 and self.is_running:
                        self.frames_loaded.emit(preloaded)
                    
                    # If no more frames to load, mark job complete and clear it
                    if not more_remaining:
                        if self.is_running:
                            self.preload_complete.emit()
                        with self.job_lock:
                            self.current_job = None
                    else:
                        # Sleep between batches to avoid CPU hogging
                        self.msleep(50)
                        
                except Exception as e:
                    # Silent fail on errors (e.g., file not found, decode error)
                    with self.job_lock:
                        self.current_job = None
                        
        except Exception as e:
            # Catch any unexpected errors to prevent crash
            print(f"[PreloaderThread] Unexpected error: {e}")
