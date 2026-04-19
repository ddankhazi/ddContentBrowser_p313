"""
DD Content Browser - Preview Panel Module
Extracted from widgets.py for better maintainability

Handles:
- Image preview (JPG, PNG, TIFF, etc.)
- HDR/EXR preview with exposure control
- PDF preview with page navigation
- Text file preview with syntax highlighting
- Zoom/pan functionality
- Metadata display
- Tag management
"""

# Suppress Qt Multimedia FFmpeg output BEFORE importing Qt
import os
os.environ["QT_LOGGING_RULES"] = "qt.multimedia.ffmpeg=false"
os.environ["QT_LOGGING_RULES"] = "*=false"  # Nuclear option - disable ALL Qt logging
os.environ["QT_DEBUG_PLUGINS"] = "0"

# Standard library imports
from pathlib import Path
from datetime import datetime

# Try PySide6 first (Maya 2025+), fallback to PySide2
try:
    from PySide6.QtWidgets import *
    from PySide6.QtGui import *
    from PySide6.QtCore import *
    from PySide6 import QtCore, QtWidgets
    UI_FONT = "Segoe UI"
    PYSIDE_VERSION = 6
    # Try to import multimedia (optional - may not be available in all PySide6 installations)
    try:
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PySide6.QtMultimediaWidgets import QVideoWidget
    except ImportError:
        QMediaPlayer = None
        QVideoWidget = None
        QAudioOutput = None
        print("[Preview] Qt Multimedia not available - video playback will use OpenCV fallback")
except ImportError:
    from PySide2.QtWidgets import *
    from PySide2.QtGui import *
    from PySide2.QtCore import *
    from PySide2 import QtCore, QtWidgets
    UI_FONT = "Segoe UI"
    PYSIDE_VERSION = 2
    # Try to import multimedia (optional)
    try:
        from PySide2.QtMultimedia import QMediaPlayer, QMediaContent
        from PySide2.QtMultimediaWidgets import QVideoWidget
    except ImportError:
        QMediaPlayer = None
        QVideoWidget = None
        print("[Preview] Qt Multimedia not available - video playback will use OpenCV fallback")

# Custom Qt message handler to suppress TGA warnings
def qt_message_handler(msg_type, context, message):
    # Suppress QTgaHandler allocation warnings (we handle large TGA with PIL)
    if "QTgaHandler" in message and "exceeds limit" in message:
        return
    # Pass through other messages
    if PYSIDE_VERSION == 6:
        from PySide6.QtCore import QtMsgType
    else:
        from PySide2.QtCore import QtMsgType
    
    if msg_type == QtMsgType.QtDebugMsg:
        print(f"Qt Debug: {message}")
    elif msg_type == QtMsgType.QtWarningMsg:
        print(f"Qt Warning: {message}")
    elif msg_type == QtMsgType.QtCriticalMsg:
        print(f"Qt Critical: {message}")
    elif msg_type == QtMsgType.QtFatalMsg:
        print(f"Qt Fatal: {message}")

# Install the message handler
qInstallMessageHandler(qt_message_handler)

# Debug mode flag
DEBUG_MODE = True

# Suppress OpenCV/FFmpeg verbose output
import os
import sys

# Environment variables to suppress FFmpeg output
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "loglevel;quiet"
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
os.environ["OPENCV_VIDEOIO_PRIORITY_FFMPEG"] = "0"
os.environ["FFMPEG_LOG_LEVEL"] = "quiet"

# Check for numpy (required for HDR/EXR processing)
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("[Preview Panel] Warning: numpy not available - HDR/EXR support disabled")

# Check for OpenCV (for advanced TIFF support)
try:
    import cv2
    # Set OpenCV logging level to ERROR only (suppresses INFO/DEBUG spam)
    if hasattr(cv2, 'setLogLevel'):
        cv2.setLogLevel(0)  # 0 = Silent
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    print("[Preview Panel] Info: OpenCV not available - using QImageReader for TIFF")


# Check for OpenEXR (for .exr files)
try:
    import OpenEXR
    import Imath
    OPENEXR_AVAILABLE = True
except ImportError:
    OPENEXR_AVAILABLE = False
    print("[Preview Panel] Info: OpenEXR not available - EXR support disabled")

# Import sequence frame cache
# Cache system temporarily disabled
# from .sequence_cache import SequenceFrameCache, SequencePreloader

# Check for PyMuPDF (for PDF preview)
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("[Preview Panel] Info: PyMuPDF not available - PDF preview disabled")

# Local imports
# NOTE: These helper functions were originally in widgets.py but moved here to avoid circular imports


def is_deep_exr(file_path):
    """
    Check if an EXR file is a deep image (contains deep data)
    
    Deep images store multiple samples per pixel and are not supported for preview.
    
    Args:
        file_path: Path to EXR file
        
    Returns:
        bool: True if file is a deep EXR, False otherwise
    """
    if not OPENEXR_AVAILABLE:
        return False
    
    try:
        with OpenEXR.File(str(file_path)) as exr_file:
            header = exr_file.header()
            
            # FAST CHECK: Check if the header contains deep data indicator
            # Deep images have a 'type' attribute set to 'deepscanline' or 'deeptile'
            if 'type' in header:
                type_value = header['type']
                if isinstance(type_value, str):
                    is_deep = 'deep' in type_value.lower()
                    if is_deep:
                        print(f"🔍 Detected deep EXR (type: {type_value})")
                        return True
                # In some versions, type is returned as bytes
                elif isinstance(type_value, bytes):
                    is_deep = b'deep' in type_value.lower()
                    if is_deep:
                        print(f"🔍 Detected deep EXR (type: {type_value})")
                        return True
            
            # SLOWER CHECK: Only if header check didn't find it
            # Some deep EXR files might not have explicit type field
            # Check first channel's pixel dtype (don't check all channels for speed)
            channels = exr_file.channels()
            if channels:
                # Just check the first channel
                first_channel_name = next(iter(channels.keys()))
                first_channel = channels[first_channel_name]
                
                try:
                    pixels = first_channel.pixels
                    # Deep data pixels return object arrays instead of numeric arrays
                    if pixels is not None and hasattr(pixels, 'dtype'):
                        import numpy as np
                        if pixels.dtype == np.object_:
                            print(f"🔍 Detected deep data in channel '{first_channel_name}' (dtype=object)")
                            return True
                except:
                    pass
            
            return False
            
    except Exception as e:
        print(f"⚠️ Error checking if EXR is deep: {e}")
        return False


def _load_exr_channel_data(channel, channel_name, width, height):
    """Helper function to load a single EXR channel and convert to RGB"""
    try:
        channel_data = np.array(channel.pixels, dtype=np.float32)
        total_pixels = width * height
        
        # DETAILED DEBUG: Print channel info
        print(f"🔬 DETAILED DEBUG for channel '{channel_name}':")
        print(f"   - Image size: {width} × {height} = {total_pixels} pixels")
        print(f"   - Channel data size: {len(channel_data)} values")
        print(f"   - Expected sizes: {total_pixels} (gray), {total_pixels*3} (RGB), {total_pixels*4} (RGBA)")
        
        # Try to get more info about the channel
        if hasattr(channel, 'type'):
            print(f"   - Channel type: {channel.type}")
        if hasattr(channel, 'sampling'):
            print(f"   - Channel sampling: {channel.sampling}")
        
        # Determine channel type by data size
        if len(channel_data) == total_pixels * 3:
            # RGB channel
            print(f"✅ '{channel_name}' is RGB (3 channels)")
            return channel_data.reshape(height, width, 3)
        elif len(channel_data) == total_pixels * 4:
            # RGBA channel
            print(f"✅ '{channel_name}' is RGBA (4 channels)")
            rgba = channel_data.reshape(height, width, 4)
            return rgba[:, :, :3]  # Drop alpha
        elif len(channel_data) == total_pixels:
            # Grayscale channel
            print(f"✅ '{channel_name}' is grayscale (1 channel)")
            grayscale = channel_data.reshape(height, width)
            return np.stack([grayscale, grayscale, grayscale], axis=2)
        else:
            print(f"❌ '{channel_name}' has INCOMPATIBLE size: {len(channel_data)}")
            print(f"   This channel is likely metadata, LUT, or different resolution!")
            print(f"   Skipping this channel...")
            return None
    except Exception as e:
        print(f"❌ Failed to load channel '{channel_name}': {e}")
        return None


def load_hdr_exr_raw(file_path, max_size=2048):
    """
    Load raw HDR/EXR float data (NO tone mapping) for fast exposure adjustment
    
    Args:
        file_path: Path to HDR/EXR file
        max_size: Maximum width/height for preview (default 2048)
        
    Returns:
        tuple: (rgb_float_array, width, height, resolution_str) or (None, None, None, None) on failure
    """
    file_path_str = str(file_path)
    file_ext = file_path_str.lower()
    
    # Check for deep EXR first
    if file_ext.endswith('.exr'):
        if is_deep_exr(file_path):
            print(f"⚠️ Deep EXR detected - preview not supported")
            return None, None, None, "Deep EXR - No Preview"
    
    # Use OpenCV for .hdr (Radiance RGBE) files if available (best option!)
    if file_ext.endswith('.hdr') and OPENCV_AVAILABLE and NUMPY_AVAILABLE:
        try:
            import cv2
            import numpy as np
            # Read HDR with OpenCV (cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR for float32)
            rgb = cv2.imread(file_path_str, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR)
            
            if rgb is None:
                raise Exception("OpenCV returned None - file may be corrupted or unsupported")
            
            # OpenCV loads as BGR, convert to RGB
            rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
            
            # Get ORIGINAL resolution BEFORE scaling (for metadata display)
            height, width = rgb.shape[:2]
            resolution_str = f"{width} x {height}"
            
            # Scale if needed
            if width > max_size or height > max_size:
                scale = min(max_size / width, max_size / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                
                # Use OpenCV resize (high quality)
                rgb = cv2.resize(rgb, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                width, height = new_width, new_height
            
            # Return RAW float data (no tone mapping!)
            return rgb, width, height, resolution_str
            
        except Exception as e:
            print(f"❌ OpenCV HDR loading failed: {e}")
            import traceback
            traceback.print_exc()
            return None, None, None, None
    
    # Use OpenEXR for .exr files if available
    if file_ext.endswith('.exr') and OPENEXR_AVAILABLE and NUMPY_AVAILABLE:
        try:
            import numpy as np
            # Open EXR file
            with OpenEXR.File(file_path_str) as exr_file:
                # Get header info
                header = exr_file.header()
                dw = header['dataWindow']
                width = dw[1][0] - dw[0][0] + 1
                height = dw[1][1] - dw[0][1] + 1
                resolution_str = f"{width} x {height}"
                
                # Read RGB channels
                channels = exr_file.channels()
                rgb = None
                
                # DEBUG: Print all available channels
                channel_names = list(channels.keys())
                print(f"🔍 DEBUG EXR Channels in {file_path}: {channel_names}")
                
                # Store channel info globally for the preview panel to use
                # (This is a bit hacky, but we need to pass this info somehow)
                if hasattr(load_hdr_exr_raw, '_current_channels'):
                    load_hdr_exr_raw._current_channels = channel_names
                    load_hdr_exr_raw._current_file = file_path_str
                
                # Try standard interleaved RGB or RGBA
                if "RGB" in channels:
                    print("✅ Found RGB channel")
                    rgb = np.array(channels["RGB"].pixels, dtype=np.float32).reshape(height, width, 3)
                elif "RGBA" in channels:
                    print("✅ Found RGBA channels")
                    rgba = np.array(channels["RGBA"].pixels, dtype=np.float32).reshape(height, width, 4)
                    rgb = rgba[:, :, :3]  # Drop alpha
                elif all(c in channels for c in ["R", "G", "B"]):
                    print("✅ Found separate R, G, B channels")
                    r = np.array(channels["R"].pixels, dtype=np.float32).reshape(height, width)
                    g = np.array(channels["G"].pixels, dtype=np.float32).reshape(height, width)
                    b = np.array(channels["B"].pixels, dtype=np.float32).reshape(height, width)
                    rgb = np.stack([r, g, b], axis=2)
                else:
                    print("❌ No standard RGB channels found, trying available channels...")
                    # Try each channel until we find one that works (skip metadata/LUT channels)
                    loaded_channel_name = None
                    for channel_name in channel_names:
                        print(f"🔄 Trying channel '{channel_name}'...")
                        rgb = _load_exr_channel_data(channels[channel_name], channel_name, width, height)
                        if rgb is not None:
                            loaded_channel_name = channel_name
                            print(f"✅ Successfully loaded channel '{channel_name}'!")
                            break
                        else:
                            print(f"⏭️ Skipping incompatible channel '{channel_name}'")
                    
                    # Store which channel we successfully loaded
                    if hasattr(load_hdr_exr_raw, '_current_channel') and loaded_channel_name:
                        load_hdr_exr_raw._current_channel = loaded_channel_name
                
                if rgb is None:
                    print(f"❌ OpenEXR failed to load any channel from: {file_path}")
                    print(f"🔄 Trying OpenImageIO as fallback...")
                    
                    # Try OpenImageIO fallback (like thumbnail generator uses)
                    try:
                        from .widgets import load_oiio_image
                        print(f"🚀 Loading EXR with OpenImageIO...")
                        
                        # Load with OIIO (returns QPixmap directly)
                        pixmap, oiio_resolution, metadata = load_oiio_image(file_path_str, max_size=max_size)
                        
                        if pixmap and not pixmap.isNull():
                            print(f"✅ OpenImageIO successfully loaded EXR!")
                            
                            # Convert QPixmap back to numpy array for consistency
                            qimage = pixmap.toImage()
                            width = qimage.width()
                            height = qimage.height()
                            
                            # Convert QImage to numpy RGB array (PySide version compatibility)
                            if PYSIDE_VERSION == 6:
                                from PySide6.QtGui import QImage
                                rgb_format = QImage.Format_RGB888
                            else:
                                from PySide2.QtGui import QImage
                                rgb_format = QImage.Format_RGB888
                            
                            ptr = qimage.bits()
                            if qimage.format() == rgb_format:
                                arr = np.array(ptr).reshape(height, width, 3)
                            else:
                                # Convert to RGB888 format first
                                qimage = qimage.convertToFormat(rgb_format)
                                ptr = qimage.bits()
                                arr = np.array(ptr).reshape(height, width, 3)
                            
                            # Convert from 8-bit to float (for consistency with OpenEXR path)
                            rgb = arr.astype(np.float32) / 255.0
                            
                            return rgb, width, height, oiio_resolution
                        else:
                            print(f"❌ OpenImageIO returned null pixmap")
                            
                    except ImportError:
                        print(f"❌ OpenImageIO not available")
                    except Exception as e:
                        print(f"❌ OpenImageIO failed: {e}")
                    
                    print(f"❌ All methods failed to load EXR: {file_path}")
                    return None, None, None, None
                
                # Scale if needed
                if width > max_size or height > max_size:
                    scale = min(max_size / width, max_size / height)
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    
                    # Simple nearest-neighbor resize (fast)
                    indices_h = np.linspace(0, height-1, new_height, dtype=int)
                    indices_w = np.linspace(0, width-1, new_width, dtype=int)
                    rgb = rgb[np.ix_(indices_h, indices_w)]
                    
                    width, height = new_width, new_height
                
                # Return RAW float data (no tone mapping!)
                return rgb, width, height, resolution_str
                
        except Exception as e:
            print(f"OpenEXR raw loading failed: {e}")
            return None, None, None, None
    
    # If neither imageio nor OpenEXR available
    return None, None, None, None


def load_hdr_exr_image(file_path, max_size=2048, exposure=0.0, return_raw=False):
    """Load HDR/EXR image with proper float HDR handling - see widgets.py for full implementation"""
    # NOTE: This is a simplified stub - full implementation is in widgets.py
    # For now, just use the raw loader + basic tone mapping
    rgb, width, height, resolution_str = load_hdr_exr_raw(file_path, max_size)
    
    if rgb is None:
        # Check if it's a deep EXR (resolution_str will contain "Deep EXR")
        if resolution_str and "Deep EXR" in resolution_str:
            return None, resolution_str
        return None, None
    
    import numpy as np
    
    # Apply exposure
    exposure_multiplier = pow(2.0, exposure)
    rgb = rgb * exposure_multiplier
    
    # Simple tone mapping
    a = 2.51
    b = 0.03
    c = 2.43
    d = 0.59
    e = 0.14
    rgb_tonemapped = np.clip((rgb * (a * rgb + b)) / (rgb * (c * rgb + d) + e), 0, 1)
    
    # Gamma correction
    gamma = 1.0 / 2.2
    rgb_tonemapped = np.power(rgb_tonemapped, gamma)
    
    # Convert to 8-bit
    rgb_8bit = (rgb_tonemapped * 255).astype(np.uint8)
    
    # Create QImage
    bytes_per_line = width * 3
    q_image = QImage(rgb_8bit.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
    q_image = q_image.copy()
    
    # Convert to QPixmap
    pixmap = QPixmap.fromImage(q_image)
    return pixmap, resolution_str


def load_pdf_page(file_path, page_number=0, max_size=1024):
    """
    Load PDF page as QPixmap for preview
    
    Args:
        file_path: Path to PDF file
        page_number: Page number to load (0-indexed)
        max_size: Maximum width/height for preview (default 1024)
        
    Returns:
        tuple: (QPixmap, page_count, resolution_str) or (None, 0, None) on failure
               Returns (None, -1, "encrypted") if PDF is password protected
    """
    if not PYMUPDF_AVAILABLE:
        print("PyMuPDF not available - cannot load PDF")
        return None, 0, None
    
    try:
        import fitz
        # Open PDF document
        doc = fitz.open(str(file_path))
        
        # Check if document is encrypted
        if doc.is_encrypted:
            print(f"PDF is password protected: {file_path}")
            doc.close()
            return None, -1, "encrypted"
        
        page_count = len(doc)
        
        # Validate page number
        if page_number < 0 or page_number >= page_count:
            page_number = 0
        
        # Get page
        try:
            page = doc[page_number]
        except (ValueError, RuntimeError) as e:
            print(f"Error accessing PDF page {page_number}: {e}")
            doc.close()
            return None, 0, None
        
        # Get page dimensions
        rect = page.rect
        width = int(rect.width)
        height = int(rect.height)
        resolution_str = f"{width} x {height}"
        
        # Calculate zoom to fit max_size
        zoom = min(max_size / width, max_size / height, 2.0)
        mat = fitz.Matrix(zoom, zoom)
        
        # Render page to pixmap
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # Convert to QImage
        img_format = QImage.Format_RGB888 if pix.n == 3 else QImage.Format_RGBA8888
        q_image = QImage(pix.samples, pix.width, pix.height, pix.stride, img_format)
        q_image = q_image.copy()
        
        # Convert to QPixmap
        pixmap = QPixmap.fromImage(q_image)
        
        # Close document
        doc.close()
        
        return pixmap, page_count, resolution_str
        
    except Exception as e:
        print(f"Error loading PDF: {e}")
        import traceback
        traceback.print_exc()
        return None, 0, None


class FlowLayout(QtWidgets.QLayout):
    """Flow layout that wraps widgets horizontally like tag chips (Qt example-based)"""
    
    def __init__(self, parent=None, margin=0, hSpacing=-1, vSpacing=-1):
        super().__init__(parent)
        self.itemList = []
        self.m_hSpace = hSpacing
        self.m_vSpace = vSpacing
        
        self.setContentsMargins(margin, margin, margin, margin)
    
    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)
    
    def addItem(self, item):
        self.itemList.append(item)
    
    def addWidget(self, widget):
        """Add widget to the flow layout"""
        self.addItem(QtWidgets.QWidgetItem(widget))
    
    def horizontalSpacing(self):
        if self.m_hSpace >= 0:
            return self.m_hSpace
        else:
            return self.smartSpacing(QtWidgets.QStyle.PM_LayoutHorizontalSpacing)
    
    def verticalSpacing(self):
        if self.m_vSpace >= 0:
            return self.m_vSpace
        else:
            return self.smartSpacing(QtWidgets.QStyle.PM_LayoutVerticalSpacing)
    
    def count(self):
        return len(self.itemList)
    
    def itemAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None
    
    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None
    
    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))
    
    def hasHeightForWidth(self):
        return True
    
    def heightForWidth(self, width):
        height = self.doLayout(QRect(0, 0, width, 0), True)
        return height
    
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)
    
    def sizeHint(self):
        return self.minimumSize()
    
    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size
    
    def doLayout(self, rect, testOnly):
        left, top, right, bottom = self.getContentsMargins()
        effectiveRect = rect.adjusted(+left, +top, -right, -bottom)
        x = effectiveRect.x()
        y = effectiveRect.y()
        lineHeight = 0
        
        for item in self.itemList:
            wid = item.widget()
            spaceX = self.horizontalSpacing()
            if spaceX == -1:
                spaceX = wid.style().layoutSpacing(
                    QtWidgets.QSizePolicy.PushButton,
                    QtWidgets.QSizePolicy.PushButton,
                    Qt.Horizontal
                )
            spaceY = self.verticalSpacing()
            if spaceY == -1:
                spaceY = wid.style().layoutSpacing(
                    QtWidgets.QSizePolicy.PushButton,
                    QtWidgets.QSizePolicy.PushButton,
                    Qt.Vertical
                )
            
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > effectiveRect.right() and lineHeight > 0:
                x = effectiveRect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0
            
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            
            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())
        
        return y + lineHeight - rect.y() + bottom
    
    def smartSpacing(self, pm):
        parent = self.parent()
        if not parent:
            return -1
        elif parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        else:
            return parent.spacing()
    
    def clear(self):
        """Remove all widgets from layout"""
        while self.count():
            item = self.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


