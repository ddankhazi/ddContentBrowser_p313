# -*- coding: utf-8 -*-
"""
DD Content Browser - Sequence Frame Cache

Background-prefetching, memory-bounded cache for image-sequence playback
(EXR/HDR/TX/TIFF - the formats expensive enough to be worth prefetching;
JPG/PNG/etc already decode fast enough synchronously).

Architecture (RV-style: the cache stores the FINISHED, display-ready frame,
not intermediate data - a hit should mean "just draw it", not "now do some
more work"):
- SequenceFrameCache: LRU cache of fully decoded AND tone-mapped uint8
  arrays, ready to wrap in a QImage/QPixmap with no further computation.
  Keyed by (sequence pattern, frame index, channel, exposure) - exposure is
  part of the key because it's baked into the stored pixels; changing it
  naturally misses and re-renders at the new value rather than needing
  explicit invalidation. Memory-budgeted in bytes rather than frame count,
  since frame size varies wildly by resolution/format. Plain dict + lock -
  safe to read/write from any thread.
- SequenceFramePrefetcher: manages a small pool of PERSISTENT WORKER
  SUBPROCESSES (mayapy.exe running sequence_decode_worker.py) that decode
  AND tone-map frames, communicating over stdin/stdout pipes. Results land
  on a thread-safe queue via lightweight reader threads that only move
  bytes (unpickle), never call into OpenImageIO/OpenCV/Qt themselves. The
  caller (PreviewPanel, on the main/GUI thread) drains that queue on a
  timer and is the ONLY place that touches the cache's contents for
  display purposes.

Why separate OS processes and not just background threads: an earlier
version of this used a ThreadPoolExecutor with workers calling
OpenImageIO/OpenCV in-process - this crashed Maya outright (a native
crash, no Python traceback, immediately after the first background decode
requests were submitted). An even earlier, abandoned attempt (see the
commented-out import that used to be in preview_panel.py) had a different
bug - its background QThread called all the way through to QPixmap
construction, which is never safe off the GUI thread - but the in-process
native-library crash persisted even after fixing that. Running decode in
genuinely separate OS processes isolates Maya from whatever in that
combination doesn't like being called concurrently in-process; if a
worker process crashes, Maya keeps running.

Author: ddankhazi
License: MIT
"""

import os
import threading
import struct
import pickle
import subprocess
from collections import OrderedDict
from queue import Queue, Empty


class SequenceFrameCache:
    """
    LRU cache of fully decoded and tone-mapped (display-ready) frames.

    Cache key: (sequence_pattern, frame_index, channel_name, exposure)
    - sequence_pattern: unique identifier for the sequence (e.g. "ocean.####.exr")
    - frame_index: 0-based index into sequence.files
    - channel_name: EXR layer/channel name, or None for everything else
    - exposure: rounded to 1 decimal (matches the UI slider's 0.1-stop
      granularity) - baked into the stored pixels, so it's part of the key

    Thread-safe: every method takes a lock.
    """

    def __init__(self, max_size_mb=1024):
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.cache = OrderedDict()  # key -> {'array','width','height','resolution_str','bytes'}
        self.current_size_bytes = 0
        self.lock = threading.Lock()

    def _key(self, sequence_pattern, frame_index, channel_name, exposure):
        return (sequence_pattern, frame_index, channel_name, round(exposure, 1))

    def get(self, sequence_pattern, frame_index, channel_name=None, exposure=0.0):
        """Returns the cached entry dict and marks it as recently used, or None on miss."""
        with self.lock:
            key = self._key(sequence_pattern, frame_index, channel_name, exposure)
            entry = self.cache.get(key)
            if entry is not None:
                self.cache.move_to_end(key)
            return entry

    def contains(self, sequence_pattern, frame_index, channel_name=None, exposure=0.0):
        with self.lock:
            return self._key(sequence_pattern, frame_index, channel_name, exposure) in self.cache

    def cached_indices(self, sequence_pattern, channel_name=None, exposure=0.0):
        """Set of frame indices currently cached for a sequence at the given
        exposure (for slider visualization)."""
        with self.lock:
            exposure_r = round(exposure, 1)
            return {key[1] for key in self.cache.keys()
                    if key[0] == sequence_pattern and key[2] == channel_name and key[3] == exposure_r}

    def put(self, sequence_pattern, frame_index, channel_name, exposure, array, width, height, resolution_str):
        with self.lock:
            key = self._key(sequence_pattern, frame_index, channel_name, exposure)
            nbytes = int(array.nbytes)

            if key in self.cache:
                self.current_size_bytes -= self.cache[key]['bytes']
                del self.cache[key]

            while self.current_size_bytes + nbytes > self.max_size_bytes and self.cache:
                _, evicted = self.cache.popitem(last=False)
                self.current_size_bytes -= evicted['bytes']

            self.cache[key] = {
                'array': array, 'width': width, 'height': height,
                'resolution_str': resolution_str, 'bytes': nbytes,
            }
            self.current_size_bytes += nbytes

    def clear(self):
        with self.lock:
            self.cache.clear()
            self.current_size_bytes = 0

    def clear_sequence(self, sequence_pattern):
        with self.lock:
            keys_to_remove = [k for k in self.cache.keys() if k[0] == sequence_pattern]
            for key in keys_to_remove:
                self.current_size_bytes -= self.cache[key]['bytes']
                del self.cache[key]

    def set_max_size_mb(self, max_size_mb):
        """Change the memory budget (e.g. from a live Settings change).
        Evicts immediately if the new budget is smaller than current usage."""
        with self.lock:
            self.max_size_bytes = max_size_mb * 1024 * 1024
            while self.current_size_bytes > self.max_size_bytes and self.cache:
                _, evicted = self.cache.popitem(last=False)
                self.current_size_bytes -= evicted['bytes']

    def get_stats(self):
        with self.lock:
            return {
                'frames_cached': len(self.cache),
                'size_mb': self.current_size_bytes / (1024 * 1024),
                'max_size_mb': self.max_size_bytes / (1024 * 1024),
            }


