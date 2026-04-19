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
    Launch the DD Content Browser with automatic reload
    
    Args:
        force_reload (bool): If True (default), reloads all modules before launching.
                           Set to False for faster startup if no code changes.
    """
    try:
        # Import and show the browser
        from ddContentBrowser.browser import show_content_browser
        browser = show_content_browser(force_reload=force_reload)
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
