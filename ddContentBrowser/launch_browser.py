"""
Quick launcher for DD Content Browser
Run this in Maya Script Editor to launch/reload the browser

Usage in Maya Script Editor (Python):
    import ddContentBrowser.launch_browser
    ddContentBrowser.launch_browser.launch()
    
Or simply:
    from ddContentBrowser.launch_browser import launch
    launch()
"""

def launch(force_reload=True):
    """
    Launch the DD Content Browser with a genuine full reload.

    Args:
        force_reload (bool): If True (default), purges all package modules and
                           re-imports fresh code before launching.
                           Set to False for faster startup if no code changes.
    """
    import sys
    try:
        if force_reload:
            # browser.py cannot reload itself from inside show_content_browser
            # (the running module keeps its own old classes). Purge here, BEFORE
            # importing browser, so code edits actually take effect.
            browser_mod = sys.modules.get('ddContentBrowser.browser')
            if browser_mod is not None:
                inst = getattr(browser_mod, '_content_browser_instance', None)
                if inst is not None:
                    try:
                        inst.close()
                        inst.deleteLater()
                    except Exception:
                        pass
                    try:
                        browser_mod._content_browser_instance = None
                    except Exception:
                        pass

            to_delete = [
                name for name in list(sys.modules.keys())
                if name == 'ddContentBrowser' or name.startswith('ddContentBrowser.')
            ]
            for name in to_delete:
                if name == 'ddContentBrowser.launch_browser':
                    continue  # keep the currently-running launcher alive
                del sys.modules[name]
            print(f"[Reload] Purged {len(to_delete)} module(s), importing fresh code...")

        # Fresh import AFTER purge -> picks up latest edits in every module.
        from ddContentBrowser.browser import show_content_browser
        browser = show_content_browser(force_reload=False)
        print("[DD Content Browser] Launched successfully!")
        return browser
    except Exception as e:
        print(f"[DD Content Browser] Error launching: {e}")
        import traceback
        traceback.print_exc()
        return None


def launch_no_reload():
    """Launch the browser without reloading modules (faster)"""
    return launch(force_reload=False)


# Auto-launch if this script is executed directly
if __name__ == "__main__":
    launch()
