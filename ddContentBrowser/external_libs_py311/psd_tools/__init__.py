"""""" # start delvewheel patch
def _delvewheel_patch_1_11_1():
    import os
    if os.path.isdir(libs_dir := os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'psd_tools.libs'))):
        os.add_dll_directory(libs_dir)


_delvewheel_patch_1_11_1()
del _delvewheel_patch_1_11_1
# end delvewheel patch

from psd_tools.api.psd_image import PSDImage
from psd_tools.version import __version__

__all__ = ["PSDImage", "__version__"]
