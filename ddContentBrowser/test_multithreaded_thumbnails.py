"""
Test script for multithreaded thumbnail generation

This script tests the new hybrid ThreadPoolExecutor-based thumbnail generator
to ensure thread safety and performance improvements.

Usage:
    python test_multithreaded_thumbnails.py

Requirements:
    - ddContentBrowser installed
    - Test images in test_images/ folder
"""

import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from ddContentBrowser.cache import ThumbnailCache, ThumbnailDiskCache, ThumbnailGenerator

def test_multithreaded_generation():
    """Test thumbnail generation with multiple workers"""
    
    print("=" * 60)
    print("Multithreaded Thumbnail Generation Test")
    print("=" * 60)
    
    # Create caches
    memory_cache = ThumbnailCache(max_size=100)
    disk_cache = ThumbnailDiskCache()
    
    # Test configurations
    configs = [
        ("Single Thread", 1),
        ("2 Workers", 2),
        ("3 Workers", 3),
        ("4 Workers", 4),
    ]
    
    # Find test images
    test_dir = Path(__file__).parent / "test_images"
    if not test_dir.exists():
        print(f"\n⚠️  Test directory not found: {test_dir}")
        print("Creating test directory...")
        test_dir.mkdir(exist_ok=True)
        print(f"Please add test images to: {test_dir}")
        return
    
    test_files = []
    for ext in ['*.jpg', '*.png', '*.tif', '*.tiff', '*.exr', '*.hdr']:
        test_files.extend(test_dir.glob(ext))
    
    if not test_files:
        print(f"\n⚠️  No test images found in {test_dir}")
        print("Supported formats: JPG, PNG, TIFF, EXR, HDR")
        return
    
    print(f"\n✓ Found {len(test_files)} test images")
    for f in test_files[:5]:  # Show first 5
        print(f"  - {f.name}")
    if len(test_files) > 5:
        print(f"  ... and {len(test_files) - 5} more")
    
    # Results storage
    results = {}
    
    # Test each configuration
    for config_name, worker_count in configs:
        print(f"\n{'─' * 60}")
        print(f"Testing: {config_name}")
        print(f"{'─' * 60}")
        
        # Clear caches
        memory_cache.clear()
        disk_cache.clear()
        
        # Create generator
        generator = ThumbnailGenerator(
            memory_cache,
            disk_cache,
            thumbnail_size=256,
            jpeg_quality=85,
            metadata_manager=None,
            max_workers=worker_count
        )
        
        # Track completed thumbnails
        completed = []
        
        def on_ready(file_path, pixmap):
            completed.append(file_path)
            print(f"  ✓ Thumbnail ready: {Path(file_path).name}")
        
        def on_failed(file_path, error):
            print(f"  ✗ Failed: {Path(file_path).name} - {error}")
        
        # Connect signals
        generator.thumbnail_ready.connect(on_ready)
        generator.generation_failed.connect(on_failed)
        
        # Start generator
        generator.start()
        
        # Add files to queue
        print(f"\nQueuing {len(test_files)} files...")
        start_time = time.time()
        
        for file_path in test_files:
            mtime = file_path.stat().st_mtime
            generator.add_to_queue(str(file_path), mtime, asset=None)
        
        # Wait for completion
        print("Processing...")
        max_wait = 60  # 60 seconds timeout
        elapsed = 0
        
        while len(completed) < len(test_files) and elapsed < max_wait:
            time.sleep(0.1)
            elapsed = time.time() - start_time
        
        # Stop generator
        generator.stop()
        generator.wait()  # Wait for thread to finish
        
        # Calculate results
        duration = time.time() - start_time
        success_count = len(completed)
        throughput = success_count / duration if duration > 0 else 0
        
        results[config_name] = {
            'duration': duration,
            'success': success_count,
            'total': len(test_files),
            'throughput': throughput
        }
        
        print(f"\n{'─' * 60}")
        print(f"Results: {config_name}")
        print(f"{'─' * 60}")
        print(f"  Duration:    {duration:.2f}s")
        print(f"  Success:     {success_count}/{len(test_files)}")
        print(f"  Throughput:  {throughput:.2f} thumbnails/sec")
    
    # Summary
    print(f"\n{'═' * 60}")
    print("SUMMARY")
    print(f"{'═' * 60}")
    
    baseline = results.get("Single Thread", {}).get('duration', 1.0)
    
    print(f"\n{'Configuration':<20} {'Time':<12} {'Speed':<12} {'Speedup':<12}")
    print(f"{'-'*20} {'-'*12} {'-'*12} {'-'*12}")
    
    for config_name, data in results.items():
        duration = data['duration']
        throughput = data['throughput']
        speedup = baseline / duration if duration > 0 else 0
        
        print(f"{config_name:<20} {duration:>8.2f}s   {throughput:>6.2f}/s    {speedup:>6.2f}x")
    
    print(f"\n{'═' * 60}")
    
    # Recommendations
    best_config = max(results.items(), key=lambda x: x[1]['throughput'])
    print(f"\n✨ Best configuration: {best_config[0]}")
    print(f"   Throughput: {best_config[1]['throughput']:.2f} thumbnails/sec")
    
    print("\n💡 Recommendation:")
    if best_config[1]['throughput'] > results["Single Thread"]['throughput'] * 1.5:
        print("   Multithreading provides significant speedup!")
        print(f"   Consider using {best_config[0]} in production.")
    else:
        print("   Multithreading provides modest speedup.")
        print("   This may be due to I/O bottleneck (slow HDD) or small files.")

if __name__ == "__main__":
    try:
        test_multithreaded_generation()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