# Backwards-compatible alias - the class used to store pre-tonemap data.
SequenceRawFrameCache = SequenceFrameCache


class _WorkerProcess:
    """
    One persistent sequence_decode_worker.py subprocess, plus its dedicated
    writer/reader/stderr-drain threads. Those threads only move bytes
    (write a pickled request, read+unpickle a pickled response) - they
    never call into OpenImageIO/OpenCV themselves, so nothing here reintroduces
    the in-process native-library concurrency that crashed Maya.
    """

    def __init__(self, mayapy_exe, worker_script, result_queue):
        self.result_queue = result_queue
        self.request_queue = Queue()
        self.alive = True

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # no console window

        self.process = subprocess.Popen(
            [mayapy_exe, worker_script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            startupinfo=startupinfo,
        )

        self.writer_thread = threading.Thread(target=self._writer_loop, daemon=True, name="SeqDecodeWriter")
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True, name="SeqDecodeReader")
        self.stderr_thread = threading.Thread(target=self._stderr_drain_loop, daemon=True, name="SeqDecodeStderr")
        self.writer_thread.start()
        self.reader_thread.start()
        self.stderr_thread.start()

    def submit(self, request):
        self.request_queue.put(request)

    def _writer_loop(self):
        while self.alive:
            request = self.request_queue.get()
            if request is None:
                break
            try:
                data = pickle.dumps(request, protocol=pickle.HIGHEST_PROTOCOL)
                self.process.stdin.write(struct.pack('>I', len(data)))
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except Exception:
                break

    def _reader_loop(self):
        stdout = self.process.stdout
        while self.alive:
            header = stdout.read(4)
            if len(header) < 4:
                break
            (length,) = struct.unpack('>I', header)
            data = b''
            while len(data) < length:
                chunk = stdout.read(length - len(data))
                if not chunk:
                    return
                data += chunk
            try:
                response = pickle.loads(data)
            except Exception:
                continue
            self.result_queue.put(response)

    def _stderr_drain_loop(self):
        # Just drain and discard - prevents the worker from blocking if it
        # ever writes to stderr (e.g. a library warning) and nobody's
        # reading it. Not surfaced anywhere; this is a persistent
        # background worker, not a one-shot subprocess call to inspect.
        try:
            while self.alive:
                if not self.process.stderr.readline():
                    break
        except Exception:
            pass

    def shutdown(self):
        self.alive = False
        self.request_queue.put(None)
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.terminate()
        except Exception:
            pass


