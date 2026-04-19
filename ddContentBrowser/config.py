"""
DD Content Browser - Configuration Module
Handles loading and saving user configuration
"""

import json
from pathlib import Path


class ContentBrowserConfig:
    """Configuration manager class"""
    
    def __init__(self):
        # Store config in user directory (persistent across updates)
        self.config_dir = Path.home() / ".ddContentBrowser"
        self.config_dir.mkdir(exist_ok=True)
        self.config_file = self.config_dir / "config.json"
        
        # Get supported formats from central registry
        from .utils import get_all_supported_extensions
        supported_formats = get_all_supported_extensions()
        
        self.default_config = {
            # Session State - Navigation & Bookmarks
            "recent_paths": [],
            "favorites": [],
            "last_path": str(Path.home()),
            
            # Session State - Window Layout
            "window_geometry": None,
            "splitter_position": None,
            "nav_splitter_position": None,
            "preview_splitter_position": None,
            
            # Session State - View Mode
            "view_mode": "grid",  # "grid" or "list"
            "preview_panel_visible": True,
            "grid_thumbnail_size": 128,
            "list_thumbnail_size": 24,
            "thumbnails_enabled": True,
            
            # Session State - UI Organization
            "nav_top_tabs_order": ["Favourites", "Folders"],
            "nav_tabs_order": ["Collections", "Advanced Filters"],
            
            # Session State - Quick View
            "quick_view_width": 800,
            "quick_view_height": 600,
            "quick_view_x": 100,
            "quick_view_y": 100,
            "quick_view_layout_mode": "fit",
            
            # Session State - Browser State (sorting/filtering)
            "sort_column": "name",
            "sort_ascending": True,
            "filter_file_types": [],
            "show_folders": True,
            "filter_min_size": 0,
            "filter_max_size": 0,
            "filter_date_from": None,
            "filter_date_to": None,
            
            # Runtime data (generated, not persisted preferences)
            "supported_formats": supported_formats  # Dynamically loaded from registry
        }
        self.config = self.load_config()
    
    def load_config(self):
        """Load configuration"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Merge with defaults for missing keys
                    for key, value in self.default_config.items():
                        if key not in config:
                            config[key] = value
                    
                    # Migrate old string-based favorites to new dict format
                    if "favorites" in config:
                        migrated = False
                        new_favorites = []
                        for fav in config["favorites"]:
                            if isinstance(fav, str):
                                # Old format - convert to new dict format
                                new_favorites.append({
                                    "path": fav,
                                    "alias": None,
                                    "color": None
                                })
                                migrated = True
                            else:
                                # Already new format
                                new_favorites.append(fav)
                        
                        if migrated:
                            config["favorites"] = new_favorites
                            print(f"[Config] Migrated {len([f for f in config['favorites'] if isinstance(f, dict)])} favorites to new format")
                            # Save the migrated config immediately
                            self.config = config
                            self.save_config()
                    
                    return config
            except Exception as e:
                print(f"Configuration load error: {e}")
        return self.default_config.copy()
    
    def save_config(self):
        """Save configuration"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Configuration save error: {e}")
    
    def add_recent_path(self, path):
        """Add path to recent paths"""
        path = str(path)
        if path in self.config["recent_paths"]:
            self.config["recent_paths"].remove(path)
        self.config["recent_paths"].insert(0, path)
        # Keep maximum 20 recent paths
        self.config["recent_paths"] = self.config["recent_paths"][:20]
        self.save_config()
