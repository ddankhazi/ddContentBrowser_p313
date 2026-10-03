# Version Management

## Current Version: 2.5.0

## How to Update Version

The version number is now centrally managed in **ONE PLACE ONLY**:

**`ddContentBrowser/__init__.py`** (at the TOP, before any imports)
```python
__version__ = '2.5.0'
```

**IMPORTANT:** The version MUST be defined at the top of `__init__.py` BEFORE importing other modules, to avoid circular import issues.

### Files that automatically use this version:

1. **browser.py** - Window title and the Help > Documentation dialog title
   - Imports: `from . import __version__`
   - Uses: `f"Content Browser for Maya | v{__version__} | by Denes Dankhazi"`

2. **Standalone launchers** - Window title
   - `standalone_launcher.py`, `standalone_launcher_portable.py`, `ddContentBrowser.pyw`, `ddContentBrowser_internal.pyw`
   - Imports: `from ddContentBrowser import __version__`
   - Uses: `f"DD Content Browser v{__version__} (Standalone)"` / `(Standalone - PORTABLE)`

3. **launch_standalone.bat** - Reads the `__version__ = '...'` line straight from `__init__.py`

### To update the version:

1. Open `ddContentBrowser/__init__.py`
2. Change the `__version__ = '2.5.0'` line to your new version
3. Update the version shown in `README.md` (title + Credits) - the README is plain text, it can't import it
4. That's it! All other files will automatically use the new version.

### Benefits:

- ✅ Single source of truth
- ✅ No need to hunt down version strings in multiple files
- ✅ Consistent versioning across all launchers and windows
- ✅ Easy to maintain and update
