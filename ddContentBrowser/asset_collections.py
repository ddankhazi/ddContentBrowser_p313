# -*- coding: utf-8 -*-
"""
DD Content Browser - Collections System
Manual and Smart collections for asset organization

Author: ddankhazi
License: MIT
"""

import json
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime

# Debug flag
DEBUG_MODE = False


class Collection:
    """Base class for collections"""
    
    def __init__(self, name: str, collection_type: str = "manual"):
        self.name = name
        self.type = collection_type  # 'manual' or 'smart'
        self.created = datetime.now().isoformat()
        self.modified = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage"""
        return {
            'name': self.name,
            'type': self.type,
            'created': self.created,
            'modified': self.modified
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'Collection':
        """Create collection from dictionary"""
        if data['type'] == 'manual':
            return ManualCollection.from_dict(data)
        elif data['type'] == 'smart':
            return SmartCollection.from_dict(data)
        else:
            raise ValueError(f"Unknown collection type: {data['type']}")


class ManualCollection(Collection):
    """Manual collection - user adds/removes files"""
    
    def __init__(self, name: str, files: Optional[List[str]] = None, bg_color: Optional[str] = None):
        super().__init__(name, "manual")
        self.files = files or []  # List of file paths
        self.bg_color = bg_color  # Hex string or None
    
    def add_file(self, file_path: str):
        """Add file to collection"""
        file_path = str(Path(file_path).resolve())
        if file_path not in self.files:
            self.files.append(file_path)
            self.modified = datetime.now().isoformat()
            if DEBUG_MODE:
                print(f"[Collections] Added {file_path} to {self.name}")
    
    def add_files(self, file_paths: List[str]):
        """Add multiple files to collection"""
        for file_path in file_paths:
            self.add_file(file_path)
    
    def remove_file(self, file_path: str):
        """Remove file from collection"""
        file_path = str(Path(file_path).resolve())
        if file_path in self.files:
            self.files.remove(file_path)
            self.modified = datetime.now().isoformat()
            if DEBUG_MODE:
                print(f"[Collections] Removed {file_path} from {self.name}")
    
    def remove_files(self, file_paths: List[str]):
        """Remove multiple files from collection"""
        for file_path in file_paths:
            self.remove_file(file_path)
    
    def contains(self, file_path: str) -> bool:
        """Check if file is in collection"""
        file_path = str(Path(file_path).resolve())
        return file_path in self.files
    
    def get_files(self) -> List[str]:
        """Get all files in collection"""
        return self.files.copy()
    
    def get_existing_files(self) -> List[str]:
        """Get only files that still exist on disk"""
        return [f for f in self.files if Path(f).exists()]
    
    def cleanup_missing_files(self):
        """Remove files that no longer exist on disk"""
        existing = self.get_existing_files()
        if len(existing) < len(self.files):
            removed_count = len(self.files) - len(existing)
            self.files = existing
            self.modified = datetime.now().isoformat()
            if DEBUG_MODE:
                print(f"[Collections] Cleaned up {removed_count} missing files from {self.name}")
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage"""
        data = super().to_dict()
        data['files'] = self.files
        bg_color = getattr(self, 'bg_color', None)
        if bg_color:
            data['bg_color'] = bg_color
        return data
    
    @staticmethod
    def from_dict(data: Dict) -> 'ManualCollection':
        """Create collection from dictionary"""
        collection = ManualCollection(
            data['name'],
            data.get('files', []),
            data.get('bg_color')
        )
        collection.created = data.get('created', datetime.now().isoformat())
        collection.modified = data.get('modified', datetime.now().isoformat())
        return collection


