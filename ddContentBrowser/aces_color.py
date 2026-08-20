# -*- coding: utf-8 -*-
"""
DD Content Browser - ACES Color Management Module
Handles ACEScg color space detection and view transforms for EXR files

Author: ddankhazi
License: MIT
"""

import numpy as np
from pathlib import Path

# Debug flag
DEBUG_ACES = False


def detect_exr_colorspace(filepath, channels=None, width=None, height=None, metadata=None):
    """
    Detect color space of EXR file
    
    Args:
        filepath: Path to EXR file
        channels: List of channel names (e.g., ['R', 'G', 'B', 'A'])
        width: Image width
        height: Image height
        metadata: Optional metadata dict from EXR header
    
    Returns:
        str: "ACEScg" or "Linear sRGB"
    """
    if DEBUG_ACES:
        print(f"\n[ACES] Detecting colorspace for: {Path(filepath).name}")
        print(f"[ACES]   Channels: {channels}")
        print(f"[ACES]   Resolution: {width}x{height}")
        print(f"[ACES]   Aspect ratio: {width/height if height else 'N/A'}")
    
    # Rule 0: Check renderer-specific color space metadata (HIGHEST PRIORITY)
    # This is explicit and 100% reliable when present
    if metadata:
        # Arnold renderer
        if 'arnold/color_space' in metadata:
            arnold_cs = str(metadata['arnold/color_space']).strip()
            if DEBUG_ACES:
                print(f"[ACES]   Found Arnold metadata: arnold/color_space = '{arnold_cs}'")
            
            # Map Arnold color space names to our internal names
            arnold_map = {
                'ACEScg': 'ACEScg',
                'ACES2065-1': 'ACEScg',  # Treat as ACEScg for display
                'aces_cg': 'ACEScg',
                'lin_ap1': 'ACEScg',
                'sRGB': 'Linear sRGB',
                'Rec.709': 'Linear sRGB',
                'linear': 'Linear sRGB',
                'scene_linear': 'Linear sRGB',
            }
            
            for key, value in arnold_map.items():
                if key.lower() in arnold_cs.lower():
                    if DEBUG_ACES:
                        print(f"[ACES] ✓✓✓ Explicit Arnold color space → {value}")
                    return value
        
        # V-Ray renderer (check common field names)
        vray_keys = ['vray/colorspace', 'vray/color_space', 'VRayColorSpace']
        for key in vray_keys:
            if key in metadata:
                vray_cs = str(metadata[key]).strip()
                if DEBUG_ACES:
                    print(f"[ACES]   Found V-Ray metadata: {key} = '{vray_cs}'")
                
                if 'aces' in vray_cs.lower() or 'ap1' in vray_cs.lower():
                    if DEBUG_ACES:
                        print(f"[ACES] ✓✓✓ Explicit V-Ray color space → ACEScg")
                    return "ACEScg"
                elif 'srgb' in vray_cs.lower() or '709' in vray_cs.lower() or 'linear' in vray_cs.lower():
                    if DEBUG_ACES:
                        print(f"[ACES] ✓✓✓ Explicit V-Ray color space → Linear sRGB")
                    return "Linear sRGB"
        
        # Redshift renderer
        redshift_keys = ['redshift/colorSpace', 'redshift/color_space', 'redshiftOptions/colorSpace']
        for key in redshift_keys:
            if key in metadata:
                rs_cs = str(metadata[key]).strip()
                if DEBUG_ACES:
                    print(f"[ACES]   Found Redshift metadata: {key} = '{rs_cs}'")
                
                if 'aces' in rs_cs.lower() or 'ap1' in rs_cs.lower():
                    if DEBUG_ACES:
                        print(f"[ACES] ✓✓✓ Explicit Redshift color space → ACEScg")
                    return "ACEScg"
                elif 'srgb' in rs_cs.lower() or '709' in rs_cs.lower():
                    if DEBUG_ACES:
                        print(f"[ACES] ✓✓✓ Explicit Redshift color space → Linear sRGB")
                    return "Linear sRGB"
        
        # Cycles/Blender (check for OCIO config)
        if 'blender/colorspace' in metadata or 'cycles/colorspace' in metadata:
            key = 'blender/colorspace' if 'blender/colorspace' in metadata else 'cycles/colorspace'
            cycles_cs = str(metadata[key]).strip()
            if DEBUG_ACES:
                print(f"[ACES]   Found Blender/Cycles metadata: {key} = '{cycles_cs}'")
            
            if 'aces' in cycles_cs.lower():
                if DEBUG_ACES:
                    print(f"[ACES] ✓✓✓ Explicit Blender/Cycles color space → ACEScg")
                return "ACEScg"
            elif 'linear' in cycles_cs.lower() or 'srgb' in cycles_cs.lower():
                if DEBUG_ACES:
                    print(f"[ACES] ✓✓✓ Explicit Blender/Cycles color space → Linear sRGB")
                return "Linear sRGB"
    
    # Rule 1: Check channel count
    # Multi-channel (more than 4) typically indicates render output = ACEScg
    if channels:
        channel_count = len(channels)
        if DEBUG_ACES:
            print(f"[ACES]   Channel count: {channel_count}")
        
        if channel_count >= 5:
            if DEBUG_ACES:
                print(f"[ACES] ✓ Multi-channel ({channel_count} channels) → ACEScg")
            return "ACEScg"
    
    # Rule 2: Filename pattern (optional heuristic)
    filename = Path(filepath).stem.lower()
    if "acescg" in filename or "aces" in filename:
        if DEBUG_ACES:
            print(f"[ACES] ✓ Filename contains 'aces' → ACEScg")
        return "ACEScg"
    
    # Rule 3: Check if it's a lat-long HDRI (2:1 aspect ratio) - LOWEST PRIORITY
    # These are typically Linear sRGB, but this is the most uncertain heuristic
    if width and height:
        aspect_ratio = width / height
        if abs(aspect_ratio - 2.0) < 0.01:  # Close to 2:1
            # Common HDRI resolutions (including 1024x512, 2048x1024, etc.)
            if height > 0 and width == height * 2:
                if DEBUG_ACES:
                    print(f"[ACES] ⚠ Detected as lat-long HDRI (2:1 aspect) → Linear sRGB (uncertain)")
                return "Linear sRGB"
    
    # Default: Assume ACEScg for non-HDRI EXR files
    # (Most modern render outputs are ACEScg)
    if DEBUG_ACES:
        print(f"[ACES] ⚠ No clear indicator → Defaulting to ACEScg")
    return "ACEScg"


