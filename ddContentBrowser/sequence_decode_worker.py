# -*- coding: utf-8 -*-
"""
DD Content Browser - Sequence Frame Decode Worker (separate-process)

Standalone worker process for sequence-playback frame decode+tonemap.
Launched via mayapy.exe (Maya's headless Python interpreter) as a
genuinely separate OS process from Maya itself - see
SequenceProcessPrefetcher in sequence_cache.py for the launching side.

Protocol: reads length-prefixed pickled request dicts from stdin, decodes
+tone-maps one frame each via sequence_decode.decode_sequence_frame_raw(),
and writes length-prefixed pickled result dicts to stdout. One request in,
one response out, in order - a simple blocking loop (the parent process
runs several of these concurrently for parallelism, not this script).

Why a separate process at all: calling OpenImageIO/OpenCV concurrently
from ThreadPoolExecutor worker THREADS inside Maya's own process crashed
Maya outright - confirmed via a real crash with no Python traceback (i.e.
a native crash, not a Python exception) immediately after the first
background decode requests were submitted. Running decode in a genuinely
separate OS process isolates Maya from whatever in that combination
doesn't like being called concurrently in-process. Deliberately imports
only sequence_decode.py (pure numpy/OIIO/OpenCV, zero Qt/Maya deps) - NOT
widgets.py, which would transitively pull in preview_panel.py's ~8000
lines of Qt widget code for no reason in a headless worker.

Author: ddankhazi
License: MIT
"""

import sys
import os
import struct
import pickle
import traceback


def _setup_import_path():
    # This file lives at <package_parent>/ddContentBrowser/sequence_decode_worker.py
    package_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(package_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)


def _read_message(stream):
    """Read one length-prefixed pickled message, or None on EOF (parent closed the pipe)."""
    header = stream.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack('>I', header)
    data = b''
    while len(data) < length:
        chunk = stream.read(length - len(data))
        if not chunk:
            return None
        data += chunk
    return pickle.loads(data)


def _write_message(stream, obj):
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(struct.pack('>I', len(data)))
    stream.write(data)
    stream.flush()


def main():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    _setup_import_path()

    from ddContentBrowser.sequence_decode import decode_sequence_frame_raw

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        request = _read_message(stdin)
        if request is None:
            break

        request_id = request.get('request_id')
        try:
            result = decode_sequence_frame_raw(
                request['file_path'], request['max_size'],
                channel_name=request.get('channel_name'),
                exposure=request.get('exposure', 0.0),
                use_aces=request.get('use_aces', False),
            )
            if result is None:
                _write_message(stdout, {'request_id': request_id, 'success': False, 'error': 'decode returned None'})
            else:
                _write_message(stdout, {
                    'request_id': request_id, 'success': True,
                    'array': result['array'], 'width': result['width'],
                    'height': result['height'], 'resolution_str': result['resolution_str'],
                })
        except Exception as e:
            _write_message(stdout, {
                'request_id': request_id, 'success': False,
                'error': f'{e}\n{traceback.format_exc()}',
            })


if __name__ == '__main__':
    main()
