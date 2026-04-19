"""
DD Content Browser Launcher - FULL RELOAD
Script to launch Content Browser in Maya with complete module reload
"""

import sys
import importlib
import os
from pathlib import Path
from PySide6 import QtWidgets

try:
    # First, close any existing browser instances at Qt level
    # This ensures we close ALL instances, even if singleton was lost during reload
    import ddContentBrowser
    
    # Try the module's close function first
    if hasattr(ddContentBrowser, 'close_content_browser'):
        ddContentBrowser.close_content_browser()
    
    # Also search for any remaining QWidget instances with our class name
    # This catches orphaned instances from previous reloads
    app = QtWidgets.QApplication.instance()
    if app:
        closed_count = 0
        for widget in app.allWidgets():
            widget_class_name = widget.__class__.__name__
            # Check for ContentBrowser or any variant
            if 'ContentBrowser' in widget_class_name and widget.isVisible():
                print(f"[Cleanup] Found widget: {widget_class_name}, closing...")
                widget.close()
                widget.deleteLater()
                closed_count += 1
        if closed_count > 0:
            print(f"[Cleanup] Closed {closed_count} ContentBrowser instance(s)")
        else:
            print("[Cleanup] No visible ContentBrowser instances found")
    
    # Clear Python __pycache__ to ensure fresh reload
    # Get ddContentBrowser module path dynamically
    if hasattr(ddContentBrowser, '__file__'):
        module_dir = Path(ddContentBrowser.__file__).parent
        pycache_dir = module_dir / '__pycache__'
        if pycache_dir.exists():
            import shutil
            try:
                shutil.rmtree(pycache_dir)
                print("[Cleanup] Cleared __pycache__")
            except:
                pass
    
    # Get all submodules that are already loaded
    modules_to_reload = []
    for module_name in list(sys.modules.keys()):
        if module_name.startswith('ddContentBrowser'):
            modules_to_reload.append(module_name)
    
    # DELETE modules from cache (not reload - that doesn't work properly!)
    print(f"[Reload] Removing {len(modules_to_reload)} module(s) from cache...")
    for module_name in modules_to_reload:
        if module_name in sys.modules:
            del sys.modules[module_name]
    
    print("[Reload] Cache cleared, re-importing package...")
    
    # Fresh import (not reload!)
    import ddContentBrowser
    
    # Show the browser (should create only one instance)
    browser = ddContentBrowser.show_content_browser()
    print("[SUCCESS] DD Content Browser launched with full reload!")
    
except Exception as e:
    print("[ERROR] Error launching Content Browser: {0}".format(e))
    import traceback
    traceback.print_exc()