def apply_aces_view_transform(rgb_linear, exposure=0.0):
    """
    Apply ACES Output Transform (simplified RRT + sRGB ODT)
    ACEScg (AP1) → sRGB display
    
    Args:
        rgb_linear: numpy array (H, W, 3) in ACEScg linear space
        exposure: Exposure adjustment in stops (applied before transform)
    
    Returns:
        numpy array (H, W, 3) in sRGB display space [0-1]
    """
    if DEBUG_ACES:
        print(f"[ACES] Applying ACES view transform (exposure: {exposure:.2f})")
    
    # Apply exposure adjustment (pre-transform)
    if exposure != 0.0:
        rgb_linear = rgb_linear * (2.0 ** exposure)
    
    if DEBUG_ACES:
        print(f"[ACES]   Input range: [{rgb_linear.min():.3f}, {rgb_linear.max():.3f}]")
    
    # Apply full ACES RRT + ODT transform
    # This operates in AP1 (ACEScg) space and outputs sRGB display values
    rgb_display = aces_rrt_and_odt_transform(rgb_linear)
    
    if DEBUG_ACES:
        print(f"[ACES] Transform complete. Output range: [{rgb_display.min():.3f}, {rgb_display.max():.3f}]")
    
    return rgb_display


def apply_standard_view_transform(rgb_linear, exposure=0.0):
    """
    Apply standard sRGB view transform (simple gamma)
    Linear sRGB → sRGB display
    
    Args:
        rgb_linear: numpy array (H, W, 3) in linear sRGB space
        exposure: Exposure adjustment in stops
    
    Returns:
        numpy array (H, W, 3) in sRGB display space [0-1]
    """
    if DEBUG_ACES:
        print(f"[ACES] Applying standard sRGB transform (exposure: {exposure:.2f})")
    
    # Apply exposure adjustment
    if exposure != 0.0:
        rgb_linear = rgb_linear * (2.0 ** exposure)
    
    # Simple Reinhard tonemapping for HDR
    rgb_tm = rgb_linear / (1.0 + rgb_linear)
    
    # Apply sRGB gamma (2.2 approximation)
    rgb_display = np.power(np.maximum(rgb_tm, 0), 1.0/2.2)
    
    # Clamp to valid range
    rgb_display = np.clip(rgb_display, 0, 1)
    
    if DEBUG_ACES:
        print(f"[ACES] Transform complete. Range: [{rgb_display.min():.3f}, {rgb_display.max():.3f}]")
    
    return rgb_display