class SmartCollection(Collection):
    """Smart collection - auto-updates based on rules"""
    
    def __init__(self, name: str, rules: Optional[Dict] = None):
        super().__init__(name, "smart")
        self.rules = rules or {}
        self.auto_update = True
    
    def set_rules(self, rules: Dict):
        """Set collection rules"""
        self.rules = rules
        self.modified = datetime.now().isoformat()
    
    def evaluate(self, assets: List) -> List[str]:
        """Evaluate rules against assets and return matching file paths"""
        # TODO: Implement smart collection rule evaluation (Phase 5 - Step 2)
        # This will use the same filter logic as Advanced Filters
        matching_files = []
        return matching_files
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage"""
        data = super().to_dict()
        data['rules'] = self.rules
        data['auto_update'] = self.auto_update
        return data
    
    @staticmethod
    def from_dict(data: Dict) -> 'SmartCollection':
        """Create collection from dictionary"""
        collection = SmartCollection(data['name'], data.get('rules', {}))
        collection.created = data.get('created', datetime.now().isoformat())
        collection.modified = data.get('modified', datetime.now().isoformat())
        collection.auto_update = data.get('auto_update', True)
        return collection


class CollectionManager:
    """Manages all collections"""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.collections: Dict[str, Collection] = {}
        
        # Config path
        if config_path:
            self.config_path = config_path
        else:
            home = Path.home()
            config_dir = home / ".ddContentBrowser"
            config_dir.mkdir(exist_ok=True)
            self.config_path = config_dir / "collections.json"
        
        # Load collections
        self.load()
    
    def create_manual_collection(self, name: str, files: Optional[List[str]] = None) -> ManualCollection:
        """Create a new manual collection"""
        if name in self.collections:
            raise ValueError(f"Collection '{name}' already exists")
        
        collection = ManualCollection(name, files)
        self.collections[name] = collection
        self.save()
        
        if DEBUG_MODE:
            print(f"[Collections] Created manual collection: {name}")
        
        return collection
    
    def create_smart_collection(self, name: str, rules: Optional[Dict] = None) -> SmartCollection:
        """Create a new smart collection"""
        if name in self.collections:
            raise ValueError(f"Collection '{name}' already exists")
        
        collection = SmartCollection(name, rules)
        self.collections[name] = collection
        self.save()
        
        if DEBUG_MODE:
            print(f"[Collections] Created smart collection: {name}")
        
        return collection
    
    def get_collection(self, name: str) -> Optional[Collection]:
        """Get collection by name"""
        return self.collections.get(name)
    
    def rename_collection(self, old_name: str, new_name: str):
        """Rename a collection"""
        if old_name not in self.collections:
            raise ValueError(f"Collection '{old_name}' not found")
        if new_name in self.collections:
            raise ValueError(f"Collection '{new_name}' already exists")
        
        collection = self.collections.pop(old_name)
        collection.name = new_name
        collection.modified = datetime.now().isoformat()
        self.collections[new_name] = collection
        self.save()
        
        if DEBUG_MODE:
            print(f"[Collections] Renamed collection: {old_name} → {new_name}")
    
    def delete_collection(self, name: str):
        """Delete a collection"""
        if name not in self.collections:
            raise ValueError(f"Collection '{name}' not found")
        
        del self.collections[name]
        self.save()
        
        if DEBUG_MODE:
            print(f"[Collections] Deleted collection: {name}")
    
    def get_all_collections(self) -> List[Collection]:
        """Get all collections"""
        return list(self.collections.values())
    
    def get_manual_collections(self) -> List[ManualCollection]:
        """Get all manual collections"""
        return [c for c in self.collections.values() if c.type == 'manual']
    
    def get_smart_collections(self) -> List[SmartCollection]:
        """Get all smart collections"""
        return [c for c in self.collections.values() if c.type == 'smart']
    
    def save(self):
        """Save collections to JSON"""
        data = {
            'version': '1.0',
            'collections': {name: col.to_dict() for name, col in self.collections.items()}
        }
        
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            if DEBUG_MODE:
                print(f"[Collections] Saved {len(self.collections)} collections to {self.config_path}")
        
        except Exception as e:
            print(f"[Collections] Error saving collections: {e}")
    
    def load(self):
        """Load collections from JSON"""
        if not self.config_path.exists():
            if DEBUG_MODE:
                print(f"[Collections] No collections file found at {self.config_path}")
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Load collections
            collections_data = data.get('collections', {})
            for name, col_data in collections_data.items():
                try:
                    collection = Collection.from_dict(col_data)
                    self.collections[name] = collection
                except Exception as e:
                    print(f"[Collections] Error loading collection '{name}': {e}")
            
            if DEBUG_MODE:
                print(f"[Collections] Loaded {len(self.collections)} collections from {self.config_path}")
        
        except Exception as e:
            print(f"[Collections] Error loading collections: {e}")
    
    def export_collections(self, export_path: Path):
        """Export all collections to a file"""
        data = {
            'version': '1.0',
            'exported': datetime.now().isoformat(),
            'collections': {name: col.to_dict() for name, col in self.collections.items()}
        }
        
        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            if DEBUG_MODE:
                print(f"[Collections] Exported collections to {export_path}")
            
            return True
        
        except Exception as e:
            print(f"[Collections] Error exporting collections: {e}")
            return False
    
    def import_collections(self, import_path: Path, overwrite: bool = False):
        """Import collections from a file"""
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            collections_data = data.get('collections', {})
            imported_count = 0
            skipped_count = 0
            
            for name, col_data in collections_data.items():
                if name in self.collections and not overwrite:
                    skipped_count += 1
                    continue
                
                try:
                    collection = Collection.from_dict(col_data)
                    self.collections[name] = collection
                    imported_count += 1
                except Exception as e:
                    print(f"[Collections] Error importing collection '{name}': {e}")
            
            if imported_count > 0:
                self.save()
            
            if DEBUG_MODE:
                print(f"[Collections] Imported {imported_count} collections, skipped {skipped_count}")
            
            return imported_count, skipped_count
        
        except Exception as e:
            print(f"[Collections] Error importing collections: {e}")
            return 0, 0
