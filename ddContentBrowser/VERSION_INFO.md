# Version Management

## Current Version: 1.6.0

## How to Update Version

The version number is now centrally managed in **ONE PLACE ONLY**:

**`ddContentBrowser/__init__.py`** (at the TOP, before any imports)
```python
__version__ = '1.3.0'
```

**IMPORTANT:** The version MUST be defined at the top of `__init__.py` BEFORE importing other modules, to avoid circular import issues.

### Files that automatically use this version:

1. **browser.py** - Window title
   - Imports: `from . import __version__`
   - Uses: `f"Content Browser for Maya | v{__version__} | by Denes Dankhazi"`

2. **standalone_launcher_portable.py** - Standalone launcher
   - Imports: `from ddContentBrowser import __version__`
   - Uses: `f"DD Content Browser v{__version__} (Standalone - PORTABLE)"`

### To update the version:

1. Open `ddContentBrowser/__init__.py`
2. Change the `__version__ = '1.2.2'` line to your new version
3. That's it! All other files will automatically use the new version.

### Benefits:

- ✅ Single source of truth
- ✅ No need to hunt down version strings in multiple files
- ✅ Consistent versioning across all launchers and windows
- ✅ Easy to maintain and update