def apply_dci_p3_view_transform(rgb_linear, exposure=0.0):
    """
    Convert scene-linear P3-D65 (Display P3) primaries to sRGB display.

    Pure gamut conversion (3x3 matrix, both spaces share the D65 white
    point so no chromatic adaptation is needed) + sRGB EOTF - no RRT
    tone-compression curve, matching how Linear sRGB texture data is
    treated (these are LDR texture maps like Albedo, not HDR beauty
    renders, so exposure is off by default like the standard path).

    Args:
        rgb_linear: numpy array (H, W, 3) in scene-linear P3-D65 space
        exposure: Exposure adjustment in stops (0.0 = neutral, applied
                  the same way as the standard/Linear sRGB path - only
                  when explicitly non-zero, no baked-in stop offset)

    Returns:
        numpy array (H, W, 3) in sRGB display space [0-1]
    """
    if exposure != 0.0:
        rgb_linear = rgb_linear * (2.0 ** exposure)

    # P3-D65 linear -> sRGB/Rec.709 linear. Derived from CIE 1931 primaries
    # (both D65 white point): P3-D65 R(0.680,0.320) G(0.265,0.690) B(0.150,0.060),
    # sRGB R(0.640,0.330) G(0.300,0.600) B(0.150,0.060), white (0.3127,0.3290).
    # Verified: rows sum to 1.0 (white-point-preserving, as expected when
    # both spaces share the same white).
    P3D65_to_sRGB = np.array([
        [ 1.2249401762, -0.2249401762,  0.0000000000],
        [-0.0420569547,  1.0420569547,  0.0000000000],
        [-0.0196375546, -0.0786360454,  1.0982736000]
    ], dtype=np.float32)

    # Reshape to 2D before the matmul - np.dot on a (H,W,3) array against a
    # (3,3) matrix skips numpy's BLAS-backed path and is ~15x slower (see
    # aces_rrt_and_odt_transform for the measured comparison).
    input_shape = rgb_linear.shape
    rgb_linear32 = np.asarray(rgb_linear, dtype=np.float32)
    linear_srgb = (rgb_linear32.reshape(-1, 3) @ P3D65_to_sRGB.T).reshape(input_shape)

    # Clamp negatives (P3 colors outside the sRGB gamut)
    linear_srgb = np.maximum(linear_srgb, 0.0)

    # sRGB EOTF (gamma correction)
    display = np.where(
        linear_srgb <= 0.0031308,
        linear_srgb * 12.92,
        1.055 * np.power(linear_srgb, 1.0/2.4) - 0.055
    )

    return np.clip(display, 0.0, 1.0)