class CachedFrameSlider(QSlider):
    """Custom slider that visualizes cached frames with colored indicators"""
    
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.cached_frames = set()  # Set of cached frame indices
        self.is_dragging = False  # Track if user is dragging the slider
        self.setMinimumHeight(22)
        self.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555;
                height: 4px;
                background: #2a2a2a;
                margin: 2px 0;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5DADE2, stop:1 #2E86C1);
                border: 1px solid #1B4F72;
                width: 12px;
                margin: -5px 0;
                border-radius: 2px;
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #85C1E9, stop:1 #5DADE2);
            }
        """)
    
    def set_cached_frames(self, cached_indices):
        """Set which frames are cached"""
        self.cached_frames = cached_indices
        self.update()  # Repaint
    
    def mousePressEvent(self, event):
        """Jump to clicked position and allow immediate dragging (like video players)"""
        if event.button() == Qt.LeftButton:
            self.is_dragging = True  # Start drag
            
            # FIRST: Emit sliderPressed so parent knows we're dragging
            self.sliderPressed.emit()
            
            # Simple calculation: use widget width directly
            pos_x = event.pos().x()
            widget_width = self.width()
            
            # Leave some margin for the handle
            handle_margin = 6  # Half of handle width
            usable_width = widget_width - (2 * handle_margin)
            
            if usable_width > 0:
                # Calculate ratio from position (accounting for margins)
                ratio = (pos_x - handle_margin) / usable_width
                ratio = max(0.0, min(1.0, ratio))  # Clamp to 0-1
                
                # Calculate value
                value = int(self.minimum() + ratio * (self.maximum() - self.minimum()))
                
                # Set value (this will trigger valueChanged)
                self.setValue(value)
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move during drag"""
        if self.is_dragging:
            # Simple calculation during drag
            pos_x = event.pos().x()
            widget_width = self.width()
            handle_margin = 6
            usable_width = widget_width - (2 * handle_margin)
            
            if usable_width > 0:
                ratio = (pos_x - handle_margin) / usable_width
                ratio = max(0.0, min(1.0, ratio))
                
                value = int(self.minimum() + ratio * (self.maximum() - self.minimum()))
                self.setValue(value)
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release - trigger cache recalculation"""
        if event.button() == Qt.LeftButton:
            self.is_dragging = False  # End drag
            # Emit signal to notify that drag ended (parent will recalculate cache)
            self.sliderReleased.emit()
        
        super().mouseReleaseEvent(event)
    
    def paintEvent(self, event):
        """Custom paint to show cached frames"""
        # Draw standard slider first
        super().paintEvent(event)
        
        # Draw cache indicators
        if not self.cached_frames or self.maximum() == 0:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get groove rectangle (where the slider track is)
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove_rect = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self
        )
        
        # Draw small dots/rectangles for cached frames inside the groove
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(80, 200, 120)))  # Green
        
        groove_width = groove_rect.width()
        groove_left = groove_rect.left()
        groove_center_y = groove_rect.center().y()
        
        for frame_index in self.cached_frames:
            if frame_index > self.maximum():
                continue
            
            # Calculate position along slider
            ratio = frame_index / self.maximum() if self.maximum() > 0 else 0
            x = int(groove_left + ratio * groove_width)
            
            # Draw small filled circle (dot) - subtle and clean
            dot_radius = 2
            painter.drawEllipse(QPoint(x, groove_center_y), dot_radius, dot_radius)


class SequencePlaybackWidget(QWidget):
    """Playback controls for image sequences
    
    Features:
    - First/Previous/Play/Pause/Stop/Next/Last buttons
    - Timeline slider with cache visualization
    - Frame counter
    - FPS selector
    - Keyboard shortcuts (Space, Arrow keys, Home/End)
    
    Signals:
        frame_changed(int): Emitted when frame changes (0-based index)
    """
    
    frame_changed = Signal(int)  # Emitted when current frame changes
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sequence = None  # ImageSequence object
        self.current_frame_index = 0  # 0-based index into sequence.files
        self.is_playing = False
        self.fps = 24  # Default FPS
        self.cache = None  # Reference to SequenceFrameCache (set externally)
        
        # Playback timer
        self.playback_timer = QtCore.QTimer()
        self.playback_timer.timeout.connect(self.advance_frame)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup playback controls UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(3)
        
        # Top row: Transport buttons
        transport_layout = QHBoxLayout()
        transport_layout.setSpacing(2)
        
        # First frame button
        self.first_button = QToolButton()
        self.first_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        self.first_button.setToolTip("First Frame (Home)")
        self.first_button.setFixedSize(28, 28)
        self.first_button.clicked.connect(self.go_to_first)
        transport_layout.addWidget(self.first_button)
        
        # Previous frame button
        self.prev_button = QToolButton()
        self.prev_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekBackward))
        self.prev_button.setToolTip("Previous Frame (Left Arrow)")
        self.prev_button.setFixedSize(28, 28)
        self.prev_button.clicked.connect(self.go_to_previous)
        transport_layout.addWidget(self.prev_button)
        
        # Play/Pause button (larger)
        self.play_button = QToolButton()
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_button.setToolTip("Play/Pause (Space)")
        self.play_button.setFixedSize(36, 28)
        self.play_button.clicked.connect(self.toggle_play_pause)
        transport_layout.addWidget(self.play_button)
        
        # Stop button
        self.stop_button = QToolButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_button.setToolTip("Stop and Reset")
        self.stop_button.setFixedSize(28, 28)
        self.stop_button.clicked.connect(self.stop)
        transport_layout.addWidget(self.stop_button)
        
        # Next frame button
        self.next_button = QToolButton()
        self.next_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekForward))
        self.next_button.setToolTip("Next Frame (Right Arrow)")
        self.next_button.setFixedSize(28, 28)
        self.next_button.clicked.connect(self.go_to_next)
        transport_layout.addWidget(self.next_button)
        
        # Last frame button
        self.last_button = QToolButton()
        self.last_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        self.last_button.setToolTip("Last Frame (End)")
        self.last_button.setFixedSize(28, 28)
        self.last_button.clicked.connect(self.go_to_last)
        transport_layout.addWidget(self.last_button)
        
        transport_layout.addSpacing(10)
        
        # Frame counter label
        self.frame_label = QLabel("Frame: - / -")
        self.frame_label.setMinimumWidth(120)
        self.frame_label.setStyleSheet(f"font-family: {UI_FONT}; color: #aaa;")
        transport_layout.addWidget(self.frame_label)
        
        transport_layout.addStretch()
        
        # FPS selector
        transport_layout.addWidget(QLabel("FPS:"))
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["24", "25", "30", "60"])
        self.fps_combo.setCurrentText("24")
        self.fps_combo.setMaximumWidth(60)
        self.fps_combo.currentTextChanged.connect(self.on_fps_changed)
        transport_layout.addWidget(self.fps_combo)
        
        layout.addLayout(transport_layout)
        
        # Bottom row: Timeline slider
        slider_layout = QHBoxLayout()
        slider_layout.setSpacing(5)
        
        # Timeline slider with custom style for cache visualization
        self.timeline_slider = CachedFrameSlider(Qt.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(0)
        self.timeline_slider.setValue(0)
        self.timeline_slider.setTickPosition(QtWidgets.QSlider.NoTicks)
        self.timeline_slider.valueChanged.connect(self.on_slider_changed)
        self.timeline_slider.sliderReleased.connect(self.on_slider_released)
        slider_layout.addWidget(self.timeline_slider, 1)
        
        layout.addLayout(slider_layout)
    
    def set_sequence(self, sequence):
        """Set the image sequence to play
        
        Args:
            sequence: ImageSequence object
        """
        self.sequence = sequence
        self.current_frame_index = 0
        self.is_playing = False
        self.playback_timer.stop()
        
        if sequence and sequence.files:
            frame_count = len(sequence.files)
            self.timeline_slider.setMaximum(frame_count - 1)
            self.timeline_slider.setValue(0)
            self.update_frame_label()
            self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.setEnabled(True)
        else:
            self.timeline_slider.setMaximum(0)
            self.frame_label.setText("Frame: - / -")
            self.setEnabled(False)
    
    def toggle_play_pause(self):
        """Toggle between play and pause"""
        if not self.sequence or not self.sequence.files:
            return
        
        if self.is_playing:
            self.pause()
        else:
            self.play()
    
    def play(self):
        """Start playback"""
        if not self.sequence or not self.sequence.files:
            return
        
        self.is_playing = True
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        
        # Calculate interval in milliseconds
        interval = int(1000.0 / self.fps)
        self.playback_timer.start(interval)
    
    def pause(self):
        """Pause playback"""
        self.is_playing = False
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.playback_timer.stop()
    
    def advance_frame(self):
        """Advance to next frame (called by timer)"""
        if not self.sequence or not self.sequence.files:
            return
        
        # Loop back to start
        self.current_frame_index = (self.current_frame_index + 1) % len(self.sequence.files)
        self.timeline_slider.setValue(self.current_frame_index)
    
    def on_slider_changed(self, value):
        """Handle slider value change"""
        self.current_frame_index = value
        self.update_frame_label()
        self.frame_changed.emit(value)
    
    def on_slider_released(self):
        """Handle slider release after drag - trigger cache recalculation"""
        # No cache recalculation needed (cache system removed)
    
    def on_fps_changed(self, fps_str):
        """Handle FPS change"""
        try:
            self.fps = int(fps_str)
            # Update timer interval if playing
            if self.is_playing:
                interval = int(1000.0 / self.fps)
                self.playback_timer.setInterval(interval)
        except ValueError:
            pass
    
    def update_frame_label(self):
        """Update frame counter label"""
        if self.sequence and self.sequence.files:
            current = self.current_frame_index + 1  # 1-based for display
            total = len(self.sequence.files)
            
            # Get actual frame number from filename
            file_path = self.sequence.files[self.current_frame_index]
            frame_num = self.sequence._extract_frame(file_path.name)
            
            if frame_num is not None:
                self.frame_label.setText(f"Frame: {current}/{total} (#{frame_num})")
            else:
                self.frame_label.setText(f"Frame: {current}/{total}")
        else:
            self.frame_label.setText("Frame: - / -")
    
    def step_forward(self):
        """Step one frame forward"""
        if not self.sequence or not self.sequence.files:
            return
        
        new_index = min(self.current_frame_index + 1, len(self.sequence.files) - 1)
        self.timeline_slider.setValue(new_index)
    
    def step_backward(self):
        """Step one frame backward"""
        if not self.sequence or not self.sequence.files:
            return
        
        new_index = max(self.current_frame_index - 1, 0)
        self.timeline_slider.setValue(new_index)
    
    def go_to_first(self):
        """Go to first frame"""
        if self.sequence and self.sequence.files:
            self.timeline_slider.setValue(0)
    
    def go_to_last(self):
        """Go to last frame"""
        if self.sequence and self.sequence.files:
            self.timeline_slider.setValue(len(self.sequence.files) - 1)
    
    def go_to_previous(self):
        """Go to previous frame (alias for step_backward)"""
        self.step_backward()
    
    def go_to_next(self):
        """Go to next frame (alias for step_forward)"""
        self.step_forward()
    
    def stop(self):
        """Stop playback and return to first frame"""
        self.pause()
        self.go_to_first()
    
    def update_cache_visualization(self):
        """Update slider with cached frame positions"""
        # No cache visualization for now
        pass
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        if event.key() == Qt.Key_Space:
            self.toggle_play_pause()
            event.accept()
        elif event.key() == Qt.Key_F:
            # Toggle fullscreen for video
            if hasattr(self, 'video_widget') and self.video_widget and self.video_widget.isVisible():
                self.toggle_video_fullscreen()
                event.accept()
        elif event.key() == Qt.Key_Escape:
            # Exit fullscreen if in fullscreen mode
            if hasattr(self, 'video_widget') and self.video_widget and self.video_widget.isFullScreen():
                self.toggle_video_fullscreen()
                event.accept()
        elif event.key() == Qt.Key_Right:
            self.pause()  # Pause if playing
            self.step_forward()
            event.accept()
        elif event.key() == Qt.Key_Left:
            self.pause()  # Pause if playing
            self.step_backward()
            event.accept()
        elif event.key() == Qt.Key_Home:
            self.pause()
            self.go_to_first_frame()
            event.accept()
        elif event.key() == Qt.Key_End:
            self.pause()
            self.go_to_last_frame()
            event.accept()
        else:
            super().keyPressEvent(event)


class PreviewPanel(QWidget):
    """Preview panel showing file preview and metadata"""
    
    def __init__(self, settings_manager, config=None, metadata_manager=None, parent=None):
        super().__init__(parent)
        self.settings = settings_manager
        self.config = config
        self.metadata_manager = metadata_manager  # For tag-based color management
        self.current_assets = []
        self.current_pixmap = None  # Store scaled preview pixmap
        self.full_res_pixmap = None  # Store full resolution pixmap for zoom
        self.preview_cache = {}  # Cache: file_path -> (pixmap, resolution)
        self.cache_max_size = 50  # Max 50 previews in cache
        self.current_image_path = None  # Track current image path
        self.zoom_mode = False  # Track if in zoom mode
        self.zoom_level = 1.0  # Current zoom level
        self.pan_offset = QPoint(0, 0)  # Pan offset
        self.last_mouse_pos = None  # For dragging
        self.hdr_exposure = 0.0  # Default HDR exposure in stops (0 = neutral, like Arnold)
        self.current_hdr_path = None  # Track current HDR file for re-loading with new exposure
        self.hdr_raw_cache = {}  # Cache raw HDR float data: file_path -> (numpy_array, width, height, resolution_str)
        self.hdr_cache_max_size = 5  # Only cache last 5 HDR raw data (they're big!)
        self.max_preview_size = 3840  # 4K preview resolution (3840px max, great quality!)
        self.max_hdr_cache_size = 5  # Maximum HDR cache items (for settings compatibility)
        
        # Text preview mode flag
        self.is_showing_text = False
        
        # PDF preview state
        self.is_showing_pdf = False
        self.current_pdf_path = None
        self.current_pdf_page = 0
        self.current_pdf_page_count = 0
        
        # Exposure adjustment debounce timer for smooth slider
        self.exposure_timer = QtCore.QTimer()
        self.exposure_timer.setSingleShot(True)
        self.exposure_timer.setInterval(20)  # 20ms delay (smooth but responsive)
        self.exposure_timer.timeout.connect(self.apply_exposure_change)
        self.pending_exposure_value = None
        self.is_dragging_exposure = False  # Track if user is dragging exposure slider
        
        # Background mode: 'dark_gray', 'light_gray', 'checkered', 'black', 'white'
        self.background_mode = 'dark_gray'  # Default
        self._load_background_setting()
        
        # Image scaling info (for user feedback when large images are downscaled)
        self.is_image_scaled = False
        self.original_image_size = None  # (width, height)
        self.scaled_image_size = None    # (width, height)
        
        # Sequence scrubbing state
        self.is_scrubbing = False  # Track if currently scrubbing through sequence
        self.scrub_start_pos = None  # Mouse position when scrubbing started
        self.scrub_start_frame = 0  # Frame index when scrubbing started
        
        # Simple frame cache (will be implemented later if needed)
        # For now: no caching, just direct loading
        
        # EXR channel switching
        self.current_exr_file_path = None  # Current EXR file path
        self.current_exr_channels = []     # List of channel names
        self.current_exr_channel = None    # Currently displayed channel name
        
        # Video fullscreen widget
        self._fullscreen_widget = None  # Fullscreen container for video + controls
        
        self.setMinimumWidth(250)  # Minimum width when visible
        self.setup_ui()
    
    def cleanup(self):
        """Cleanup resources (call before closing)"""
        # No thread to cleanup for now
        pass
    
    def _load_background_setting(self):
        """Load background mode from settings"""
        try:
            value = self.settings.get('preview', 'background_mode', 'dark_gray')
            self.background_mode = value
        except Exception:
            self.background_mode = 'dark_gray'
    
    def _save_background_setting(self):
        """Save background mode to settings"""
        try:
            self.settings.set('preview', 'background_mode', self.background_mode)
            self.settings.save()
        except Exception:
            pass
    
    def show_background_menu(self, pos):
        """Show context menu for background selection and EXR channel switching"""
        if PYSIDE_VERSION == 6:
            from PySide6.QtWidgets import QMenu
            from PySide6.QtGui import QAction
        else:
            from PySide2.QtWidgets import QMenu, QAction
        
        menu = QMenu(self)
        
        # === EXR Channel Selection (if viewing EXR) ===
        if self.current_exr_channels:
            channels_menu = menu.addMenu("📺 EXR Channels")
            
            for channel_name in self.current_exr_channels:
                action = QAction(channel_name, self)
                action.setCheckable(True)
                action.setChecked(channel_name == self.current_exr_channel)
                action.triggered.connect(lambda checked=False, ch=channel_name: self.switch_exr_channel(ch))
                channels_menu.addAction(action)
            
            menu.addSeparator()
        
        # === Background Options ===
        bg_menu = menu.addMenu("🎨 Background")
        
        bg_options = [
            ('dark_gray', 'Dark Gray'),
            ('light_gray', 'Light Gray'),
            ('checkered', 'Checkered (Transparent)'),
            ('black', 'Black'),
            ('white', 'White')
        ]
        
        for mode, label in bg_options:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode == self.background_mode)
            action.triggered.connect(lambda checked=False, m=mode: self.set_background_mode(m))
            bg_menu.addAction(action)
        
        menu.exec_(pos)
    
    def switch_exr_channel(self, channel_name):
        """Switch to a different EXR channel"""
        if not self.current_exr_file_path or channel_name == self.current_exr_channel:
            return
        
        print(f"🔄 Switching EXR channel to: {channel_name}")
        
        # Load the specific channel
        try:
            pixmap, resolution_str = self.load_exr_channel(self.current_exr_file_path, channel_name)
            if pixmap:
                self.current_exr_channel = channel_name
                self.current_pixmap = pixmap
                
                # Update title to show channel
                filename = Path(self.current_exr_file_path).name
                self.title_label.setText(f"Preview - {filename} [{channel_name}]")
                
                # Update preview (keeping zoom state)
                if not self.zoom_mode:
                    self.fit_pixmap_to_label()
                else:
                    # In zoom mode, update with current zoom
                    self.full_res_pixmap = pixmap
                    self.set_preview_pixmap(pixmap)
                
                # Add to cache with channel-specific key
                cache_key = f"{self.current_exr_file_path}#{channel_name}"
                self.add_to_cache(cache_key, pixmap, resolution_str)
                
                print(f"✅ Successfully switched to channel '{channel_name}'")
            else:
                print(f"❌ Failed to load channel '{channel_name}'")
                
        except Exception as e:
            print(f"❌ Error switching to channel '{channel_name}': {e}")
            import traceback
            traceback.print_exc()
    
    def load_exr_channel(self, file_path, channel_name):
        """
        Load a specific channel from an EXR file directly with OpenEXR
        
        NOTE: This should only be called for non-deep EXR files.
        Deep EXR check should be done before calling this function.
        
        Args:
            file_path: Path to EXR file
            channel_name: Name of channel to load (e.g. "diffuse", "specular", "zdepth")
            
        Returns:
            tuple: (QPixmap, resolution_str) or (None, None)
        """
        try:
            # Check raw data cache first (for exposure adjustment without reloading)
            raw_cache_key = f"{file_path}#{channel_name}#raw"
            if raw_cache_key in self.hdr_raw_cache:
                print(f"🚀 Using cached raw data for channel '{channel_name}' (fast exposure adjustment)")
                rgb_raw, width, height, resolution_str = self.hdr_raw_cache[raw_cache_key]
                
                # Apply tone mapping with current exposure
                pixmap = self.apply_hdr_tone_mapping(rgb_raw, width, height, self.hdr_exposure, file_path=file_path)
                if pixmap:
                    return pixmap, resolution_str
                else:
                    print("⚠️ Tone mapping failed, reloading from disk...")
            
            # Check pixmap cache (for fast display without tone mapping)
            cache_key = f"{file_path}#{channel_name}#{self.hdr_exposure:.1f}"
            if cache_key in self.preview_cache:
                return self.preview_cache[cache_key]
            
            import sys
            import os
            
            # Add external_libs to path
            external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
            if external_libs not in sys.path:
                sys.path.insert(0, external_libs)
            
            import OpenEXR
            import numpy as np
            
            with OpenEXR.File(str(file_path)) as exr_file:
                header = exr_file.header()
                dw = header['dataWindow']
                width = dw[1][0] - dw[0][0] + 1
                height = dw[1][1] - dw[0][1] + 1
                
                channels = exr_file.channels()
                channel_list = list(channels.keys())
                
                rgb = None
                
                # Try to load the requested channel
                # 1. Try as direct channel name (e.g. "RGB", "RGBA")
                if channel_name in channels:
                    data = channels[channel_name].pixels
                    if data is not None:
                        if data.ndim == 3 and data.shape[2] >= 3:
                            rgb = data[:, :, :3]  # Take RGB only
                        elif data.ndim == 2:
                            # Single channel, convert to RGB
                            rgb = np.stack([data, data, data], axis=2)
                        else:
                            rgb = data
                
                # 2. Try as prefix with .R .G .B (e.g. "diffuse" → "diffuse.R", "diffuse.G", "diffuse.B")
                if rgb is None:
                    r_name = f"{channel_name}.R"
                    g_name = f"{channel_name}.G"
                    b_name = f"{channel_name}.B"
                    
                    if all(c in channels for c in [r_name, g_name, b_name]):
                        r = channels[r_name].pixels
                        g = channels[g_name].pixels
                        b = channels[b_name].pixels
                        
                        if r is not None and g is not None and b is not None:
                            # Try to stack if possible
                            try:
                                rgb = np.stack([r, g, b], axis=2)
                            except Exception as stack_error:
                                # Fallback: just use R channel as grayscale
                                if hasattr(r, 'ndim') and r.ndim == 2:
                                    rgb = np.stack([r, r, r], axis=2)
                                elif hasattr(r, '__len__'):
                                    # Try to reshape from 1D array
                                    try:
                                        r_2d = np.array(r).reshape(height, width)
                                        rgb = np.stack([r_2d, r_2d, r_2d], axis=2)
                                    except:
                                        print(f"❌ Cannot reshape channel data")
                                        return None, None
                
                # 3. Try as single channel with common suffixes
                if rgb is None:
                    for suffix in ['', '.R', '.r', '.x', '.X']:
                        test_name = f"{channel_name}{suffix}"
                        if test_name in channels:
                            print(f"✅ Found single channel: {test_name}")
                            data = channels[test_name].pixels
                            if data is not None:
                                if hasattr(data, 'ndim') and data.ndim == 2:
                                    rgb = np.stack([data, data, data], axis=2)
                                elif hasattr(data, '__len__'):
                                    # Try to reshape
                                    try:
                                        data_2d = np.array(data).reshape(height, width)
                                        rgb = np.stack([data_2d, data_2d, data_2d], axis=2)
                                    except:
                                        pass
                                else:
                                    rgb = data
                                if rgb is not None:
                                    break
                
                if rgb is None:
                    print(f"❌ Could not find channel '{channel_name}'")
                    print(f"💡 Available channels: {', '.join(channel_list[:10])}{'...' if len(channel_list) > 10 else ''}")
                    return None, None
                
                # Now we have rgb data (RAW float)
                
                # Convert float16 to float32
                if rgb.dtype == np.float16:
                    rgb = rgb.astype(np.float32)
                
                # Store ORIGINAL resolution BEFORE downsampling (for metadata display)
                resolution_str = f"{width} x {height}"
                
                # Downsample to max preview size (4K) if needed
                # This saves memory and improves tone mapping performance
                import cv2
                if width > self.max_preview_size or height > self.max_preview_size:
                    scale = min(self.max_preview_size / width, self.max_preview_size / height)
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    
                    rgb = cv2.resize(rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
                    width, height = new_width, new_height
                
                # Store downsampled raw data in cache for high quality exposure adjustments
                raw_cache_key = f"{file_path}#{channel_name}#raw"
                self.hdr_raw_cache[raw_cache_key] = (rgb, width, height, resolution_str)
                
                # Apply tone mapping with current exposure using centralized function
                # This handles ACES automatically based on file tags
                pixmap = self.apply_hdr_tone_mapping(rgb, width, height, self.hdr_exposure, file_path=file_path)
                
                if not pixmap:
                    print(f"❌ Tone mapping failed")
                    return None, None
                
                # Cache the final pixmap with exposure key
                cache_key = f"{file_path}#{channel_name}#{self.hdr_exposure:.1f}"
                self.preview_cache[cache_key] = (pixmap, resolution_str)
                
                return pixmap, resolution_str
                
        except Exception as e:
            print(f"❌ Error loading EXR channel: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def load_hdr_file(self, file_path):
        """
        Load HDR file with full resolution raw data caching (like load_exr_channel)
        
        Args:
            file_path: Path to HDR file
            
        Returns:
            tuple: (QPixmap, resolution_str) or (None, None)
        """
        try:
            # Check raw data cache first (for exposure adjustment without reloading)
            if file_path in self.hdr_raw_cache:
                print(f"🚀 Using cached raw HDR data (fast exposure adjustment)")
                rgb_raw, width, height, resolution_str = self.hdr_raw_cache[file_path]
                
                # Apply tone mapping with current exposure
                pixmap = self.apply_hdr_tone_mapping(rgb_raw, width, height, self.hdr_exposure, file_path=file_path)
                if pixmap:
                    return pixmap, resolution_str
                else:
                    print("⚠️ Tone mapping failed, reloading from disk...")
            
            print(f"🔄 Loading HDR file from disk...")
            
            import sys
            import os
            import cv2
            import numpy as np
            
            # Add external_libs to path
            external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
            if external_libs not in sys.path:
                sys.path.insert(0, external_libs)
            
            # Load HDR with OpenCV (FULL RESOLUTION)
            rgb = cv2.imread(str(file_path), cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR)
            
            if rgb is None:
                print(f"❌ Failed to load HDR with OpenCV")
                return None, None
            
            # OpenCV loads as BGR, convert to RGB
            rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
            
            # Get ORIGINAL resolution BEFORE downsampling (for metadata display)
            height, width = rgb.shape[:2]
            resolution_str = f"{width} x {height}"
            
            # Convert float16 to float32 if needed
            if rgb.dtype == np.float16:
                rgb = rgb.astype(np.float32)
            
            # Downsample to max preview size (4K) if needed
            if width > self.max_preview_size or height > self.max_preview_size:
                scale = min(self.max_preview_size / width, self.max_preview_size / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                
                rgb = cv2.resize(rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
                width, height = new_width, new_height
            
            # Store downsampled raw data in cache
            self.hdr_raw_cache[file_path] = (rgb, width, height, resolution_str)
            
            # Apply tone mapping with current exposure
            pixmap = self.apply_hdr_tone_mapping(rgb, width, height, self.hdr_exposure, file_path=file_path)
            
            if not pixmap:
                print(f"❌ Tone mapping failed")
                return None, None
            
            return pixmap, resolution_str
            
        except Exception as e:
            print(f"❌ Error loading HDR file: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def detect_exr_channels(self, file_path):
        """
        Detect and store available EXR channels
        
        NOTE: This should only be called for non-deep EXR files.
        Check with is_deep_exr() before calling this function.
        """
        if not OPENEXR_AVAILABLE:
            return
        
        try:
            # Open EXR file to read channel names
            with OpenEXR.File(str(file_path)) as exr_file:
                channels = exr_file.channels()
                channel_names = list(channels.keys())
                
                # Store EXR info - enable channel switching for ALL EXRs
                self.current_exr_file_path = file_path
                self.current_exr_channels = channel_names
                
                # The first channel will be displayed by default (widgets.py auto-selects it)
                # User can switch between any available channels via right-click menu
                self.current_exr_channel = channel_names[0] if channel_names else None
                
        except Exception as e:
            print(f"❌ Error detecting EXR channels: {e}")
            # Clear EXR info on error
            self.current_exr_file_path = None
            self.current_exr_channels = []
            self.current_exr_channel = None
    
    def set_background_mode(self, mode):
        """Set background mode and update display"""
        if mode == self.background_mode:
            return
        
        self.background_mode = mode
        self._save_background_setting()
        self._apply_background()
    
    def _apply_background(self):
        """Apply current background mode to graphics view"""
        if self.background_mode == 'dark_gray':
            self.graphics_view.setStyleSheet("QGraphicsView { background-color: #2a2a2a; border: 1px solid #555; }")
            self.graphics_view.setBackgroundBrush(QBrush())  # Clear custom brush
        
        elif self.background_mode == 'light_gray':
            self.graphics_view.setStyleSheet("QGraphicsView { background-color: #909090; border: 1px solid #555; }")
            self.graphics_view.setBackgroundBrush(QBrush())
        
        elif self.background_mode == 'black':
            self.graphics_view.setStyleSheet("QGraphicsView { background-color: #000000; border: 1px solid #555; }")
            self.graphics_view.setBackgroundBrush(QBrush())
        
        elif self.background_mode == 'white':
            self.graphics_view.setStyleSheet("QGraphicsView { background-color: #ffffff; border: 1px solid #555; }")
            self.graphics_view.setBackgroundBrush(QBrush())
        
        elif self.background_mode == 'checkered':
            # Create checkered pattern
            checker_size = 16
            pixmap = QPixmap(checker_size * 2, checker_size * 2)
            pixmap.fill(QColor(128, 128, 128))  # Light gray
            
            painter = QPainter(pixmap)
            painter.fillRect(0, 0, checker_size, checker_size, QColor(89, 89, 89))  # Dark gray
            painter.fillRect(checker_size, checker_size, checker_size, checker_size, QColor(89, 89, 89))
            painter.end()
            
            self.graphics_view.setStyleSheet("QGraphicsView { border: 1px solid #555; }")
            self.graphics_view.setBackgroundBrush(QBrush(pixmap))
    
    def setup_ui(self):
        """Setup preview panel UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Title label with zoom info
        title_layout = QHBoxLayout()
        self.title_label = QLabel("Preview")
        self.title_label.setStyleSheet(f"font-weight: bold; font-size: 12px; font-family: {UI_FONT}; padding: 5px;")
        title_layout.addWidget(self.title_label)
        
        self.zoom_label = QLabel("")
        self.zoom_label.setStyleSheet(f"font-size: 10px; font-family: {UI_FONT}; color: #888; padding: 5px;")
        title_layout.addWidget(self.zoom_label)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # Create splitter between preview and info tabs
        self.preview_splitter = QtWidgets.QSplitter(Qt.Vertical)
        self.preview_splitter.setHandleWidth(3)
        self.preview_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #555;
            }
            QSplitter::handle:hover {
                background-color: #777;
            }
        """)
        
        # Top part: Preview area + controls in a container
        preview_container = QWidget()
        self.preview_layout = QVBoxLayout(preview_container)
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_layout.setSpacing(5)
        
        # Preview image area using QGraphicsView (allows free positioning, no forced centering!)
        self.graphics_view = QGraphicsView()
        self.graphics_view.setMinimumHeight(200)
        self.graphics_view.setStyleSheet("QGraphicsView { background-color: #2a2a2a; border: 1px solid #555; }")
        self.graphics_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.graphics_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.graphics_view.setDragMode(QGraphicsView.NoDrag)
        
        # NO transformation anchor - we'll do it manually!
        self.graphics_view.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.graphics_view.setResizeAnchor(QGraphicsView.NoAnchor)
        
        # Disable keyboard focus - preview panel should NOT steal focus from browser
        # This was causing Space key (Quick View) to open Maya hotbox instead
        self.graphics_view.setFocusPolicy(Qt.NoFocus)
        
        # Create scene
        self.graphics_scene = QtWidgets.QGraphicsScene()
        self.graphics_view.setScene(self.graphics_scene)
        self.pixmap_item = None
        
        # Install event filter instead of overriding methods directly
        self.graphics_view.viewport().installEventFilter(self)
        self.graphics_view.installEventFilter(self)
        self.graphics_view.setMouseTracking(True)
        
                # Apply saved background mode
        self._apply_background()
        
        self.preview_layout.addWidget(self.graphics_view)
        
        # Zoom controls toolbar (only visible in zoom mode)
        self.zoom_controls = QWidget()
        zoom_controls_layout = QHBoxLayout(self.zoom_controls)
        zoom_controls_layout.setContentsMargins(5, 2, 5, 2)
        zoom_controls_layout.setSpacing(5)
        
        zoom_controls_layout.addWidget(QLabel("Zoom:"))
        
        # Zoom out button
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setMaximumWidth(30)
        self.zoom_out_btn.setToolTip("Zoom Out")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        zoom_controls_layout.addWidget(self.zoom_out_btn)
        
        # Zoom in button
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setMaximumWidth(30)
        self.zoom_in_btn.setToolTip("Zoom In")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        zoom_controls_layout.addWidget(self.zoom_in_btn)
        
        # 100% button
        self.zoom_100_btn = QPushButton("100%")
        self.zoom_100_btn.setMaximumWidth(50)
        self.zoom_100_btn.setToolTip("Actual Size (1:1)")
        self.zoom_100_btn.clicked.connect(self.zoom_100)
        zoom_controls_layout.addWidget(self.zoom_100_btn)
        
        # Fit button
        self.zoom_fit_btn = QPushButton("Fit")
        self.zoom_fit_btn.setMaximumWidth(50)
        self.zoom_fit_btn.setToolTip("Fit to View")
        self.zoom_fit_btn.clicked.connect(self.zoom_fit)
        zoom_controls_layout.addWidget(self.zoom_fit_btn)
        
        zoom_controls_layout.addStretch()
        
        # Exit zoom mode button
        self.zoom_exit_btn = QPushButton("Exit Zoom")
        self.zoom_exit_btn.setToolTip("Exit Zoom Mode (or double-click)")
        self.zoom_exit_btn.clicked.connect(self.exit_zoom_mode)
        zoom_controls_layout.addWidget(self.zoom_exit_btn)
        
        self.preview_layout.addWidget(self.zoom_controls)
        self.zoom_controls.hide()  # Hidden by default
        
        # HDR/EXR Exposure control (always visible for HDR/EXR files)
        self.exposure_controls = QWidget()
        exposure_layout = QHBoxLayout(self.exposure_controls)
        exposure_layout.setContentsMargins(5, 2, 5, 2)
        exposure_layout.setSpacing(5)
        
        exposure_layout.addWidget(QLabel("Exposure:"))
        
        # Exposure slider (-5.0 to +5.0 stops, default 0.0, like Arnold/Maya)
        # Use CachedFrameSlider for better click behavior (jumps to clicked position)
        self.exposure_slider = CachedFrameSlider(Qt.Horizontal)
        self.exposure_slider.setMinimum(-50)  # -5.0 stops
        self.exposure_slider.setMaximum(50)   # +5.0 stops
        self.exposure_slider.setValue(0)      # 0.0 (neutral, default)
        self.exposure_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.exposure_slider.setTickInterval(10)  # Tick every 1.0 stop
        self.exposure_slider.valueChanged.connect(self.on_exposure_changed)
        self.exposure_slider.sliderPressed.connect(self.on_exposure_slider_pressed)
        self.exposure_slider.sliderReleased.connect(self.on_exposure_slider_released)
        exposure_layout.addWidget(self.exposure_slider, 1)
        
        # Exposure value label
        self.exposure_label = QLabel("0.0")
        self.exposure_label.setMinimumWidth(40)
        self.exposure_label.setStyleSheet("color: #aaa;")
        exposure_layout.addWidget(self.exposure_label)
        
        # Reset button
        reset_btn = QPushButton("Reset")
        reset_btn.setMaximumWidth(50)
        reset_btn.setToolTip("Reset to neutral (0.0)")
        reset_btn.clicked.connect(lambda: self.exposure_slider.setValue(0))
        exposure_layout.addWidget(reset_btn)
        
        self.preview_layout.addWidget(self.exposure_controls)
        self.exposure_controls.hide()  # Hidden by default, shown only for HDR/EXR
        
        # === Sequence Playback Controls (only visible for image sequences) ===
        self.sequence_playback = SequencePlaybackWidget()
        # Cache disabled for now
        # self.sequence_playback.cache = self.sequence_frame_cache
        self.sequence_playback.frame_changed.connect(self.on_sequence_frame_changed)
        self.preview_layout.addWidget(self.sequence_playback)
        self.sequence_playback.hide()  # Hidden by default, shown only for sequences
        
        # === Video Playback (QMediaPlayer with Qt Multimedia) ===
        has_qt_multimedia = QMediaPlayer is not None
        self.video_widget = QVideoWidget() if has_qt_multimedia else QLabel("Video playback not available")
        self.video_widget.setStyleSheet("background-color: black; border: none; outline: none;")
        self.video_widget.setFocusPolicy(Qt.NoFocus)  # Disable focus to prevent border
        self.video_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)  # Fill available space
        self.video_widget.setMinimumHeight(200)  # Match graphics_view minimum height
        self.video_widget.setMouseTracking(True)  # Enable mouse tracking for scrubbing
        self.video_widget.installEventFilter(self)  # Install event filter for drag scrubbing
        if has_qt_multimedia and hasattr(self.video_widget, 'setAspectRatioMode'):
            # Qt.KeepAspectRatio ensures video fits and is centered
            self.video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        self.preview_layout.addWidget(self.video_widget, 1)  # stretch factor 1 to fill space
        self.video_widget.hide()
        
        # Video drag scrubbing state
        self.video_dragging = False
        self.video_drag_start_x = 0
        self.video_drag_start_position = 0
        
        # Qt Multimedia player
        if has_qt_multimedia:
            if PYSIDE_VERSION == 6:
                self.media_player = QMediaPlayer()
                self.audio_output = QAudioOutput()
                self.media_player.setAudioOutput(self.audio_output)
                self.media_player.setVideoOutput(self.video_widget)
                # Connect to mediaStatusChanged for initial frame display
                self.media_player.mediaStatusChanged.connect(self.on_media_status_changed)
            else:
                # PySide2 fallback
                from PySide2.QtMultimedia import QMediaPlayer as QMediaPlayerClass
                self.media_player = QMediaPlayerClass(None, QMediaPlayerClass.VideoSurface)
                self.media_player.setVideoOutput(self.video_widget)
                # Connect to mediaStatusChanged for initial frame display
                self.media_player.mediaStatusChanged.connect(self.on_media_status_changed)
        else:
            self.media_player = None
        
        # Video playback controls widget
        self.video_playback = QWidget()
        video_layout = QHBoxLayout(self.video_playback)
        video_layout.setContentsMargins(5, 2, 5, 2)
        video_layout.setSpacing(5)
        
        # Stop button
        self.video_stop_button = QToolButton()
        self.video_stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.video_stop_button.setToolTip("Stop")
        self.video_stop_button.setFixedSize(28, 28)
        self.video_stop_button.clicked.connect(self.stop_video_playback)
        video_layout.addWidget(self.video_stop_button)
        
        # Skip backward button (5 seconds)
        self.video_skip_back_button = QToolButton()
        self.video_skip_back_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        self.video_skip_back_button.setToolTip("Skip backward 5s")
        self.video_skip_back_button.setFixedSize(28, 28)
        self.video_skip_back_button.clicked.connect(self.skip_backward_video)
        video_layout.addWidget(self.video_skip_back_button)
        
        # Previous frame button
        self.video_prev_frame_button = QToolButton()
        self.video_prev_frame_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekBackward))
        self.video_prev_frame_button.setToolTip("Previous frame")
        self.video_prev_frame_button.setFixedSize(28, 28)
        self.video_prev_frame_button.clicked.connect(self.video_prev_frame)
        video_layout.addWidget(self.video_prev_frame_button)
        
        # Play/Pause button
        self.video_play_button = QToolButton()
        self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.video_play_button.setToolTip("Play/Pause (Space)")
        self.video_play_button.setFixedSize(36, 28)
        self.video_play_button.clicked.connect(self.toggle_video_playback)
        video_layout.addWidget(self.video_play_button)
        
        # Next frame button
        self.video_next_frame_button = QToolButton()
        self.video_next_frame_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekForward))
        self.video_next_frame_button.setToolTip("Next frame")
        self.video_next_frame_button.setFixedSize(28, 28)
        self.video_next_frame_button.clicked.connect(self.video_next_frame)
        video_layout.addWidget(self.video_next_frame_button)
        
        # Skip forward button (5 seconds)
        self.video_skip_forward_button = QToolButton()
        self.video_skip_forward_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        self.video_skip_forward_button.setToolTip("Skip forward 5s")
        self.video_skip_forward_button.setFixedSize(28, 28)
        self.video_skip_forward_button.clicked.connect(self.skip_forward_video)
        video_layout.addWidget(self.video_skip_forward_button)
        
        # Volume button (mute/unmute)
        self.video_volume_button = QToolButton()
        self.video_volume_button.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        self.video_volume_button.setToolTip("Mute/Unmute (Right-click for volume slider)")
        self.video_volume_button.setFixedSize(28, 28)
        # Don't use InstantPopup - we want manual control
        video_layout.addWidget(self.video_volume_button)
        
        # Volume popup widget (vertical slider)
        self.video_volume_popup = QWidget()
        self.video_volume_popup.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.video_volume_popup.setStyleSheet("""
            QWidget {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QSlider::groove:vertical {
                background: #2a2a2a;
                width: 6px;
                border-radius: 3px;
            }
            QSlider::handle:vertical {
                background: #808080;
                border: 1px solid #555;
                height: 12px;
                margin: -3px 0;
                border-radius: 6px;
            }
            QSlider::handle:vertical:hover {
                background: #999;
            }
            QLabel {
                color: #bbb;
                font-size: 9pt;
            }
        """)
        volume_popup_layout = QVBoxLayout(self.video_volume_popup)
        volume_popup_layout.setContentsMargins(8, 8, 8, 8)
        volume_popup_layout.setSpacing(5)
        
        # Vertical volume slider
        self.video_volume_slider = QtWidgets.QSlider(Qt.Vertical)
        self.video_volume_slider.setMinimum(0)
        self.video_volume_slider.setMaximum(100)
        self.video_volume_slider.setValue(100)  # 100% default
        self.video_volume_slider.setFixedHeight(100)
        self.video_volume_slider.setFixedWidth(24)
        self.video_volume_slider.setToolTip("Volume")
        if has_qt_multimedia:
            self.video_volume_slider.valueChanged.connect(self.on_video_volume_changed)
        volume_popup_layout.addWidget(self.video_volume_slider, 0, Qt.AlignCenter)
        
        # Volume percentage label
        self.video_volume_label = QLabel("100%")
        self.video_volume_label.setAlignment(Qt.AlignCenter)
        volume_popup_layout.addWidget(self.video_volume_label)
        
        # Connect volume button - left click = mute toggle
        self.video_volume_button.clicked.connect(self.toggle_video_mute)
        # Install event filter for right-click to show volume popup
        self.video_volume_button.installEventFilter(self)
        
        # Timeline slider (use CachedFrameSlider for click-to-jump behavior)
        self.video_slider = CachedFrameSlider(Qt.Horizontal)
        self.video_slider.setMinimum(0)
        self.video_slider.setMaximum(1000)
        self.video_slider.setValue(0)
        self.video_slider_dragging = False  # Track if user is dragging
        self.video_slider_updating = False  # Track if we're updating programmatically
        if has_qt_multimedia:
            # Use sliderPressed to track drag start
            self.video_slider.sliderPressed.connect(self.on_video_slider_pressed)
            # Use valueChanged to handle all position changes (click and drag)
            self.video_slider.valueChanged.connect(self.on_video_slider_value_changed)
            # Use sliderReleased for final seek when released
            self.video_slider.sliderReleased.connect(self.on_video_slider_released)
        video_layout.addWidget(self.video_slider)
        
        # Time label
        self.video_time_label = QLabel("0:00 / 0:00")
        self.video_time_label.setMinimumWidth(100)
        self.video_time_label.setStyleSheet(f"font-family: {UI_FONT}; color: #aaa;")
        video_layout.addWidget(self.video_time_label)
        
        # Fullscreen button (AFTER timeline slider)
        self.video_fullscreen_button = QToolButton()
        # Use text instead of icon for consistent color
        self.video_fullscreen_button.setText("⛶")
        self.video_fullscreen_button.setStyleSheet(f"""
            QToolButton {{
                font-size: 14pt;
                color: #808080;
                background: transparent;
                border: none;
                padding-bottom: 2px;
            }}
            QToolButton:hover {{
                color: #aaa;
            }}
        """)
        self.video_fullscreen_button.setToolTip("Fullscreen (F)")
        self.video_fullscreen_button.setFixedSize(28, 28)
        self.video_fullscreen_button.clicked.connect(self.toggle_video_fullscreen)
        video_layout.addWidget(self.video_fullscreen_button)


        
        self.preview_layout.addWidget(self.video_playback)
        self.video_playback.hide()
        
        # Connect media player signals
        if has_qt_multimedia:
            if PYSIDE_VERSION == 6:
                self.media_player.positionChanged.connect(self.on_video_position_changed)
                self.media_player.durationChanged.connect(self.on_video_duration_changed)
                self.media_player.playbackStateChanged.connect(self.on_video_state_changed)
            else:
                self.media_player.positionChanged.connect(self.on_video_position_changed)
                self.media_player.durationChanged.connect(self.on_video_duration_changed)
                self.media_player.stateChanged.connect(self.on_video_state_changed)
        
        # Video slider state (prevent feedback loop)
        self.video_slider_updating = False
        
        # Text file preview controls (only visible for text files)
        self.text_controls = QWidget()
        text_controls_layout = QHBoxLayout(self.text_controls)
        text_controls_layout.setContentsMargins(5, 2, 5, 2)
        text_controls_layout.setSpacing(5)
        
        # Line wrap toggle
        self.line_wrap_checkbox = QCheckBox("Wrap Lines")
        self.line_wrap_checkbox.setChecked(True)  # Default: wrap on
        self.line_wrap_checkbox.toggled.connect(self.on_line_wrap_changed)
        text_controls_layout.addWidget(self.line_wrap_checkbox)
        
        text_controls_layout.addWidget(QLabel("Font Size:"))
        
        # Font size slider (6-20pt)
        self.font_size_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.font_size_slider.setMinimum(6)
        self.font_size_slider.setMaximum(20)
        self.font_size_slider.setValue(9)  # Default 9pt
        self.font_size_slider.setMaximumWidth(100)
        self.font_size_slider.valueChanged.connect(self.on_font_size_changed)
        text_controls_layout.addWidget(self.font_size_slider)
        
        # Font size label
        self.font_size_label = QLabel("9")
        self.font_size_label.setMinimumWidth(20)
        self.font_size_label.setStyleSheet("color: #aaa;")
        text_controls_layout.addWidget(self.font_size_label)
        
        text_controls_layout.addStretch()
        
        # Load Full File button (toggle)
        self.load_full_btn = QPushButton("📄 Load Full")
        self.load_full_btn.setMaximumWidth(90)
        self.load_full_btn.setCheckable(True)
        self.load_full_btn.setToolTip("Load full file content (may be slow for large files)")
        self.load_full_btn.clicked.connect(self.toggle_load_full_file)
        text_controls_layout.addWidget(self.load_full_btn)
        
        # Copy to clipboard button
        self.copy_text_btn = QPushButton("📋 Copy")
        self.copy_text_btn.setMaximumWidth(70)
        self.copy_text_btn.setToolTip("Copy text to clipboard")
        self.copy_text_btn.clicked.connect(self.copy_text_to_clipboard)
        text_controls_layout.addWidget(self.copy_text_btn)
        
        self.preview_layout.addWidget(self.text_controls)
        self.text_controls.hide()  # Hidden by default, shown only for text files
        
        # Store current text content for controls
        self.current_text_content = None
        self.current_text_item = None
        self.current_text_asset = None  # Store current asset for reload
        self.is_full_text_loaded = False  # Track if full file is loaded
        
        # Add preview container to splitter
        self.preview_splitter.addWidget(preview_container)
        
        # === PDF Navigation Overlay (modern, floating controls) ===
        # Previous page button (left overlay)
        self.pdf_prev_overlay = QPushButton("◀")
        self.pdf_prev_overlay.setParent(self.graphics_view)
        self.pdf_prev_overlay.setFixedSize(50, 80)
        self.pdf_prev_overlay.setToolTip("Previous Page (Left Arrow)")
        self.pdf_prev_overlay.setCursor(Qt.PointingHandCursor)
        self.pdf_prev_overlay.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(0, 0, 0, 120);
                border: 1px solid rgba(255, 255, 255, 50);
                border-radius: 5px;
                color: white;
                font-size: 24px;
                font-family: {UI_FONT};
            }}
            QPushButton:hover {{
                background-color: rgba(0, 120, 215, 180);
                border-color: rgba(255, 255, 255, 120);
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 120, 215, 220);
            }}
            QPushButton:disabled {{
                background-color: rgba(0, 0, 0, 60);
                color: rgba(255, 255, 255, 80);
            }}
        """)
        self.pdf_prev_overlay.clicked.connect(self.pdf_previous_page)
        self.pdf_prev_overlay.hide()
        
        # Next page button (right overlay)
        self.pdf_next_overlay = QPushButton("▶")
        self.pdf_next_overlay.setParent(self.graphics_view)
        self.pdf_next_overlay.setFixedSize(50, 80)
        self.pdf_next_overlay.setToolTip("Next Page (Right Arrow)")
        self.pdf_next_overlay.setCursor(Qt.PointingHandCursor)
        self.pdf_next_overlay.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(0, 0, 0, 120);
                border: 1px solid rgba(255, 255, 255, 50);
                border-radius: 5px;
                color: white;
                font-size: 24px;
                font-family: {UI_FONT};
            }}
            QPushButton:hover {{
                background-color: rgba(0, 120, 215, 180);
                border-color: rgba(255, 255, 255, 120);
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 120, 215, 220);
            }}
            QPushButton:disabled {{
                background-color: rgba(0, 0, 0, 60);
                color: rgba(255, 255, 255, 80);
            }}
        """)
        self.pdf_next_overlay.clicked.connect(self.pdf_next_page)
        self.pdf_next_overlay.hide()
        
        # Page indicator overlay (bottom center)
        self.pdf_page_overlay = QLabel("1 / 1")
        self.pdf_page_overlay.setParent(self.graphics_view)
        self.pdf_page_overlay.setAlignment(Qt.AlignCenter)
        self.pdf_page_overlay.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(0, 0, 0, 150);
                border: 1px solid rgba(255, 255, 255, 80);
                border-radius: 12px;
                color: white;
                font-size: 13px;
                font-family: {UI_FONT};
                font-weight: bold;
                padding: 6px 16px;
            }}
        """)
        self.pdf_page_overlay.hide()
        
        # Tab widget for Metadata and Tags (same style as other tabs in the app)
        self.info_tabs = QtWidgets.QTabWidget()
        self.info_tabs.setMovable(True)  # Enable drag & drop tab reordering like other tabs
        
        # Metadata tab
        metadata_tab = QWidget()
        metadata_tab_layout = QVBoxLayout(metadata_tab)
        metadata_tab_layout.setContentsMargins(0, 0, 0, 0)
        metadata_tab_layout.setSpacing(0)
        
        metadata_scroll = QScrollArea()
        metadata_scroll.setWidgetResizable(True)
        metadata_scroll.setMinimumHeight(80)  # Reduced from 250 to 80 for compact view
        metadata_scroll.setMaximumHeight(400)
        metadata_scroll.setStyleSheet("QScrollArea { border: none; background-color: #2a2a2a; }")
        
        metadata_widget = QWidget()
        self.metadata_layout = QVBoxLayout(metadata_widget)
        self.metadata_layout.setAlignment(Qt.AlignTop)
        self.metadata_layout.setSpacing(3)  # Reduced from 8 to 3
        self.metadata_layout.setContentsMargins(5, 5, 5, 5)
        metadata_scroll.setWidget(metadata_widget)
        
        metadata_tab_layout.addWidget(metadata_scroll)
        self.info_tabs.addTab(metadata_tab, "Metadata")
        
        # Tags tab
        tags_tab = QWidget()
        tags_tab_layout = QVBoxLayout(tags_tab)
        tags_tab_layout.setContentsMargins(5, 5, 5, 5)
        tags_tab_layout.setSpacing(5)
        
        # Tag input area
        tag_input_layout = QHBoxLayout()
        tag_input_layout.setSpacing(5)
        
        self.tag_input = QtWidgets.QLineEdit()
        self.tag_input.setPlaceholderText("Add tag...")
        self.tag_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
                font-family: {UI_FONT};
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border-color: #4b7daa;
            }}
        """)
        self.tag_input.returnPressed.connect(self.add_tag)
        tag_input_layout.addWidget(self.tag_input)
        
        # Setup autocomplete for tag input
        self.setup_tag_autocomplete()
        
        self.add_tag_btn = QPushButton("+ Add")
        self.add_tag_btn.setMaximumWidth(60)
        self.add_tag_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #4b7daa;
                border: none;
                border-radius: 3px;
                padding: 5px;
                color: white;
                font-family: {UI_FONT};
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #5a8db8;
            }}
            QPushButton:pressed {{
                background-color: #3a6d9a;
            }}
        """)
        self.add_tag_btn.clicked.connect(self.add_tag)
        tag_input_layout.addWidget(self.add_tag_btn)
        
        # Browse Tags button
        self.browse_tags_btn = QPushButton("📚 Browse")
        self.browse_tags_btn.setMaximumWidth(80)
        self.browse_tags_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                color: #cccccc;
                font-family: {UI_FONT};
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #4a4a4a;
                border-color: #666;
            }}
            QPushButton:pressed {{
                background-color: #2a2a2a;
            }}
        """)
        self.browse_tags_btn.clicked.connect(self.show_browse_tags_dialog)
        self.browse_tags_btn.setToolTip("Browse all available tags by category")
        tag_input_layout.addWidget(self.browse_tags_btn)
        
        # Clear All Tags button
        self.clear_all_tags_btn = QPushButton("🗑️ Clear All")
        self.clear_all_tags_btn.setMaximumWidth(80)
        self.clear_all_tags_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                color: #cccccc;
                font-family: {UI_FONT};
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #8B0000;
                border-color: #A00000;
                color: white;
            }}
            QPushButton:pressed {{
                background-color: #6B0000;
            }}
        """)
        self.clear_all_tags_btn.clicked.connect(self.clear_all_tags_from_selection)
        self.clear_all_tags_btn.setToolTip("Remove all tags from selected file(s)")
        tag_input_layout.addWidget(self.clear_all_tags_btn)
        
        tags_tab_layout.addLayout(tag_input_layout)
        
        # Tags display area (scrollable)
        tags_scroll = QScrollArea()
        tags_scroll.setWidgetResizable(True)
        tags_scroll.setStyleSheet("QScrollArea { border: none; background-color: #2a2a2a; }")
        
        self.tags_container = QWidget()  # Store as instance variable for later access
        self.tags_layout = FlowLayout()  # Flow layout for tag chips
        self.tags_layout.setSpacing(5)
        self.tags_layout.setContentsMargins(0, 5, 0, 5)
        self.tags_container.setLayout(self.tags_layout)
        tags_scroll.setWidget(self.tags_container)
        
        tags_tab_layout.addWidget(tags_scroll)
        
        # Tag info label
        self.tag_info_label = QLabel("No tags yet. Add tags to organize your assets.")
        self.tag_info_label.setStyleSheet(f"color: #888; font-size: 10px; font-family: {UI_FONT}; padding: 5px;")
        self.tag_info_label.setAlignment(Qt.AlignCenter)
        self.tag_info_label.setWordWrap(True)
        tags_tab_layout.addWidget(self.tag_info_label)
        
        self.info_tabs.addTab(tags_tab, "Tags")
        
        # Set minimum height for info tabs (similar to Collections/Advanced Filters tabs)
        self.info_tabs.setMinimumHeight(120)
        
        # Add info tabs to splitter
        self.preview_splitter.addWidget(self.info_tabs)
        
        # Restore splitter position from config or set default
        if self.config and "preview_splitter_position" in self.config.config:
            try:
                from base64 import b64decode
                state_str = self.config.config["preview_splitter_position"]
                state_bytes = QtCore.QByteArray.fromBase64(state_str.encode())
                self.preview_splitter.restoreState(state_bytes)
            except:
                # If restore fails, use default sizes
                self.preview_splitter.setSizes([600, 400])
        else:
            # Set initial splitter sizes (60% preview, 40% info)
            self.preview_splitter.setSizes([600, 400])
        
        # Connect signal to save position when moved
        if self.config:
            self.preview_splitter.splitterMoved.connect(self.on_preview_splitter_moved)
        
        # Add splitter to main layout
        layout.addWidget(self.preview_splitter)
        
        # Show empty state
        self.show_empty_state()
    
    def resizeEvent(self, event):
        """Handle resize - refit image to new panel width and reposition PDF overlays"""
        super().resizeEvent(event)
        
        # Only resize if NOT in zoom mode
        if not self.zoom_mode and self.current_pixmap and not self.current_pixmap.isNull():
            self.fit_pixmap_to_label()
        
        # Update PDF overlay positions
        self.update_pdf_overlay_positions()
        
        # Update text wrap width on resize
        if self.current_text_item and self.line_wrap_checkbox.isChecked():
            try:
                viewport_width = self.graphics_view.viewport().width() - 20
                self.current_text_item.setTextWidth(viewport_width)
                
                # Update scene rect to fit new text bounds (without processEvents)
                text_rect = self.current_text_item.boundingRect()
                padded_rect = text_rect.adjusted(-10, -10, 10, 100)
                self.graphics_scene.setSceneRect(padded_rect)
            except RuntimeError:
                # Object was already deleted, reset reference
                self.current_text_item = None
    
    def fit_pixmap_to_label(self):
        """Fit current pixmap to view"""
        if not self.current_pixmap or self.current_pixmap.isNull():
            return
        
        # In zoom mode, update the zoom pixmap instead of fitting
        if self.zoom_mode:
            self.full_res_pixmap = self.current_pixmap
            self.set_preview_pixmap(self.full_res_pixmap)
            # Don't reset zoom/pan - maintain current view
            return
        
        self.set_preview_pixmap(self.current_pixmap)
        self.fit_preview_to_view()
    
    def update_pdf_overlay_positions(self):
        """Update PDF overlay button positions (called on resize)"""
        if not self.is_showing_pdf:
            return
        
        view_width = self.graphics_view.width()
        view_height = self.graphics_view.height()
        
        # Previous button - left side, vertically centered
        self.pdf_prev_overlay.move(10, (view_height - self.pdf_prev_overlay.height()) // 2)
        
        # Next button - right side, vertically centered
        self.pdf_next_overlay.move(
            view_width - self.pdf_next_overlay.width() - 10,
            (view_height - self.pdf_next_overlay.height()) // 2
        )
        
        # Page indicator - bottom center
        self.pdf_page_overlay.adjustSize()  # Adjust to text size
        self.pdf_page_overlay.move(
            (view_width - self.pdf_page_overlay.width()) // 2,
            view_height - self.pdf_page_overlay.height() - 15
        )
    
    def show_empty_state(self):
        """Show empty state when no file is selected"""
        self.title_label.setText("Preview")
        self.set_preview_pixmap(None)
        self.current_image_path = None
        self.current_hdr_path = None
        self.exit_zoom_mode()  # Exit zoom mode when deselecting
        self.clear_metadata()
        self.exposure_controls.hide()  # Hide exposure controls
        self.text_controls.hide()  # Hide text controls
        self.video_playback.hide()  # Hide video controls
        
        # Stop video playback and hide video widget
        if self.media_player:
            self.media_player.stop()
            if PYSIDE_VERSION == 6:
                from PySide6.QtCore import QUrl
                self.media_player.setSource(QUrl())  # Clear source
            else:
                from PySide2.QtMultimedia import QMediaContent
                self.media_player.setMedia(QMediaContent())  # Clear media
            # Reset button icon
            self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.video_widget.hide()
        self.graphics_view.show()  # Show graphics view again
        
        # Clear EXR channel info
        self.current_exr_file_path = None
        self.current_exr_channels = []
        self.current_exr_channel = None
        
        # Hide PDF overlay controls
        self.pdf_prev_overlay.hide()
        self.pdf_next_overlay.hide()
        self.pdf_page_overlay.hide()
        
        self.is_showing_text = False  # Reset text mode flag
        self.is_showing_pdf = False  # Reset PDF mode flag
        self.graphics_view.viewport().setCursor(Qt.ArrowCursor)  # Reset cursor
        
        # Reset text preview state
        self.is_full_text_loaded = False
        if hasattr(self, 'load_full_btn'):
            self.load_full_btn.setChecked(False)
            self.load_full_btn.setText("📄 Load Full")
    
    def on_exposure_slider_pressed(self):
        """User started dragging the exposure slider"""
        self.is_dragging_exposure = True
    
    def on_exposure_slider_released(self):
        """User released the exposure slider - apply exposure at full quality"""
        self.is_dragging_exposure = False
        # Apply exposure immediately at FULL quality when slider is released
        if self.pending_exposure_value is not None:
            self.exposure_timer.stop()  # Cancel any pending timer
            # Use apply_exposure_change (full quality) instead of fast path
            self.apply_exposure_change()
    
    def on_exposure_changed(self, value):
        """Handle exposure slider change - update preview while dragging"""
        exposure_stops = value / 10.0  # Slider -50 to +50 -> -5.0 to +5.0 stops
        
        # Format label with +/- sign (like Arnold) - update immediately
        if exposure_stops >= 0:
            self.exposure_label.setText(f"+{exposure_stops:.1f}")
        else:
            self.exposure_label.setText(f"{exposure_stops:.1f}")
        
        # Store pending value
        self.pending_exposure_value = exposure_stops
        
        # If dragging, apply exposure immediately (fast path from cache)
        if self.is_dragging_exposure:
            # Apply directly without timer for smooth dragging
            self.hdr_exposure = exposure_stops
            self._apply_exposure_fast()
        else:
            # Not dragging (programmatic change or click) - use debounce timer
            self.exposure_timer.stop()
            self.exposure_timer.start()
    
    def _apply_exposure_fast(self):
        """Fast exposure application during drag (no debounce) with lower quality"""
        exposure_stops = self.hdr_exposure
        
        # Use lower resolution during drag for performance (like Nuke/Resolve)
        # Target max 512px on longest side for fast dragging
        # Even in zoom mode, we can downsample because set_preview_pixmap preserves transform
        drag_max_size = 512
        
        # Check if we're viewing a specific EXR channel
        if self.current_exr_file_path and self.current_exr_channel:
            # Channel-specific raw data cache
            raw_cache_key = f"{self.current_exr_file_path}#{self.current_exr_channel}#raw"
            if raw_cache_key in self.hdr_raw_cache:
                rgb_raw, width, height, resolution_str = self.hdr_raw_cache[raw_cache_key]
                
                # Downsample for faster tone mapping during drag
                import cv2
                import numpy as np
                
                # Calculate scale to fit within drag_max_size
                scale = min(drag_max_size / width, drag_max_size / height)
                if scale < 1.0:  # Only downsample if needed
                    drag_width = max(1, int(width * scale))
                    drag_height = max(1, int(height * scale))
                    rgb_drag = cv2.resize(rgb_raw, (drag_width, drag_height), interpolation=cv2.INTER_LINEAR)
                else:
                    # Already small enough
                    drag_width, drag_height = width, height
                    rgb_drag = rgb_raw
                
                pixmap = self.apply_hdr_tone_mapping(rgb_drag, drag_width, drag_height, exposure_stops, file_path=self.current_exr_file_path)
                if pixmap:
                    self.current_pixmap = pixmap
                    self.fit_pixmap_to_label()
                return
        
        # Standard HDR/EXR
        if self.current_hdr_path and self.current_hdr_path in self.hdr_raw_cache:
            rgb_raw, width, height, resolution_str = self.hdr_raw_cache[self.current_hdr_path]
            
            # Downsample for faster tone mapping during drag
            import cv2
            import numpy as np
            
            # Calculate scale to fit within drag_max_size
            scale = min(drag_max_size / width, drag_max_size / height)
            if scale < 1.0:  # Only downsample if needed
                drag_width = max(1, int(width * scale))
                drag_height = max(1, int(height * scale))
                rgb_drag = cv2.resize(rgb_raw, (drag_width, drag_height), interpolation=cv2.INTER_LINEAR)
            else:
                # Already small enough
                drag_width, drag_height = width, height
                rgb_drag = rgb_raw
            
            pixmap = self.apply_hdr_tone_mapping(rgb_drag, drag_width, drag_height, exposure_stops, file_path=self.current_hdr_path)
            if pixmap:
                self.current_pixmap = pixmap
                self.fit_pixmap_to_label()
    
    def apply_exposure_change(self):
        """Actually apply the exposure change (called after debounce timer)"""
        if self.pending_exposure_value is None:
            return
        
        exposure_stops = self.pending_exposure_value
        self.hdr_exposure = exposure_stops
        
        # Check if we're viewing a specific EXR channel
        if self.current_exr_file_path and self.current_exr_channel:
            # Channel-specific raw data cache
            raw_cache_key = f"{self.current_exr_file_path}#{self.current_exr_channel}#raw"
            if raw_cache_key in self.hdr_raw_cache:
                print(f"🚀 FAST: Adjusting exposure for channel '{self.current_exr_channel}' (cached raw data)")
                rgb_raw, width, height, resolution_str = self.hdr_raw_cache[raw_cache_key]
                
                # Apply tone mapping with new exposure
                pixmap = self.apply_hdr_tone_mapping(rgb_raw, width, height, exposure_stops, file_path=self.current_exr_file_path)
                
                if pixmap:
                    self.current_pixmap = pixmap
                    # Update title to show channel + exposure
                    filename = Path(self.current_exr_file_path).name
                    self.title_label.setText(f"Preview - {filename} [{self.current_exr_channel}]")
                    # Update preview
                    self.fit_pixmap_to_label()
                return
        
        # Fast re-tone map from cached raw data if available (standard HDR/EXR)
        if self.current_hdr_path and self.current_hdr_path in self.hdr_raw_cache:
            # print(f"🚀 FAST PATH: Using cached raw data for exposure adjustment")
            rgb_raw, width, height, resolution_str = self.hdr_raw_cache[self.current_hdr_path]
            
            # Apply tone mapping with new exposure (FAST - no disk I/O!) with ACES support
            pixmap = self.apply_hdr_tone_mapping(rgb_raw, width, height, exposure_stops, file_path=self.current_hdr_path)
            
            if pixmap:
                self.current_pixmap = pixmap
                # Update preview cache too
                self.add_to_cache(self.current_hdr_path, pixmap, resolution_str)
                self.fit_pixmap_to_label()
        elif self.current_hdr_path:
            # print(f"⚠️ SLOW PATH: Raw data not cached, reloading from disk...")
            # Fallback: raw data not cached - reload from disk (slower)
            # Remove from preview cache to force reload
            if self.current_hdr_path in self.preview_cache:
                del self.preview_cache[self.current_hdr_path]
            
            # Reload with new exposure (use max_preview_size setting)
            pixmap, resolution_str = load_hdr_exr_image(self.current_hdr_path, max_size=self.max_preview_size, exposure=exposure_stops)
            
            if pixmap:
                self.current_pixmap = pixmap
                self.add_to_cache(self.current_hdr_path, pixmap, resolution_str)
                self.fit_pixmap_to_label()
    
    def apply_hdr_tone_mapping(self, rgb_raw, width, height, exposure_stops, file_path=None):
        """Apply tone mapping to raw HDR data - FAST (no disk I/O)
        
        Args:
            rgb_raw: Raw float RGB data
            width: Image width
            height: Image height
            exposure_stops: Exposure adjustment in stops
            file_path: Optional file path for tag-based color management
        """
        if not NUMPY_AVAILABLE:
            return None
        
        try:
            # Check if this is an EXR file and if we should use ACES color management
            use_aces = False
            if file_path and file_path.lower().endswith('.exr') and self.metadata_manager:
                # Check for colorspace/view transform tags
                try:
                    file_metadata = self.metadata_manager.get_file_metadata(str(file_path))
                    file_tags = file_metadata.get('tags', [])
                    tag_names = [tag['name'] for tag in file_tags]
                    tag_names_lower = [name.lower() for name in tag_names]  # Case-insensitive comparison
                    
                    # Check for ACEScg tag or sRGB(ACES) view transform tag (case-insensitive)
                    if "acescg" in tag_names_lower or "srgb(aces)" in tag_names_lower:
                        use_aces = True
                    elif "linearsrgb" in tag_names_lower or "linear srgb" in tag_names_lower or "srgb" in tag_names_lower:
                        use_aces = False
                    else:
                        # No color space tag found - use default
                        use_aces = False
                        
                except Exception as e:
                    use_aces = False
            
            # Apply appropriate view transform
            if use_aces:
                # Import ACES module
                from .aces_color import apply_aces_view_transform
                
                # Apply -1 stop compensation to match Nuke/Maya reference
                # This compensates for the inherent brightness difference in our pipeline
                compensated_exposure = exposure_stops - 1.0
                
                rgb_display = apply_aces_view_transform(rgb_raw, exposure=compensated_exposure)
            else:
                # Standard tone mapping (existing code)
                # Apply exposure compensation in stops
                # Apply -1 stop compensation for consistency with ACES path
                compensated_exposure = exposure_stops - 1.0
                exposure_multiplier = pow(2.0, compensated_exposure)
                rgb = rgb_raw * exposure_multiplier
                
                # ACES Filmic tone mapping
                a = 2.51
                b = 0.03
                c = 2.43
                d = 0.59
                e = 0.14
                rgb_tonemapped = np.clip((rgb * (a * rgb + b)) / (rgb * (c * rgb + d) + e), 0, 1)
                
                # Gamma correction (2.2 for sRGB)
                gamma = 1.0 / 2.2
                rgb_display = np.power(rgb_tonemapped, gamma)
            
            # Convert to 8-bit
            rgb_8bit = (rgb_display * 255).astype(np.uint8)
            
            # Create QImage
            bytes_per_line = width * 3
            q_image = QImage(rgb_8bit.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
            q_image = q_image.copy()
            
            # Convert to QPixmap
            pixmap = QPixmap.fromImage(q_image)
            
            return pixmap
            
        except Exception as e:
            print(f"Tone mapping error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def add_to_hdr_raw_cache(self, file_path, rgb_raw, width, height, resolution_str):
        """Add raw HDR float data to cache with LRU eviction"""
        # If cache is full, remove oldest entry
        if len(self.hdr_raw_cache) >= self.hdr_cache_max_size:
            first_key = next(iter(self.hdr_raw_cache))
            del self.hdr_raw_cache[first_key]
        
        # Add new entry (store a COPY to prevent modification)
        self.hdr_raw_cache[file_path] = (rgb_raw.copy(), width, height, resolution_str)
    
    def show_hdr_placeholder(self, filename):
        """Show placeholder for HDR/EXR files that couldn't be loaded"""
        # Create a simple placeholder pixmap
        placeholder = QPixmap(400, 300)
        placeholder.fill(QColor(60, 60, 60))
        
        # Draw icon and text
        painter = QPainter(placeholder)
        painter.setPen(QColor(180, 180, 180))
        
        # Draw large icon
        font = QFont(UI_FONT, 48)
        painter.setFont(font)
        painter.drawText(placeholder.rect(), Qt.AlignCenter, "🌅")
        
        # Draw filename below
        font = QFont(UI_FONT, 10)
        painter.setFont(font)
        text_rect = placeholder.rect().adjusted(0, 100, 0, 0)
        painter.drawText(text_rect, Qt.AlignCenter, f"HDR/EXR Preview\n\n{filename}\n\nCould not load file")
        
        painter.end()
        
        self.current_pixmap = placeholder
        self.fit_pixmap_to_label()
        
        # Add metadata note
        self.add_metadata_row("⚠️", "Error", "Failed to load HDR/EXR")
        self.add_metadata_row("💡", "Tip", "Check if file is corrupted")
    
    def show_deep_exr_placeholder(self, filename):
        """Show placeholder for Deep EXR files (not supported for preview)"""
        # Create a simple placeholder pixmap
        placeholder = QPixmap(400, 300)
        placeholder.fill(QColor(60, 60, 60))
        
        # Draw icon and text
        painter = QPainter(placeholder)
        painter.setPen(QColor(180, 180, 180))
        
        # Draw large icon
        font = QFont(UI_FONT, 48)
        painter.setFont(font)
        painter.drawText(placeholder.rect(), Qt.AlignCenter, "🔍")
        
        # Draw info text below
        font = QFont(UI_FONT, 10)
        painter.setFont(font)
        text_rect = placeholder.rect().adjusted(20, 100, -20, 0)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, 
                        f"Deep EXR - No Preview\n\n{filename}\n\nDeep images contain multiple samples per pixel\nand are not supported for preview.")
        
        painter.end()
        
        self.current_pixmap = placeholder
        self.fit_pixmap_to_label()
        
        # Add metadata note
        self.add_metadata_row("ℹ️", "Type", "Deep EXR (multi-sample)")
        self.add_metadata_row("⚠️", "Preview", "Not supported")
        self.add_metadata_row("💡", "Info", "Deep data requires specialized tools")
    
    def eventFilter(self, obj, event):
        """Event filter for graphics view and video widget - handles mouse events for zoom/pan and scrubbing"""
        
        # === Fullscreen Widget Events ===
        if hasattr(self, '_fullscreen_widget') and self._fullscreen_widget:
            # Handle events from fullscreen widget or video widget when in fullscreen
            if obj == self._fullscreen_widget or (obj == self.video_widget and self._fullscreen_widget.isVisible()):
                
                # LOG ALL EVENTS for debugging
                event_name = {
                    QEvent.MouseButtonPress: "MouseButtonPress",
                    QEvent.MouseButtonRelease: "MouseButtonRelease",
                    QEvent.MouseMove: "MouseMove",
                    QEvent.KeyPress: "KeyPress",
                }.get(event.type(), f"Event({event.type()})")
                
                if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseMove):
                    mouse_pos = event.position() if hasattr(event, 'position') else event.pos()
                    if obj == self._fullscreen_widget:
                        mouse_y = mouse_pos.y()
                        obj_source = "fullscreen_widget"
                    else:
                        global_pos = self.video_widget.mapToGlobal(mouse_pos.toPoint())
                        local_pos = self._fullscreen_widget.mapFromGlobal(global_pos)
                        mouse_y = local_pos.y()
                        obj_source = "video_widget"
                    
                if event.type() == QEvent.KeyPress:
                    if event.key() == Qt.Key_Escape or event.key() == Qt.Key_F:
                        self.toggle_video_fullscreen()
                        return True
                
                elif event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                    # Check if click is over controls
                    mouse_pos = event.position() if hasattr(event, 'position') else event.pos()
                    if obj == self._fullscreen_widget:
                        mouse_y = mouse_pos.y()
                    else:  # video_widget
                        global_pos = self.video_widget.mapToGlobal(mouse_pos.toPoint())
                        local_pos = self._fullscreen_widget.mapFromGlobal(global_pos)
                        mouse_y = local_pos.y()
                    
                    fullscreen_height = self._fullscreen_widget.height()
                    controls_height = self.video_playback.height()
                    controls_start_y = fullscreen_height - controls_height
                    mouse_over_controls = mouse_y >= controls_start_y
                    
                    if not mouse_over_controls:
                        # Start video scrubbing
                        self.video_dragging = True
                        self.video_drag_start_x = mouse_pos.x()
                        self.video_drag_start_position = self.media_player.position()
                        return True
                    return False
                
                elif event.type() == QEvent.MouseMove:
                    # DON'T trust event coordinates - get REAL cursor position from system
                    real_global_pos = QCursor.pos()
                    real_local_pos = self._fullscreen_widget.mapFromGlobal(real_global_pos)
                    mouse_x = real_local_pos.x()
                    mouse_y = real_local_pos.y()
                    
                    # Also get event coordinates for comparison
                    mouse_pos = event.position() if hasattr(event, 'position') else event.pos()
                    if obj == self._fullscreen_widget:
                        event_x = mouse_pos.x()
                        event_y = mouse_pos.y()
                        obj_source = "fullscreen_widget"
                    else:
                        global_pos = self.video_widget.mapToGlobal(mouse_pos.toPoint())
                        local_pos = self._fullscreen_widget.mapFromGlobal(global_pos)
                        event_x = local_pos.x()
                        event_y = local_pos.y()
                        obj_source = "video_widget"
                    
                    fullscreen_height = self._fullscreen_widget.height()
                    controls_height = self.video_playback.height() if hasattr(self, 'video_playback') else 0
                    controls_start_y = fullscreen_height - controls_height
                    is_over_controls = mouse_y > controls_start_y
                    
                    # Handle video scrubbing if dragging
                    if self.video_dragging:
                        delta_x = mouse_pos.x() - self.video_drag_start_x
                        duration = self.media_player.duration()
                        
                        if duration > 0:
                            # 1 pixel = 100ms movement
                            delta_ms = int(delta_x * 100)
                            new_position = max(0, min(duration, self.video_drag_start_position + delta_ms))
                            
                            # Seek to new position
                            self.media_player.setPosition(new_position)
                            
                            # Update slider manually
                            if hasattr(self, 'video_slider'):
                                self.video_slider_updating = True
                                slider_value = int((new_position / duration) * 1000)
                                self.video_slider.setValue(slider_value)
                                self.video_slider_updating = False
                        # Don't check controls during scrubbing
                        return True
                    
                    # Check if mouse is over video playback controls
                    if hasattr(self, 'video_playback') and self.video_playback and self.video_playback.isVisible():
                        # Already calculated above
                        mouse_over_controls = is_over_controls
                        
                        # Check if state changed (enter/leave controls area)
                        was_over_controls = getattr(self, '_cursor_was_over_controls', False)
                        
                        if mouse_over_controls != was_over_controls:
                            # State changed - ENTER or LEAVE
                            if mouse_over_controls:
                                # Stop hide timer
                                if hasattr(self, '_fullscreen_hide_timer') and self._fullscreen_hide_timer:
                                    self._fullscreen_hide_timer.stop()
                                # Show controls
                                if hasattr(self, '_fullscreen_opacity_effect') and self._fullscreen_opacity_effect:
                                    self._fullscreen_opacity_effect.setOpacity(1.0)
                                    if hasattr(self, 'video_playback') and self.video_playback:
                                        self.video_playback.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                            else:
                                # Start hide timer
                                if hasattr(self, '_fullscreen_hide_timer') and self._fullscreen_hide_timer:
                                    self._fullscreen_hide_timer.stop()
                                    self._fullscreen_hide_timer.start()
                            
                            # Update state
                            self._cursor_was_over_controls = mouse_over_controls
                        else:
                            # No state change but restart timer if cursor moves AWAY from controls
                            if not mouse_over_controls:
                                if hasattr(self, '_fullscreen_hide_timer') and self._fullscreen_hide_timer:
                                    self._fullscreen_hide_timer.stop()
                                    self._fullscreen_hide_timer.start()
                    
                    return False
                
                elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                    # End video scrubbing
                    if self.video_dragging:
                        self.video_dragging = False
                        return True
                    return False
        
        # === Volume Button Right-Click ===
        if (hasattr(self, 'video_volume_button') and obj == self.video_volume_button):
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
                self.show_volume_popup()
                return True
        
        # === Video Widget Drag Scrubbing ===
        # Works both in normal and fullscreen mode
        if (hasattr(self, 'video_widget') and hasattr(self, 'media_player') and 
            obj == self.video_widget and self.media_player):
            event_type = event.type()
            
            if event_type == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                # Check if mouse is over video playback controls in fullscreen mode
                mouse_over_controls = False
                if hasattr(self, '_fullscreen_widget') and self._fullscreen_widget and self._fullscreen_widget.isVisible():
                    if hasattr(self, 'video_playback') and self.video_playback:
                        mouse_pos = event.position() if hasattr(event, 'position') else event.pos()
                        # Convert to global, then to video_playback coordinates
                        global_pos = self.video_widget.mapToGlobal(mouse_pos.toPoint())
                        controls_pos = self.video_playback.mapFromGlobal(global_pos)
                        mouse_over_controls = self.video_playback.rect().contains(controls_pos)
                
                # Only start scrubbing if NOT clicking on controls
                if not mouse_over_controls:
                    # Start drag scrubbing
                    self.video_dragging = True
                    self.video_drag_start_x = event.position().x()
                    self.video_drag_start_position = self.media_player.position()
                    return True
                return False
            
            elif event_type == QEvent.MouseMove and self.video_dragging:
                # Drag scrubbing - move through video
                delta_x = event.position().x() - self.video_drag_start_x
                duration = self.media_player.duration()
                
                if duration > 0:
                    # 1 pixel = 100ms movement
                    delta_ms = int(delta_x * 100)
                    new_position = max(0, min(duration, self.video_drag_start_position + delta_ms))
                    
                    # Seek to new position
                    self.media_player.setPosition(new_position)
                    
                    # Update slider manually (since positionChanged is blocked during drag)
                    if hasattr(self, 'video_slider'):
                        self.video_slider_updating = True
                        slider_value = int((new_position / duration) * 1000)
                        self.video_slider.setValue(slider_value)
                        self.video_slider_updating = False
                return True
            
            elif event_type == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                # End drag scrubbing
                self.video_dragging = False
                return True
        
        # === Graphics View Events ===
        # Only filter events from graphics_view or its viewport
        if not hasattr(self, 'graphics_view') or obj not in (self.graphics_view, self.graphics_view.viewport()):
            return super().eventFilter(obj, event)
        
        event_type = event.type()
        
        # === PDF Navigation with Arrow Keys === DISABLED
        # PDF has its own navigation buttons in the preview panel
        # Arrow keys should be used for file navigation in the browser, not PDF page navigation
        # This was causing conflicts with Quick View activation and file navigation
        # if self.is_showing_pdf and event_type == QEvent.KeyPress:
        #     key = event.key()
        #     if key == Qt.Key_Left:
        #         # Left arrow - previous page
        #         if self.current_pdf_page > 0:
        #             self.pdf_previous_page()
        #         return True
        #     elif key == Qt.Key_Right:
        #         # Right arrow - next page
        #         if self.current_pdf_page < self.current_pdf_page_count - 1:
        #             self.pdf_next_page()
        #         return True
        
        # Handle Ctrl+Wheel for font size adjustment in text mode
        if self.is_showing_text and event_type == QEvent.Wheel:
            modifiers = QtWidgets.QApplication.keyboardModifiers()
            if modifiers == Qt.ControlModifier:
                # Ctrl+Scroll to change font size
                delta = event.angleDelta().y()
                current_size = self.font_size_slider.value()
                
                # Increase or decrease by 1
                if delta > 0:
                    new_size = min(current_size + 1, 20)  # Max 20
                else:
                    new_size = max(current_size - 1, 6)   # Min 6
                
                if new_size != current_size:
                    self.font_size_slider.setValue(new_size)
                
                return True  # Event handled, don't scroll
        
        # In text mode (without Ctrl), let all events pass through for text selection
        if self.is_showing_text:
            return False  # Don't filter, let the default handler work
        
        # Handle image-specific events (zoom mode)
        
        # Double-click - enter/exit zoom mode (works for both single images and sequences)
        if event_type == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            # For sequences, check if we have files
            is_sequence = (self.current_assets and len(self.current_assets) == 1 and 
                          self.current_assets[0].is_sequence and self.current_assets[0].sequence)
            
            if is_sequence and self.current_assets[0].sequence.files:
                # Sequence: use current frame as zoom source
                if not self.zoom_mode:
                    # Cancel any ongoing scrubbing
                    self.is_scrubbing = False
                    self.scrub_start_pos = None
                    
                    current_frame_index = self.sequence_playback.current_frame_index
                    current_frame_path = self.current_assets[0].sequence.files[current_frame_index]
                    self.current_image_path = current_frame_path
                    self.enter_zoom_mode()
                else:
                    self.exit_zoom_mode()
                return True  # Event handled
            elif self.current_image_path and Path(self.current_image_path).exists():
                # Single image
                if not self.zoom_mode:
                    self.enter_zoom_mode()
                else:
                    self.exit_zoom_mode()
                return True  # Event handled
        
        # Mouse wheel - zoom in zoom mode
        if event_type == QEvent.Wheel and self.zoom_mode and self.pixmap_item:
            # Get mouse position in scene coordinates BEFORE zoom
            old_pos = self.graphics_view.mapToScene(event.position().toPoint())
            
            # Calculate zoom factor
            delta = event.angleDelta().y()
            zoom_factor = 1.15 if delta > 0 else 1.0 / 1.15
            
            # Update zoom level
            old_zoom = self.zoom_level
            if delta > 0:
                self.zoom_level = min(self.zoom_level * zoom_factor, 10.0)
            else:
                self.zoom_level = max(self.zoom_level * zoom_factor, 0.1)
            
            # Snap to 100%
            if 0.95 <= self.zoom_level <= 1.05:
                self.zoom_level = 1.0
            
            # Calculate actual zoom factor applied
            actual_factor = self.zoom_level / old_zoom
            
            # Apply zoom using view transform
            self.graphics_view.scale(actual_factor, actual_factor)
            
            # Get mouse position in scene coordinates AFTER zoom
            new_pos = self.graphics_view.mapToScene(event.position().toPoint())
            
            # Calculate offset to keep point under cursor
            delta_pos = new_pos - old_pos
            
            # Translate view to compensate
            self.graphics_view.translate(delta_pos.x(), delta_pos.y())
            
            # Update zoom label
            self._update_zoom_label()
            
            return True  # Event handled
        
        # Right-click - show background context menu
        if event_type == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
            self.show_background_menu(event.globalPos() if hasattr(event, 'globalPos') else event.globalPosition().toPoint())
            return True  # Event handled
        
        # === SEQUENCE SCRUBBING (LMB drag) ===
        # Check if we're viewing a sequence
        is_sequence = (self.current_assets and len(self.current_assets) == 1 and 
                      self.current_assets[0].is_sequence and self.current_assets[0].sequence)
        
        # Scrubbing: LMB drag (works in both normal and zoom mode)
        if is_sequence:
            # Mouse press - start scrubbing (LMB)
            if event_type == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                try:
                    self.scrub_start_pos = event.globalPosition().toPoint()
                except AttributeError:
                    self.scrub_start_pos = event.globalPos()
                
                self.scrub_start_frame = self.sequence_playback.current_frame_index
                self.is_scrubbing = True
                
                # Pause playback while scrubbing
                if self.sequence_playback.is_playing:
                    self.sequence_playback.pause()
                
                self.graphics_view.setCursor(Qt.SizeHorCursor)
                return True  # Event handled
            
            # Mouse move - scrub through frames
            if event_type == QEvent.MouseMove and self.is_scrubbing and self.scrub_start_pos is not None:
                try:
                    current_pos = event.globalPosition().toPoint()
                except AttributeError:
                    current_pos = event.globalPos()
                
                # Calculate horizontal offset in pixels (relative to start)
                delta_x = current_pos.x() - self.scrub_start_pos.x()
                
                # Get viewport width and frame count
                viewport_width = self.graphics_view.viewport().width()
                sequence = self.current_assets[0].sequence
                frame_count = len(sequence.files)
                
                # Map viewport width to frame range
                # If you drag the full viewport width, you go through all frames
                frame_offset = int((delta_x / viewport_width) * frame_count)
                
                # Calculate new frame index (relative to start frame)
                new_frame_index = self.scrub_start_frame + frame_offset
                new_frame_index = max(0, min(new_frame_index, frame_count - 1))
                
                # Update frame if changed
                if new_frame_index != self.sequence_playback.current_frame_index:
                    self.sequence_playback.timeline_slider.setValue(new_frame_index)
                
                return True  # Event handled
            
            # Mouse release - stop scrubbing (LMB)
            if event_type == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton and self.is_scrubbing:
                    
                    self.is_scrubbing = False
                    self.scrub_start_pos = None
                    self.graphics_view.setCursor(Qt.ArrowCursor)
                    
                    # No cache recalculation needed (cache system removed)
                    
                    return True  # Event handled
        
        # Mouse press - start panning in zoom mode (MMB)
        if event_type == QEvent.MouseButtonPress and self.zoom_mode and event.button() == Qt.MiddleButton:
            try:
                self.last_mouse_pos = event.globalPosition().toPoint()
            except AttributeError:
                self.last_mouse_pos = event.globalPos()
            
            self.graphics_view.setCursor(Qt.ClosedHandCursor)
            return True  # Event handled
        
        # Mouse move - pan in zoom mode
        if event_type == QEvent.MouseMove and self.zoom_mode and self.last_mouse_pos is not None:
            try:
                current_pos = event.globalPosition().toPoint()
            except AttributeError:
                current_pos = event.globalPos()
            
            delta = current_pos - self.last_mouse_pos
            self.last_mouse_pos = current_pos
            
            # Scroll the graphics view
            h_bar = self.graphics_view.horizontalScrollBar()
            v_bar = self.graphics_view.verticalScrollBar()
            
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            
            return True  # Event handled
        
        # Mouse release - stop panning (MMB)
        if event_type == QEvent.MouseButtonRelease and self.zoom_mode and event.button() == Qt.MiddleButton:
            self.last_mouse_pos = None
            self.graphics_view.setCursor(Qt.OpenHandCursor)
            return True  # Event handled
        
        # Don't filter other events
        return False
    
    def enter_zoom_mode(self):
        """Enter zoom mode - load full resolution image or PDF"""
        if not self.current_image_path:
            return
        
        try:
            file_path_str = str(self.current_image_path)
            file_ext = file_path_str.lower()
            
            # === EXR CHANNEL ZOOM ===
            if file_ext.endswith('.exr') and self.current_exr_file_path and self.current_exr_channel:
                # Use cached raw channel data
                raw_cache_key = f"{self.current_exr_file_path}#{self.current_exr_channel}#raw"
                
                if raw_cache_key in self.hdr_raw_cache:
                    rgb, width, height, resolution_str = self.hdr_raw_cache[raw_cache_key]
                    print(f"🔍 Entering zoom mode for EXR channel '{self.current_exr_channel}' ({width}×{height})")
                    
                    # Apply tone mapping with current exposure
                    pixmap = self.apply_hdr_tone_mapping(rgb, width, height, self.hdr_exposure, file_path=self.current_exr_file_path)
                    
                    if pixmap and not pixmap.isNull():
                        self.full_res_pixmap = pixmap
                    else:
                        print("❌ Failed to create zoom pixmap from EXR channel")
                        return
                else:
                    print(f"⚠️ No cached raw data for EXR channel '{self.current_exr_channel}'")
                    return
            
            # === HDR ZOOM ===
            elif file_ext.endswith('.hdr') and file_path_str in self.hdr_raw_cache:
                # Use cached raw HDR data
                rgb, width, height, resolution_str = self.hdr_raw_cache[file_path_str]
                print(f"🔍 Entering zoom mode for HDR ({width}×{height})")
                
                # Apply tone mapping with current exposure
                pixmap = self.apply_hdr_tone_mapping(rgb, width, height, self.hdr_exposure, file_path=file_path_str)
                
                if pixmap and not pixmap.isNull():
                    self.full_res_pixmap = pixmap
                else:
                    print("❌ Failed to create zoom pixmap from HDR")
                    return
            
            # === PDF ZOOM ===
            elif file_ext.endswith('.pdf') and PYMUPDF_AVAILABLE:
                # Load current PDF page at FULL resolution (max 4096 for quality)
                pixmap, page_count, resolution = load_pdf_page(
                    self.current_pdf_path,
                    self.current_pdf_page,
                    max_size=4096  # High quality zoom
                )
                
                if pixmap and not pixmap.isNull():
                    self.full_res_pixmap = pixmap
                else:
                    print("Failed to load high-res PDF page")
                    return
            
            # === RenderMan .tx files with OpenImageIO ===
            elif file_ext.endswith('.tx'):
                try:
                    from .widgets import load_oiio_image
                    # Load full resolution (mip_level=0) for zoom mode
                    pixmap, resolution, metadata = load_oiio_image(
                        file_path_str,
                        max_size=4096,  # High quality zoom
                        mip_level=0,
                        exposure=0.0,
                        metadata_manager=self.metadata_manager
                    )
                    
                    if pixmap and not pixmap.isNull():
                        self.full_res_pixmap = pixmap
                        # Store metadata for info display
                        if metadata:
                            self.original_image_size = (metadata['width'], metadata['height'])
                    else:
                        raise Exception("OIIO loader returned null pixmap")
                        
                except Exception as e:
                    # Fallback to Qt
                    self.full_res_pixmap = QPixmap(file_path_str)
            
            # === TIFF with OpenCV ===
            elif (file_ext.endswith('.tif') or file_ext.endswith('.tiff')) and OPENCV_AVAILABLE and NUMPY_AVAILABLE:
                try:
                    import cv2
                    import numpy as np
                    
                    # Read FULL resolution image with OpenCV
                    img = cv2.imread(file_path_str, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)
                    
                    if img is not None:
                        # Normalize bit depth FIRST (before color conversion!)
                        if img.dtype == np.uint16:
                            img = (img / 256).astype(np.uint8)
                        elif img.dtype == np.float32 or img.dtype == np.float64:
                            img = np.clip(img, 0, 1)
                            img = (img * 255).astype(np.uint8)
                        
                        # NOW convert to RGB (after normalization)
                        if len(img.shape) == 2:
                            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                        elif len(img.shape) == 3 and img.shape[2] == 4:
                            img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
                        elif len(img.shape) == 3 and img.shape[2] == 3:
                            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        
                        # Convert to QPixmap
                        height, width, channels = img.shape
                        bytes_per_line = width * channels
                        q_image = QImage(img.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                        self.full_res_pixmap = QPixmap.fromImage(q_image.copy())
                    else:
                        raise Exception("OpenCV could not load TIFF")
                        
                except Exception as e:
                    # Fallback to standard QPixmap loading
                    self.full_res_pixmap = QPixmap(file_path_str)
            
            # === Standard images (JPG, PNG, etc.) ===
            else:
                # For PSD files, use psd-tools (NOT PIL - color issues)
                # For TGA files, use PIL
                if file_path_str.lower().endswith('.psd'):
                    # Check if we already have the PSD loaded in cache (from preview)
                    # If yes, just use it (don't reload!)
                    if file_path_str in self.preview_cache:
                        print(f"[Preview-ZOOM] Using cached PSD (no reload needed)")
                        cached_data = self.preview_cache[file_path_str]
                        # Cache stores tuple: (pixmap, resolution_str)
                        self.full_res_pixmap = cached_data[0]
                        # Parse resolution from cached string
                        resolution_parts = cached_data[1].split(' x ')
                        if len(resolution_parts) == 2:
                            self.original_image_size = (int(resolution_parts[0]), int(resolution_parts[1]))
                        self.is_image_scaled = False
                        self.scaled_image_size = None
                    else:
                        # Not in cache, load it now
                        try:
                            print(f"[Preview-ZOOM] Loading PSD with psd-tools composite (max 8K)...")
                            from .cache import ThumbnailGenerator
                            
                            # Load full composite up to 8K resolution
                            composite_pixmap = ThumbnailGenerator._load_psd_composite(Path(file_path_str), max_size=8192)
                            
                            if composite_pixmap and not composite_pixmap.isNull():
                                print(f"[Preview-ZOOM] ✓ PSD composite: {composite_pixmap.width()}x{composite_pixmap.height()}")
                                self.full_res_pixmap = composite_pixmap
                                self.original_image_size = (composite_pixmap.width(), composite_pixmap.height())
                                self.is_image_scaled = False
                                self.scaled_image_size = None
                            else:
                                print(f"[Preview-ZOOM] ✗ PSD composite loading failed")
                                self.full_res_pixmap = None
                        except Exception as e:
                            print(f"[Preview-ZOOM] PSD loading exception: {e}")
                            self.full_res_pixmap = None
                elif file_path_str.lower().endswith('.tga'):
                    # TGA files - use PIL
                    try:
                        import sys
                        import os
                        external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
                        if external_libs not in sys.path:
                            sys.path.insert(0, external_libs)
                        
                        from PIL import Image
                        # Disable decompression bomb warning for large images
                        Image.MAX_IMAGE_PIXELS = None
                        print(f"[Preview-ZOOM] Loading TGA with PIL: {file_path_str}")
                        pil_image = Image.open(file_path_str)
                        print(f"[Preview-ZOOM] PIL opened: mode={pil_image.mode}, size={pil_image.size}")
                        
                        # Convert to RGB
                        if pil_image.mode not in ('RGB', 'L'):
                            pil_image = pil_image.convert('RGB')
                        elif pil_image.mode == 'L':
                            pil_image = pil_image.convert('RGB')
                        
                        # Store original size
                        self.original_image_size = (pil_image.width, pil_image.height)
                        
                        # Scale down if too large for Preview (8K limit)
                        max_dimension = 8192
                        if pil_image.width > max_dimension or pil_image.height > max_dimension:
                            scale_factor = max_dimension / max(pil_image.width, pil_image.height)
                            new_width = int(pil_image.width * scale_factor)
                            new_height = int(pil_image.height * scale_factor)
                            pil_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                            
                            # Store scaling info
                            self.is_image_scaled = True
                            self.scaled_image_size = (new_width, new_height)
                        else:
                            self.is_image_scaled = False
                            self.scaled_image_size = None
                        
                        # Convert PIL to QPixmap
                        import numpy as np
                        img_array = np.array(pil_image)
                        height, width = img_array.shape[:2]
                        
                        # PIL RGB → Qt needs BGR byte order for Format_RGB888
                        # OR use BGRA → Format_ARGB32 (more reliable on Windows)
                        if img_array.shape[2] == 3:
                            # Add alpha channel for consistent BGRA handling
                            img_bgra = np.dstack([img_array[:, :, 2], img_array[:, :, 1], img_array[:, :, 0], np.full((height, width), 255, dtype=np.uint8)])
                            bytes_per_line = width * 4
                            q_image = QImage(img_bgra.tobytes(), width, height, bytes_per_line, QImage.Format_ARGB32)
                        else:
                            bytes_per_line = width * 3
                            q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                        
                        self.full_res_pixmap = QPixmap.fromImage(q_image.copy())
                        print(f"[Preview-ZOOM] ✓ TGA loaded: {width}x{height}")
                    except Exception as pil_error:
                        print(f"[Preview-ZOOM] TGA loading failed: {pil_error}")
                        self.full_res_pixmap = None
                else:
                    # Non-TGA files: Use QImageReader for consistency with normal preview (handles EXIF orientation automatically)
                    try:
                        image_reader = QImageReader(file_path_str)
                        image_reader.setAllocationLimit(2048)  # 2 GB limit for large TGA files
                        image_reader.setAutoTransform(True)  # Auto-apply EXIF orientation
                        
                        # Check image size before loading - limit to 8K (8192x8192) for performance
                        image_size = image_reader.size()
                        max_dimension = 8192
                        
                        # Reset scaling info
                        self.is_image_scaled = False
                        self.original_image_size = None
                        self.scaled_image_size = None
                        
                        if image_size.width() > max_dimension or image_size.height() > max_dimension:
                            # Scale down large images
                            scale_factor = max_dimension / max(image_size.width(), image_size.height())
                            new_width = int(image_size.width() * scale_factor)
                            new_height = int(image_size.height() * scale_factor)
                            from PySide6.QtCore import QSize
                            image_reader.setScaledSize(QSize(new_width, new_height))
                            
                            # Store scaling info for user feedback
                            self.is_image_scaled = True
                            self.original_image_size = (image_size.width(), image_size.height())
                            self.scaled_image_size = (new_width, new_height)
                        
                        # Read full resolution image (or scaled version)
                        image = image_reader.read()
                        
                        if not image.isNull():
                            self.full_res_pixmap = QPixmap.fromImage(image)
                        else:
                            # Fallback: try direct QPixmap load
                            self.full_res_pixmap = QPixmap(file_path_str)
                            
                    except Exception as e:
                        # Fallback to standard QPixmap loading
                        
                        # Try PIL for TGA/PSD/special formats
                        if file_path_str.lower().endswith(('.tga', '.tiff', '.tif', '.psd')):
                            try:
                                import sys
                                import os
                                external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
                                if external_libs not in sys.path:
                                    sys.path.insert(0, external_libs)
                                
                                from PIL import Image
                                pil_image = Image.open(file_path_str)
                                
                                # Convert to RGB
                                if pil_image.mode not in ('RGB', 'L'):
                                    pil_image = pil_image.convert('RGB')
                                elif pil_image.mode == 'L':
                                    pil_image = pil_image.convert('RGB')
                                
                                # Store original size
                                self.original_image_size = (pil_image.width, pil_image.height)
                                
                                # Scale down if too large for Preview (8K limit)
                                max_dimension = 8192
                                if pil_image.width > max_dimension or pil_image.height > max_dimension:
                                    scale_factor = max_dimension / max(pil_image.width, pil_image.height)
                                    new_width = int(pil_image.width * scale_factor)
                                    new_height = int(pil_image.height * scale_factor)
                                    pil_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                                    
                                    # Store scaling info
                                    self.is_image_scaled = True
                                    self.scaled_image_size = (new_width, new_height)
                                else:
                                    self.is_image_scaled = False
                                    self.scaled_image_size = None
                                
                                # Convert PIL to QPixmap
                                import numpy as np
                                img_array = np.array(pil_image)
                                height, width = img_array.shape[:2]
                                channels = img_array.shape[2] if len(img_array.shape) == 3 else 1
                                
                                if channels == 3:
                                    bytes_per_line = width * 3
                                    q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                                    self.full_res_pixmap = QPixmap.fromImage(q_image.copy())
                            except Exception as pil_error:
                                self.full_res_pixmap = QPixmap(file_path_str)
                        else:
                            self.full_res_pixmap = QPixmap(file_path_str)
            
            if self.full_res_pixmap.isNull():
                return
            
            self.zoom_mode = True
            self.pan_offset = QPoint(0, 0)
            
            # Keep PDF overlay controls visible in zoom mode for easy page navigation
            # (They stay visible so you can navigate pages while zoomed)
            
            # Set pixmap at original size
            self.set_preview_pixmap(self.full_res_pixmap)
            
            # Reset view transform and fit to window initially
            self.graphics_view.resetTransform()
            self.graphics_view.fitInView(self.pixmap_item, Qt.KeepAspectRatio)
            
            # Calculate the zoom level from fitInView
            # This gives us the current fit zoom level
            rect = self.pixmap_item.boundingRect()
            view_rect = self.graphics_view.viewport().rect()
            x_ratio = view_rect.width() / rect.width()
            y_ratio = view_rect.height() / rect.height()
            self.zoom_level = min(x_ratio, y_ratio)
            
            # Update title
            self.title_label.setText(f"🔍 Zoom Mode")
            self._update_zoom_label()
            
            # Show zoom controls
            self.zoom_controls.show()
            
            # Change cursor
            self.graphics_view.setCursor(Qt.OpenHandCursor)
            
        except Exception as e:
            print(f"Error loading full resolution: {e}")
    
    def exit_zoom_mode(self):
        """Exit zoom mode - return to preview"""
        if self.zoom_mode:
            self.zoom_mode = False
            self.full_res_pixmap = None
            self.zoom_level = 1.0
            self.pan_offset = QPoint(0, 0)
            self.zoom_label.setText("")
            
            # Reset graphics view transform
            self.graphics_view.resetTransform()
            
            # Temporarily disable scrollbars for accurate fitting
            self.graphics_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.graphics_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            
            # Hide zoom controls
            self.zoom_controls.hide()
            
            # Force layout update
            self.layout().invalidate()
            self.layout().activate()
            self.updateGeometry()
            QtCore.QCoreApplication.processEvents()
            self.graphics_view.updateGeometry()
            
            # Restore PDF overlay controls if we were viewing a PDF
            if self.is_showing_pdf:
                self.pdf_prev_overlay.show()
                self.pdf_next_overlay.show()
                self.pdf_page_overlay.show()
                self.update_pdf_overlay_positions()
            
            # For sequences, reload the current frame at preview quality
            if self.current_assets and len(self.current_assets) == 1:
                asset = self.current_assets[0]
                if asset.is_sequence and asset.sequence:
                    # Reload current frame at preview resolution
                    current_frame_index = self.sequence_playback.current_frame_index
                    if current_frame_index < len(asset.sequence.files):
                        frame_path = asset.sequence.files[current_frame_index]
                        self.load_sequence_frame(frame_path, asset)
                    # Restore scrollbar policy
                    self.graphics_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                    self.graphics_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                    return
            
            # For single images, restore preview
            if self.current_pixmap:
                self.fit_pixmap_to_label()
            
            # Restore scrollbar policy
            self.graphics_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.graphics_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            
            # Reset cursor
            self.graphics_view.setCursor(Qt.ArrowCursor)
            
            # Restore title
            if self.current_image_path:
                self.title_label.setText(f"Preview: {Path(self.current_image_path).name}")
    
    def _update_zoom_label(self):
        """Update zoom label with current zoom level and scaling info"""
        zoom_text = f"{int(self.zoom_level * 100)}%"
        
        # Add scaling warning if image was downscaled
        if self.is_image_scaled and self.original_image_size and self.scaled_image_size:
            orig_w, orig_h = self.original_image_size
            scaled_w, scaled_h = self.scaled_image_size
            zoom_text += f"  ⚠️ Scaled to 8K (Original: {orig_w}×{orig_h})"
        
        self.zoom_label.setText(zoom_text)
    
    def set_preview_pixmap(self, pixmap):
        """Set pixmap in graphics view"""
        # In zoom mode, just update the pixmap without clearing scene (preserve zoom/pan)
        if self.zoom_mode and self.pixmap_item:
            if pixmap:
                # Store the current scene rect (full res size)
                current_scene_rect = self.graphics_scene.sceneRect()
                original_width = current_scene_rect.width()
                original_height = current_scene_rect.height()
                
                # Update the pixmap
                self.pixmap_item.setPixmap(pixmap)
                
                # CRITICAL: Scale the pixmap item to fill the original scene rect
                # This way the downsampled pixmap appears at the same size and position
                scale_x = original_width / pixmap.width()
                scale_y = original_height / pixmap.height()
                
                from PySide6.QtGui import QTransform
                item_transform = QTransform()
                item_transform.scale(scale_x, scale_y)
                self.pixmap_item.setTransform(item_transform)
                
                # Keep the original scene rect
                self.graphics_scene.setSceneRect(current_scene_rect)
            return
        
        # Normal mode: clear scene and add new pixmap
        self.graphics_scene.clear()
        self.current_text_item = None  # Clear text item reference when showing images
        self.is_showing_text = False  # Reset text mode flag when showing images
        if pixmap:
            self.pixmap_item = self.graphics_scene.addPixmap(pixmap)
            self.graphics_scene.setSceneRect(self.pixmap_item.boundingRect())
            # Reset cursor to arrow for images
            self.graphics_view.viewport().setCursor(Qt.ArrowCursor)
        else:
            self.pixmap_item = None
            # Reset cursor to arrow
            self.graphics_view.viewport().setCursor(Qt.ArrowCursor)
    
    def show_placeholder_with_text(self, text):
        """Show a placeholder text message in the preview area"""
        self.graphics_scene.clear()
        self.pixmap_item = None
        self.current_text_item = None
        self.is_showing_text = False
        
        # Create a text item for the error message
        text_item = self.graphics_scene.addText(text)
        text_item.setDefaultTextColor(QColor("#888888"))
        
        # Center the text in the view
        text_rect = text_item.boundingRect()
        view_rect = self.graphics_view.viewport().rect()
        x = (view_rect.width() - text_rect.width()) / 2
        y = (view_rect.height() - text_rect.height()) / 2
        text_item.setPos(x, y)
        
        # Set scene rect to view size
        self.graphics_scene.setSceneRect(0, 0, view_rect.width(), view_rect.height())
    
    def fit_preview_to_view(self):
        """Fit the entire preview image in view"""
        if self.pixmap_item:
            # Reset transform before scaling
            self.graphics_view.resetTransform()
            
            # Calculate scale to fit BOTH dimensions (use the smaller scale!)
            # Add small margin (10px each side)
            viewport_rect = self.graphics_view.viewport().rect()
            scene_rect = self.graphics_scene.sceneRect()
            margin = 10
            available_width = viewport_rect.width() - 2 * margin
            available_height = viewport_rect.height() - 2 * margin
            
            scale_x = available_width / scene_rect.width()
            scale_y = available_height / scene_rect.height()
            scale = min(scale_x, scale_y)  # Use SMALLER scale to fit both dimensions
            
            # Apply the scale
            self.graphics_view.scale(scale, scale)
            
            # Center the image
            self.graphics_view.centerOn(self.pixmap_item)
    
    def update_zoom_display(self):
        """Update display with current zoom level"""
        if not self.full_res_pixmap or not self.zoom_mode:
            return
        
        # Set the original full-res pixmap (without scaling)
        self.set_preview_pixmap(self.full_res_pixmap)
        
        # Reset transform and apply zoom via transform
        self.graphics_view.resetTransform()
        self.graphics_view.scale(self.zoom_level, self.zoom_level)
        
        # Update zoom label
        self._update_zoom_label()

    
    def zoom_in(self):
        """Zoom in button - centered on current view"""
        if self.zoom_mode and self.pixmap_item:
            # Get the center of the current viewport in scene coordinates BEFORE zoom
            viewport_rect = self.graphics_view.viewport().rect()
            center_point = self.graphics_view.mapToScene(viewport_rect.center())
            
            # Calculate zoom factor
            old_zoom = self.zoom_level
            self.zoom_level *= 1.25
            self.zoom_level = min(self.zoom_level, 10.0)
            zoom_factor = self.zoom_level / old_zoom
            
            # Apply zoom using view transform
            self.graphics_view.scale(zoom_factor, zoom_factor)
            
            # Get the center point in scene coordinates AFTER zoom
            new_center = self.graphics_view.mapToScene(viewport_rect.center())
            
            # Calculate offset to keep the center point in place
            delta_pos = new_center - center_point
            
            # Translate view to compensate
            self.graphics_view.translate(delta_pos.x(), delta_pos.y())
            
            # Update zoom label
            self._update_zoom_label()
    
    def zoom_out(self):
        """Zoom out button - centered on current view"""
        if self.zoom_mode and self.pixmap_item:
            # Get the center of the current viewport in scene coordinates BEFORE zoom
            viewport_rect = self.graphics_view.viewport().rect()
            center_point = self.graphics_view.mapToScene(viewport_rect.center())
            
            # Calculate zoom factor
            old_zoom = self.zoom_level
            self.zoom_level /= 1.25
            self.zoom_level = max(self.zoom_level, 0.1)
            zoom_factor = self.zoom_level / old_zoom
            
            # Apply zoom using view transform
            self.graphics_view.scale(zoom_factor, zoom_factor)
            
            # Get the center point in scene coordinates AFTER zoom
            new_center = self.graphics_view.mapToScene(viewport_rect.center())
            
            # Calculate offset to keep the center point in place
            delta_pos = new_center - center_point
            
            # Translate view to compensate
            self.graphics_view.translate(delta_pos.x(), delta_pos.y())
            
            # Update zoom label
            self._update_zoom_label()

    
    def zoom_100(self):
        """Zoom to 100% (actual size - 1:1 pixel ratio) centered on current view"""
        if self.zoom_mode and self.full_res_pixmap and self.pixmap_item:
            # Get the center of the current viewport in scene coordinates BEFORE zoom
            viewport_rect = self.graphics_view.viewport().rect()
            center_point = self.graphics_view.mapToScene(viewport_rect.center())
            
            # Calculate zoom factor from current zoom to 1.0
            old_zoom = self.zoom_level
            self.zoom_level = 1.0
            zoom_factor = self.zoom_level / old_zoom
            
            # Apply zoom using view transform
            self.graphics_view.scale(zoom_factor, zoom_factor)
            
            # Get the center point in scene coordinates AFTER zoom
            new_center = self.graphics_view.mapToScene(viewport_rect.center())
            
            # Calculate offset to keep the center point in place
            delta_pos = new_center - center_point
            
            # Translate view to compensate
            self.graphics_view.translate(delta_pos.x(), delta_pos.y())
            
            # Update zoom label
            self._update_zoom_label()
    
    def zoom_fit(self):
        """Fit image to viewport"""
        if self.zoom_mode and self.full_res_pixmap:
            self.update_zoom_display()
            self.fit_preview_to_view()
    
    def clear_metadata(self):
        """Clear metadata labels"""
        while self.metadata_layout.count():
            item = self.metadata_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def add_metadata_row(self, icon, label, value):
        """Add a metadata row with icon, label, and value"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 1, 0, 1)
        row_layout.setSpacing(6)
        
        # Icon
        icon_label = QLabel(icon)
        icon_label.setFixedWidth(20)
        icon_label.setStyleSheet(f"font-size: 13px; font-family: {UI_FONT};")
        row_layout.addWidget(icon_label)
        
        # Label
        label_widget = QLabel(f"<b>{label}:</b>")
        label_widget.setMinimumWidth(75)
        label_widget.setStyleSheet(f"font-size: 11px; font-family: {UI_FONT};")
        row_layout.addWidget(label_widget)
        
        # Value
        value_widget = QLabel(str(value))
        value_widget.setWordWrap(True)
        value_widget.setStyleSheet(f"color: #b0b0b0; font-size: 11px; font-family: {UI_FONT};")
        row_layout.addWidget(value_widget, 1)
        
        # Add the row widget to metadata layout
        self.metadata_layout.addWidget(row_widget)
    
    def add_compact_exif_header(self, meta):
        """Add compact EXIF header (Adobe Bridge style)
        Shows: f/2.8 · 1/1000s · ISO 1600 | 7952×5304 | 9.09 MB · 350 ppi
        """
        parts = []
        
        # Exposure data
        if 'aperture' in meta:
            parts.append(meta['aperture'])
        if 'shutter_speed' in meta:
            parts.append(meta['shutter_speed'])
        if 'iso' in meta:
            parts.append(f"ISO {meta['iso']}")
        
        exposure_str = " · ".join(parts) if parts else ""
        
        # Resolution
        resolution_str = meta.get('dimensions', '')
        
        # File size
        size_str = ""
        if 'file_size' in meta:
            size = meta['file_size']
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.2f} KB"
            elif size < 1024 * 1024 * 1024:
                size_str = f"{size / (1024 * 1024):.2f} MB"
            else:
                size_str = f"{size / (1024 * 1024 * 1024):.2f} GB"
        
        # Create compact header widget
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 8, 5, 8)
        header_layout.setSpacing(10)
        
        # Exposure label (bold, larger)
        if exposure_str:
            exposure_label = QLabel(f"<b>{exposure_str}</b>")
            exposure_label.setStyleSheet(f"font-size: 12px; font-family: {UI_FONT}; color: #ffffff;")
            header_layout.addWidget(exposure_label)
            
            # Separator
            sep1 = QLabel("|")
            sep1.setStyleSheet(f"color: #555; font-size: 12px;")
            header_layout.addWidget(sep1)
        
        # Resolution
        if resolution_str:
            res_label = QLabel(resolution_str)
            res_label.setStyleSheet(f"font-size: 11px; font-family: {UI_FONT}; color: #b0b0b0;")
            header_layout.addWidget(res_label)
            
            if size_str:
                sep2 = QLabel("|")
                sep2.setStyleSheet(f"color: #555; font-size: 12px;")
                header_layout.addWidget(sep2)
        
        # Size
        if size_str:
            size_label = QLabel(size_str)
            size_label.setStyleSheet(f"font-size: 11px; font-family: {UI_FONT}; color: #b0b0b0;")
            header_layout.addWidget(size_label)
        
        header_layout.addStretch()
        
        # Add separator line before header (same style as multi-select)
        self.metadata_layout.addSpacing(6)
        separator = QLabel("─" * 40)
        separator.setStyleSheet("color: #555;")
        self.metadata_layout.addWidget(separator)
        
        # Add header
        self.metadata_layout.addWidget(header_widget)
        
        # Add separator line after header (same style as multi-select)
        separator2 = QLabel("─" * 40)
        separator2.setStyleSheet("color: #555;")
        self.metadata_layout.addWidget(separator2)
        self.metadata_layout.addSpacing(6)
    
    def add_metadata_tags_display(self, assets):
        """Add read-only tags display in metadata tab with Edit button"""
        # Create row widget similar to other metadata rows
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 1, 0, 1)
        row_layout.setSpacing(6)
        
        # Icon
        icon_label = QLabel("🏷️")
        icon_label.setFixedWidth(20)
        icon_label.setStyleSheet(f"font-size: 13px; font-family: {UI_FONT};")
        row_layout.addWidget(icon_label)
        
        # Label
        label_widget = QLabel(f"<b>Tags:</b>")
        label_widget.setMinimumWidth(75)
        label_widget.setStyleSheet(f"font-size: 11px; font-family: {UI_FONT};")
        row_layout.addWidget(label_widget)
        
        # Get tags from metadata database
        try:
            from .metadata import get_metadata_manager
            metadata = get_metadata_manager()
        except ImportError:
            metadata = None
        
        if not metadata:
            row_layout.addWidget(QLabel("(no tags)"), 1)
            self.metadata_layout.addWidget(row_widget)
            return
        
        # Collect all tags from selected files
        all_file_tags = {}  # {file_path: [{'id': int, 'name': str, 'category': str, 'color': str}, ...]}
        total_files = len(assets)
        
        for asset in assets:
            file_path = str(asset.file_path)
            file_meta = metadata.get_file_metadata(file_path)
            if file_meta and file_meta.get('tags'):
                all_file_tags[file_path] = file_meta['tags']
        
        if not all_file_tags:
            # No tags on any files
            no_tags_label = QLabel("(no tags)")
            no_tags_label.setStyleSheet(f"color: #b0b0b0; font-size: 11px; font-family: {UI_FONT};")
            row_layout.addWidget(no_tags_label, 1)
        else:
            # Count tag occurrences
            tag_counts = {}  # {tag_id: {'tag': dict, 'count': int}}
            for file_tags in all_file_tags.values():
                for tag_dict in file_tags:
                    tag_id = tag_dict['id']
                    if tag_id not in tag_counts:
                        tag_counts[tag_id] = {'tag': tag_dict, 'count': 0}
                    tag_counts[tag_id]['count'] += 1
            
            # Separate common and partial tags
            common_tags = []  # Tags in ALL files
            partial_tags = []  # Tags in SOME files
            
            for tag_id, data in tag_counts.items():
                if data['count'] == total_files:
                    common_tags.append(data['tag'])
                else:
                    partial_tags.append((data['tag'], data['count']))
            
            # Sort tags
            common_tags.sort(key=lambda x: x['name'])  # Sort by tag name
            partial_tags.sort(key=lambda x: x[0]['name'])  # Sort by tag name
            
            # Create tags text display
            tags_text_parts = []
            
            # Common tags (bold)
            for tag_dict in common_tags:
                tag_text = tag_dict['name']
                tags_text_parts.append(f"<b>{tag_text}</b>")
            
            # Partial tags (normal with count)
            for tag_dict, count in partial_tags:
                tag_text = tag_dict['name']
                tags_text_parts.append(f"{tag_text} ({count}/{total_files})")
            
            # Create tags display label
            if tags_text_parts:
                tags_display = QLabel(", ".join(tags_text_parts))
                tags_display.setWordWrap(True)
                tags_display.setStyleSheet(f"color: #b0b0b0; font-size: 11px; font-family: {UI_FONT};")
                tags_display.setToolTip("Bold tags are in all selected files.\nTags with counts are in some files.\nClick 'Edit Tags' button to modify.")
                row_layout.addWidget(tags_display, 1)
            else:
                no_tags_label = QLabel("(no tags)")
                no_tags_label.setStyleSheet(f"color: #b0b0b0; font-size: 11px; font-family: {UI_FONT};")
                row_layout.addWidget(no_tags_label, 1)
        
        # Add "Edit Tags" button
        edit_button = QtWidgets.QPushButton("Edit Tags")
        edit_button.setFixedWidth(80)
        edit_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #3a3a3a;
                border: 1px solid #555;
                color: #cccccc;
                padding: 2px 8px;
                font-size: 10px;
                font-family: {UI_FONT};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: #4a4a4a;
                border-color: #666;
            }}
            QPushButton:pressed {{
                background-color: #2a2a2a;
            }}
        """)
        edit_button.clicked.connect(lambda: self.info_tabs.setCurrentIndex(1))  # Switch to Tags tab (index 1)
        edit_button.setToolTip("Switch to Tags tab to edit tags")
        row_layout.addWidget(edit_button)
        
        # Add the row widget to metadata layout
        self.metadata_layout.addWidget(row_widget)
    
    def update_preview(self, assets):
        """Update preview panel with selected assets"""
        self.current_assets = assets
        
        # Refresh browse dialog colors if open (selection changed)
        if hasattr(self, '_active_browse_dialog') and self._active_browse_dialog:
            try:
                dialog = self._active_browse_dialog
                if hasattr(dialog, '_tag_buttons') and hasattr(dialog, '_mm'):
                    self._refresh_browse_dialog_buttons(dialog, dialog._tag_buttons, dialog._mm)
            except:
                pass  # Dialog might be closed
        
        if not assets:
            self.show_empty_state()
            return
        
        if len(assets) == 1:
            # Single file - show full preview and metadata
            self.show_single_file(assets[0])
        else:
            # Multiple files - show first file + summary
            self.show_multiple_files(assets)
    
    def show_single_file(self, asset):
        """Show preview and metadata for single file"""
        # Exit zoom mode when switching files
        self.exit_zoom_mode()
        
        # Reset exposure to neutral when switching files
        self.exposure_slider.setValue(0)
        self.hdr_exposure = 0.0
        
        # Clear previous pixmap to avoid showing wrong image on load failure
        self.current_pixmap = None
        self.graphics_scene.clear()
        self.current_text_item = None
        
        # Reset mode flags
        self.is_showing_text = False
        self.is_showing_pdf = False
        
        # Hide all control panels initially
        self.exposure_controls.hide()
        self.text_controls.hide()
        self.sequence_playback.hide()
        
        # Hide PDF overlay controls
        self.pdf_prev_overlay.hide()
        self.pdf_next_overlay.hide()
        self.pdf_page_overlay.hide()
        
        # CRITICAL FIX: Always ensure correct widget visibility when switching files
        # If we're NOT showing a video, ensure graphics_view is visible and video_widget is hidden
        # This fixes the issue where video → image switching doesn't update the display
        if not asset.is_video_file:
            # Stop any playing video first
            if hasattr(self, 'media_player') and self.media_player:
                self.media_player.stop()
            # Hide video widgets, show graphics view
            self.video_widget.hide()
            self.video_playback.hide()
            self.graphics_view.show()
        
        self.title_label.setText(f"Preview: {asset.name}")
        self.clear_metadata()
        
        # Check if this is an image sequence
        if asset.is_sequence and asset.sequence:
            # Show sequence playback controls
            self.sequence_playback.set_sequence(asset.sequence)
            self.sequence_playback.show()
            
            # Load and display the first frame by default (matching the frame counter)
            if asset.sequence.files:
                first_frame_path = asset.sequence.files[0]
                self.load_sequence_frame(first_frame_path, asset)
                # Update playback widget to show frame 0
                self.sequence_playback.current_frame_index = 0
                self.sequence_playback.timeline_slider.setValue(0)
                self.sequence_playback.update_frame_label()
            
            # Add metadata for sequence before returning
            self.add_metadata_row("📄", "Name", asset.name)
            seq = asset.sequence
            self.add_metadata_row("🎬", "Sequence", f"{seq.frame_count} frames")
            self.add_metadata_row("📊", "Frame Range", f"{seq.first_frame}-{seq.last_frame}")
            if not seq.is_continuous and seq.missing_frames:
                missing_count = len(seq.missing_frames)
                self.add_metadata_row("⚠️", "Missing", f"{missing_count} frames")
            self.add_metadata_row("💾", "Total Size", self.format_file_size(seq.total_size))
            
            # File type
            file_type = asset.extension.upper() + " sequence"
            self.add_metadata_row("🗂️", "Type", file_type)
            
            # Modified date
            try:
                mod_time = datetime.fromtimestamp(asset.file_path.stat().st_mtime)
                date_str = mod_time.strftime("%Y-%m-%d %H:%M:%S")
                self.add_metadata_row("📅", "Modified", date_str)
            except:
                pass
            
            # Path (shortened)
            path_str = str(asset.file_path)
            if len(path_str) > 50:
                path_str = "..." + path_str[-47:]
            self.add_metadata_row("📂", "Path", path_str)
            
            # Add tags display in metadata (read-only)
            self.add_metadata_tags_display([asset])
            
            # Load tags for this asset (in Tags tab)
            self.load_tags(asset)
            
            # Don't load individual file preview for sequences
            return
        
        # Store current image path for zoom viewer
        if asset.is_image_file:
            self.current_image_path = asset.file_path
        else:
            self.current_image_path = None
        
        # Load preview image (with cache!)
        pixmap = None
        resolution_str = None
        self.current_pixmap = None
        
        file_path_str = str(asset.file_path)
        
        if asset.is_image_file:
            # Check if HDR/EXR format first (before cache check)
            file_ext = file_path_str.lower()
            is_hdr_exr = file_ext.endswith('.hdr') or file_ext.endswith('.exr')
            
            # Set up exposure controls for HDR/EXR only
            if is_hdr_exr:
                self.current_hdr_path = file_path_str
                self.exposure_controls.show()
                # Reset exposure to neutral (0.0) when opening new HDR/EXR
                self.exposure_slider.setValue(0)
                self.hdr_exposure = 0.0
                
                # Clear all caches for old files to force fresh load with exposure=0
                # This ensures exposure reset works properly
                old_raw_keys = [k for k in list(self.hdr_raw_cache.keys()) if not k.startswith(file_path_str)]
                for old_key in old_raw_keys:
                    del self.hdr_raw_cache[old_key]
                
                old_preview_keys = [k for k in list(self.preview_cache.keys()) 
                                   if k != file_path_str and (k.startswith('\\\\') or k.startswith('/') or ':' in k)]
                for old_key in old_preview_keys:
                    del self.preview_cache[old_key]
            else:
                self.current_hdr_path = None
                # exposure_controls already hidden above
            
            # Check cache (skip cache for HDR formats that need exposure control)
            if not is_hdr_exr and file_path_str in self.preview_cache:
                # Cache hit! Instant load (only for non-HDR images)
                pixmap, resolution_str = self.preview_cache[file_path_str]
                self.current_pixmap = pixmap
                self.fit_pixmap_to_label()
            else:
                # Cache miss - show loading indicator
                self.graphics_scene.clear()
                self.current_text_item = None
                QApplication.processEvents()  # Update UI immediately
                
                # Load and cache
                try:
                    if is_hdr_exr:
                        # Use imageio (HDR) or OpenEXR (EXR) with exposure control
                        # Higher quality preview: adjustable via settings
                        
                        # === EXR Channel Detection ===
                        if file_ext.endswith('.exr'):
                            # FAST CHECK: Check if already tagged as deep data (from thumbnail generation)
                            is_deep = False
                            if self.metadata_manager:
                                file_metadata = self.metadata_manager.get_file_metadata(file_path_str)
                                file_tags = file_metadata.get('tags', [])
                                tag_names_lower = [tag['name'].lower() for tag in file_tags]
                                if "deepdata" in tag_names_lower:
                                    is_deep = True
                                    if hasattr(self, 'debug_mode') and self.debug_mode:
                                        print(f"⚡ Deep EXR detected via tag (instant) - skipping preview")
                            
                            # SLOW CHECK: If not tagged yet, check the file (first time only)
                            if not is_deep and is_deep_exr(file_path_str):
                                is_deep = True
                                # Tag it for next time
                                if self.metadata_manager:
                                    try:
                                        tag_id = self.metadata_manager.add_tag("deepdata", category=None, color=None)
                                        self.metadata_manager.add_tag_to_file(file_path_str, tag_id)
                                        if hasattr(self, 'debug_mode') and self.debug_mode:
                                            print(f"🔖 Tagged as 'deepdata' for future fast detection")
                                    except:
                                        pass
                            
                            if is_deep:
                                print(f"⚠️ Deep EXR detected - skipping preview")
                                self.graphics_scene.clear()
                                self.current_text_item = None
                                self.show_deep_exr_placeholder(asset.name)
                                pixmap = None  # Skip further processing
                            else:
                                self.detect_exr_channels(file_path_str)
                                
                                # Load first channel using new channel loader
                                if self.current_exr_channels:
                                    pixmap, resolution_str = self.load_exr_channel(file_path_str, self.current_exr_channel)
                        else:
                            # HDR files (not EXR) - load with full res raw data caching
                            # Clear EXR channel info for HDR files
                            self.current_exr_file_path = None
                            self.current_exr_channels = []
                            self.current_exr_channel = None
                            
                            pixmap, resolution_str = self.load_hdr_file(file_path_str)
                        
                        if pixmap:
                            self.current_pixmap = pixmap
                            self.add_to_cache(file_path_str, pixmap, resolution_str)
                            self.fit_pixmap_to_label()
                        else:
                            # Check if it's a deep EXR
                            if resolution_str and "Deep EXR" in resolution_str:
                                self.graphics_scene.clear()
                                self.current_text_item = None
                                self.show_deep_exr_placeholder(asset.name)
                            else:
                                self.graphics_scene.clear()
                                self.current_text_item = None
                                self.show_hdr_placeholder(asset.name)
                    else:
                        # Standard image formats (PNG, JPG, TIF, etc.) - NO exposure control
                        self.current_hdr_path = None
                        self.exposure_controls.hide()  # Hide exposure slider for non-HDR
                        
                        # Special handling for RenderMan .tx files - use OpenImageIO
                        file_ext = file_path_str.lower()
                        if file_ext.endswith('.tx'):
                            try:
                                from .widgets import load_oiio_image
                                pixmap, resolution_str, metadata = load_oiio_image(
                                    file_path_str,
                                    max_size=1024,  # Preview size
                                    mip_level=0,
                                    exposure=0.0,
                                    metadata_manager=self.metadata_manager
                                )
                                
                                if pixmap and not pixmap.isNull():
                                    self.current_pixmap = pixmap
                                    self.add_to_cache(file_path_str, pixmap, resolution_str)
                                    self.fit_pixmap_to_label()
                                else:
                                    raise Exception("OIIO returned null pixmap")
                                    
                            except Exception as e:
                                self.graphics_scene.clear()
                                self.current_text_item = None
                        # Special handling for 16-bit/32-bit TIFF files - use OpenCV for better support
                        elif (file_ext.endswith('.tif') or file_ext.endswith('.tiff')) and OPENCV_AVAILABLE and NUMPY_AVAILABLE:
                            try:
                                import cv2
                                import numpy as np
                                
                                # Read image with OpenCV (supports 16-bit and 32-bit TIFF)
                                img = cv2.imread(file_path_str, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)
                                
                                if img is not None:
                                    # Get original size for resolution metadata
                                    height, width = img.shape[:2]
                                    resolution_str = f"{width} x {height}"
                                    
                                    # Normalize bit depth FIRST (before color conversion!)
                                    if img.dtype == np.uint16:
                                        # 16-bit image - normalize to 8-bit
                                        img = (img / 256).astype(np.uint8)
                                    elif img.dtype == np.float32 or img.dtype == np.float64:
                                        # 32-bit float - simple clipping and normalization
                                        img = np.clip(img, 0, 1)  # Clip to 0-1 range
                                        img = (img * 255).astype(np.uint8)
                                    
                                    # NOW convert to RGB (after normalization)
                                    if len(img.shape) == 2:
                                        # Grayscale - convert to RGB
                                        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                                    elif len(img.shape) == 3 and img.shape[2] == 4:
                                        # RGBA - convert to RGB
                                        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
                                    elif len(img.shape) == 3 and img.shape[2] == 3:
                                        # BGR - convert to RGB
                                        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                                    
                                    # Resize for preview if too large
                                    max_preview = 1024  # Higher quality for preview vs thumbnail
                                    if width > max_preview or height > max_preview:
                                        scale = min(max_preview / width, max_preview / height)
                                        new_width = int(width * scale)
                                        new_height = int(height * scale)
                                        img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                                    
                                    # Convert numpy array to QPixmap
                                    height, width, channels = img.shape
                                    bytes_per_line = width * channels
                                    q_image = QImage(img.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                                    pixmap = QPixmap.fromImage(q_image.copy())
                                    
                                    if not pixmap.isNull():
                                        self.current_pixmap = pixmap
                                        self.add_to_cache(file_path_str, pixmap, resolution_str)
                                        self.fit_pixmap_to_label()
                                    else:
                                        raise Exception("Failed to convert to QPixmap")
                                else:
                                    raise Exception("OpenCV could not load the TIFF image")
                                    
                            except Exception as e:
                                print(f"TIFF OpenCV loading failed: {e}, trying QImageReader fallback...")
                                # Fall back to QImageReader for standard TIFF handling
                                image_reader = QImageReader(file_path_str)
                                image_reader.setAllocationLimit(2048)  # 2 GB limit for large images
                                image_reader.setAutoTransform(True)  # Auto-apply EXIF orientation
                                
                                original_size = image_reader.size()
                                if original_size.isValid():
                                    resolution_str = f"{original_size.width()} x {original_size.height()}"
                                
                                if original_size.width() > 1024 or original_size.height() > 1024:
                                    if original_size.width() > original_size.height():
                                        scaled_size = QSize(1024, int(1024 * original_size.height() / original_size.width()))
                                    else:
                                        scaled_size = QSize(int(1024 * original_size.width() / original_size.height()), 1024)
                                    image_reader.setScaledSize(scaled_size)
                                
                                image = image_reader.read()
                                if not image.isNull():
                                    pixmap = QPixmap.fromImage(image)
                                    
                                    self.current_pixmap = pixmap
                                    self.add_to_cache(file_path_str, pixmap, resolution_str)
                                    self.fit_pixmap_to_label()
                                else:
                                    # QImageReader also failed - try tifffile for special formats
                                    try:
                                        import tifffile
                                        import numpy as np
                                        
                                        # Read TIFF with tifffile (handles Affinity/compressed TIFFs)
                                        img_array = tifffile.imread(file_path_str)
                                        
                                        # Get resolution
                                        if len(img_array.shape) == 3:
                                            height, width, channels = img_array.shape
                                        else:
                                            height, width = img_array.shape
                                            channels = 1
                                        resolution_str = f"{width} x {height}"
                                        
                                        # Normalize to 8-bit
                                        if img_array.dtype == np.uint32:
                                            # Affinity uses uint32 with limited range - normalize to actual min/max
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
                                        
                                        # Convert to RGB if needed
                                        if len(img_array.shape) == 2:
                                            img_array = np.stack([img_array, img_array, img_array], axis=2)
                                        elif len(img_array.shape) == 3 and img_array.shape[2] > 3:
                                            img_array = img_array[:, :, :3]
                                        
                                        # Resize if too large
                                        from PIL import Image
                                        pil_image = Image.fromarray(img_array)
                                        if pil_image.width > 1024 or pil_image.height > 1024:
                                            pil_image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                                        
                                        # Convert to QPixmap
                                        img_array = np.array(pil_image)
                                        height, width = img_array.shape[:2]
                                        bytes_per_line = width * 3
                                        q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                                        pixmap = QPixmap.fromImage(q_image.copy())
                                        
                                        self.current_pixmap = pixmap
                                        self.add_to_cache(file_path_str, pixmap, resolution_str)
                                        self.fit_pixmap_to_label()
                                    except Exception as tiff_error:
                                        print(f"tifffile also failed: {tiff_error}")
                                        self.graphics_scene.clear()
                                        self.current_text_item = None
                        elif file_ext.endswith(('.tga', '.psd')):
                            # TGA/PSD files - use PIL (Qt has allocation issues)
                            
                            # For PSD files, use psd-tools directly instead of PIL
                            # PIL may have color channel issues with Photoshop files
                            if file_ext.endswith('.psd'):
                                try:
                                    import time
                                    import sys
                                    import os
                                    external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
                                    if external_libs not in sys.path:
                                        sys.path.insert(0, external_libs)
                                    
                                    from PIL import Image
                                    Image.MAX_IMAGE_PIXELS = None
                                    
                                    start_time = time.time()
                                    
                                    # Get original dimensions first
                                    with Image.open(file_path_str) as psd:
                                        original_width = psd.width
                                        original_height = psd.height
                                        resolution_str = f"{original_width} x {original_height}"
                                    
                                    # Load PSD with PIL (fast path)
                                    pil_image = Image.open(file_path_str)
                                    
                                    # Convert to RGB (handle all color modes)
                                    if pil_image.mode not in ('RGB', 'RGBA'):
                                        pil_image = pil_image.convert('RGB')
                                    
                                    # Scale to 2048 for preview display
                                    max_preview = 2048
                                    if pil_image.width > max_preview or pil_image.height > max_preview:
                                        pil_image.thumbnail((max_preview, max_preview), Image.Resampling.LANCZOS)
                                    
                                    # Convert PIL to QPixmap
                                    import numpy as np
                                    img_array = np.array(pil_image)
                                    height, width = img_array.shape[:2]
                                    
                                    # Handle RGB/RGBA
                                    if len(img_array.shape) == 3:
                                        channels = img_array.shape[2]
                                        if channels == 4:
                                            # RGBA
                                            bytes_per_line = width * 4
                                            q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGBA8888)
                                        else:
                                            # RGB
                                            bytes_per_line = width * 3
                                            q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                                    else:
                                        # Grayscale
                                        bytes_per_line = width
                                        q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_Grayscale8)
                                    
                                    composite_pixmap = QPixmap.fromImage(q_image.copy())
                                    pil_image.close()
                                    
                                    if composite_pixmap and not composite_pixmap.isNull():
                                        # Store in cache (for zoom mode)
                                        self.add_to_cache(file_path_str, composite_pixmap, resolution_str)
                                        
                                        # Scale down for preview display (like other formats: TGA, TIFF use 1024)
                                        # Use 2048 for PSD to maintain quality
                                        max_preview = 2048
                                        if composite_pixmap.width() > max_preview or composite_pixmap.height() > max_preview:
                                            scale = min(max_preview / composite_pixmap.width(), max_preview / composite_pixmap.height())
                                            new_width = int(composite_pixmap.width() * scale)
                                            new_height = int(composite_pixmap.height() * scale)
                                            display_pixmap = composite_pixmap.scaled(new_width, new_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                            print(f"[PREVIEW-DEBUG] Scaled to {new_width}x{new_height} for display")
                                        else:
                                            display_pixmap = composite_pixmap
                                        
                                        # Set display pixmap (will be used for preview)
                                        self.current_pixmap = display_pixmap
                                        
                                        # Fit to view
                                        self.fit_pixmap_to_label()
                                        print(f"{'='*60}\n")
                                    else:
                                        print(f"[PREVIEW-DEBUG] ✗ PSD composite loading failed")
                                        self.graphics_scene.clear()
                                        self.current_text_item = None
                                except Exception as e:
                                    print(f"[PREVIEW-DEBUG] PSD loading exception: {e}")
                                    self.graphics_scene.clear()
                                    self.current_text_item = None
                            else:
                                # TGA files - use PIL
                                try:
                                    import sys
                                    import os
                                    external_libs = os.path.join(os.path.dirname(__file__), 'external_libs')
                                    if external_libs not in sys.path:
                                        sys.path.insert(0, external_libs)
                                    
                                    from PIL import Image
                                    Image.MAX_IMAGE_PIXELS = None
                                    print(f"[PREVIEW-DEBUG] Opening TGA with PIL...")
                                    pil_image = Image.open(file_path_str)
                                    print(f"[PREVIEW-DEBUG] PIL opened: mode={pil_image.mode}, size={pil_image.size}")
                                    
                                    # Get original size for resolution
                                    resolution_str = f"{pil_image.width} x {pil_image.height}"
                                    
                                    # Convert to RGB
                                    if pil_image.mode not in ('RGB', 'L'):
                                        print(f"[PREVIEW-DEBUG] Converting {pil_image.mode} -> RGB")
                                        pil_image = pil_image.convert('RGB')
                                    elif pil_image.mode == 'L':
                                        print(f"[PREVIEW-DEBUG] Converting L -> RGB")
                                        pil_image = pil_image.convert('RGB')
                                    else:
                                        print(f"[PREVIEW-DEBUG] Already RGB, no conversion needed")
                                    
                                    # Resize for preview if needed (1024px max)
                                    if pil_image.width > 1024 or pil_image.height > 1024:
                                        print(f"[PREVIEW-DEBUG] Resizing from {pil_image.width}x{pil_image.height} to fit 1024px")
                                        pil_image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                                        print(f"[PREVIEW-DEBUG] Resized to {pil_image.width}x{pil_image.height}")
                                    
                                    # Convert to QPixmap
                                    import numpy as np
                                    img_array = np.array(pil_image)
                                    height, width = img_array.shape[:2]
                                    
                                    print(f"[PREVIEW-DEBUG] NumPy array shape: {img_array.shape}, dtype: {img_array.dtype}")
                                    print(f"[PREVIEW-DEBUG] Converting to QImage with Format_RGB888...")
                                    
                                    bytes_per_line = width * 3
                                    q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                                    pixmap = QPixmap.fromImage(q_image.copy())
                                    
                                    print(f"[PREVIEW-DEBUG] ✓ QPixmap created: {pixmap.width()}x{pixmap.height()}")
                                    print(f"{'='*60}\n")
                                    
                                    self.current_pixmap = pixmap
                                    self.add_to_cache(file_path_str, pixmap, resolution_str)
                                    self.fit_pixmap_to_label()
                                except Exception as e:
                                    print(f"[PREVIEW-DEBUG] TGA loading failed: {e}")
                                    self.graphics_scene.clear()
                                    self.current_text_item = None
                        else:
                            # Standard 8-bit image formats (PNG, JPG, etc.) - use QImageReader
                            image_reader = QImageReader(file_path_str)
                            image_reader.setAllocationLimit(2048)  # 2 GB limit for large images
                            image_reader.setAutoTransform(True)  # Auto-apply EXIF orientation
                            
                            # Check original size (for resolution metadata)
                            original_size = image_reader.size()
                            if original_size.isValid():
                                resolution_str = f"{original_size.width()} x {original_size.height()}"
                            
                            # If image is larger than 1024px, scale it down during load
                            if original_size.width() > 1024 or original_size.height() > 1024:
                                if original_size.width() > original_size.height():
                                    scaled_size = QSize(1024, int(1024 * original_size.height() / original_size.width()))
                                else:
                                    scaled_size = QSize(int(1024 * original_size.width() / original_size.height()), 1024)
                                image_reader.setScaledSize(scaled_size)
                            
                            # Read the (scaled) image
                            image = image_reader.read()
                            
                            if not image.isNull():
                                pixmap = QPixmap.fromImage(image)
                                
                                self.current_pixmap = pixmap
                                
                                # Add to cache
                                self.add_to_cache(file_path_str, pixmap, resolution_str)
                                
                                # Fit to current panel size
                                self.fit_pixmap_to_label()
                            else:
                                self.graphics_scene.clear()
                                self.current_text_item = None
                            
                except Exception as e:
                    print(f"Preview load error: {e}")
                    self.graphics_scene.clear()
                    self.current_text_item = None
                    self.add_metadata_row("⚠️", "Error", f"Load error: {str(e)}")
        elif asset.is_video_file:
            # Video file - extract middle frame for preview
            self.show_video_preview(asset)
        elif asset.is_pdf_file:
            # PDF file - show preview with page navigation
            self.show_pdf_preview(asset)
        elif self.is_text_file(asset):
            # Text file - show text preview
            self.show_text_preview(asset)
        else:
            # Non-image file - check if it's a text file
            if self.is_text_file(asset):
                self.show_text_preview(asset)
            else:
                # Other non-image, non-text files - show icon/placeholder
                self.graphics_scene.clear()
        
        # Add metadata - Adobe Bridge style layout
        # 1. Basic file information
        self.add_metadata_row("📄", "Name", asset.name)
        
        # File size
        if not asset.is_folder:
            self.add_metadata_row("💾", "Size", self.format_file_size(asset.size))
        
        # File type with special handling for PDF and folders
        if asset.is_folder:
            file_type = "Folder"
        elif asset.is_pdf_file:
            file_type = "PDF Document"
        elif asset.extension:
            file_type = asset.extension.upper() + " file"
        else:
            file_type = "File"
        self.add_metadata_row("🗂️", "Type", file_type)
        
        # Modified date
        try:
            mod_time = datetime.fromtimestamp(asset.file_path.stat().st_mtime)
            date_str = mod_time.strftime("%Y-%m-%d %H:%M:%S")
            self.add_metadata_row("�", "Modified", date_str)
        except:
            pass
        
        # Path (show directory, not filename which is already shown)
        path_str = str(asset.file_path.parent)  # Get directory only
        if len(path_str) > 60:
            # Show beginning + end, cut middle
            path_str = path_str[:30] + "..." + path_str[-27:]
        self.add_metadata_row("📂", "Path", path_str)
        
        # 2. Compact EXIF header (if image with EXIF data)
        exif_meta = None
        if asset.is_image_file:
            try:
                from .metadata_extractor import FileMetadata
                file_meta = FileMetadata(asset.file_path, extract_full=True)
                exif_meta = file_meta.get_metadata()
                
                # Build metadata dict for compact header
                header_data = {}
                if 'aperture' in exif_meta:
                    header_data['aperture'] = exif_meta['aperture']
                if 'shutter_speed' in exif_meta:
                    header_data['shutter_speed'] = exif_meta['shutter_speed']
                if 'iso' in exif_meta:
                    header_data['iso'] = exif_meta['iso']
                if resolution_str:
                    header_data['dimensions'] = resolution_str
                header_data['file_size'] = asset.size
                
                # Only show compact header if we have EXIF data
                if 'aperture' in header_data or 'shutter_speed' in header_data or 'iso' in header_data:
                    self.add_compact_exif_header(header_data)
            except:
                # EXIF extraction failed - skip silently
                pass
        
        # If this is a sequence, add sequence-specific metadata
        if asset.is_sequence and asset.sequence:
            seq = asset.sequence
            self.add_metadata_row("🎬", "Sequence", f"{seq.frame_count} frames")
            self.add_metadata_row("📊", "Frame Range", f"{seq.first_frame}-{seq.last_frame}")
            if not seq.is_continuous and seq.missing_frames:
                missing_count = len(seq.missing_frames)
                self.add_metadata_row("⚠️", "Missing", f"{missing_count} frames")
            self.add_metadata_row("💾", "Total Size", self.format_file_size(seq.total_size))
        
        # If this is a video file, add video-specific metadata
        if asset.is_video_file:
            try:
                import cv2
                # Suppress OpenCV/FFmpeg verbose output
                if hasattr(cv2, 'setLogLevel'):
                    cv2.setLogLevel(0)  # 0 = Silent
                cap = cv2.VideoCapture(str(asset.file_path))
                if cap.isOpened():
                    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    duration = frame_count / fps if fps > 0 else 0
                    
                    # Video info
                    self.add_metadata_row("📐", "Resolution", f"{width} x {height}")
                    self.add_metadata_row("🎬", "Frames", f"{frame_count}")
                    self.add_metadata_row("📊", "FPS", f"{fps:.2f}")
                    
                    # Duration (formatted as MM:SS or HH:MM:SS)
                    if duration >= 3600:
                        hours = int(duration // 3600)
                        minutes = int((duration % 3600) // 60)
                        seconds = int(duration % 60)
                        duration_str = f"{hours}h {minutes}m {seconds}s"
                    elif duration >= 60:
                        minutes = int(duration // 60)
                        seconds = int(duration % 60)
                        duration_str = f"{minutes}m {seconds}s"
                    else:
                        duration_str = f"{duration:.1f}s"
                    self.add_metadata_row("⏱️", "Duration", duration_str)
                    
                    cap.release()
            except Exception as e:
                print(f"[PREVIEW] Error extracting video metadata: {e}")
        
        # 3. Add tags display in metadata (read-only)
        self.add_metadata_tags_display([asset])
        
        # 4. Detailed Camera Data (EXIF) section
        if exif_meta and asset.is_image_file:
            # Add section header
            section_header = QLabel("<b>Camera Data (EXIF)</b>")
            section_header.setStyleSheet(f"color: #ffffff; font-size: 12px; font-family: {UI_FONT}; padding: 8px 0 4px 0;")
            self.metadata_layout.addWidget(section_header)
            
            # Camera info
            if 'camera_make' in exif_meta and 'camera_model' in exif_meta:
                camera = f"{exif_meta['camera_make']} {exif_meta['camera_model']}"
                self.add_metadata_row("📷", "Camera", camera)
            elif 'camera_model' in exif_meta:
                self.add_metadata_row("📷", "Camera", exif_meta['camera_model'])
            
            # Lens
            if 'lens' in exif_meta:
                self.add_metadata_row("🔭", "Lens", exif_meta['lens'])
            
            # ISO
            if 'iso' in exif_meta:
                iso_str = f"{exif_meta['iso']}"
                if 'iso_category' in exif_meta:
                    iso_str += f" ({exif_meta['iso_category']})"
                self.add_metadata_row("📊", "ISO", iso_str)
            
            # Aperture
            if 'aperture' in exif_meta:
                aperture_str = exif_meta['aperture']
                if 'aperture_category' in exif_meta:
                    aperture_str += f" ({exif_meta['aperture_category']})"
                self.add_metadata_row("🔍", "Aperture", aperture_str)
            
            # Shutter Speed
            if 'shutter_speed' in exif_meta:
                self.add_metadata_row("⏱️", "Shutter", exif_meta['shutter_speed'])
            
            # Focal Length
            if 'focal_length' in exif_meta:
                focal_str = exif_meta['focal_length']
                if 'focal_length_category' in exif_meta:
                    focal_str += f" ({exif_meta['focal_length_category']})"
                self.add_metadata_row("�", "Focal Length", focal_str)
            
            # White Balance
            if 'white_balance' in exif_meta:
                self.add_metadata_row("⚪", "White Balance", exif_meta['white_balance'])
            
            # Flash
            if 'flash' in exif_meta:
                self.add_metadata_row("⚡", "Flash", exif_meta['flash'])
            
            # Resolution (if we have it)
            if resolution_str:
                self.add_metadata_row("📐", "Resolution", resolution_str)
        
        # Load tags for this asset (in Tags tab)
        self.load_tags(asset)
        
        # Force tags container to update and show
        if hasattr(self, 'tags_container') and self.tags_container:
            self.tags_container.update()
            self.tags_container.updateGeometry()
            if hasattr(self, 'tags_layout'):
                self.tags_layout.update()
                self.tags_layout.activate()
    
    def add_to_cache(self, file_path, pixmap, resolution):
        """Add preview to cache with LRU eviction"""
        # If cache is full, remove oldest entry
        if len(self.preview_cache) >= self.cache_max_size:
            # Remove first (oldest) item
            first_key = next(iter(self.preview_cache))
            del self.preview_cache[first_key]
        
        # Add new entry
        self.preview_cache[file_path] = (pixmap, resolution)
    
    def show_multiple_files(self, assets):
        """Show preview and summary for multiple files"""
        count = len(assets)
        self.title_label.setText(f"🖼️ {count} files selected")
        self.clear_metadata()
        
        self.current_pixmap = None
        self.current_image_path = None  # Clear for multi-select
        self.exit_zoom_mode()  # Exit zoom mode when multi-selecting
        self.is_showing_text = False  # Reset text mode flag
        
        # Show first file preview ONLY if already in cache (instant!)
        first_asset = assets[0]
        file_path_str = str(first_asset.file_path)
        
        if first_asset.is_image_file and file_path_str in self.preview_cache:
            # Cache hit - show instantly
            pixmap, _ = self.preview_cache[file_path_str]
            self.current_pixmap = pixmap
            self.fit_pixmap_to_label()
        else:
            # No cache - show placeholder (don't load!)
            self.graphics_scene.clear()
            self.current_text_item = None
        
        # First file info
        self.add_metadata_row("📄", "First", first_asset.name)
        self.add_metadata_row("💾", "Size", self.format_file_size(first_asset.size))
        
        # Summary for remaining files
        if count > 1:
            self.metadata_layout.addSpacing(10)
            separator = QLabel("─" * 30)
            separator.setStyleSheet("color: #555;")
            self.metadata_layout.addWidget(separator)
            
            # Quick summary (no file I/O!)
            total_size = sum(a.size for a in assets)  # Size already in memory
            
            self.add_metadata_row("📊", "Total files", str(count))
            self.add_metadata_row("💾", "Total size", self.format_file_size(total_size))
            
            # Count file types (quick, no I/O)
            folders_count = sum(1 for a in assets if a.is_folder)
            files_count = count - folders_count
            
            # Build types breakdown
            type_counts = {}
            for asset in assets:
                if not asset.is_folder and asset.extension:
                    ext = asset.extension.upper()
                    type_counts[ext] = type_counts.get(ext, 0) + 1
            
            # Build types string
            types_parts = []
            
            # Add folders if any
            if folders_count > 0:
                folder_label = "Folder" if folders_count == 1 else "Folders"
                types_parts.append(f"{folders_count} {folder_label}")
            
            # Add file types if any
            if type_counts:
                types_parts.extend([f"{cnt} {ext}" for ext, cnt in sorted(type_counts.items())])
            
            # Show Types row if we have anything to show
            if types_parts:
                types_str = ", ".join(types_parts)
                self.add_metadata_row("🗂️", "Types", types_str)
        
        # Add tags display in metadata (read-only)
        self.add_metadata_tags_display(assets)
        
        # Load common tags (tags that ALL selected files share) in Tags tab
        self.load_common_tags(assets)
        
        # Force tags container to update and show
        if hasattr(self, 'tags_container') and self.tags_container:
            self.tags_container.update()
            self.tags_container.updateGeometry()
            if hasattr(self, 'tags_layout'):
                self.tags_layout.update()
                self.tags_layout.activate()
    
    def format_file_size(self, size_bytes):
        """Format file size in human readable format"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    
    def is_text_file(self, asset):
        """Check if file is a text file"""
        text_extensions = [
            '.txt', '.log', '.md', '.json', '.xml', '.yaml', '.yml',
            '.py', '.mel', '.js', '.html', '.css', '.sh', '.bat',
            '.ini', '.cfg', '.conf', '.csv', '.tsv'
        ]
        return asset.extension.lower() in text_extensions
    
    def show_text_preview(self, asset):
        """Show text file preview in graphics view"""
        try:
            # Show text controls, hide exposure controls
            self.text_controls.show()
            self.exposure_controls.hide()
            
            # Set text mode flag
            self.is_showing_text = True
            
            # Reset load full state for NEW file (different asset)
            if not hasattr(self, 'current_text_asset') or self.current_text_asset != asset:
                self.is_full_text_loaded = False
                if hasattr(self, 'load_full_btn'):
                    self.load_full_btn.setChecked(False)
                    self.load_full_btn.setText("📄 Load Full")
            
            # Store current asset for reload
            self.current_text_asset = asset
            
            # Clear scene and reset text item reference
            self.graphics_scene.clear()
            self.current_text_item = None
            
            # Read file content (with encoding detection)
            file_path_str = str(asset.file_path)
            
            # Determine read limit based on load_full mode
            if self.is_full_text_loaded:
                read_limit = None  # Read entire file
                line_limit = None  # Show all lines
            else:
                read_limit = 50000  # Read first 50KB
                line_limit = 500    # Show first 500 lines
            
            # Try UTF-8 first, fallback to latin-1
            try:
                with open(file_path_str, 'r', encoding='utf-8') as f:
                    if read_limit:
                        content = f.read(read_limit)
                    else:
                        content = f.read()
            except UnicodeDecodeError:
                with open(file_path_str, 'r', encoding='latin-1') as f:
                    if read_limit:
                        content = f.read(read_limit)
                    else:
                        content = f.read()
            
            # Store full content for clipboard
            self.current_text_content = content
            
            # Limit preview lines if needed
            lines = content.split('\n')
            total_lines = len(lines)
            
            if line_limit is not None and total_lines > line_limit:
                # Partial mode: show only first N lines
                lines = lines[:line_limit]
                lines.append(f'\n... (showing first {line_limit} lines of {total_lines}, click "Load Full" to see all) ...')
            
            preview_text = '\n'.join(lines)
            
            # Create text item with monospace font
            text_item = self.graphics_scene.addText(preview_text)
            self.current_text_item = text_item
            
            # Make text selectable and copyable
            text_item.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            
            # Apply font settings
            font = QFont("Consolas", self.font_size_slider.value())
            if not font.exactMatch():
                font = QFont("Courier New", self.font_size_slider.value())
            text_item.setFont(font)
            text_item.setDefaultTextColor(QColor(220, 220, 220))  # Light gray text
            
            # Apply line wrap setting - ALWAYS set text width to viewport
            viewport_width = self.graphics_view.viewport().width() - 20
            if self.line_wrap_checkbox.isChecked():
                text_item.setTextWidth(viewport_width)
            else:
                text_item.setTextWidth(-1)  # No wrap
            
            # Force Qt to process layout updates to ensure text is fully rendered
            QApplication.processEvents()
            
            # Force document layout to recalculate (critical for accurate bounding rect!)
            doc_layout = text_item.document().documentLayout()
            doc_layout.documentSizeChanged.emit(text_item.document().size())
            
            # Process events again after layout update
            QApplication.processEvents()
            
            # NOW get the bounding rect (should be accurate)
            text_rect = text_item.boundingRect()
            
            # Set scene rect to text bounds with extra padding at bottom
            # Add padding: 10px on sides, 100px at bottom to ensure last lines visible
            padded_rect = text_rect.adjusted(-10, -10, 10, 100)
            self.graphics_scene.setSceneRect(padded_rect)
            
            # Don't use fitInView - just reset view to show top-left
            self.graphics_view.resetTransform()
            self.graphics_view.ensureVisible(0, 0, 10, 10)
            
            # Set cursor to I-beam (text selection cursor)
            self.graphics_view.viewport().setCursor(Qt.IBeamCursor)
            
        except Exception as e:
            print(f"Text preview error: {e}")
            self.graphics_scene.clear()
            self.current_text_content = None
            self.current_text_item = None
            error_text = f"Error loading text preview:\n{str(e)}"
            text_item = self.graphics_scene.addText(error_text)
            text_item.setDefaultTextColor(QColor(255, 100, 100))  # Red for errors
    
    def on_line_wrap_changed(self, checked):
        """Handle line wrap toggle"""
        if self.current_text_item:
            try:
                viewport_width = self.graphics_view.viewport().width() - 20
                if checked:
                    # Enable wrap
                    self.current_text_item.setTextWidth(viewport_width)
                else:
                    # Disable wrap
                    self.current_text_item.setTextWidth(-1)
                
                # Force layout update
                QApplication.processEvents()
                doc_layout = self.current_text_item.document().documentLayout()
                doc_layout.documentSizeChanged.emit(self.current_text_item.document().size())
                QApplication.processEvents()
                
                # Update scene rect with padding
                text_rect = self.current_text_item.boundingRect()
                padded_rect = text_rect.adjusted(-10, -10, 10, 100)
                self.graphics_scene.setSceneRect(padded_rect)
                
                # Reset view to top
                self.graphics_view.resetTransform()
                self.graphics_view.ensureVisible(0, 0, 10, 10)
            except RuntimeError:
                # Object was already deleted, reset reference
                self.current_text_item = None
    
    def on_font_size_changed(self, value):
        """Handle font size change"""
        self.font_size_label.setText(str(value))
        
        if self.current_text_item:
            try:
                # Store scroll position
                scroll_y = self.graphics_view.verticalScrollBar().value()
                
                # Update font size
                font = QFont("Consolas", value)
                if not font.exactMatch():
                    font = QFont("Courier New", value)
                self.current_text_item.setFont(font)
                
                # Re-apply text width if wrap is enabled
                if self.line_wrap_checkbox.isChecked():
                    viewport_width = self.graphics_view.viewport().width() - 20
                    self.current_text_item.setTextWidth(viewport_width)
                
                # Force layout update
                QApplication.processEvents()
                doc_layout = self.current_text_item.document().documentLayout()
                doc_layout.documentSizeChanged.emit(self.current_text_item.document().size())
                QApplication.processEvents()
                
                # Update scene rect with padding
                text_rect = self.current_text_item.boundingRect()
                padded_rect = text_rect.adjusted(-10, -10, 10, 100)
                self.graphics_scene.setSceneRect(padded_rect)
            except RuntimeError:
                # Object was already deleted, reset reference
                self.current_text_item = None
                return
            
            # Restore scroll position
            self.graphics_view.verticalScrollBar().setValue(scroll_y)
    
    def copy_text_to_clipboard(self):
        """Copy text content to clipboard"""
        if self.current_text_content:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.current_text_content)
            
            # Show confirmation in button
            original_text = self.copy_text_btn.text()
            self.copy_text_btn.setText("✓ Copied!")
            QtCore.QTimer.singleShot(1500, lambda: self.copy_text_btn.setText(original_text))
    
    def pdf_previous_page(self):
        """Navigate to previous PDF page"""
        if self.current_pdf_page > 0:
            self.current_pdf_page -= 1
            self.reload_pdf_page()
    
    def pdf_next_page(self):
        """Navigate to next PDF page"""
        if self.current_pdf_page < self.current_pdf_page_count - 1:
            self.current_pdf_page += 1
            self.reload_pdf_page()
    
    def reload_pdf_page(self):
        """Reload current PDF page after navigation"""
        if not self.current_pdf_path:
            return
        
        # Use high resolution if in zoom mode, otherwise preview size
        target_size = 4096 if self.zoom_mode else self.max_preview_size
        
        # Load page at appropriate resolution
        pixmap, page_count, resolution = load_pdf_page(
            self.current_pdf_path, 
            self.current_pdf_page, 
            target_size
        )
        
        if pixmap:
            self.current_pixmap = pixmap
            self.set_preview_pixmap(pixmap)
            
            if self.zoom_mode:
                # In zoom mode, show full resolution at 100%
                self.graphics_scene.setSceneRect(pixmap.rect())
            else:
                # In preview mode, fit to view
                self.fit_preview_to_view()
            
            # Update overlay page indicator
            self.pdf_page_overlay.setText(f"{self.current_pdf_page + 1} / {page_count}")
            
            # Enable/disable overlay buttons
            self.pdf_prev_overlay.setEnabled(self.current_pdf_page > 0)
            self.pdf_next_overlay.setEnabled(self.current_pdf_page < page_count - 1)
            
            # Reposition overlays after content change
            self.update_pdf_overlay_positions()
        else:
            # Check if PDF is password protected
            if page_count == -1 and resolution == "encrypted":
                self.show_placeholder_with_text(f"🔒 Password Protected PDF\n\nPage {self.current_pdf_page + 1}")
            else:
                # Show error if page failed to load
                self.show_placeholder_with_text(f"Failed to load PDF page {self.current_pdf_page + 1}")
            
            self.pdf_prev_overlay.hide()
            self.pdf_next_overlay.hide()
            self.pdf_page_overlay.hide()
    
    def show_video_preview(self, asset):
        """Show video file preview using Qt Multimedia (QMediaPlayer)"""
        # Hide other controls
        self.exposure_controls.hide()
        self.text_controls.hide()
        self.sequence_playback.hide()
        
        if not self.media_player:
            # Fallback: show placeholder if Qt Multimedia not available
            self.show_placeholder_with_text("⚠️ Qt Multimedia not available\nVideo playback requires PySide6.QtMultimedia")
            return
        
        try:
            # Stop previous video if playing
            self.media_player.stop()
            
            video_path = str(asset.file_path)
            
            # Reset slider to beginning
            self.video_slider.setValue(0)
            self.video_time_label.setText("0:00 / 0:00")
            
            # Hide graphics view, show video widget
            self.graphics_view.hide()
            self.video_widget.show()
            self.video_playback.show()
            
            # Detect FPS using OpenCV
            try:
                import cv2
                # Suppress OpenCV/FFmpeg verbose output
                if hasattr(cv2, 'setLogLevel'):
                    cv2.setLogLevel(0)  # 0 = Silent
                cap = cv2.VideoCapture(video_path)
                self.video_fps = cap.get(cv2.CAP_PROP_FPS)
                cap.release()
                if self.video_fps <= 0:
                    self.video_fps = 24.0  # Fallback
            except:
                self.video_fps = 24.0  # Default fallback
            
            # Load video with QMediaPlayer
            if PYSIDE_VERSION == 6:
                from PySide6.QtCore import QUrl
                self.media_player.setSource(QUrl.fromLocalFile(video_path))
            else:
                # PySide2
                from PySide2.QtCore import QUrl
                from PySide2.QtMultimedia import QMediaContent
                self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(video_path)))
            
            # Wait for media to be loaded, then play-pause to show first frame
            self._video_needs_initial_pause = True
            
        except Exception as e:
            print(f"[PREVIEW] Video preview error: {e}")
            import traceback
            traceback.print_exc()
            self.show_placeholder_with_text(f"⚠️ Video preview error:\n{str(e)}")
    
    def show_pdf_preview(self, asset):
        """Show PDF file preview with floating overlay navigation"""
        self.is_showing_pdf = True
        self.is_showing_text = False
        self.text_controls.hide()
        
        # Load first page
        self.current_pdf_path = asset.file_path
        self.current_pdf_page = 0
        
        pixmap, page_count, resolution = load_pdf_page(
            asset.file_path, 
            0, 
            self.max_preview_size
        )
        
        if pixmap:
            self.current_pdf_page_count = page_count
            self.current_pixmap = pixmap
            self.current_image_path = asset.file_path  # Enable zoom for PDF
            self.set_preview_pixmap(pixmap)
            self.fit_preview_to_view()
            
            # Show and update PDF overlay controls
            self.pdf_page_overlay.setText(f"1 / {page_count}")
            self.pdf_prev_overlay.setEnabled(False)
            self.pdf_next_overlay.setEnabled(page_count > 1)
            
            # Show overlays
            self.pdf_prev_overlay.show()
            self.pdf_next_overlay.show()
            self.pdf_page_overlay.show()
            
            # Position overlays
            self.update_pdf_overlay_positions()
            
            # Don't steal focus from file_list - Quick View needs Space key to work
            # (Previously set focus here for PDF keyboard navigation, but that's now disabled)
            
            # Update title
            self.title_label.setText(f"Preview: {asset.name}")
        else:
            # Check if PDF is password protected
            if page_count == -1 and resolution == "encrypted":
                self.show_placeholder_with_text(f"🔒 Password Protected PDF\n\n{asset.name}")
            else:
                # Show error placeholder for other errors
                self.show_placeholder_with_text(f"Failed to load PDF:\n{asset.name}")
            
            self.pdf_prev_overlay.hide()
            self.pdf_next_overlay.hide()
            self.pdf_page_overlay.hide()
    
    def toggle_load_full_file(self):
        """Toggle between partial and full file loading"""
        if not self.current_text_asset:
            return
        
        # Toggle the flag
        self.is_full_text_loaded = self.load_full_btn.isChecked()
        
        # Update button text
        if self.is_full_text_loaded:
            self.load_full_btn.setText("📄 Partial")
            self.load_full_btn.setToolTip("Click to show preview only (faster)")
        else:
            self.load_full_btn.setText("📄 Load Full")
            self.load_full_btn.setToolTip("Load full file content (may be slow for large files)")
        
        # Reload the text preview with new mode
        self.show_text_preview(self.current_text_asset)
    
    def _is_high_bit_tiff(self, file_path):
        """
        Check if TIFF file is 16-bit or 32-bit (needs HDR treatment)
        
        Args:
            file_path: Path to TIFF file
            
        Returns:
            bool: True if 16/32-bit TIFF, False otherwise
        """
        file_ext = file_path.lower()
        if not (file_ext.endswith('.tif') or file_ext.endswith('.tiff')):
            return False
        
        # Try to detect bit depth using OpenCV if available
        if OPENCV_AVAILABLE:
            try:
                import cv2
                import numpy as np
                # Just read image info without loading full data
                img = cv2.imread(file_path, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH)
                if img is not None:
                    # Check data type - 16-bit or 32-bit float indicates HDR TIFF
                    is_hdr = img.dtype in [np.uint16, np.float32, np.float64]
                    return is_hdr
            except Exception as e:
                pass
                pass
        
        # Fallback: Use QImageReader to check format
        try:
            reader = QImageReader(file_path)
            reader.setAllocationLimit(2048)  # 2 GB limit for large images
            if reader.canRead():
                # Read just one pixel to check format
                reader.setScaledSize(QSize(1, 1))  # Minimal read
                image = reader.read()
                if not image.isNull():
                    # If depth is more than 8 bits per channel, treat as HDR
                    return image.depth() > 24  # 24 = 8 bits * 3 channels (RGB)
        except:
            pass
        
        return False
    
    def _load_tiff_as_hdr_raw(self, file_path):
        """
        Load TIFF as raw HDR float data for exposure control
        
        Args:
            file_path: Path to TIFF file
            
        Returns:
            tuple: (rgb_float_array, width, height, resolution_str) or (None, None, None, None)
        """
        if not OPENCV_AVAILABLE or not NUMPY_AVAILABLE:
            return None, None, None, None
        
        try:
            import cv2
            import numpy as np
            
            # Read image with OpenCV (preserving original bit depth)
            img = cv2.imread(file_path, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)
            
            if img is None:
                return None, None, None, None
            
            # Get dimensions
            if len(img.shape) == 2:
                height, width = img.shape
                channels = 1
            else:
                height, width, channels = img.shape
            
            resolution_str = f"{width} x {height}"
            
            # Convert to RGB if needed
            if len(img.shape) == 2:
                # Grayscale - convert to RGB
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            elif img.shape[2] == 4:
                # RGBA - convert to RGB
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
            elif img.shape[2] == 3:
                # BGR - convert to RGB
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            
            # Convert to float32 for HDR processing
            if img.dtype == np.uint8:
                # 8-bit - normalize to 0-1 range
                img_float = img.astype(np.float32) / 255.0
            elif img.dtype == np.uint16:
                # 16-bit - normalize to 0-1 range
                img_float = img.astype(np.float32) / 65535.0
            elif img.dtype in [np.float32, np.float64]:
                # 32-bit float - intelligent normalization for TIFF HDR data
                img_float = img.astype(np.float32)
                
                # Get image statistics for better normalization
                min_val = img_float.min()
                max_val = img_float.max()
                mean_val = img_float.mean()
                
                # Different normalization strategies based on data range
                if max_val <= 1.0 and min_val >= 0.0:
                    # Already in 0-1 range - use as is
                    pass
                elif max_val > 100.0:
                    # Very high values - use percentile-based normalization to preserve details
                    percentile_99 = np.percentile(img_float, 99)
                    percentile_95 = np.percentile(img_float, 95)
                    percentile_90 = np.percentile(img_float, 90)
                    
                    # Use 90th percentile for normalization to preserve most of the image
                    # but allow highlights to be clipped for better overall exposure
                    if percentile_90 > 0.1:  # Avoid division by very small numbers
                        normalization_value = percentile_90 * 2.0  # Give some headroom
                        img_float = img_float / normalization_value
                        img_float = np.clip(img_float, 0, 10.0)  # Allow significant headroom for exposure
                    else:
                        # Fallback to 99th percentile if 90th is too small
                        img_float = img_float / percentile_99
                        img_float = np.clip(img_float, 0, 5.0)
                elif max_val > 10.0:
                    # Moderate values - apply intelligent scaling
                    # Use 95th percentile to avoid outliers
                    percentile_95 = np.percentile(img_float, 95)
                    if percentile_95 > 1.0:
                        img_float = img_float / percentile_95
                        img_float = np.clip(img_float, 0, 2.0)  # Allow some headroom for exposure
                elif min_val < 0.0:
                    # Has negative values - shift and normalize
                    img_float = img_float - min_val  # Shift to start at 0
                    img_float = img_float / img_float.max()  # Normalize to 0-1
                else:
                    # Values between 1-10 - might be in linear space, use moderate normalization
                    img_float = img_float / max(max_val, 2.0)
            else:
                # Unknown format
                return None, None, None, None
            
            # Resize if too large (for performance)
            max_size = self.max_preview_size if hasattr(self, 'max_preview_size') else 1024
            if width > max_size or height > max_size:
                scale = min(max_size / width, max_size / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                img_float = cv2.resize(img_float, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                width, height = new_width, new_height
                resolution_str = f"{width} x {height} (scaled)"
            
            return img_float, width, height, resolution_str
            
        except Exception as e:
            print(f"TIFF HDR raw loading failed: {e}")
            return None, None, None, None
    
    def _load_tiff_fallback(self, file_path):
        """
        Fallback TIFF loading using the original OpenCV method
        
        Args:
            file_path: Path to TIFF file
            
        Returns:
            QPixmap or None
        """
        if not OPENCV_AVAILABLE or not NUMPY_AVAILABLE:
            return None
        
        try:
            import cv2
            import numpy as np
            
            # Read image with OpenCV
            img = cv2.imread(file_path, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)
            
            if img is None:
                return None
            
            # Normalize bit depth FIRST (before color conversion!)
            if img.dtype == np.uint16:
                img = (img / 256).astype(np.uint8)
            elif img.dtype == np.float32 or img.dtype == np.float64:
                img = np.clip(img, 0, 1)
                img = (img * 255).astype(np.uint8)
            
            # NOW convert to RGB (after normalization)
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            elif len(img.shape) == 3 and img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
            elif len(img.shape) == 3 and img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            
            # Convert to QPixmap
            height, width, channels = img.shape
            bytes_per_line = width * channels
            q_image = QImage(img.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_image.copy())
            
            return pixmap if not pixmap.isNull() else None
            
        except Exception as e:
            print(f"TIFF fallback loading failed: {e}")
            return None
    
    # Tag Management Methods
    
    def setup_tag_autocomplete(self):
        """Setup autocomplete for tag input"""
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            
            # Get all tag names
            all_tags = mm.get_all_tags()
            tag_names = [tag['name'] for tag in all_tags]
            
            # Create completer
            completer = QCompleter(tag_names)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setCompletionMode(QCompleter.PopupCompletion)
            
            # Apply to input
            self.tag_input.setCompleter(completer)
            
            if DEBUG_MODE:
                print(f"Autocomplete loaded with {len(tag_names)} tags")
        except Exception as e:
            print(f"Error setting up tag autocomplete: {e}")
    
    def show_browse_tags_dialog(self):
        """Show dialog with all available tags grouped by category"""
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            
            # Get tags grouped by category
            tags_by_category = mm.get_tags_by_category()
            
            if not tags_by_category:
                QtWidgets.QMessageBox.information(
                    self, 
                    "No Tags", 
                    "No tags are available yet. Tags will be created automatically when you add them."
                )
                return
            
            # Create dialog
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("Browse Available Tags")
            dialog.setMinimumWidth(700)
            dialog.setMinimumHeight(550)
            dialog.setModal(False)  # Non-modal - can interact with main window
            dialog.setStyleSheet(f"""
                QDialog {{
                    background-color: #2a2a2a;
                }}
                QLabel {{
                    color: #ffffff;
                    font-family: {UI_FONT};
                }}
                QCheckBox {{
                    color: #ffffff;
                    font-family: {UI_FONT};
                    font-size: 11px;
                    spacing: 5px;
                }}
                QCheckBox::indicator {{
                    width: 16px;
                    height: 16px;
                    border: 1px solid #555;
                    border-radius: 3px;
                    background-color: #3a3a3a;
                }}
                QCheckBox::indicator:checked {{
                    background-color: #4b7daa;
                    border-color: #5a8db8;
                }}
                QGroupBox {{
                    color: #ffffff;
                    border: 1px solid #555;
                    border-radius: 5px;
                    margin-top: 10px;
                    padding-top: 10px;
                    font-family: {UI_FONT};
                    font-size: 12px;
                    font-weight: bold;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 0 5px;
                    color: #4b7daa;
                }}
                QPushButton {{
                    background-color: #3a3a3a;
                    border: 1px solid #555;
                    border-radius: 3px;
                    padding: 8px 16px;
                    color: #ffffff;
                    font-family: {UI_FONT};
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: #4a4a4a;
                    border-color: #666;
                }}
                QPushButton:pressed {{
                    background-color: #2a2a2a;
                }}
                QPushButton#addButton {{
                    background-color: #4b7daa;
                    border-color: #5a8db8;
                }}
                QPushButton#addButton:hover {{
                    background-color: #5a8db8;
                }}
                QPushButton#addButton:pressed {{
                    background-color: #3a6d9a;
                }}
            """)
            
            # Main layout
            main_layout = QVBoxLayout(dialog)
            
            # Info label (will update dynamically)
            info_label = QLabel()
            def update_info_label():
                count = len(self.current_assets) if self.current_assets else 0
                if count == 0:
                    info_label.setText("No files selected. Select file(s) to add tags.")
                elif count == 1:
                    info_label.setText(f"Select tags to add to: {self.current_assets[0].name}")
                else:
                    info_label.setText(f"Select tags to add to {count} selected file(s)")
            
            update_info_label()
            info_label.setStyleSheet(f"font-size: 12px; padding: 5px; color: #cccccc; font-family: {UI_FONT};")
            main_layout.addWidget(info_label)
            
            # Store update function for later use
            dialog.update_info_label = update_info_label
            
            # Search/filter input
            search_input = QtWidgets.QLineEdit()
            search_input.setPlaceholderText("🔍 Search tags...")
            search_input.setStyleSheet(f"""
                QLineEdit {{
                    background-color: #3a3a3a;
                    border: 1px solid #555;
                    border-radius: 3px;
                    padding: 6px;
                    color: #ffffff;
                    font-family: {UI_FONT};
                    font-size: 11px;
                }}
                QLineEdit:focus {{
                    border-color: #4b7daa;
                }}
            """)
            main_layout.addWidget(search_input)
            
            # Edit Mode toggle button
            edit_mode_layout = QHBoxLayout()
            edit_mode_layout.addStretch()
            
            edit_mode_btn = QPushButton("📝 Edit Mode")
            edit_mode_btn.setCheckable(True)
            edit_mode_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #3a3a3a;
                    border: 1px solid #555;
                    border-radius: 3px;
                    padding: 6px 12px;
                    color: #cccccc;
                    font-family: {UI_FONT};
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: #4a4a4a;
                    border-color: #666;
                }}
                QPushButton:checked {{
                    background-color: #4b7daa;
                    border-color: #5a8db8;
                    color: white;
                    font-weight: bold;
                }}
                QPushButton:checked:hover {{
                    background-color: #5a8db8;
                }}
            """)
            edit_mode_layout.addWidget(edit_mode_btn)
            main_layout.addLayout(edit_mode_layout)
            
            # Store edit mode button reference on dialog
            dialog._edit_mode_btn = edit_mode_btn
            
            # Scroll area for categories
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea { border: none; }")
            
            scroll_widget = QWidget()
            scroll_layout = QVBoxLayout(scroll_widget)
            scroll_layout.setSpacing(8)
            scroll_layout.setContentsMargins(8, 8, 8, 8)
            
            # Store tag chip buttons and category widgets for filtering
            tag_buttons = {}
            category_widgets = {}  # {category_name: {'label': QLabel, 'container': QWidget, 'separator': QLabel}}
            
            # Create collapsible group for each category
            for category in sorted(tags_by_category.keys()):
                tags = tags_by_category[category]
                
                # Category header
                category_label = QLabel(f"▼ {category}")
                category_label.setStyleSheet(f"""
                    font-size: 11px;
                    font-weight: bold;
                    color: #cccccc;
                    padding: 3px 0px 2px 0px;
                    font-family: {UI_FONT};
                """)
                scroll_layout.addWidget(category_label)
                
                # Container for tag chips with flow layout
                chips_container = QWidget()
                chips_layout = FlowLayout()
                chips_layout.setSpacing(5)
                chips_layout.setContentsMargins(0, 3, 0, 3)
                
                # Get current file tags for visualization
                current_file_tags = {}  # {tag_id: count}
                if self.current_assets:
                    for asset in self.current_assets:
                        file_path = str(asset.file_path)
                        file_meta = mm.get_file_metadata(file_path)
                        if file_meta and file_meta.get('tags'):
                            for tag_dict in file_meta['tags']:
                                tag_id = tag_dict['id']
                                current_file_tags[tag_id] = current_file_tags.get(tag_id, 0) + 1
                
                total_files = len(self.current_assets) if self.current_assets else 0
                
                # Create chip-style toggle button for each tag
                for tag in sorted(tags, key=lambda x: x['name']):
                    tag_id = tag['id']
                    tag_name = tag['name']
                    
                    # Check if this tag exists on selected files
                    tag_count = current_file_tags.get(tag_id, 0)
                    
                    # Determine button text and styling
                    if tag_count == 0:
                        # No files have this tag - normal (no X button)
                        btn_text = tag_name
                        bg_color = "#4a4a4a"
                        text_color = "white"
                        has_remove_btn = False
                    elif tag_count == total_files:
                        # ALL files have this tag - green tint (with X button)
                        btn_text = f"✓ {tag_name}"
                        bg_color = "#2a5a2a"  # Dark green
                        text_color = "#90EE90"  # Light green
                        has_remove_btn = True
                    else:
                        # SOME files have this tag - show count (with X button)
                        btn_text = f"{tag_name} ({tag_count}/{total_files})"
                        bg_color = "#4a4a2a"  # Yellowish tint
                        text_color = "#FFD700"  # Gold
                        has_remove_btn = True
                    
                    # Create container widget for button + remove button
                    chip_widget = QWidget()
                    chip_layout = QHBoxLayout(chip_widget)
                    chip_layout.setContentsMargins(0, 0, 0, 0)
                    chip_layout.setSpacing(0)
                    
                    chip_btn = QtWidgets.QPushButton(btn_text)
                    chip_btn.setCheckable(True)
                    chip_btn.setProperty('tag_data', tag)
                    chip_btn.setProperty('tag_count', tag_count)
                    chip_btn.setProperty('total_files', total_files)
                    chip_btn.setFixedHeight(26)
                    chip_btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {bg_color};
                            border: 1px solid #555;
                            border-radius: 3px;
                            padding: 4px 10px;
                            color: {text_color};
                            font-family: {UI_FONT};
                            font-size: 11px;
                            text-align: left;
                        }}
                        QPushButton:hover {{
                            background-color: #5a5a5a;
                            border-color: #666;
                        }}
                        QPushButton:checked {{
                            background-color: #4b7daa;
                            border-color: #5a8db8;
                            color: #ffffff;
                            font-weight: bold;
                        }}
                        QPushButton:checked:hover {{
                            background-color: #5a8db8;
                        }}
                    """)
                    
                    chip_layout.addWidget(chip_btn)
                    
                    # Always create remove button, but hide if not needed
                    remove_btn = QtWidgets.QPushButton("×")
                    remove_btn.setFixedSize(20, 26)
                    remove_btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {bg_color};
                            border: 1px solid #555;
                            border-left: none;
                            border-radius: 0px 3px 3px 0px;
                            color: {text_color};
                            font-family: {UI_FONT};
                            font-size: 14px;
                            font-weight: bold;
                            padding: 0px;
                        }}
                        QPushButton:hover {{
                            background-color: #8B0000;
                            color: white;
                        }}
                        QPushButton:pressed {{
                            background-color: #6B0000;
                        }}
                    """)
                    remove_btn.clicked.connect(
                        lambda checked=False, td=tag, dlg=dialog, btns=tag_buttons: self._remove_tag_from_selection(td, dlg, btns)
                    )
                    remove_btn.setToolTip(f"Remove '{tag_name}' from selection")
                    chip_layout.addWidget(remove_btn)
                    
                    # Show/hide based on tag count
                    if has_remove_btn:
                        remove_btn.show()
                        # Adjust main button border radius (no right radius)
                        chip_btn.setStyleSheet(f"""
                            QPushButton {{
                                background-color: {bg_color};
                                border: 1px solid #555;
                                border-radius: 3px 0px 0px 3px;
                                padding: 4px 10px;
                                color: {text_color};
                                font-family: {UI_FONT};
                                font-size: 11px;
                                text-align: left;
                            }}
                            QPushButton:hover {{
                                background-color: #5a5a5a;
                                border-color: #666;
                            }}
                            QPushButton:checked {{
                                background-color: #4b7daa;
                                border-color: #5a8db8;
                                color: #ffffff;
                                font-weight: bold;
                            }}
                            QPushButton:checked:hover {{
                                background-color: #5a8db8;
                            }}
                        """)
                    else:
                        remove_btn.hide()
                    
                    # Store reference to main button
                    chip_widget._main_button = chip_btn
                    chip_widget._tag_data = tag
                    
                    tag_buttons[tag['id']] = chip_widget
                    chips_layout.addWidget(chip_widget)
                
                chips_container.setLayout(chips_layout)
                scroll_layout.addWidget(chips_container)
                
                # Add thin separator line
                separator = QLabel()
                separator.setFixedHeight(1)
                separator.setStyleSheet("background-color: #3a3a3a; margin: 2px 0px;")
                scroll_layout.addWidget(separator)
                
                # Store category widgets for filtering
                category_widgets[category] = {
                    'label': category_label,
                    'container': chips_container,
                    'separator': separator
                }
            
            scroll_layout.addStretch()
            scroll.setWidget(scroll_widget)
            main_layout.addWidget(scroll)
            
            # Connect search input to filter function
            def filter_tags():
                search_text = search_input.text().strip().lower()
                
                for category, widgets in category_widgets.items():
                    category_label = widgets['label']
                    chips_container = widgets['container']
                    separator = widgets['separator']
                    
                    # Get all tag buttons in this category
                    visible_count = 0
                    chips_layout = chips_container.layout()
                    
                    for i in range(chips_layout.count()):
                        item = chips_layout.itemAt(i)
                        if item and item.widget():
                            chip_widget = item.widget()
                            
                            # Get main button from chip widget
                            if hasattr(chip_widget, '_main_button'):
                                tag_btn = chip_widget._main_button
                                tag_name = tag_btn.text().lower()
                                
                                # Show/hide based on search
                                if not search_text or search_text in tag_name:
                                    chip_widget.show()
                                    visible_count += 1
                                else:
                                    chip_widget.hide()
                    
                    # Show/hide category if no tags match
                    if visible_count > 0:
                        category_label.show()
                        chips_container.show()
                        separator.show()
                    else:
                        category_label.hide()
                        chips_container.hide()
                        separator.hide()
            
            # Note: search filter connected later after dialog setup
            
            # Button layout
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            
            # Select All / Deselect All buttons
            select_all_btn = QPushButton("Select All")
            select_all_btn.clicked.connect(lambda: self._toggle_all_tag_buttons(tag_buttons, True))
            button_layout.addWidget(select_all_btn)
            
            deselect_all_btn = QPushButton("Deselect All")
            deselect_all_btn.clicked.connect(lambda: self._toggle_all_tag_buttons(tag_buttons, False))
            button_layout.addWidget(deselect_all_btn)
            
            button_layout.addStretch()
            
            # Clear All Tags button
            clear_all_btn = QPushButton("🗑️ Clear All Tags")
            clear_all_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #3a3a3a;
                    border: 1px solid #555;
                    border-radius: 3px;
                    padding: 8px 16px;
                    color: #cccccc;
                    font-family: {UI_FONT};
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: #8B0000;
                    border-color: #A00000;
                    color: white;
                }}
                QPushButton:pressed {{
                    background-color: #6B0000;
                }}
            """)
            clear_all_btn.clicked.connect(self.clear_all_tags_from_selection)
            clear_all_btn.setToolTip("Remove all tags from selected file(s)")
            button_layout.addWidget(clear_all_btn)
            
            button_layout.addStretch()
            
            # Add Selected button
            add_btn = QPushButton("Add Selected Tags")
            add_btn.setObjectName("addButton")
            add_btn.clicked.connect(lambda: self._add_selected_tags(dialog, tag_buttons))
            button_layout.addWidget(add_btn)
            
            # Cancel button
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(dialog.reject)
            button_layout.addWidget(cancel_btn)
            
            main_layout.addLayout(button_layout)
            
            # Store dialog and buttons for later refresh
            dialog._tag_buttons = tag_buttons
            dialog._mm = mm
            dialog._edit_mode = False
            dialog._category_widgets = category_widgets
            dialog._add_btn = add_btn
            dialog._clear_all_btn = clear_all_btn
            dialog._info_label = info_label
            dialog._search_input = search_input
            
            # Connect search filter
            search_input.textChanged.connect(lambda: self._filter_browse_tags(dialog))
            
            # Connect edit mode toggle
            def toggle_edit_mode(checked):
                dialog._edit_mode = checked
                if checked:
                    edit_mode_btn.setText("✅ Edit Mode")
                    # Hide add/clear buttons in edit mode
                    add_btn.hide()
                    clear_all_btn.hide()
                    # Update info label
                    info_label.setText("📝 Edit Mode: Manage categories and tags")
                    # Switch to edit view
                    self._switch_to_edit_mode(dialog, tag_buttons, category_widgets, scroll_layout, mm)
                else:
                    edit_mode_btn.setText("📝 Edit Mode")
                    # Show add/clear buttons
                    add_btn.show()
                    clear_all_btn.show()
                    # Restore info label
                    update_info_label()
                    # Switch back to normal view
                    self._switch_to_normal_mode(dialog, tag_buttons, category_widgets)
            
            edit_mode_btn.toggled.connect(toggle_edit_mode)
            
            # Store active browse dialog reference in main window
            self._active_browse_dialog = dialog
            
            # Clear reference when dialog is destroyed
            dialog.destroyed.connect(lambda: setattr(self, '_active_browse_dialog', None))
            
            # Show dialog (modeless - non-blocking)
            dialog.show()
            
        except Exception as e:
            print(f"Error showing browse tags dialog: {e}")
            import traceback
            traceback.print_exc()
    
    def _toggle_all_tag_buttons(self, tag_buttons, checked):
        """Toggle all tag chip buttons in the browse tags dialog"""
        for chip_widget in tag_buttons.values():
            if hasattr(chip_widget, '_main_button'):
                chip_widget._main_button.setChecked(checked)
    
    def _filter_browse_tags(self, dialog):
        """Filter tags in browse dialog based on search input"""
        if not hasattr(dialog, '_search_input') or not hasattr(dialog, '_category_widgets'):
            return
        
        search_text = dialog._search_input.text().strip().lower()
        category_widgets = dialog._category_widgets
        
        # Check if we're in edit mode
        is_edit_mode = hasattr(dialog, '_edit_mode_btn') and dialog._edit_mode_btn.isChecked()
        
        for category, widgets in category_widgets.items():
            category_label = widgets['label']
            chips_container = widgets['container']
            separator = widgets['separator']
            
            # In edit mode, use edit_label and tag_list instead
            if is_edit_mode:
                category_display = widgets.get('edit_label', category_label)
                tags_display = widgets.get('tag_list', chips_container)
            else:
                category_display = category_label
                tags_display = chips_container
            
            # Get all tag buttons in this category
            visible_count = 0
            
            if is_edit_mode and 'tag_list' in widgets:
                # In edit mode, check tag_list items
                tag_list = widgets['tag_list']
                tag_list_layout = tag_list.layout()
                
                if tag_list_layout:
                    for i in range(tag_list_layout.count()):
                        item = tag_list_layout.itemAt(i)
                        if item and item.widget():
                            tag_row = item.widget()
                            # Get tag name from the row (first label in the layout)
                            if hasattr(tag_row, 'layout') and tag_row.layout():
                                row_layout = tag_row.layout()
                                if row_layout.count() > 0:
                                    first_item = row_layout.itemAt(0)
                                    if first_item and isinstance(first_item.widget(), QLabel):
                                        tag_label = first_item.widget()
                                        # Remove bullet point "• " from tag name
                                        tag_text = tag_label.text()
                                        tag_name = tag_text.replace("• ", "").lower()
                                        
                                        if not search_text or search_text in tag_name:
                                            tag_row.show()
                                            visible_count += 1
                                        else:
                                            tag_row.hide()
            else:
                # Normal mode - check chip widgets
                chips_layout = chips_container.layout()
                
                if chips_layout is None:
                    continue
                
                for i in range(chips_layout.count()):
                    item = chips_layout.itemAt(i)
                    if item and item.widget():
                        chip_widget = item.widget()
                        
                        # Get main button from chip widget
                        if hasattr(chip_widget, '_main_button'):
                            tag_btn = chip_widget._main_button
                            tag_name = tag_btn.text().lower()
                            
                            # Show/hide based on search
                            if not search_text or search_text in tag_name:
                                chip_widget.show()
                                visible_count += 1
                            else:
                                chip_widget.hide()
            
            # Show/hide category if no tags match
            if visible_count > 0:
                category_display.show()
                tags_display.show()
                separator.show()
            else:
                category_display.hide()
                tags_display.hide()
                separator.hide()
    
    def _switch_to_edit_mode(self, dialog, tag_buttons, category_widgets, scroll_layout, mm):
        """Switch Browse Tags dialog to edit mode"""
        # Hide tag chip buttons (normal mode)
        for chip_widget in tag_buttons.values():
            chip_widget.hide()
        
        # Show edit widgets for each category
        for category_name, widgets in category_widgets.items():
            label = widgets['label']
            container = widgets['container']
            
            # Remove existing edit widgets if they exist
            if 'edit_label' in widgets and widgets['edit_label']:
                old_edit_label = widgets['edit_label']
                old_edit_label.setParent(None)
                old_edit_label.deleteLater()
                widgets['edit_label'] = None
            
            if 'tag_list' in widgets and widgets['tag_list']:
                old_tag_list = widgets['tag_list']
                old_tag_list.setParent(None)
                old_tag_list.deleteLater()
                widgets['tag_list'] = None
            
            # Update category label with edit buttons
            edit_label = QWidget()
            edit_layout = QHBoxLayout(edit_label)
            edit_layout.setContentsMargins(0, 0, 0, 0)
            edit_layout.setSpacing(8)
            
            cat_text = QLabel(f"▼ {category_name}")
            cat_text.setStyleSheet(f"font-size: 11px; font-weight: bold; color: #cccccc; font-family: {UI_FONT};")
            edit_layout.addWidget(cat_text)
            
            # Edit category button
            edit_cat_btn = QPushButton("Rename")
            edit_cat_btn.setFixedHeight(24)
            edit_cat_btn.setMinimumWidth(60)
            edit_cat_btn.setToolTip("Rename category")
            edit_cat_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #3a3a3a;
                    border: 1px solid #555;
                    border-radius: 3px;
                    color: #cccccc;
                    font-size: 10px;
                    font-family: {UI_FONT};
                    padding: 2px 10px;
                }}
                QPushButton:hover {{
                    background-color: #4b7daa;
                    color: white;
                }}
            """)
            edit_cat_btn.clicked.connect(lambda checked=False, cat=category_name: self._edit_category_name(dialog, cat, mm))
            edit_layout.addWidget(edit_cat_btn)
            
            # Delete category button
            del_cat_btn = QPushButton("Delete")
            del_cat_btn.setFixedHeight(24)
            del_cat_btn.setMinimumWidth(60)
            del_cat_btn.setToolTip("Delete category")
            del_cat_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #3a3a3a;
                    border: 1px solid #555;
                    border-radius: 3px;
                    color: #cccccc;
                    font-size: 10px;
                    font-family: {UI_FONT};
                    padding: 2px 10px;
                }}
                QPushButton:hover {{
                    background-color: #8B0000;
                    color: white;
                }}
            """)
            del_cat_btn.clicked.connect(lambda checked=False, cat=category_name: self._delete_category(dialog, cat, mm))
            edit_layout.addWidget(del_cat_btn)
            
            edit_layout.addStretch()
            
            # Replace label
            label.hide()
            scroll_layout.insertWidget(scroll_layout.indexOf(label), edit_label)
            widgets['edit_label'] = edit_label
            
            # Create tag list for this category
            tags = mm.get_tags_by_category().get(category_name, [])
            tag_list_widget = QWidget()
            tag_list_layout = QVBoxLayout(tag_list_widget)
            tag_list_layout.setContentsMargins(20, 5, 5, 5)
            tag_list_layout.setSpacing(3)
            
            for tag in tags:
                tag_row = QWidget()
                tag_row_layout = QHBoxLayout(tag_row)
                tag_row_layout.setContentsMargins(0, 0, 0, 0)
                tag_row_layout.setSpacing(8)
                
                # Tag name bullet
                tag_label = QLabel(f"• {tag['name']}")
                tag_label.setStyleSheet(f"color: #cccccc; font-family: {UI_FONT}; font-size: 11px;")
                tag_row_layout.addWidget(tag_label)
                tag_row_layout.addStretch()
                
                # Move to category button
                move_tag_btn = QPushButton("Move to...")
                move_tag_btn.setFixedHeight(22)
                move_tag_btn.setMinimumWidth(70)
                move_tag_btn.setToolTip("Move tag to another category")
                move_tag_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #3a3a3a;
                        border: 1px solid #555;
                        border-radius: 3px;
                        color: #cccccc;
                        font-size: 10px;
                        font-family: {UI_FONT};
                        padding: 2px 8px;
                    }}
                    QPushButton:hover {{
                        background-color: #2a5a2a;
                        color: #90EE90;
                    }}
                """)
                move_tag_btn.clicked.connect(lambda checked=False, t=tag: self._move_tag_to_category(dialog, t, mm))
                tag_row_layout.addWidget(move_tag_btn)
                
                # Edit tag button
                edit_tag_btn = QPushButton("Rename")
                edit_tag_btn.setFixedHeight(22)
                edit_tag_btn.setMinimumWidth(55)
                edit_tag_btn.setToolTip("Rename tag")
                edit_tag_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #3a3a3a;
                        border: 1px solid #555;
                        border-radius: 3px;
                        color: #cccccc;
                        font-size: 10px;
                        font-family: {UI_FONT};
                        padding: 2px 8px;
                    }}
                    QPushButton:hover {{
                        background-color: #4b7daa;
                        color: white;
                    }}
                """)
                edit_tag_btn.clicked.connect(lambda checked=False, t=tag: self._edit_tag_name(dialog, t, mm))
                tag_row_layout.addWidget(edit_tag_btn)
                
                # Delete tag button
                del_tag_btn = QPushButton("Delete")
                del_tag_btn.setFixedHeight(22)
                del_tag_btn.setMinimumWidth(55)
                del_tag_btn.setToolTip("Delete tag")
                del_tag_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #3a3a3a;
                        border: 1px solid #555;
                        border-radius: 3px;
                        color: #cccccc;
                        font-size: 10px;
                        font-family: {UI_FONT};
                        padding: 2px 8px;
                    }}
                    QPushButton:hover {{
                        background-color: #8B0000;
                        color: white;
                    }}
                """)
                del_tag_btn.clicked.connect(lambda checked=False, t=tag: self._delete_tag(dialog, t, mm))
                tag_row_layout.addWidget(del_tag_btn)
                
                tag_list_layout.addWidget(tag_row)
            
            # Add tag button
            add_tag_btn = QPushButton("➕ Add Tag")
            add_tag_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #2a5a2a;
                    border: 1px solid #3a7a3a;
                    border-radius: 3px;
                    padding: 4px 8px;
                    color: #90EE90;
                    font-family: {UI_FONT};
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    background-color: #3a7a3a;
                    color: white;
                }}
            """)
            add_tag_btn.clicked.connect(lambda checked=False, cat=category_name: self._add_tag_to_category(dialog, cat, mm))
            tag_list_layout.addWidget(add_tag_btn)
            
            # Hide chip container, show tag list
            container.hide()
            scroll_layout.insertWidget(scroll_layout.indexOf(container), tag_list_widget)
            widgets['tag_list'] = tag_list_widget
        
        # Add "Add Category" button at bottom
        add_cat_widget = QWidget()
        add_cat_layout = QHBoxLayout(add_cat_widget)
        add_cat_layout.setContentsMargins(0, 10, 0, 0)
        
        add_cat_btn = QPushButton("➕ Add Category")
        add_cat_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2a5a2a;
                border: 1px solid #3a7a3a;
                border-radius: 3px;
                padding: 8px 16px;
                color: #90EE90;
                font-family: {UI_FONT};
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #3a7a3a;
                color: white;
            }}
        """)
        add_cat_btn.clicked.connect(lambda: self._add_category(dialog, mm))
        add_cat_layout.addWidget(add_cat_btn)
        add_cat_layout.addStretch()
        
        scroll_layout.addWidget(add_cat_widget)
        dialog._add_cat_widget = add_cat_widget
    
    def _switch_to_normal_mode(self, dialog, tag_buttons, category_widgets):
        """Switch Browse Tags dialog back to normal mode"""
        # Show tag chip buttons
        for chip_widget in tag_buttons.values():
            if chip_widget:
                try:
                    chip_widget.show()
                except (RuntimeError, AttributeError):
                    pass  # Already deleted
        
        # Remove edit widgets and restore original labels
        for category_name, widgets in list(category_widgets.items()):
            # Safely remove edit_label
            if 'edit_label' in widgets and widgets['edit_label']:
                try:
                    widgets['edit_label'].setParent(None)
                    widgets['edit_label'].deleteLater()
                except (RuntimeError, AttributeError):
                    pass  # Already deleted
                widgets['edit_label'] = None
                
                if 'label' in widgets and widgets['label']:
                    try:
                        widgets['label'].show()
                    except (RuntimeError, AttributeError):
                        pass
            
            # Safely remove tag_list
            if 'tag_list' in widgets and widgets['tag_list']:
                try:
                    widgets['tag_list'].setParent(None)
                    widgets['tag_list'].deleteLater()
                except (RuntimeError, AttributeError):
                    pass  # Already deleted
                widgets['tag_list'] = None
                
                if 'container' in widgets and widgets['container']:
                    try:
                        widgets['container'].show()
                    except (RuntimeError, AttributeError):
                        pass
        
        # Remove add category button
        if hasattr(dialog, '_add_cat_widget') and dialog._add_cat_widget:
            try:
                dialog._add_cat_widget.setParent(None)
                dialog._add_cat_widget.deleteLater()
            except (RuntimeError, AttributeError):
                pass  # Already deleted
            dialog._add_cat_widget = None
    
    def _edit_category_name(self, dialog, category_name, mm):
        """Edit category name"""
        # Check if category has any tags
        tags_by_category = mm.get_tags_by_category()
        if category_name not in tags_by_category or len(tags_by_category[category_name]) == 0:
            QtWidgets.QMessageBox.warning(
                dialog,
                "Cannot Rename",
                f"Category '{category_name}' has no tags.\n\n"
                "Add tags to this category first, or delete it."
            )
            return
        
        new_name, ok = QtWidgets.QInputDialog.getText(
            dialog,
            "Rename Category",
            f"Rename category '{category_name}' to:",
            QtWidgets.QLineEdit.Normal,
            category_name
        )
        
        if ok and new_name and new_name != category_name:
            if mm.update_category_name(category_name, new_name):
                # Refresh edit mode view
                self._refresh_edit_mode(dialog, mm)
            else:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Error",
                    "Failed to rename category"
                )
    
    def _delete_category(self, dialog, category_name, mm):
        """Delete category"""
        reply = QtWidgets.QMessageBox.warning(
            dialog,
            "Delete Category",
            f"Delete category '{category_name}' and all its tags?\n\nThis will also remove all file associations!",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            if mm.delete_category(category_name):
                # Refresh edit mode view
                self._refresh_edit_mode(dialog, mm)
            else:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Error",
                    "Failed to delete category"
                )
    
    def _edit_tag_name(self, dialog, tag, mm):
        """Edit tag name"""
        new_name, ok = QtWidgets.QInputDialog.getText(
            dialog,
            "Rename Tag",
            f"Rename tag '{tag['name']}' to:",
            QtWidgets.QLineEdit.Normal,
            tag['name']
        )
        
        if ok and new_name and new_name != tag['name']:
            if mm.update_tag_name(tag['id'], new_name):
                # Refresh edit mode view
                self._refresh_edit_mode(dialog, mm)
            else:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Error",
                    f"Failed to rename tag. Tag '{new_name}' may already exist."
                )
    
    def _move_tag_to_category(self, dialog, tag, mm):
        """Move tag to another category"""
        # Get all categories
        tags_by_category = mm.get_tags_by_category()
        categories = sorted(tags_by_category.keys())
        
        # Remove current category from list
        current_category = tag.get('category') or 'Uncategorized'
        if current_category in categories:
            categories.remove(current_category)
        
        if not categories:
            QtWidgets.QMessageBox.information(
                dialog,
                "No Categories",
                "No other categories available. Create a new category first."
            )
            return
        
        # Show selection dialog
        category, ok = QtWidgets.QInputDialog.getItem(
            dialog,
            "Move Tag",
            f"Move tag '{tag['name']}' to category:",
            categories,
            0,
            False
        )
        
        if ok and category:
            if mm.move_tag_to_category(tag['id'], category):
                # Refresh edit mode view
                self._refresh_edit_mode(dialog, mm)
            else:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Error",
                    "Failed to move tag"
                )
    
    def _delete_tag(self, dialog, tag, mm):
        """Delete tag"""
        reply = QtWidgets.QMessageBox.warning(
            dialog,
            "Delete Tag",
            f"Delete tag '{tag['name']}'?\n\nThis will remove it from all files!",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            if mm.delete_tag(tag['id']):
                # Refresh edit mode view
                self._refresh_edit_mode(dialog, mm)
            else:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Error",
                    "Failed to delete tag"
                )
    
    def _add_tag_to_category(self, dialog, category_name, mm):
        """Add new tag to category"""
        tag_name, ok = QtWidgets.QInputDialog.getText(
            dialog,
            "Add Tag",
            f"Enter new tag name for category '{category_name}':",
            QtWidgets.QLineEdit.Normal,
            ""
        )
        
        if ok and tag_name:
            tag_id = mm.add_tag(tag_name, category=category_name)
            if tag_id:
                # Refresh edit mode view
                self._refresh_edit_mode(dialog, mm)
            else:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Error",
                    f"Failed to add tag. Tag '{tag_name}' may already exist."
                )
    
    def _add_category(self, dialog, mm):
        """Add new category"""
        category_name, ok = QtWidgets.QInputDialog.getText(
            dialog,
            "Add Category",
            "Enter new category name:",
            QtWidgets.QLineEdit.Normal,
            ""
        )
        
        if ok and category_name:
            # Check if category already exists
            tags_by_category = mm.get_tags_by_category()
            if category_name in tags_by_category:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Category Exists",
                    f"Category '{category_name}' already exists!"
                )
                return
            
            # Get uncategorized tags
            uncategorized_tags = tags_by_category.get('Uncategorized', [])
            
            if uncategorized_tags:
                # Show dialog to choose existing uncategorized tag or create new
                tag_names = [tag['name'] for tag in uncategorized_tags]
                tag_names.insert(0, "➕ Create New Tag...")
                
                choice, ok2 = QtWidgets.QInputDialog.getItem(
                    dialog,
                    "Add Tag to Category",
                    f"Select an uncategorized tag to move to '{category_name}',\nor create a new one:",
                    tag_names,
                    0,
                    False
                )
                
                if ok2:
                    if choice == "➕ Create New Tag...":
                        # Create new tag
                        new_tag_name, ok3 = QtWidgets.QInputDialog.getText(
                            dialog,
                            "Create New Tag",
                            f"Enter new tag name for '{category_name}':",
                            QtWidgets.QLineEdit.Normal,
                            ""
                        )
                        
                        if ok3 and new_tag_name:
                            tag_id = mm.add_tag(new_tag_name, category=category_name)
                            if tag_id:
                                self._refresh_edit_mode(dialog, mm)
                            else:
                                QtWidgets.QMessageBox.warning(
                                    dialog,
                                    "Error",
                                    f"Failed to add tag. Tag '{new_tag_name}' may already exist."
                                )
                    else:
                        # Move existing tag to new category
                        selected_tag = next((t for t in uncategorized_tags if t['name'] == choice), None)
                        if selected_tag:
                            if mm.move_tag_to_category(selected_tag['id'], category_name):
                                self._refresh_edit_mode(dialog, mm)
                            else:
                                QtWidgets.QMessageBox.warning(
                                    dialog,
                                    "Error",
                                    "Failed to move tag"
                                )
            else:
                # No uncategorized tags, create new tag
                tag_name, ok2 = QtWidgets.QInputDialog.getText(
                    dialog,
                    "Add First Tag",
                    f"Add first tag for category '{category_name}':\n(No uncategorized tags available)",
                    QtWidgets.QLineEdit.Normal,
                    ""
                )
                
                if ok2 and tag_name:
                    tag_id = mm.add_tag(tag_name, category=category_name)
                    if tag_id:
                        self._refresh_edit_mode(dialog, mm)
                    else:
                        QtWidgets.QMessageBox.warning(
                            dialog,
                            "Error",
                            f"Failed to add tag. Tag '{tag_name}' may already exist."
                        )
    
    def _refresh_edit_mode(self, dialog, mm):
        """Refresh edit mode view after changes"""
        # Get references
        tag_buttons = dialog._tag_buttons
        category_widgets = dialog._category_widgets
        
        # Find scroll area and save position
        scroll_area = dialog.findChild(QScrollArea)
        scroll_widget = scroll_area.widget()
        scroll_layout = scroll_widget.layout()
        
        # Save scroll position
        scroll_position = scroll_area.verticalScrollBar().value()
        
        # Switch to normal mode (cleans up edit widgets)
        self._switch_to_normal_mode(dialog, tag_buttons, category_widgets)
        
        # Remove "Add Category" button if exists
        if hasattr(dialog, '_add_cat_widget') and dialog._add_cat_widget:
            dialog._add_cat_widget.setParent(None)
            dialog._add_cat_widget.deleteLater()
            dialog._add_cat_widget = None
        
        # Rebuild tag buttons from database
        tags_by_category = mm.get_tags_by_category()
        
        # Clear old category widgets
        dialog._category_widgets = {}
        
        # Remove all widgets from scroll layout
        while scroll_layout.count():
            item = scroll_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()
        
        # Recreate category structure (similar to show_browse_tags_dialog)
        category_widgets = {}
        new_tag_buttons = {}
        
        for category in sorted(tags_by_category.keys()):
            tags = tags_by_category[category]
            
            # Category header
            category_label = QLabel(f"▼ {category}")
            category_label.setStyleSheet(f"""
                font-size: 11px;
                font-weight: bold;
                color: #cccccc;
                padding: 3px 0px 2px 0px;
                font-family: {UI_FONT};
            """)
            scroll_layout.addWidget(category_label)
            
            # Container for tag chips
            chips_container = QWidget()
            chips_layout = FlowLayout()
            
            for tag in tags:
                # Create chip widget (simplified - just for structure, will be hidden in edit mode)
                chip_widget = QWidget()
                chip_layout = QHBoxLayout(chip_widget)
                chip_layout.setContentsMargins(0, 0, 0, 0)
                chip_layout.setSpacing(0)
                
                chip_btn = QPushButton(tag['name'])
                chip_btn.setCheckable(True)
                chip_btn.setProperty('tag_data', tag)
                chip_layout.addWidget(chip_btn)
                
                chip_widget._main_button = chip_btn
                chip_widget._tag_data = tag
                
                new_tag_buttons[tag['id']] = chip_widget
                chips_layout.addWidget(chip_widget)
            
            chips_container.setLayout(chips_layout)
            scroll_layout.addWidget(chips_container)
            
            # Separator
            separator = QLabel()
            separator.setFixedHeight(1)
            separator.setStyleSheet("background-color: #555; margin: 8px 0px;")
            scroll_layout.addWidget(separator)
            
            # Store references
            category_widgets[category] = {
                'label': category_label,
                'container': chips_container,
                'separator': separator
            }
        
        # Update dialog references
        dialog._tag_buttons = new_tag_buttons
        dialog._category_widgets = category_widgets
        
        # Switch back to edit mode
        self._switch_to_edit_mode(dialog, new_tag_buttons, category_widgets, scroll_layout, mm)
        
        # Restore scroll position after a short delay (widgets need to be rendered)
        try:
            from PySide6.QtCore import QTimer
        except ImportError:
            from PySide2.QtCore import QTimer
        
        QTimer.singleShot(50, lambda: scroll_area.verticalScrollBar().setValue(scroll_position))
    
    def _show_tag_context_menu(self, pos, button, dialog, tag_buttons):
        """Show context menu for tag button in browse dialog"""
        tag_data = button.property('tag_data')
        tag_count = button.property('tag_count')
        
        if tag_count == 0:
            # No files have this tag - no context menu needed
            return
        
        menu = QtWidgets.QMenu()
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: #2a2a2a;
                border: 1px solid #555;
                color: white;
                font-family: {UI_FONT};
                font-size: 11px;
            }}
            QMenu::item:selected {{
                background-color: #4b7daa;
            }}
        """)
        
        remove_action = menu.addAction(f"🗑️ Remove '{tag_data['name']}' from selection")
        
        action = menu.exec_(button.mapToGlobal(pos))
        
        if action == remove_action:
            self._remove_tag_from_selection(tag_data, dialog, tag_buttons)
    
    def _remove_tag_from_selection(self, tag_data, dialog, tag_buttons):
        """Remove specific tag from all selected files"""
        if not self.current_assets:
            return
        
        try:
            mm = dialog._mm if hasattr(dialog, '_mm') else None
            if not mm:
                from .metadata import get_metadata_manager
                mm = get_metadata_manager()
            
            tag_id = tag_data['id']
            tag_name = tag_data['name']
            
            # Remove from all selected files
            removed_count = 0
            for asset in self.current_assets:
                file_path = str(asset.file_path)
                mm.remove_tag_from_file(file_path, tag_id)
                removed_count += 1
            
            # Reload displays
            if len(self.current_assets) == 1:
                self.load_tags(self.current_assets[0])
            else:
                self.load_common_tags(self.current_assets)
            
            self.update_preview(self.current_assets)
            
            # Refresh browse dialog buttons
            self._refresh_browse_dialog_buttons(dialog, tag_buttons, mm)
            
            print(f"✓ Removed '{tag_name}' from {removed_count} file(s)")
            
        except Exception as e:
            print(f"Error removing tag: {e}")
            import traceback
            traceback.print_exc()
    
    def _refresh_browse_dialog_buttons(self, dialog, tag_buttons, mm):
        """Refresh button colors/text in browse dialog based on current selection"""
        # If no selection, treat as 0 files (all tags grey)
        if not self.current_assets:
            current_file_tags = {}
            total_files = 0
        else:
            # Recalculate current file tags
            current_file_tags = {}
            for asset in self.current_assets:
                file_path = str(asset.file_path)
                file_meta = mm.get_file_metadata(file_path)
                if file_meta and file_meta.get('tags'):
                    for tag_dict in file_meta['tags']:
                        tag_id = tag_dict['id']
                        current_file_tags[tag_id] = current_file_tags.get(tag_id, 0) + 1
            
            total_files = len(self.current_assets)
        
        # Update each chip widget
        for tag_id, chip_widget in tag_buttons.items():
            if not hasattr(chip_widget, '_main_button') or not hasattr(chip_widget, '_tag_data'):
                continue
            
            button = chip_widget._main_button
            tag_data = chip_widget._tag_data
            tag_name = tag_data['name']
            tag_count = current_file_tags.get(tag_id, 0)
            
            # Update stored properties
            button.setProperty('tag_count', tag_count)
            button.setProperty('total_files', total_files)
            
            # Determine new text and colors
            if tag_count == 0:
                btn_text = tag_name
                bg_color = "#4a4a4a"
                text_color = "white"
                has_remove = False
            elif tag_count == total_files:
                btn_text = f"✓ {tag_name}"
                bg_color = "#2a5a2a"
                text_color = "#90EE90"
                has_remove = True
            else:
                btn_text = f"{tag_name} ({tag_count}/{total_files})"
                bg_color = "#4a4a2a"
                text_color = "#FFD700"
                has_remove = True
            
            # Update button text
            button.setText(btn_text)
            is_checked = button.isChecked()
            
            # Update button style
            border_radius = "3px" if not has_remove else "3px 0px 0px 3px"
            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    border: 1px solid #555;
                    border-radius: {border_radius};
                    padding: 4px 10px;
                    color: {text_color};
                    font-family: {UI_FONT};
                    font-size: 11px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: #5a5a5a;
                    border-color: #666;
                }}
                QPushButton:checked {{
                    background-color: #4b7daa;
                    border-color: #5a8db8;
                    color: #ffffff;
                    font-weight: bold;
                }}
                QPushButton:checked:hover {{
                    background-color: #5a8db8;
                }}
            """)
            
            # Show/hide remove button
            layout = chip_widget.layout()
            if layout and layout.count() > 1:
                remove_btn = layout.itemAt(1).widget()
                if remove_btn:
                    if has_remove:
                        remove_btn.show()
                        remove_btn.setStyleSheet(f"""
                            QPushButton {{
                                background-color: {bg_color};
                                border: 1px solid #555;
                                border-left: none;
                                border-radius: 0px 3px 3px 0px;
                                color: {text_color};
                                font-family: {UI_FONT};
                                font-size: 14px;
                                font-weight: bold;
                                padding: 0px;
                            }}
                            QPushButton:hover {{
                                background-color: #8B0000;
                                color: white;
                            }}
                            QPushButton:pressed {{
                                background-color: #6B0000;
                            }}
                        """)
                    else:
                        remove_btn.hide()
    
    def _reset_tag_database(self):
        """Reset entire tag database - WARNING: destructive operation!"""
        reply = QtWidgets.QMessageBox.warning(
            self,
            "⚠️ Reset Tag Database",
            "This will DELETE ALL TAGS and file associations!\n\n"
            "This cannot be undone!\n\n"
            "Are you absolutely sure?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            
            mm.reset_database()
            
            # Clear current display
            self.clear_tags()
            self.clear_metadata()
            
            # Reload autocomplete (now empty)
            self.setup_tag_autocomplete()
            
            QtWidgets.QMessageBox.information(
                self,
                "Database Reset",
                "Tag database has been reset.\n\nAll tags and associations have been deleted."
            )
            
            print("⚠️ Tag database reset complete")
            
        except Exception as e:
            print(f"Error resetting database: {e}")
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to reset database:\n{e}"
            )
    
    def _add_selected_tags(self, dialog, tag_buttons):
        """Add selected tags from browse dialog to current file(s)"""
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            
            # Get selected tags
            selected_tags = []
            for tag_id, chip_widget in tag_buttons.items():
                if hasattr(chip_widget, '_main_button'):
                    button = chip_widget._main_button
                    if button.isChecked():
                        tag_data = button.property('tag_data')
                        selected_tags.append(tag_data)
            
            if not selected_tags:
                QtWidgets.QMessageBox.information(
                    dialog,
                    "No Tags Selected",
                    "Please select at least one tag to add."
                )
                return
            
            # Add tags to all selected files
            if not self.current_assets:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "No Files Selected",
                    "Please select file(s) to add tags to."
                )
                return
            
            # Add each selected tag
            for tag_data in selected_tags:
                tag_name = tag_data['name']
                tag_id = tag_data['id']  # Get the ID from tag_data!
                
                # Add to all selected files
                for asset in self.current_assets:
                    file_path = str(asset.file_path)
                    
                    # Check if tag already exists
                    existing_metadata = mm.get_file_metadata(file_path)
                    if existing_metadata and existing_metadata.get('tags'):
                        existing_tag_ids = [t['id'] for t in existing_metadata['tags']]
                        if tag_id in existing_tag_ids:
                            continue  # Skip if already has this tag
                    
                    # Add tag (with ID, not name!)
                    mm.add_tag_to_file(file_path, tag_id)
            
            # Reload tags display (both Tags tab and Metadata tab)
            if len(self.current_assets) == 1:
                self.load_tags(self.current_assets[0])
            else:
                self.load_common_tags(self.current_assets)
            
            # Force update of tags container
            if hasattr(self, 'tags_container') and self.tags_container:
                self.tags_container.update()
                self.tags_container.updateGeometry()
            
            # Update metadata tab as well
            self.update_preview(self.current_assets)
            
            # Don't close dialog - let user continue adding tags
            # dialog.accept()  # Commented out - dialog stays open
            
            # Deselect all tags after adding (ready for next batch)
            for chip_widget in tag_buttons.values():
                if hasattr(chip_widget, '_main_button'):
                    chip_widget._main_button.setChecked(False)
            
            # Update info label to reflect current selection
            if hasattr(dialog, 'update_info_label'):
                dialog.update_info_label()
            
            # Refresh browse dialog button colors
            self._refresh_browse_dialog_buttons(dialog, tag_buttons, mm)
            
            # Show confirmation
            tag_names = ", ".join([t['name'] for t in selected_tags[:5]])
            if len(selected_tags) > 5:
                tag_names += f"... (+{len(selected_tags) - 5} more)"
            
            print(f"✓ Added {len(selected_tags)} tag(s) to {len(self.current_assets)} file(s): {tag_names}")
            
        except Exception as e:
            print(f"Error adding selected tags: {e}")
            import traceback
            traceback.print_exc()
    
    def add_tag(self):
        """Add a new tag from input field (supports bulk tagging for multiple files)"""
        tag_text = self.tag_input.text().strip()
        
        if not tag_text:
            return
        
        # Get ALL selected files (bulk tagging support!)
        if not self.current_assets or len(self.current_assets) == 0:
            print("No asset selected to tag")
            return
        
        # REMOVED: Don't check UI for duplicates - we want to add to files that DON'T have it yet!
        # The tag might already be displayed as a partial tag, but we still want to add it
        # to the files that don't have it yet.
        
        # Save to database
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            
            # Add tag to database (or get existing)
            tag_id = mm.add_tag(tag_text)
            
            # Check which files already have this tag
            files_with_tag = []
            files_without_tag = []
            
            for asset in self.current_assets:
                current_file = str(asset.file_path)
                metadata = mm.get_file_metadata(current_file)
                
                # Check if this file already has this tag
                has_tag = False
                if metadata and metadata.get('tags'):
                    for existing_tag in metadata['tags']:
                        if existing_tag['id'] == tag_id:
                            has_tag = True
                            break
                
                if has_tag:
                    files_with_tag.append(asset.name)
                else:
                    files_without_tag.append(current_file)
            
            # Add tag only to files that don't have it yet
            # Note: Database will handle duplicates (INSERT OR IGNORE) as safety net
            tagged_count = 0
            for file_path in files_without_tag:
                mm.add_tag_to_file(file_path, tag_id)
                tagged_count += 1
            
            if tagged_count > 0:
                if tagged_count == 1:
                    print(f"✓ Tag added: {tag_text} -> 1 file")
                else:
                    print(f"✓ Tag added: {tag_text} -> {tagged_count} files")
            
            if len(files_with_tag) > 0:
                print(f"ℹ {len(files_with_tag)} file(s) already had this tag")
                
        except Exception as e:
            print(f"Error saving tag: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Reload the tags display to show updated state
        # If multiple files selected, reload common tags (this will show the updated partial/common state)
        # If single file, reload that file's tags
        if len(self.current_assets) == 1:
            self.load_tags(self.current_assets[0])
        else:
            self.load_common_tags(self.current_assets)
        
        # Clear input
        self.tag_input.clear()
    
    def create_tag_chip(self, tag_text, tag_id=None, is_common=True, count=None, total=None):
        """Create a visual tag chip widget
        
        Args:
            tag_text: Tag name
            tag_id: Tag ID from database
            is_common: True if tag is in ALL files, False if partial
            count: Number of files with this tag (for partial tags)
            total: Total number of selected files (for partial tags)
        """
        # CRITICAL: Check if chip already exists (prevent duplicates)
        for i in range(self.tags_layout.count()):
            item = self.tags_layout.itemAt(i)
            if item and item.widget():
                existing_widget = item.widget()
                existing_id = existing_widget.property('tag_id')
                existing_text = existing_widget.property('tag_text')
                if existing_id == tag_id and existing_text == tag_text:
                    # Chip already exists, skip creation
                    return
        
        tag_chip = QWidget(self.tags_container)  # PARENT to tags_container!
        tag_chip.setProperty('tag_id', tag_id)  # Store tag_id for later removal
        tag_chip.setProperty('tag_text', tag_text)  # Store tag_text
        
        # Set fixed height and auto width (increased from 24 to 26)
        tag_chip.setFixedHeight(26)
        tag_chip.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        
        # Different styling for common vs partial tags
        if is_common:
            # Common tags: solid grey background
            bg_color = "#4a4a4a"
            border_style = "1px solid #555"
        else:
            # Partial tags: darker background, dashed border
            bg_color = "#2a2a2a"
            border_style = "1px dashed #555"
        
        tag_chip.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border: {border_style};
                border-radius: 3px;
                padding: 0px;
            }}
        """)
        
        chip_layout = QHBoxLayout(tag_chip)
        chip_layout.setContentsMargins(8, 4, 8, 4)
        chip_layout.setSpacing(5)
        
        # Tag label with count for partial tags
        if is_common:
            display_text = tag_text
            tooltip = f"{tag_text} - in all files"
        else:
            display_text = f"{tag_text} ({count}/{total})"
            tooltip = f"{tag_text} - in {count} of {total} files"
        
        tag_label = QLabel(display_text)
        tag_label.setStyleSheet(f"""
            QLabel {{
                color: {"white" if is_common else "#aaa"};
                font-family: {UI_FONT};
                font-size: 11px;
                background: transparent;
                border: none;
            }}
        """)
        tag_label.setToolTip(tooltip)
        chip_layout.addWidget(tag_label)
        
        # Remove button
        remove_btn = QPushButton("×")
        remove_btn.setFixedSize(16, 16)
        remove_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #555;
                border: 1px solid #666;
                border-radius: 2px;
                color: #aaa;
                font-size: 12px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: #666;
                color: #fff;
                border-color: #777;
            }}
            QPushButton:pressed {{
                background-color: #777;
                border-color: #888;
            }}
        """)
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.clicked.connect(lambda: self.remove_tag_chip(tag_chip, tag_text))
        chip_layout.addWidget(remove_btn)
        
        # Add to layout
        self.tags_layout.addWidget(tag_chip)
        
        # CRITICAL: Explicitly show the chip widget
        tag_chip.show()
        tag_chip.setVisible(True)
        
        # Force layout update
        self.tags_layout.update()
        self.tags_layout.activate()  # Force layout recalculation
        
        if hasattr(self, 'tags_container') and self.tags_container:
            self.tags_container.updateGeometry()
            self.tags_container.show()
    
    def remove_tag_chip(self, chip_widget, tag_text):
        """Remove a tag chip (supports bulk removal from multiple files)"""
        # Get ALL selected files (bulk removal support!)
        if self.current_assets and len(self.current_assets) > 0:
            tag_id = chip_widget.property('tag_id')
            
            # Remove from database for ALL selected files
            if tag_id:
                try:
                    from .metadata import get_metadata_manager
                    mm = get_metadata_manager()
                    
                    removed_count = 0
                    for asset in self.current_assets:
                        current_file = str(asset.file_path)
                        mm.remove_tag_from_file(current_file, tag_id)
                        removed_count += 1
                    
                    if removed_count == 1:
                        print(f"Tag removed: {tag_text} -> {self.current_assets[0].name}")
                    else:
                        print(f"Tag removed: {tag_text} -> {removed_count} files")
                except Exception as e:
                    print(f"Error removing tag: {e}")
        
        # Remove from layout
        self.tags_layout.removeWidget(chip_widget)
        chip_widget.deleteLater()
        
        # Show info label if no tags remain
        if self.tags_layout.count() == 0:
            self.tag_info_label.show()
    
    def clear_tags(self):
        """Clear all tag chips"""
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.tag_info_label.show()
    
    def clear_all_tags_from_selection(self):
        """Remove ALL tags from selected file(s) with confirmation"""
        if not self.current_assets:
            QtWidgets.QMessageBox.information(
                self,
                "No Files Selected",
                "Please select file(s) to clear tags from."
            )
            return
        
        # Count total tags across all files
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            
            total_tags = 0
            for asset in self.current_assets:
                file_path = str(asset.file_path)
                metadata = mm.get_file_metadata(file_path)
                if metadata and metadata.get('tags'):
                    total_tags += len(metadata['tags'])
            
            if total_tags == 0:
                QtWidgets.QMessageBox.information(
                    self,
                    "No Tags",
                    "Selected file(s) have no tags to remove."
                )
                return
            
            # Confirmation dialog
            file_count = len(self.current_assets)
            file_text = f"{file_count} file(s)" if file_count > 1 else self.current_assets[0].name
            
            reply = QtWidgets.QMessageBox.question(
                self,
                "Clear All Tags",
                f"Remove ALL tags from {file_text}?\n\nThis will remove {total_tags} tag(s).",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            
            if reply != QtWidgets.QMessageBox.Yes:
                return
            
            # Remove all tags from all selected files
            removed_count = 0
            for asset in self.current_assets:
                file_path = str(asset.file_path)
                metadata = mm.get_file_metadata(file_path)
                if metadata and metadata.get('tags'):
                    for tag in metadata['tags']:
                        mm.remove_tag_from_file(file_path, tag['id'])
                        removed_count += 1
            
            # Reload display
            if len(self.current_assets) == 1:
                self.load_tags(self.current_assets[0])
            else:
                self.load_common_tags(self.current_assets)
            
            # Update metadata tab
            self.update_preview(self.current_assets)
            
            # Refresh browse dialog if open
            if hasattr(self, '_active_browse_dialog') and self._active_browse_dialog:
                try:
                    dialog = self._active_browse_dialog
                    if hasattr(dialog, '_tag_buttons') and hasattr(dialog, '_mm'):
                        self._refresh_browse_dialog_buttons(dialog, dialog._tag_buttons, dialog._mm)
                except:
                    pass  # Dialog might be closed
            
            print(f"✓ Cleared {removed_count} tag(s) from {file_count} file(s)")
            
        except Exception as e:
            print(f"Error clearing tags: {e}")
            import traceback
            traceback.print_exc()
    
    def load_tags(self, asset):
        """Load tags for an asset from metadata system"""
        # Clear existing tags
        self.clear_tags()
        
        if not asset:
            return
        
        # Load tags from database
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            
            file_path = str(asset.file_path)
            metadata = mm.get_file_metadata(file_path)
            
            if metadata and metadata.get('tags'):
                for tag in metadata['tags']:
                    self.create_tag_chip(tag['name'], tag['id'])
                
                # Hide info label if we have tags
                if len(metadata['tags']) > 0:
                    self.tag_info_label.hide()
                    
                # Debug: print(f"Loaded {len(metadata['tags'])} tags for {asset.name}")
        except Exception as e:
            print(f"Error loading tags: {e}")
    
    def load_common_tags(self, assets):
        """Load tags for multiple files - shows common and partial tags in separate sections"""
        # Clear existing tags
        self.clear_tags()
        
        # CRITICAL: Process pending events so deleteLater() completes before adding new tags
        if PYSIDE_VERSION == 6:
            from PySide6.QtCore import QCoreApplication
        else:
            from PySide2.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        if not assets:
            return
        
        try:
            from .metadata import get_metadata_manager
            mm = get_metadata_manager()
            
            # Get tags for all files
            all_file_tags = {}
            for asset in assets:
                file_path = str(asset.file_path)
                metadata = mm.get_file_metadata(file_path)
                if metadata and metadata.get('tags'):
                    # Store tags by tag_id for easy comparison
                    all_file_tags[file_path] = {tag['id']: tag for tag in metadata['tags']}
            
            if not all_file_tags:
                return  # No files have tags
            
            # Collect all unique tags and count occurrences
            tag_counts = {}  # {tag_id: {'tag': tag_dict, 'count': int}}
            for file_tags in all_file_tags.values():
                for tag_id, tag in file_tags.items():
                    if tag_id not in tag_counts:
                        tag_counts[tag_id] = {'tag': tag, 'count': 0}
                    tag_counts[tag_id]['count'] += 1
            
            total_files = len(assets)
            common_tags = {}  # Tags in ALL files
            partial_tags = {}  # Tags in SOME files
            
            for tag_id, data in tag_counts.items():
                if data['count'] == total_files:
                    common_tags[tag_id] = data['tag']
                else:
                    partial_tags[tag_id] = (data['tag'], data['count'])
            
            # Display tags (common first, then partial)
            if common_tags or partial_tags:
                # Add common tag chips
                for tag in common_tags.values():
                    self.create_tag_chip(tag['name'], tag['id'], is_common=True)
                
                # Add partial tag chips (with count)
                for tag, count in partial_tags.values():
                    self.create_tag_chip(tag['name'], tag['id'], is_common=False, count=count, total=total_files)
                
                self.tag_info_label.hide()
            
        except Exception as e:
            import traceback
            print(f"Error loading common tags: {e}")
            traceback.print_exc()
    
    def on_preview_splitter_moved(self, pos, index):
        """Save preview splitter position when moved"""
        if self.config:
            splitter_state = self.preview_splitter.saveState().toBase64().data().decode()
            self.config.config["preview_splitter_position"] = splitter_state
            self.config.save_config()
    
    def on_sequence_frame_changed(self, frame_index):
        """Handle sequence frame change from playback widget
        
        Args:
            frame_index: 0-based index into sequence.files
        """
        if not self.current_assets or not self.current_assets[0].is_sequence:
            return
        
        asset = self.current_assets[0]
        sequence = asset.sequence
        
        if not sequence or frame_index >= len(sequence.files):
            return
        
        # Get the frame Path object (sequence.files is a list of Path objects)
        frame_path = sequence.files[frame_index]
        
        # If in zoom mode, load the new frame directly into zoom without resetting
        if self.zoom_mode:
            # Update current_image_path to new frame
            self.current_image_path = frame_path
            
            # Load the new frame at full resolution
            file_path_str = str(frame_path)
            file_ext = file_path_str.lower()
            
            # Update EXR file path if it's an EXR file (for channel switching support)
            if file_ext.endswith('.exr'):
                self.current_exr_file_path = file_path_str
            
            # Load based on file type (same logic as enter_zoom_mode)
            new_pixmap = None
            
            # Standard images
            if file_ext.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tga', '.psd')):
                # Simple load for standard formats
                new_pixmap = QPixmap(file_path_str)
            # TIFF
            elif file_ext.endswith(('.tif', '.tiff')):
                try:
                    import cv2
                    import numpy as np
                    img = cv2.imread(file_path_str, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)
                    if img is not None:
                        if img.dtype == np.uint16:
                            img = (img / 256).astype(np.uint8)
                        elif img.dtype == np.float32 or img.dtype == np.float64:
                            img = np.clip(img, 0, 1)
                            img = (img * 255).astype(np.uint8)
                        if len(img.shape) == 2:
                            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                        elif len(img.shape) == 3 and img.shape[2] == 4:
                            img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
                        elif len(img.shape) == 3 and img.shape[2] == 3:
                            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        height, width, channels = img.shape
                        bytes_per_line = width * channels
                        q_image = QImage(img.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                        new_pixmap = QPixmap.fromImage(q_image.copy())
                except:
                    new_pixmap = QPixmap(file_path_str)
            # HDR/EXR
            elif file_ext.endswith(('.hdr', '.exr')):
                try:
                    # For EXR, also load channel list
                    if file_ext.endswith('.exr') and OPENEXR_AVAILABLE:
                        # Get available channels by opening the file
                        try:
                            with OpenEXR.File(file_path_str) as exr_file:
                                channels = exr_file.channels()
                                channel_names = list(channels.keys())
                        except Exception as e:
                            print(f"⚠️ Failed to read EXR channels: {e}")
                            channel_names = []
                        
                        if channel_names:
                            self.current_exr_channels = channel_names
                            # Keep current channel if it exists in new frame, otherwise use first
                            if self.current_exr_channel and self.current_exr_channel in channel_names:
                                # Keep current channel selection
                                pass
                            else:
                                # Switch to first available channel
                                self.current_exr_channel = channel_names[0]
                            
                            print(f"🎬 Sequence frame EXR channels: {', '.join(channel_names)} (current: {self.current_exr_channel})")
                            
                            # Load the specific channel
                            new_pixmap, resolution_str = self.load_exr_channel(file_path_str, self.current_exr_channel)
                        else:
                            # No channels, load as standard HDR
                            rgb_raw, width, height, resolution_str = load_hdr_exr_raw(file_path_str, max_size=self.max_preview_size)
                            if rgb_raw is not None:
                                self.add_to_hdr_raw_cache(file_path_str, rgb_raw, width, height, resolution_str)
                                self.current_hdr_path = file_path_str
                                new_pixmap = self.apply_hdr_tone_mapping(rgb_raw, width, height, self.hdr_exposure, file_path=file_path_str)
                            else:
                                new_pixmap, _ = load_hdr_exr_image(file_path_str, max_size=self.max_preview_size, exposure=self.hdr_exposure)
                    else:
                        # HDR file - load raw data and cache it
                        rgb_raw, width, height, resolution_str = load_hdr_exr_raw(file_path_str, max_size=self.max_preview_size)
                        
                        if rgb_raw is not None:
                            # Cache the raw data
                            self.add_to_hdr_raw_cache(file_path_str, rgb_raw, width, height, resolution_str)
                            self.current_hdr_path = file_path_str
                            
                            # Apply tone mapping with current exposure
                            new_pixmap = self.apply_hdr_tone_mapping(rgb_raw, width, height, self.hdr_exposure, file_path=file_path_str)
                        else:
                            # Fallback to load_hdr_exr_image
                            new_pixmap, _ = load_hdr_exr_image(file_path_str, max_size=self.max_preview_size, exposure=self.hdr_exposure)
                except Exception as e:
                    print(f"Error loading HDR/EXR frame in zoom: {e}")
                    import traceback
                    traceback.print_exc()
                    new_pixmap = None
            else:
                # Fallback
                new_pixmap = QPixmap(file_path_str)
            
            # Replace the pixmap in zoom mode
            if new_pixmap and not new_pixmap.isNull():
                self.full_res_pixmap = new_pixmap
                
                # Update the scene with new pixmap (keeping zoom and pan)
                if self.pixmap_item:
                    self.pixmap_item.setPixmap(new_pixmap)
                else:
                    self.graphics_scene.clear()
                    self.pixmap_item = self.graphics_scene.addPixmap(new_pixmap)
                    self.pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        else:
            # Normal mode: just load the frame
            self.load_sequence_frame(frame_path, asset)
    
    def load_sequence_frame(self, frame_path, asset):
        """Load and display a specific frame from a sequence
        
        Args:
            frame_path: Path to the frame file
            asset: The sequence AssetItem (for metadata access)
        """
        # Don't clear scene if in zoom mode - we'll update the pixmap item instead
        if not self.zoom_mode:
            self.graphics_scene.clear()
            self.current_text_item = None
            self.current_pixmap = None
        
        file_path_str = str(frame_path)
        file_ext = file_path_str.lower()
        
        # Get sequence info for cache key
        sequence = asset.sequence if asset and asset.sequence else None
        if not sequence:
            return
        
        # Find frame index in sequence
        frame_index = None
        for idx, seq_file in enumerate(sequence.files):
            if str(seq_file) == file_path_str:
                frame_index = idx
                break
        
        if frame_index is None:
            return
        
        # Check if this is HDR/EXR
        is_hdr_exr = file_ext.endswith('.hdr') or file_ext.endswith('.exr')
        
        # Setup exposure controls if HDR/EXR
        if is_hdr_exr:
            self.current_hdr_path = file_path_str
            self.exposure_controls.show()
            # Keep current exposure value (don't reset for sequences)
            
            # For EXR, detect channels (needed for zoom mode)
            if file_ext.endswith('.exr') and OPENEXR_AVAILABLE:
                try:
                    with OpenEXR.File(file_path_str) as exr_file:
                        channels = exr_file.channels()
                        channel_names = list(channels.keys())
                        
                    if channel_names:
                        self.current_exr_file_path = file_path_str
                        self.current_exr_channels = channel_names
                        # Keep current channel if it exists, otherwise use first
                        if not self.current_exr_channel or self.current_exr_channel not in channel_names:
                            self.current_exr_channel = channel_names[0]
                except Exception as e:
                    print(f"⚠️ Failed to detect EXR channels: {e}")
        else:
            self.current_hdr_path = None
            self.exposure_controls.hide()
        
        # Load the frame directly (no caching for now)
        pixmap = None
        resolution_str = None
        try:
            if is_hdr_exr:
                # For EXR with channels, load the specific channel
                if file_ext.endswith('.exr') and self.current_exr_file_path and self.current_exr_channel:
                    # Load specific channel (handles caching internally)
                    pixmap, resolution_str = self.load_exr_channel(file_path_str, self.current_exr_channel)
                else:
                    # Load HDR/EXR with exposure (standard RGB)
                    rgb_raw, width, height, resolution_str = load_hdr_exr_raw(file_path_str, max_size=self.max_preview_size)
                    
                    if rgb_raw is not None:
                        self.add_to_hdr_raw_cache(file_path_str, rgb_raw, width, height, resolution_str)
                        pixmap = self.apply_hdr_tone_mapping(rgb_raw, width, height, self.hdr_exposure, file_path=file_path_str)
                    else:
                        pixmap, resolution_str = load_hdr_exr_image(file_path_str, max_size=self.max_preview_size, exposure=self.hdr_exposure)
                
                if pixmap:
                    self.current_pixmap = pixmap
                    self.add_to_cache(file_path_str, pixmap, resolution_str)
                    self.fit_pixmap_to_label()
            else:
                # Standard image loading
                if file_ext.endswith('.tx'):
                    try:
                        from .widgets import load_oiio_image
                        pixmap, resolution_str, metadata = load_oiio_image(
                            file_path_str,
                            max_size=1024,
                            mip_level=0,
                            exposure=0.0,
                            metadata_manager=self.metadata_manager
                        )
                    except:
                        pixmap = None
                
                # For TGA files, skip QImageReader (causes warnings) and use PIL directly
                if not pixmap and file_ext.endswith('.tga'):
                    try:
                        from PIL import Image
                        Image.MAX_IMAGE_PIXELS = None  # Disable decompression bomb warning
                        
                        pil_image = Image.open(file_path_str)
                        original_size = pil_image.size
                        resolution_str = f"{original_size[0]} x {original_size[1]}"
                        
                        # Convert to RGB
                        if pil_image.mode not in ('RGB', 'L'):
                            pil_image = pil_image.convert('RGB')
                        elif pil_image.mode == 'L':
                            pil_image = pil_image.convert('RGB')
                        
                        # Scale if needed
                        if original_size[0] > 1024 or original_size[1] > 1024:
                            pil_image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                        
                        # Convert PIL to QPixmap
                        import numpy as np
                        img_array = np.array(pil_image)
                        height, width = img_array.shape[:2]
                        bytes_per_line = width * 3
                        
                        q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                        pixmap = QPixmap.fromImage(q_image.copy())
                        
                    except Exception as pil_error:
                        print(f"[Preview] PIL loading failed for {Path(file_path_str).name}: {pil_error}")
                        pixmap = None
                
                if not pixmap:
                    # Use standard Qt loading for other formats
                    reader = QImageReader(file_path_str)
                    reader.setAutoTransform(True)
                    
                    # Scale if needed
                    size = reader.size()
                    if size.width() > 1024 or size.height() > 1024:
                        scaled_size = size.scaled(1024, 1024, Qt.KeepAspectRatio)
                        reader.setScaledSize(scaled_size)
                    
                    image = reader.read()
                    if not image.isNull():
                        pixmap = QPixmap.fromImage(image)
                        resolution_str = f"{size.width()} x {size.height()}"
                    else:
                        # QImageReader failed - try PIL fallback for other special formats
                        try:
                            from PIL import Image
                            Image.MAX_IMAGE_PIXELS = None  # Disable decompression bomb warning
                            
                            pil_image = Image.open(file_path_str)
                            original_size = pil_image.size
                            resolution_str = f"{original_size[0]} x {original_size[1]}"
                            
                            # Convert to RGB
                            if pil_image.mode not in ('RGB', 'L'):
                                pil_image = pil_image.convert('RGB')
                            elif pil_image.mode == 'L':
                                pil_image = pil_image.convert('RGB')
                            
                            # Scale if needed
                            if original_size[0] > 1024 or original_size[1] > 1024:
                                pil_image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                            
                            # Convert PIL to QPixmap
                            import numpy as np
                            img_array = np.array(pil_image)
                            height, width = img_array.shape[:2]
                            bytes_per_line = width * 3
                            
                            q_image = QImage(img_array.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888)
                            pixmap = QPixmap.fromImage(q_image.copy())
                            
                        except Exception as pil_error:
                            print(f"[Preview] PIL fallback failed for {Path(file_path_str).name}: {pil_error}")
                            pixmap = None
                
                if pixmap and not pixmap.isNull():
                    self.current_pixmap = pixmap
                    self.fit_pixmap_to_label()
        
        except Exception as e:
            print(f"Error loading sequence frame {frame_path}: {e}")
            self.graphics_scene.clear()
            self.current_text_item = None
    
    # ========================================================================
    # VIDEO PLAYBACK CONTROLS
    # ========================================================================
    
    def toggle_video_playback(self):
        """Toggle video play/pause using QMediaPlayer"""
        if not self.media_player:
            return
        
        if PYSIDE_VERSION == 6:
            from PySide6.QtMultimedia import QMediaPlayer
            if self.media_player.playbackState() == QMediaPlayer.PlayingState:
                self.media_player.pause()
                self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            else:
                self.media_player.play()
                self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            # PySide2
            from PySide2.QtMultimedia import QMediaPlayer
            if self.media_player.state() == QMediaPlayer.PlayingState:
                self.media_player.pause()
                self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            else:
                self.media_player.play()
                self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
    
    def on_video_state_changed(self, state):
        """Update play/pause button icon when playback state changes"""
        if PYSIDE_VERSION == 6:
            from PySide6.QtMultimedia import QMediaPlayer
            if state == QMediaPlayer.PlayingState:
                self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
            else:
                self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            from PySide2.QtMultimedia import QMediaPlayer
            if state == QMediaPlayer.PlayingState:
                self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
            else:
                self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
    
    def on_video_slider_pressed(self):
        """Handle slider press - mark that user is dragging"""
        self.video_slider_dragging = True
    
    def on_video_slider_value_changed(self, value):
        """Handle slider value change - seek when clicked (not when updating from playback)"""
        if not self.media_player or getattr(self, 'video_slider_updating', False):
            return
        
        # Seek to new position (works for both click and drag)
        duration = self.media_player.duration()
        if duration > 0:
            position = int((value / 1000.0) * duration)
            self.media_player.setPosition(position)
    
    def on_video_slider_released(self):
        """Handle slider released - stop blocking position updates"""
        self.video_slider_dragging = False
    
    def on_video_position_changed(self, position):
        """Update slider when video position changes"""
        if not self.media_player:
            return
        
        # Don't update slider if user is dragging it or dragging on video widget
        if getattr(self, 'video_slider_dragging', False) or getattr(self, 'video_dragging', False):
            return
        
        duration = self.media_player.duration()
        if duration > 0:
            # Prevent feedback loop
            self.video_slider_updating = True
            slider_value = int((position / duration) * 1000)
            self.video_slider.setValue(slider_value)
            self.video_slider_updating = False
            
            # Update time label
            current_time = self.format_time(position)
            total_time = self.format_time(duration)
            self.video_time_label.setText(f"{current_time} / {total_time}")
    
    def on_video_duration_changed(self, duration):
        """Handle video duration change"""
        total_time = self.format_time(duration)
        self.video_time_label.setText(f"0:00 / {total_time}")
    
    def format_time(self, ms):
        """Format milliseconds to MM:SS"""
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{int(minutes)}:{int(seconds):02d}"
    
    def stop_video_playback(self):
        """Stop video and reset to beginning"""
        if not self.media_player:
            return
        self.media_player.stop()
        self.video_slider.setValue(0)
        self.video_time_label.setText("0:00 / 0:00")
        self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
    
    def skip_backward_video(self):
        """Skip backward 5 seconds"""
        if not self.media_player:
            return
        current_pos = self.media_player.position()
        new_pos = max(0, current_pos - 5000)  # 5 seconds = 5000ms
        self.media_player.setPosition(new_pos)
    
    def skip_forward_video(self):
        """Skip forward 5 seconds"""
        if not self.media_player:
            return
        current_pos = self.media_player.position()
        duration = self.media_player.duration()
        new_pos = min(duration, current_pos + 5000)  # 5 seconds = 5000ms
        self.media_player.setPosition(new_pos)
    
    def video_prev_frame(self):
        """Go to previous frame (1 frame back based on FPS)"""
        if not self.media_player:
            return
        
        # Get FPS from detected value
        fps = getattr(self, 'video_fps', 24.0)
        duration = self.media_player.duration()
        
        if duration > 0:
            # Calculate frame duration in milliseconds
            frame_duration_ms = 1000.0 / fps
            current_pos = self.media_player.position()
            new_pos = max(0, current_pos - frame_duration_ms)
            
            # Just seek - frame should be visible from initial play-pause on load
            self.media_player.setPosition(int(new_pos))
    
    def video_next_frame(self):
        """Go to next frame (1 frame forward based on FPS)"""
        if not self.media_player:
            return
        
        # Get FPS from detected value
        fps = getattr(self, 'video_fps', 24.0)
        duration = self.media_player.duration()
        
        if duration > 0:
            # Calculate frame duration in milliseconds
            frame_duration_ms = 1000.0 / fps
            current_pos = self.media_player.position()
            new_pos = min(duration, current_pos + frame_duration_ms)
            
            # Just seek - frame should be visible from initial play-pause on load
            self.media_player.setPosition(int(new_pos))
    
    def _pause_and_reset_video(self):
        """Helper to pause video and show first frame after brief play"""
        if self.media_player:
            self.media_player.pause()
            # Only reset to 0 if we actually want the first frame (initial load)
            # Don't reset if user already seeked somewhere
            if getattr(self, '_video_needs_initial_pause', False):
                self.media_player.setPosition(0)
            # Set button icon to Play (since we're pausing)
            self.video_play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
    
    def on_media_status_changed(self, status):
        """Handle media status changes - show first frame when loaded"""
        if PYSIDE_VERSION == 6:
            from PySide6.QtMultimedia import QMediaPlayer
            if status == QMediaPlayer.LoadedMedia:
                if getattr(self, '_video_needs_initial_pause', False):
                    self._video_needs_initial_pause = False
                    self.media_player.setPosition(0)
                    self.media_player.play()
                    QtCore.QTimer.singleShot(100, lambda: self._pause_and_reset_video())
        else:
            from PySide2.QtMultimedia import QMediaPlayer
            if status == QMediaPlayer.LoadedMedia:
                if getattr(self, '_video_needs_initial_pause', False):
                    self._video_needs_initial_pause = False
                    self.media_player.setPosition(0)
                    self.media_player.play()
                    QtCore.QTimer.singleShot(100, lambda: self._pause_and_reset_video())
    
    def show_volume_popup(self):
        """Show volume slider popup below the volume button"""
        if not self.media_player:
            return
        
        # Ensure popup is properly sized before positioning
        self.video_volume_popup.adjustSize()
        
        # Position popup above the volume button
        button_pos = self.video_volume_button.mapToGlobal(QPoint(0, 0))
        popup_x = button_pos.x() - (self.video_volume_popup.width() // 2) + (self.video_volume_button.width() // 2)
        popup_y = button_pos.y() - self.video_volume_popup.height() - 5  # Above button
        
        self.video_volume_popup.move(popup_x, popup_y)
        self.video_volume_popup.show()
    
    def toggle_video_mute(self):
        """Toggle mute/unmute"""
        if not self.media_player:
            return
        
        if PYSIDE_VERSION == 6:
            # PySide6 uses QAudioOutput
            if hasattr(self, 'audio_output'):
                current_volume = self.audio_output.volume()
                if current_volume > 0:
                    # Mute: save current volume and set to 0
                    self._saved_volume = current_volume
                    self.audio_output.setVolume(0)
                    self.video_volume_button.setIcon(self.style().standardIcon(QStyle.SP_MediaVolumeMuted))
                else:
                    # Unmute: restore saved volume or default to 100%
                    restore_volume = getattr(self, '_saved_volume', 1.0)
                    self.audio_output.setVolume(restore_volume)
                    self.video_volume_button.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
                    # Update slider to match
                    self.video_volume_slider.setValue(int(restore_volume * 100))
        else:
            # PySide2
            is_muted = self.media_player.isMuted()
            self.media_player.setMuted(not is_muted)
            if not is_muted:
                self.video_volume_button.setIcon(self.style().standardIcon(QStyle.SP_MediaVolumeMuted))
            else:
                self.video_volume_button.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
    
    def on_video_volume_changed(self, value):
        """Handle volume slider change"""
        if not self.media_player:
            return
        
        # Update volume label
        self.video_volume_label.setText(f"{value}%")
        
        if PYSIDE_VERSION == 6:
            # PySide6: value is 0-100, convert to 0.0-1.0
            if hasattr(self, 'audio_output'):
                volume = value / 100.0
                self.audio_output.setVolume(volume)
                # Update mute button icon
                if volume == 0:
                    self.video_volume_button.setIcon(self.style().standardIcon(QStyle.SP_MediaVolumeMuted))
                else:
                    self.video_volume_button.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        else:
            # PySide2
            self.media_player.setVolume(value)
            if value == 0:
                self.video_volume_button.setIcon(self.style().standardIcon(QStyle.SP_MediaVolumeMuted))
            else:
                self.video_volume_button.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
    
    def toggle_video_fullscreen(self):
        """Toggle fullscreen mode for video widget with controls"""
        if not self.video_widget:
            return
        
        if hasattr(self, '_fullscreen_widget') and self._fullscreen_widget and self._fullscreen_widget.isVisible():
            # Exit fullscreen
            self._fullscreen_widget.hide()
            
            try:
                # Stop and cleanup hide timer
                if hasattr(self, '_fullscreen_hide_timer') and self._fullscreen_hide_timer:
                    self._fullscreen_hide_timer.stop()
                    self._fullscreen_hide_timer.deleteLater()
                    self._fullscreen_hide_timer = None
                
                # Remove opacity effect and reset mouse transparency
                if hasattr(self, '_fullscreen_opacity_effect'):
                    try:
                        if self._fullscreen_opacity_effect:
                            self.video_playback.setGraphicsEffect(None)
                            self._fullscreen_opacity_effect.deleteLater()
                    except RuntimeError:
                        # Already deleted, that's fine
                        pass
                    del self._fullscreen_opacity_effect
                
                # Re-enable mouse events on controls (in case it was disabled)
                if hasattr(self, 'video_playback') and self.video_playback:
                    self.video_playback.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                
                # Reset video playback controls style to normal
                self.video_playback.setStyleSheet("")
                
                # Re-parent video widget back to preview layout (after graphics_view)
                # Find the correct index (video should be after graphics_view, before controls)
                graphics_view_index = self.preview_layout.indexOf(self.graphics_view)
                self.preview_layout.insertWidget(graphics_view_index + 1, self.video_widget, 1)  # stretch factor 1
                
                # Re-parent controls back to preview layout (at the end)
                self.preview_layout.addWidget(self.video_playback)
                
                # Show the widgets
                self.video_widget.show()
                self.video_playback.show()
                
                # Update button text (exit fullscreen mode)
                self.video_fullscreen_button.setText("⛶")
                self.video_fullscreen_button.setToolTip("Fullscreen (F)")
                
                # Delete fullscreen widget
                self._fullscreen_widget.deleteLater()
                self._fullscreen_widget = None
                
            except Exception as e:
                print(f"ERROR during fullscreen exit: {e}")
                import traceback
                traceback.print_exc()
        else:
            # Create fullscreen widget
            self._fullscreen_widget = QWidget()
            self._fullscreen_widget.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self._fullscreen_widget.setStyleSheet("background-color: black;")
            self._fullscreen_widget.setMouseTracking(True)  # Track mouse movement
            
            # Create layout for fullscreen widget
            fullscreen_layout = QVBoxLayout(self._fullscreen_widget)
            fullscreen_layout.setContentsMargins(0, 0, 0, 0)
            fullscreen_layout.setSpacing(0)  # No spacing - controls overlay at bottom
            
            # Re-parent video widget to fullscreen widget (with stretch)
            fullscreen_layout.addWidget(self.video_widget, 1)  # stretch factor 1 - fill space
            
            # Enable mouse tracking on video widget too
            self.video_widget.setMouseTracking(True)
            
            # Install event filter on video widget for mouse movement
            self.video_widget.installEventFilter(self)
            
            # Style the video playback controls for fullscreen
            # Use same gray background as preview panel (#2a2a2a)
            self.video_playback.setStyleSheet("""
                QWidget {
                    background-color: #2a2a2a;
                }
            """)
            
            # Re-parent controls to fullscreen widget (no stretch - fixed height at bottom)
            fullscreen_layout.addWidget(self.video_playback, 0)  # stretch factor 0 - fixed size
            
            # Install event filter for ESC key and mouse tracking
            self._fullscreen_widget.installEventFilter(self)
            
            # Create auto-hide timer for controls
            self._fullscreen_hide_timer = QtCore.QTimer()
            self._fullscreen_hide_timer.setSingleShot(True)
            self._fullscreen_hide_timer.setInterval(3000)  # Hide after 3 seconds of inactivity
            self._fullscreen_hide_timer.timeout.connect(self._hide_fullscreen_controls)
            self._fullscreen_hide_timer.start()
            
            # Create continuous cursor tracking timer for auto-hide control
            self._cursor_tracking_timer = QtCore.QTimer()
            self._cursor_tracking_timer.setInterval(100)  # Every 100ms
            self._cursor_tracking_timer.timeout.connect(self._track_cursor_position)
            self._cursor_tracking_timer.start()
            
            # Track whether cursor was over controls (to detect enter/leave)
            self._cursor_was_over_controls = False
            
            # Create opacity effect for controls
            self._fullscreen_opacity_effect = QGraphicsOpacityEffect(self.video_playback)
            self.video_playback.setGraphicsEffect(self._fullscreen_opacity_effect)
            self._fullscreen_opacity_effect.setOpacity(1.0)  # Start fully visible
            
            # Show fullscreen
            self._fullscreen_widget.showFullScreen()
            
            # Ensure widgets are visible
            self.video_widget.show()
            self.video_playback.show()
            
            # Update button text (fullscreen mode - show exit icon)
            self.video_fullscreen_button.setText("⛝")  # Exit fullscreen icon
            self.video_fullscreen_button.setToolTip("Exit Fullscreen (F or Esc)")
    
    def _hide_fullscreen_controls(self):
        """Hide controls in fullscreen mode by setting opacity to 0"""
        try:
            # IMPORTANT: Check if mouse is currently over controls before hiding
            if hasattr(self, '_fullscreen_widget') and self._fullscreen_widget and hasattr(self, 'video_playback'):
                # Get current mouse position
                from PySide6.QtGui import QCursor
                cursor_pos = QCursor.pos()
                local_pos = self._fullscreen_widget.mapFromGlobal(cursor_pos)
                mouse_y = local_pos.y()
                
                fullscreen_height = self._fullscreen_widget.height()
                controls_height = self.video_playback.height()
                controls_start_y = fullscreen_height - controls_height
                mouse_over_controls = mouse_y >= controls_start_y
                
                if mouse_over_controls:
                    # Don't hide! Mouse is over controls
                    return
            if hasattr(self, '_fullscreen_opacity_effect') and self._fullscreen_opacity_effect:
                self._fullscreen_opacity_effect.setOpacity(0.0)
                # Disable mouse events when invisible so they pass through to video widget
                if hasattr(self, 'video_playback') and self.video_playback:
                    self.video_playback.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                
                # IMPORTANT: Reset state - cursor is definitely NOT over controls now (they're hidden!)
                self._cursor_was_over_controls = False
        except Exception as e:
            import traceback
            traceback.print_exc()
    
    def _track_cursor_position(self):
        """Continuously track cursor position for debugging"""
        if hasattr(self, '_fullscreen_widget') and self._fullscreen_widget:
            from PySide6.QtGui import QCursor
            cursor_pos = QCursor.pos()
            local_pos = self._fullscreen_widget.mapFromGlobal(cursor_pos)
            
            fullscreen_height = self._fullscreen_widget.height()
            controls_height = self.video_playback.height() if hasattr(self, 'video_playback') else 0
            controls_start_y = fullscreen_height - controls_height
            is_over = local_pos.y() > controls_start_y
            
            # Check if state changed and restart timer if needed
            was_over = getattr(self, '_cursor_was_over_controls', False)
            if is_over != was_over:
                if is_over:
                    # ENTERED controls area - stop timer, show controls
                    if hasattr(self, '_fullscreen_hide_timer') and self._fullscreen_hide_timer:
                        self._fullscreen_hide_timer.stop()
                    if hasattr(self, '_fullscreen_opacity_effect') and self._fullscreen_opacity_effect:
                        self._fullscreen_opacity_effect.setOpacity(1.0)
                        if hasattr(self, 'video_playback') and self.video_playback:
                            self.video_playback.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                else:
                    # LEFT controls area - start timer
                    if hasattr(self, '_fullscreen_hide_timer') and self._fullscreen_hide_timer:
                        self._fullscreen_hide_timer.stop()
                        self._fullscreen_hide_timer.start()
                
                self._cursor_was_over_controls = is_over
    
    def _show_fullscreen_controls(self, mouse_over_controls=False):
        """Show controls in fullscreen mode (called when controls become visible again)
        
        Args:
            mouse_over_controls: Not used anymore - kept for compatibility
        """
        # Just show controls - timer management is now done in MouseMove enter/leave logic
        if hasattr(self, '_fullscreen_opacity_effect') and self._fullscreen_opacity_effect:
            self._fullscreen_opacity_effect.setOpacity(1.0)
            if hasattr(self, 'video_playback') and self.video_playback:
                self.video_playback.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    
    def cleanup(self):
        """Cleanup resources (called on close)"""
        # Stop video playback and release resources
        if self.media_player:
            self.media_player.stop()
            if PYSIDE_VERSION == 6:
                from PySide6.QtCore import QUrl
                self.media_player.setSource(QUrl())
            else:
                from PySide2.QtMultimedia import QMediaContent
                self.media_player.setMedia(QMediaContent())
        print("[PREVIEW] Cleanup completed")
    
    # Cache system removed for simplification
    # Will be reimplemented if needed




