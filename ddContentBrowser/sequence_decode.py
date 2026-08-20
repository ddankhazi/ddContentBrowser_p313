# -*- coding: utf-8 -*-
"""
DD Content Browser - Sequence Frame Decode (Qt/Maya-free)

Pure numpy/OpenImageIO/OpenCV decode+tone-map logic for image-sequence
playback (EXR/HDR/TX/TIFF). Deliberately has ZERO Qt or Maya imports, even
transitively - this module is imported both by widgets.py (for the normal
in-app code paths) AND by sequence_decode_worker.py, which runs as a
separate mayapy.exe OS process (see that file for why: calling
OpenImageIO/OpenCV concurrently from ThreadPoolExecutor worker THREADS
inside Maya's own process was crashing Maya outright - confirmed via a real
crash with no Python traceback, i.e. a native crash, immediately after the
first background decode requests were submitted). A worker process that
accidentally pulled in preview_panel.py's ~8000 lines of Qt widget code
(which widgets.py imports at module level) would be needlessly heavy and
risky to import headless - keeping this module import-light is the point.

Author: ddankhazi
License: MIT
"""


def _resize_float_rgb(img, new_width, new_height):
    """Resize a float32 (H,W,C) image without cv2 (avoids numpy/cv2 ABI mismatch)."""
    import numpy as np
    from PIL import Image
    channels = []
    for c in range(img.shape[2]):
        ch = np.ascontiguousarray(img[:, :, c], dtype=np.float32)
        pil = Image.fromarray(ch, mode='F').resize((new_width, new_height), Image.BILINEAR)
        channels.append(np.asarray(pil, dtype=np.float32))
    return np.stack(channels, axis=2)


def _compute_auto_mip_level(width, height, max_size):
    """
    Compute the target mip level using standard power-of-two mip-chain
    halving math (level N covers native / 2^N). Returns 0 (native/full res)
    if no clamp was requested (max_size falsy = "Off") or the native
    resolution is already <= max_size.

    Note: this does NOT check how many mip levels actually exist in the
    file - the OIIO 'miplevels' spec attribute is not reliably populated
    across .tx builds (confirmed empirically: real maketx-built .tx files
    report miplevels=1 despite having a full mip chain down to 1x1). The
    caller must verify the returned level exists via seek_subimage() and
    walk down toward 0 if it doesn't.
    """
    if not max_size:
        return 0
    native_max = max(width, height)
    if native_max <= max_size:
        return 0
    import math
    return int(math.floor(math.log2(native_max / max_size)))


def load_oiio_image_array(file_path, max_size=2048, mip_level=0):
    """
    Load image using OpenImageIO and return as numpy array (worker thread/
    process safe). Returns raw float32 array - caller handles tone mapping.

    Args:
        file_path: Path to image file
        max_size: Maximum width/height for thumbnail
        mip_level: Mipmap level to load (0 = full res, 1 = half res, etc.),
                   or 'auto' to pick the smallest mip level that still covers max_size

    Returns:
        numpy array (RGB, float32) or None on failure
    """
    try:
        import sys
        from .utils import get_external_libs_dir
        external_libs = get_external_libs_dir()
        if external_libs not in sys.path:
            sys.path.append(external_libs)

        from OpenImageIO import ImageInput
        import numpy as np

        file_path_str = str(file_path)

        inp = ImageInput.open(file_path_str)
        if not inp:
            return None

        spec = inp.spec()
        width = spec.width
        height = spec.height

        if mip_level == 'auto':
            mip_level = _compute_auto_mip_level(width, height, max_size)

        # Seek to the requested mip level, probing downward if it doesn't
        # exist (seek_subimage() is the source of truth - the 'miplevels'
        # spec attribute is not reliably populated, see _compute_auto_mip_level)
        while mip_level > 0 and not inp.seek_subimage(0, mip_level):
            mip_level -= 1
        if mip_level > 0:
            spec = inp.spec()
            width = spec.width
            height = spec.height

        if width <= 0 or height <= 0:
            return None

        pixels = inp.read_image()
        inp.close()

        if pixels is None:
            return None

        img = np.array(pixels, dtype=np.float32)

        if img.size == 0:
            return None

        if img.ndim == 2:
            img = np.stack([img, img, img], axis=2)
        elif img.ndim == 3:
            actual_channels = img.shape[2]
            if actual_channels == 1:
                img = np.concatenate([img, img, img], axis=2)
            elif actual_channels == 2:
                img = np.concatenate([img[:, :, 0:1], img[:, :, 0:1], img[:, :, 0:1]], axis=2)
            elif actual_channels == 4:
                img = img[:, :, :3]
            elif actual_channels > 4:
                img = img[:, :, :3]

        if width > max_size or height > max_size:
            scale = min(max_size / width, max_size / height)
            new_width = int(width * scale)
            new_height = int(height * scale)

            if new_width < 1 or new_height < 1:
                return None

            img = _resize_float_rgb(img, new_width, new_height)

        return img

    except Exception:
        return None