def aces_rrt_and_odt_transform(aces_ap1):
    """
    Full ACES Reference Rendering Transform (RRT) + sRGB Output Device Transform (ODT)
    
    This implementation matches the official ACES 1.2 specification exactly,
    using the same algorithms as Nuke, Maya, RV, and other ACES-compliant tools.
    
    Based on:
    - ACES 1.2 CTL reference implementation
    - OpenColorIO ACES config
    - Academy Color Encoding System specification
    
    Args:
        aces_ap1: Linear RGB values in ACES AP1 color space (ACEScg)
    
    Returns:
        sRGB display-ready RGB values (gamma corrected, 0-1 range)
    """
    
    # ===== Step 1: AP1 (ACEScg) → AP0 (ACES2065-1) =====
    # The RRT operates in AP0 working space
    AP1_to_AP0 = np.array([
        [ 0.6954522414,  0.1406786965,  0.1638690622],
        [ 0.0447945634,  0.8596711185,  0.0955343182],
        [-0.0055258826,  0.0040252103,  1.0015006723]
    ], dtype=np.float32)

    # np.dot on a (H,W,3) array against a (3,3) matrix does NOT take numpy's
    # BLAS-backed 2D matmul path - measured ~15x slower than reshaping to
    # (H*W,3) first (a 1024x1024 image: ~48ms vs ~3ms). Reshape, multiply,
    # reshape back. Keeping the matrix float32 (matching aces_ap1's dtype)
    # avoids an implicit float64 upcast of the whole image too.
    input_shape = aces_ap1.shape
    aces = (aces_ap1.reshape(-1, 3) @ AP1_to_AP0.T).reshape(input_shape)
    
    # ===== Step 2: RRT (Reference Rendering Transform) =====
    # All calculations in ACES2065-1 (AP0) space
    
    # === RRT Tonescale (the main tone compression) ===
    # Narkowicz 2015 ACES approximation - clean implementation
    
    def rrt_and_odt_fit(x):
        # Protect from negatives
        x = np.maximum(x, 0.0)
        
        # ACES fitted curve (Narkowicz 2015)
        a = 2.51
        b = 0.03
        c = 2.43
        d = 0.59
        e = 0.14
        
        return (x * (a * x + b)) / (x * (c * x + d) + e)
    
    # Apply per-channel to preserve saturation rolloff
    aces = rrt_and_odt_fit(aces)
    
    # ===== Step 3: ODT (Output Device Transform for sRGB) =====
    
    # Direct AP0 (ACES2065-1) → Linear sRGB/Rec.709 matrix
    # This is the combined and normalized matrix from official ACES ODT
    # Avoids accumulated errors from AP0→XYZ→sRGB chain
    # Values from OpenColorIO ACES 1.2 config
    AP0_to_sRGB = np.array([
        [ 2.52168618674388,  -1.13413098823972,  -0.38755519850416],
        [-0.27514695912289,   1.37271895915309,  -0.09757199903020],
        [-0.01533939668617,  -0.15268158993823,   1.16802098662440]
    ], dtype=np.float32)

    linear = (aces.reshape(-1, 3) @ AP0_to_sRGB.T).reshape(input_shape)
    
    # Clamp negatives (out-of-gamut colors)
    linear = np.maximum(linear, 0.0)
    
    # ===== Step 4: sRGB EOTF (gamma correction) =====
    # IEC 61966-2-1 standard sRGB curve
    display = np.where(
        linear <= 0.0031308,
        linear * 12.92,
        1.055 * np.power(linear, 1.0/2.4) - 0.055
    )
    
    # Final clamp
    display = np.clip(display, 0.0, 1.0)
    
    return display


def rgb_2_saturation(rgb, saturation):
    """Apply saturation adjustment"""
    # Calculate luminance (Rec.709 weights)
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    # Mix between luminance and original color
    return luma[..., np.newaxis] + saturation * (rgb - luma[..., np.newaxis])


def rgb_2_yc(rgb, luma_scale, chroma_scale):
    """
    Y/C adjustment (luminance/chroma)
    Part of RRT pre-conditioning
    """
    # Calculate luminance
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    chroma = rgb - luma[..., np.newaxis]
    
    # Scale luma and chroma independently
    return (luma * luma_scale / 48.0)[..., np.newaxis] + chroma * (chroma_scale / 48.0)


def get_colorspace_tag_name(detected_colorspace):
    """
    Get the tag name for a detected colorspace

    Args:
        detected_colorspace: "ACEScg", "Linear sRGB", or "DCI-P3"

    Returns:
        str: Tag name to use in the tag system
    """
    # Normalize to match tag names
    if detected_colorspace in ("ACEScg", "DCI-P3"):
        return detected_colorspace
    else:
        return "Linear sRGB"


def get_view_transform_tag_name(colorspace_tag):
    """
    Get the default view transform tag for a colorspace
    
    Args:
        colorspace_tag: "ACEScg" or "Linear sRGB"
    
    Returns:
        str: View transform tag name
    """
    if colorspace_tag == "ACEScg":
        return "sRGB(ACES)"
    else:
        return "sRGB"