class SequenceFramePrefetcher:
    """
    Background prefetcher for image-sequence frames, backed by a small pool
    of persistent worker SUBPROCESSES (see _WorkerProcess) instead of
    threads - see this module's docstring for why.

    request() computes which frames in a window around the current playhead
    still need decoding+tone-mapping and dispatches them round-robin across
    the worker pool. The caller must periodically call drain(cache) from
    the main/GUI thread - that's the only place results are moved into the
    cache and the only place a slider-visualization update should be
    triggered.
    """

    def __init__(self, max_workers=2):
        from .utils import get_mayapy_executable
        mayapy_exe = get_mayapy_executable()
        worker_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sequence_decode_worker.py')

        self._result_queue = Queue()
        self._lock = threading.Lock()
        self._next_request_id = 0
        self._id_to_key = {}
        self._in_flight_keys = set()
        self._round_robin_index = 0

        self._workers = [
            _WorkerProcess(mayapy_exe, worker_script, self._result_queue)
            for _ in range(max_workers)
        ]

    def request(self, sequence, current_index, cache, max_size, channel_name=None,
                exposure=0.0, metadata_manager=None, ahead=8, behind=2):
        """
        Ensure a window of frames around current_index is cached or in-flight.

        Args:
            sequence: ImageSequence (needs .pattern and .files)
            current_index: 0-based index of the frame currently being shown
            cache: SequenceFrameCache to check against (avoid re-requesting hits)
            max_size: preview resolution clamp to decode at
            channel_name: EXR layer/channel to decode (None for other formats)
            exposure: current exposure in stops (baked into the decoded result)
            metadata_manager: for ACES/colorspace tag lookup on .exr - looked
                up HERE, on the caller's thread (fast SQLite reads, same
                pattern cache.py's thumbnail workers already use), and sent
                to the worker as a plain bool since the worker process has
                no database access of its own
            ahead: how many frames after current_index to prefetch
            behind: how many frames before current_index to prefetch (small -
                    playback is forward-biased, but scrubbing back a little
                    is common)
        """
        if not sequence or not sequence.files:
            return

        frame_count = len(sequence.files)
        pattern = sequence.pattern
        exposure_r = round(exposure, 1)

        start = max(0, current_index - behind)
        end = min(frame_count - 1, current_index + ahead)

        # Forward-biased order: current+1, current+2, ... then the small
        # trailing window - so playback direction gets decoded first.
        indices = list(range(current_index + 1, end + 1)) + list(range(current_index, start - 1, -1))

        for index in indices:
            file_path = sequence.files[index]
            key = (pattern, index, channel_name, exposure_r)

            with self._lock:
                if key in self._in_flight_keys:
                    continue
                if cache.contains(pattern, index, channel_name, exposure_r):
                    continue
                self._in_flight_keys.add(key)
                request_id = self._next_request_id
                self._next_request_id += 1
                self._id_to_key[request_id] = key
                worker = self._workers[self._round_robin_index % len(self._workers)]
                self._round_robin_index += 1

            use_aces = False
            file_ext = str(file_path).lower()
            if file_ext.endswith('.exr') and metadata_manager:
                try:
                    file_metadata = metadata_manager.get_file_metadata(str(file_path))
                    tag_names_lower = [t['name'].lower() for t in file_metadata.get('tags', [])]
                    use_aces = "acescg" in tag_names_lower or "srgb(aces)" in tag_names_lower
                except Exception:
                    use_aces = False

            worker.submit({
                'request_id': request_id, 'file_path': str(file_path), 'max_size': max_size,
                'channel_name': channel_name, 'exposure': exposure_r, 'use_aces': use_aces,
            })

    def drain(self, cache, max_items=50):
        """
        Move any completed decode results into the cache. Call this from
        the main/GUI thread on a timer. Returns the set of (pattern,
        frame_index) pairs that were newly cached this call, for slider
        visualization updates.
        """
        newly_cached = set()
        for _ in range(max_items):
            try:
                response = self._result_queue.get_nowait()
            except Empty:
                break

            request_id = response.get('request_id')
            with self._lock:
                key = self._id_to_key.pop(request_id, None)
                if key is not None:
                    self._in_flight_keys.discard(key)

            if key is None or not response.get('success'):
                continue

            pattern, frame_index, channel_name, exposure = key
            cache.put(
                pattern, frame_index, channel_name, exposure,
                response['array'], response['width'], response['height'], response['resolution_str'],
            )
            newly_cached.add((pattern, frame_index))

        return newly_cached

    def clear_pending(self):
        """Drop any queued-but-undelivered results (does not cancel in-flight decodes)."""
        with self._lock:
            self._in_flight_keys.clear()
            self._id_to_key.clear()
        while True:
            try:
                self._result_queue.get_nowait()
            except Empty:
                break

    def shutdown(self):
        for worker in self._workers:
            worker.shutdown()