def decode_tiff_array(file_path, max_size=1024):
    """
    Decode a TIFF to a display-ready uint8 RGB numpy array via OpenImageIO,
    using its native pixel format (no float upcast for uint8-native TIFFs).

    Returns:
        tuple: (uint8 RGB numpy array, resolution_string) or (None, None)
    """
    try:
        import sys
        import numpy as np
        import cv2
        from .utils import get_external_libs_dir
        external_libs = get_external_libs_dir()
        if external_libs not in sys.path:
            sys.path.append(external_libs)
        from OpenImageIO import ImageInput

        inp = ImageInput.open(str(file_path))
        if not inp:
            return None, None

        spec = inp.spec()
        w0, h0 = spec.width, spec.height
        pixels = inp.read_image(spec.format)  # native format - avoids float upcast
        inp.close()

        if pixels is None:
            return None, None

        img_array = np.array(pixels)
        resolution_str = f"{w0} x {h0}"

        if img_array.ndim == 3:
            ch = img_array.shape[2]
            if ch in (1, 2):
                img_array = img_array[:, :, 0]
            elif ch >= 4:
                img_array = img_array[:, :, :3]

        # For float data, resize BEFORE the percentile-based normalization
        # below - np.percentile on the full-res array is a sort-based op
        # and measured ~215ms alone on a 4096x4096 float32 TIFF, dwarfing
        # everything else in this function. Resizing first (cv2 handles
        # float32 fine) cuts that to the cost of a 1024x1024 percentile.
        if img_array.dtype.kind == 'f' and (w0 > max_size or h0 > max_size):
            scale = min(max_size / w0, max_size / h0)
            new_w = max(1, int(w0 * scale))
            new_h = max(1, int(h0 * scale))
            img_array = cv2.resize(img_array, (new_w, new_h), interpolation=cv2.INTER_AREA)
            already_resized = True
        else:
            already_resized = False

        if img_array.dtype.kind == 'f':
            img_array = np.nan_to_num(img_array, nan=0.0, posinf=1.0, neginf=0.0)
            max_val = float(np.max(img_array)) if img_array.size else 0.0
            if max_val > 1.0:
                p99 = float(np.percentile(img_array, 99)) if img_array.size else 255.0
                scale_max = p99 if p99 > 0 else max_val
                img_array = np.clip(img_array / max(scale_max, 1e-6), 0.0, 1.0)
            else:
                img_array = np.clip(img_array, 0.0, 1.0)
            img_array = (img_array * 255.0).astype(np.uint8)
        elif img_array.dtype != np.uint8:
            if img_array.dtype.kind in ('i', 'u'):
                info = np.iinfo(img_array.dtype)
                denom = float(max(info.max - info.min, 1))
                img_array = ((img_array.astype(np.float32) - info.min) / denom * 255.0).astype(np.uint8)
            else:
                img_array = np.clip(img_array, 0, 255).astype(np.uint8)

        if img_array.ndim == 2:
            img_array = np.stack([img_array, img_array, img_array], axis=2)

        if not already_resized and (w0 > max_size or h0 > max_size):
            scale = min(max_size / w0, max_size / h0)
            new_w = max(1, int(w0 * scale))
            new_h = max(1, int(h0 * scale))
            img_array = cv2.resize(img_array, (new_w, new_h), interpolation=cv2.INTER_AREA)

        img_array = np.ascontiguousarray(img_array)
        return img_array, resolution_str

    except Exception:
        return None, None