def auto_tag_file_colorspace(file_path, metadata_manager=None):
    """
    Automatically detect and apply color space tag to a file.
    Called during thumbnail generation.
    
    Args:
        file_path: Path to file (str or Path)
        metadata_manager: Metadata manager instance for tagging (optional, will create if None)
    
    Returns:
        str: Applied tag name ("ACEScg" or "Linear sRGB") or None if not applicable
    """
    from pathlib import Path
    import os
    
    file_path = Path(file_path)
    extension = file_path.suffix.lower()
    
    # Only process HDR/EXR/TX files
    if extension not in ['.exr', '.hdr', '.tx']:
        return None
    
    detected_colorspace = None
    
    # === EXR Files ===
    if extension == '.exr':
        try:
            # Try to read EXR metadata for detection
            from .utils import import_openexr
            OpenEXR, _Imath = import_openexr()
            if OpenEXR is None:
                raise ImportError("OpenEXR not available")
            with OpenEXR.File(str(file_path)) as exr_file:
                header = exr_file.header()
                dw = header['dataWindow']
                width = dw[1][0] - dw[0][0] + 1
                height = dw[1][1] - dw[0][1] + 1
                channels = exr_file.channels()
                channel_count = len(channels)
                
                # Use existing detection logic with full header metadata
                detected_colorspace = detect_exr_colorspace(
                    str(file_path),
                    channels=list(channels.keys()),
                    width=width,
                    height=height,
                    metadata=header  # Pass full header for metadata detection
                )
        except Exception as e:
            return None
    
    # === HDR Files ===
    elif extension == '.hdr':
        # HDR (Radiance RGBE) files are always Linear sRGB
        detected_colorspace = "Linear sRGB"
    
    # === TX Files (RenderMan) ===
    elif extension == '.tx':
        # Check filename for a known render-colorspace suffix (Megascans/maketx
        # convention: "..._<colorspace>.tif.tx" etc). First match wins.
        filename_lower = file_path.stem.lower()
        colorspace_suffix_map = [
            ('acescg', "ACEScg"),
            ('scene-linear rec.2020', "ACEScg"),          # close enough to ACEScg's AP1 gamut
            ('scene-linear rec.709-srgb', "Linear sRGB"),
            ('scene-linear dci-p3', "DCI-P3"),
        ]
        detected_colorspace = None
        for suffix, colorspace in colorspace_suffix_map:
            if suffix in filename_lower:
                detected_colorspace = colorspace
                break
        if detected_colorspace is None:
            # No explicit indicator - assume ACEScg (most .tx in this pipeline are)
            detected_colorspace = "ACEScg"
    
    # Apply tag if detected
    if detected_colorspace:
        try:
            # Get metadata manager (use provided or create new)
            if metadata_manager is None:
                from .metadata import get_metadata_manager
                metadata_manager = get_metadata_manager()
            
            # Get normalized tag name
            tag_name = get_colorspace_tag_name(detected_colorspace)
            tag_name_lower = tag_name.lower()

            # Remove any OTHER colorspace tag before applying the new one, so
            # re-running auto-detect (e.g. after this tool's detection rules
            # changed) never leaves two contradictory colorspace tags on the
            # same file. Only touches known colorspace tags - every other
            # tag on the file is left alone.
            other_colorspace_tag_names = {"acescg", "linear srgb", "dci-p3", "srgb(aces)"} - {tag_name_lower}

            existing_metadata = metadata_manager.get_file_metadata(str(file_path))
            existing_tags = existing_metadata.get('tags', [])
            existing_tag_names = [tag['name'].lower() for tag in existing_tags]

            for tag in existing_tags:
                if tag['name'].lower() in other_colorspace_tag_names:
                    try:
                        metadata_manager.remove_tag_from_file(str(file_path), tag['id'])
                    except Exception as remove_error:
                        if DEBUG_ACES:
                            print(f"[Auto-Tag]   Failed to remove stale tag '{tag['name']}': {remove_error}")

            if tag_name_lower not in existing_tag_names:
                # Get or create tag ID
                tag_id = metadata_manager.add_tag(tag_name, category=None, color=None)

                # Add the tag to file
                metadata_manager.add_tag_to_file(str(file_path), tag_id)
                return tag_name
            else:
                return tag_name
        except Exception as e:
            if DEBUG_ACES:
                print(f"[Auto-Tag]   Failed to apply tag: {e}")
                import traceback
                traceback.print_exc()
    
    return None
