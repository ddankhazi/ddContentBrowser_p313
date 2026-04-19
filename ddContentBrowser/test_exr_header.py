"""
Test script to inspect EXR header attributes
Can be run from Maya console or standalone Python
"""
import sys
import os

# Add external_libs to path
# Handle both Maya console (no __file__) and standalone execution
try:
    script_dir = os.path.dirname(__file__)
except NameError:
    # Running from Maya console - use hardcoded path
    script_dir = r"C:\Users\dankhazid\Documents\maya\2026\scripts\ddContentBrowser"

external_libs = os.path.join(script_dir, 'external_libs')
if external_libs not in sys.path:
    sys.path.insert(0, external_libs)

import OpenEXR

# Test with a sample EXR file (you'll need to provide a path)
test_file = r"U:/projects/env_thewalk/render/3d_build/sets/mattePaint/build_setup/render/frames/mattePaint_setup_v001/mattePaint_setup_v001_wip_1680623947/mattePaint_setup_v001.0096.exr"  # CHANGE THIS PATH

if len(sys.argv) > 1:
    test_file = sys.argv[1]

if os.path.exists(test_file):
    print(f"Reading EXR file: {test_file}\n")
    
    try:
        with OpenEXR.File(test_file) as exr:
            header = exr.header()
            
            print("=" * 60)
            print("EXR HEADER ATTRIBUTES:")
            print("=" * 60)
            
            for key, value in header.items():
                print(f"\n{key}:")
                print(f"  Type: {type(value)}")
                print(f"  Value: {value}")
            
            print("\n" + "=" * 60)
            print("CHANNELS:")
            print("=" * 60)
            channels = exr.channels()
            for ch_name in channels.keys():
                print(f"  - {ch_name}")
            
            # Special check for chromaticities
            print("\n" + "=" * 60)
            print("COLOR SPACE DETECTION:")
            print("=" * 60)
            
            if 'chromaticities' in header:
                chrom = header['chromaticities']
                print("✓ Chromaticities found!")
                print(f"  Red:   {chrom.get('red', 'N/A')}")
                print(f"  Green: {chrom.get('green', 'N/A')}")
                print(f"  Blue:  {chrom.get('blue', 'N/A')}")
                print(f"  White: {chrom.get('white', 'N/A')}")
                
                # Check if it matches ACEScg AP1
                # ACEScg primaries (tolerance 0.001)
                acescg_red = (0.713, 0.293)
                acescg_green = (0.165, 0.830)
                acescg_blue = (0.128, 0.044)
                
                def match_primary(actual, expected, tolerance=0.001):
                    if actual and len(actual) == 2:
                        return (abs(actual[0] - expected[0]) < tolerance and 
                                abs(actual[1] - expected[1]) < tolerance)
                    return False
                
                red_match = match_primary(chrom.get('red'), acescg_red)
                green_match = match_primary(chrom.get('green'), acescg_green)
                blue_match = match_primary(chrom.get('blue'), acescg_blue)
                
                if red_match and green_match and blue_match:
                    print("\n  → Detected: ACEScg (ACES AP1)")
                else:
                    print("\n  → Detected: Other color space (likely Rec.709/sRGB)")
            else:
                print("✗ No chromaticities attribute found")
                print("  → Will need to use heuristics for color space detection")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"File not found: {test_file}")
    print("\nUsage: python test_exr_header.py <path_to_exr_file>")
    print("\nThis script will print all attributes stored in the EXR header,")
    print("including chromaticities if present.")