def tonemap_hdr_linear_array(rgb, exposure_stops=0.0, use_aces=False):
    """
    Apply the same tone-mapping as PreviewPanel.apply_hdr_tone_mapping(),
    but return a uint8 array instead of a QPixmap. Keep this in sync with
    apply_hdr_tone_mapping() if that logic ever changes.

    Args:
        rgb: float32 (H,W,3) array in scene-linear space
        exposure_stops: exposure adjustment in stops
        use_aces: whether to apply the ACES view transform vs standard
            Filmic+gamma - the caller determines this (e.g. from an .exr's
            ACEScg tag) since this function has no metadata/database access
            of its own (it may be running in a separate OS process)

    Returns:
        uint8 (H,W,3) RGB array, display-ready
    """
    import numpy as np

    compensated_exposure = exposure_stops - 1.0

    if use_aces:
        from .aces_color import apply_aces_view_transform
        rgb_display = apply_aces_view_transform(rgb, exposure=compensated_exposure)
    else:
        exposure_multiplier = pow(2.0, compensated_exposure)
        rgb2 = rgb * exposure_multiplier
        a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
        rgb_tonemapped = np.clip((rgb2 * (a * rgb2 + b)) / (rgb2 * (c * rgb2 + d) + e), 0, 1)
        rgb_display = np.power(rgb_tonemapped, 1.0 / 2.2)

    return (rgb_display * 255).astype(np.uint8)


def tonemap_tx_array(rgb, file_path_str, exposure=0.0):
    """
    Apply the same .tx color-space detection + view transform as
    load_oiio_image()'s .tx branch, but to an already-decoded array instead
    of reading the file.

    Kept as a separate small function rather than refactoring
    load_oiio_image() to share it, to avoid touching that already-verified
    path; if this colorspace-detection logic changes again, both places
    need the same edit (also true of aces_color.auto_tag_file_colorspace's
    .tx branch, which all three keep in sync with today).

    Args:
        rgb: float32 (H,W,3) array in the file's native scene-linear space
        file_path_str: original file path (for the filename-suffix colorspace detection)
        exposure: exposure compensation in stops

    Returns:
        uint8 (H,W,3) RGB array, display-ready
    """
    import numpy as np
    from pathlib import Path

    filename = Path(file_path_str).stem.lower()
    colorspace_suffix_map = [
        ('acescg', "ACEScg"),
        ('scene-linear rec.2020', "ACEScg"),
        ('scene-linear rec.709-srgb', "Linear sRGB"),
        ('scene-linear dci-p3', "DCI-P3"),
    ]
    detected_colorspace = None
    for suffix, colorspace in colorspace_suffix_map:
        if suffix in filename:
            detected_colorspace = colorspace
            break
    if detected_colorspace is None:
        detected_colorspace = "ACEScg"

    compensated_exposure = exposure - 1.0

    if detected_colorspace == "ACEScg":
        from .aces_color import apply_aces_view_transform
        img = apply_aces_view_transform(rgb, exposure=compensated_exposure)
    elif detected_colorspace == "DCI-P3":
        from .aces_color import apply_dci_p3_view_transform
        img = apply_dci_p3_view_transform(rgb, exposure=0.0)
    else:
        img = rgb
        if exposure != 0.0:
            img = img * pow(2.0, compensated_exposure)
        if img.max() > 1.0:
            a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
            img = np.clip((img * (a * img + b)) / (img * (c * img + d) + e), 0, 1)
        img = np.clip(img, 0, 1)
        img = np.power(img, 1.0 / 2.2)

    return (img * 255).astype(np.uint8)


