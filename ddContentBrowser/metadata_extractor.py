# -*- coding: utf-8 -*-
"""
DD Content Browser - Metadata Extractor
Extracts metadata from various file types for advanced filtering

Author: ddankhazi
License: MIT
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Debug flag
DEBUG_MODE = False


class FileMetadata:
    """Stores metadata for a single file"""
    
    def __init__(self, file_path: Path, extract_full: bool = False):
        self.file_path = file_path
        self.metadata = {}
        self.full_metadata_extracted = False
        
        # Always extract basic metadata (fast, no file opening)
        self.extract_basic_metadata()
        
        # Only extract full metadata if explicitly requested
        if extract_full:
            self.extract_full_metadata()
    
    def extract_basic_metadata(self):
        """Extract basic metadata available for all files (NO file opening, very fast)"""
        try:
            stat = self.file_path.stat()
            
            # Basic info
            self.metadata['file_name'] = self.file_path.name
            self.metadata['file_type'] = self.file_path.suffix.lower()
            self.metadata['file_size'] = stat.st_size
            self.metadata['file_size_category'] = self._categorize_size(stat.st_size)
            
            # Dates
            self.metadata['date_created'] = datetime.fromtimestamp(stat.st_ctime)
            self.metadata['date_modified'] = datetime.fromtimestamp(stat.st_mtime)
            
            # Type category
            self.metadata['type_category'] = self._get_type_category()
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[MetadataExtractor] Error extracting basic metadata for {self.file_path}: {e}")
    
    def extract_full_metadata(self):
        """Extract format-specific metadata (may open files - slower)"""
        if self.full_metadata_extracted:
            return  # Already extracted
        
        try:
            # Extract format-specific metadata
            if self.metadata['type_category'] == 'image':
                self._extract_image_metadata()
            elif self.metadata['type_category'] == 'maya':
                self._extract_maya_metadata()
            elif self.metadata['type_category'] == '3d_model':
                self._extract_3d_metadata()
            
            self.full_metadata_extracted = True
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[MetadataExtractor] Error extracting metadata for {self.file_path}: {e}")
    
    def _categorize_size(self, size_bytes: int) -> str:
        """Categorize file size"""
        if size_bytes < 1024 * 1024:  # < 1 MB
            return "Tiny (< 1 MB)"
        elif size_bytes < 10 * 1024 * 1024:  # < 10 MB
            return "Small (1-10 MB)"
        elif size_bytes < 100 * 1024 * 1024:  # < 100 MB
            return "Medium (10-100 MB)"
        elif size_bytes < 1024 * 1024 * 1024:  # < 1 GB
            return "Large (100 MB - 1 GB)"
        else:
            return "Huge (> 1 GB)"
    
    def _get_type_category(self) -> str:
        """Get file type category"""
        ext = self.metadata['file_type']
        
        if ext in ['.jpg', '.jpeg', '.png', '.tif', '.tiff', '.tga', '.bmp', '.gif']:
            return 'image'
        elif ext in ['.hdr', '.exr']:
            return 'hdr_image'
        elif ext in ['.ma', '.mb']:
            return 'maya'
        elif ext in ['.obj', '.fbx', '.abc', '.usd', '.dae', '.stl']:
            return '3d_model'
        elif ext in ['.vdb']:
            return 'volume'
        elif ext in ['.hda']:
            return 'houdini'
        elif ext in ['.mel', '.py', '.txt']:
            return 'script'
        elif ext in ['.pdf']:
            return 'document'
        else:
            return 'other'
    
    def _extract_image_metadata(self):
        """Extract image-specific metadata"""
        try:
            # Try using PIL/Pillow
            from PIL import Image
            import warnings
            
            # Increase decompression bomb limit for large images (e.g., 8K textures)
            # Set to 200 megapixels (default is ~89 MP)
            Image.MAX_IMAGE_PIXELS = 200000000
            
            # Suppress decompression bomb warnings
            warnings.filterwarnings('ignore', category=Image.DecompressionBombWarning)
            
            with Image.open(self.file_path) as img:
                self.metadata['width'] = img.width
                self.metadata['height'] = img.height
                self.metadata['dimensions'] = f"{img.width} x {img.height}"
                
                # Resolution category based on larger dimension
                max_dimension = max(img.width, img.height)
                if max_dimension <= 512:
                    self.metadata['resolution_category'] = "S (≤512px)"
                elif max_dimension <= 1024:
                    self.metadata['resolution_category'] = "M (≤1K)"
                elif max_dimension <= 2048:
                    self.metadata['resolution_category'] = "L (≤2K)"
                elif max_dimension <= 4096:
                    self.metadata['resolution_category'] = "XL (≤4K)"
                elif max_dimension <= 8192:
                    self.metadata['resolution_category'] = "XXL (≤8K)"
                elif max_dimension <= 16384:
                    self.metadata['resolution_category'] = "XXXL (≤16K)"
                else:
                    self.metadata['resolution_category'] = "Ultra (>16K)"
                
                # Aspect ratio category
                aspect = img.width / img.height if img.height > 0 else 1.0
                
                # Check common aspect ratios (with tolerance)
                if 0.95 <= aspect <= 1.05:
                    self.metadata['aspect_ratio'] = "Square (1:1)"
                # Photo aspect ratios
                elif 1.48 <= aspect <= 1.52:
                    self.metadata['aspect_ratio'] = "3:2"
                elif 0.66 <= aspect <= 0.68:
                    self.metadata['aspect_ratio'] = "2:3 (Portrait)"
                elif 1.32 <= aspect <= 1.35:
                    self.metadata['aspect_ratio'] = "4:3"
                elif 0.74 <= aspect <= 0.76:
                    self.metadata['aspect_ratio'] = "3:4 (Portrait)"
                # Cinema/Video aspect ratios
                elif 1.77 <= aspect <= 1.79:
                    self.metadata['aspect_ratio'] = "16:9"
                elif 0.56 <= aspect <= 0.57:
                    self.metadata['aspect_ratio'] = "9:16 (Portrait)"
                elif 2.35 <= aspect <= 2.40:
                    self.metadata['aspect_ratio'] = "Cinema (2.39:1)"
                elif 2.0 <= aspect <= 2.1:
                    self.metadata['aspect_ratio'] = "Univisium (2:1)"
                # Wide formats
                elif aspect > 2.5:
                    self.metadata['aspect_ratio'] = "Panoramic"
                elif aspect < 0.5:
                    self.metadata['aspect_ratio'] = "Portrait (Tall)"
                else:
                    self.metadata['aspect_ratio'] = "Other"
                
                # Color mode
                self.metadata['color_mode'] = img.mode
                
                # Bit depth (approximate)
                if img.mode in ['1', 'L', 'P']:
                    self.metadata['bit_depth'] = "8-bit"
                elif img.mode in ['RGB', 'RGBA']:
                    self.metadata['bit_depth'] = "8-bit per channel"
                elif img.mode == 'I':
                    self.metadata['bit_depth'] = "32-bit"
                else:
                    self.metadata['bit_depth'] = img.mode
                
                # Try to extract EXIF
                try:
                    exif = img._getexif()
                    if exif:
                        # Camera info
                        if 272 in exif:  # Model
                            self.metadata['camera_model'] = exif[272]
                        if 271 in exif:  # Make
                            self.metadata['camera_make'] = exif[271]
                        
                        # Lens info
                        if 42036 in exif:  # LensModel
                            self.metadata['lens'] = exif[42036]
                        
                        # Exposure settings
                        if 34855 in exif:  # ISOSpeedRatings
                            iso = exif[34855]
                            self.metadata['iso'] = iso
                            # ISO category for filtering
                            if iso <= 400:
                                self.metadata['iso_category'] = "Low (≤400)"
                            elif iso <= 1600:
                                self.metadata['iso_category'] = "Medium (400-1600)"
                            elif iso <= 6400:
                                self.metadata['iso_category'] = "High (1600-6400)"
                            else:
                                self.metadata['iso_category'] = "Very High (>6400)"
                        
                        if 33434 in exif:  # ExposureTime
                            exposure = exif[33434]
                            if isinstance(exposure, tuple):
                                # Already in fraction format
                                self.metadata['shutter_speed'] = f"{exposure[0]}/{exposure[1]}s"
                            else:
                                # Convert decimal to fraction (e.g., 0.001 -> 1/1000s)
                                if exposure >= 1:
                                    self.metadata['shutter_speed'] = f"{exposure:.1f}s"
                                else:
                                    # Convert to 1/x format for speeds < 1 second
                                    denominator = int(round(1 / exposure))
                                    self.metadata['shutter_speed'] = f"1/{denominator}s"
                        
                        if 33437 in exif:  # FNumber
                            fnumber = exif[33437]
                            if isinstance(fnumber, tuple):
                                aperture = fnumber[0] / fnumber[1]
                            else:
                                aperture = fnumber
                            self.metadata['aperture'] = f"f/{aperture:.1f}"
                            # Aperture category
                            if aperture <= 2.8:
                                self.metadata['aperture_category'] = "Fast (≤f/2.8)"
                            elif aperture <= 5.6:
                                self.metadata['aperture_category'] = "Medium (f/2.8-5.6)"
                            else:
                                self.metadata['aperture_category'] = "Narrow (>f/5.6)"
                        
                        if 37386 in exif:  # FocalLength
                            focal = exif[37386]
                            if isinstance(focal, tuple):
                                focal_mm = focal[0] / focal[1]
                            else:
                                focal_mm = focal
                            self.metadata['focal_length'] = f"{focal_mm:.0f}mm"
                            # Focal length category
                            if focal_mm < 35:
                                self.metadata['focal_length_category'] = "Wide (<35mm)"
                            elif focal_mm <= 70:
                                self.metadata['focal_length_category'] = "Normal (35-70mm)"
                            else:
                                self.metadata['focal_length_category'] = "Tele (>70mm)"
                        
                        # White Balance
                        if 41987 in exif:  # WhiteBalance
                            wb = exif[41987]
                            self.metadata['white_balance'] = "Auto" if wb == 0 else "Manual"
                        
                        # Flash
                        if 37385 in exif:  # Flash
                            flash = exif[37385]
                            self.metadata['flash'] = "Yes" if flash & 1 else "No"
                        
                        # Orientation
                        if 274 in exif:
                            orientation = exif[274]
                            if orientation in [1, 2]:
                                self.metadata['orientation'] = "Landscape"
                            elif orientation in [5, 6, 7, 8]:
                                self.metadata['orientation'] = "Portrait"
                except:
                    pass
                
        except ImportError:
            # PIL not available
            pass
        except Exception as e:
            if DEBUG_MODE:
                print(f"[MetadataExtractor] Error extracting image metadata: {e}")
    
    def _extract_maya_metadata(self):
        """Extract Maya-specific metadata (if possible)"""
        # For now, just basic categorization
        self.metadata['maya_type'] = 'Scene'
        
        # Could potentially parse .ma files (ASCII) for more info
        # But that would be slow, so skip for now
    
    def _extract_3d_metadata(self):
        """Extract 3D model metadata"""
        # Basic categorization
        ext = self.metadata['file_type']
        
        if ext == '.obj':
            self.metadata['3d_format'] = 'Wavefront OBJ'
        elif ext == '.fbx':
            self.metadata['3d_format'] = 'Autodesk FBX'
        elif ext == '.abc':
            self.metadata['3d_format'] = 'Alembic Cache'
        elif ext == '.usd':
            self.metadata['3d_format'] = 'Universal Scene Description'
        elif ext == '.dae':
            self.metadata['3d_format'] = 'DAE Collada'
        elif ext == '.stl':
            self.metadata['3d_format'] = 'STL'
    
    def get_metadata(self) -> Dict[str, Any]:
        """Return metadata dictionary"""
        return self.metadata


class MetadataCache:
    """Cache for file metadata"""
    
    def __init__(self):
        self.cache = {}  # {file_path_str: FileMetadata}
    
    def get(self, file_path: Path) -> Optional[FileMetadata]:
        """Get metadata from cache"""
        path_str = str(file_path)
        return self.cache.get(path_str)
    
    def add(self, file_path: Path, metadata: FileMetadata):
        """Add metadata to cache"""
        path_str = str(file_path)
        self.cache[path_str] = metadata
    
    def clear(self):
        """Clear cache"""
        self.cache.clear()
    
    def get_or_create(self, file_path: Path) -> FileMetadata:
        """Get from cache or create new"""
        cached = self.get(file_path)
        if cached:
            return cached
        
        # Create new
        metadata = FileMetadata(file_path)
        self.add(file_path, metadata)
        return metadata