def decode_sequence_frame_raw(file_path, max_size, channel_name=None, exposure=0.0, use_aces=False):
    """
    Decode AND tone-map a single image-sequence frame. No Qt calls, no
    database/metadata access - safe to run in a worker thread OR a fully
    separate OS process (see sequence_decode_worker.py).

    Doing the tone-mapping here too (not just decode+resize) is the point:
    a cache is only worth what it saves on the hit path, and tone-mapping a
    1920x1080 EXR frame (Filmic curve + gamma) measured ~150-250ms on its
    own - nearly as expensive as the decode. If the cache only stored raw
    linear data and re-tone-mapped on every display, a "cache hit" would
    still block the UI thread for that long on every frame, which defeats
    the purpose for playback. Storing the finished, display-ready image
    means a hit is just a numpy->QImage->QPixmap wrap on the main thread
    (a few ms), while the expensive math happens ahead of time.

    Args:
        file_path: Path to the frame file
        max_size: Maximum width/height for the decoded array (falsy = no clamp)
        channel_name: For .exr files with named layers, which channel/layer to load
        exposure: exposure compensation in stops, baked into the result -
            the cache key includes this, so changing exposure naturally
            misses and re-decodes+re-tonemaps at the new value
        use_aces: for .exr, whether to use the ACES view transform (the
            caller determines this from the file's colorspace tag, since
            this function has no database access of its own)

    Returns:
        dict with keys 'array' (uint8 RGB, display-ready), 'width',
        'height', 'resolution_str', or None if this format isn't handled by
        the fast path or decode failed - caller should fall back to its
        normal synchronous loader.
    """
    file_path_str = str(file_path)
    ext = file_path_str.lower()

    try:
        import numpy as np

        if ext.endswith('.exr'):
            from .utils import read_exr_via_oiio
            width, height, channels = read_exr_via_oiio(file_path_str)

            # Same channel-name lookup ladder as PreviewPanel.load_exr_channel()
            rgb = None
            if channel_name and channel_name in channels:
                data = channels[channel_name]
                if data.ndim == 3 and data.shape[2] >= 3:
                    rgb = data[:, :, :3]
                elif data.ndim == 2:
                    rgb = np.stack([data, data, data], axis=2)
                else:
                    rgb = data
            if rgb is None and channel_name:
                r_name, g_name, b_name = f"{channel_name}.R", f"{channel_name}.G", f"{channel_name}.B"
                if all(c in channels for c in (r_name, g_name, b_name)):
                    rgb = np.stack([channels[r_name], channels[g_name], channels[b_name]], axis=2)
            if rgb is None and channel_name:
                for suffix in ('', '.R', '.r', '.x', '.X'):
                    test_name = f"{channel_name}{suffix}"
                    if test_name in channels:
                        data = channels[test_name]
                        rgb = np.stack([data, data, data], axis=2) if data.ndim == 2 else data
                        break
            if rgb is None:
                # No channel requested (or not found) - fall back to the
                # first available channel group, same as an unmatched
                # channel_name would eventually surface as an error upstream
                if not channels:
                    return None
                first = next(iter(channels.values()))
                if first.ndim == 3 and first.shape[2] >= 3:
                    rgb = first[:, :, :3]
                elif first.ndim == 2:
                    rgb = np.stack([first, first, first], axis=2)
                else:
                    return None

            if rgb.dtype == np.float16:
                rgb = rgb.astype(np.float32)

            resolution_str = f"{width} x {height}"
            if max_size and (width > max_size or height > max_size):
                import cv2
                scale = min(max_size / width, max_size / height)
                new_width, new_height = int(width * scale), int(height * scale)
                rgb = cv2.resize(rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
                width, height = new_width, new_height

            display = tonemap_hdr_linear_array(rgb, exposure_stops=exposure, use_aces=use_aces)
            return {'array': display, 'width': width, 'height': height, 'resolution_str': resolution_str}

        elif ext.endswith('.hdr'):
            import sys
            from .utils import get_external_libs_dir
            external_libs = get_external_libs_dir()
            if external_libs not in sys.path:
                sys.path.append(external_libs)
            from OpenImageIO import ImageInput

            inp = ImageInput.open(file_path_str)
            if not inp:
                return None
            spec = inp.spec()
            width, height = spec.width, spec.height
            pixels = inp.read_image()
            inp.close()
            if pixels is None:
                return None

            rgb = np.array(pixels, dtype=np.float32)
            if rgb.ndim == 2:
                rgb = np.stack([rgb, rgb, rgb], axis=2)
            elif rgb.ndim == 3 and rgb.shape[2] >= 4:
                rgb = rgb[:, :, :3]

            resolution_str = f"{width} x {height}"
            if max_size and (width > max_size or height > max_size):
                import cv2
                scale = min(max_size / width, max_size / height)
                new_width, new_height = int(width * scale), int(height * scale)
                rgb = cv2.resize(rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
                width, height = new_width, new_height

            # .hdr is always Linear sRGB (no ACES tag lookup - Radiance HDR
            # has no colorspace metadata)
            display = tonemap_hdr_linear_array(rgb, exposure_stops=exposure, use_aces=False)
            return {'array': display, 'width': width, 'height': height, 'resolution_str': resolution_str}

        elif ext.endswith('.tx'):
            rgb = load_oiio_image_array(file_path_str, max_size=max_size, mip_level='auto')
            if rgb is None:
                return None
            height, width = rgb.shape[:2]
            display = tonemap_tx_array(rgb, file_path_str, exposure=exposure)
            return {'array': display, 'width': width, 'height': height, 'resolution_str': f"{width} x {height}"}

        elif ext.endswith(('.tif', '.tiff')):
            array, resolution_str = decode_tiff_array(file_path_str, max_size=max_size)
            if array is None:
                return None
            height, width = array.shape[:2]
            return {'array': array, 'width': width, 'height': height, 'resolution_str': resolution_str}

        else:
            # Standard formats (jpg/png/bmp/tga/psd/gif/webp) already decode
            # fast enough synchronously - not worth prefetching
            return None

    except Exception:
        return None
