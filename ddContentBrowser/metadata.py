"""
DD Content Browser - Metadata Module
SQLite-based tag, rating, and color label system
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


class MetadataManager:
    """Manage file metadata (tags, ratings, colors) in SQLite database"""
    
    def __init__(self, db_path: Path = None):
        """
        Initialize metadata manager
        
        Args:
            db_path: Path to SQLite database (default: ~/.ddContentBrowser/tags.db)
        """
        if db_path is None:
            from .utils import get_metadata_db_path
            db_path = get_metadata_db_path()
        
        self.db_path = db_path
        self.conn = None
        self._init_database()
    
    def _init_database(self):
        """Initialize database connection and create tables if needed"""
        # Allow SQLite connection to be used from multiple threads
        # This is safe for our use case (mostly reads, occasional tag writes)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Access columns by name
        
        cursor = self.conn.cursor()
        
        # File metadata table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_metadata (
                file_path TEXT PRIMARY KEY,
                rating INTEGER DEFAULT 0,
                color_label TEXT DEFAULT NULL,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tags table (hierarchical)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                category TEXT DEFAULT NULL,
                color TEXT DEFAULT NULL,
                parent_id INTEGER,
                FOREIGN KEY (parent_id) REFERENCES tags(id)
            )
        ''')
        
        # File-tag relationship (many-to-many)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_tags (
                file_path TEXT NOT NULL,
                tag_id INTEGER NOT NULL,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (file_path, tag_id),
                FOREIGN KEY (file_path) REFERENCES file_metadata(file_path),
                FOREIGN KEY (tag_id) REFERENCES tags(id)
            )
        ''')
        
        # Create indexes for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_rating ON file_metadata(rating)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_color ON file_metadata(color_label)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_category ON tags(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_tags_path ON file_tags(file_path)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_tags_tag ON file_tags(tag_id)')
        
        self.conn.commit()
    
    def load_default_tags(self, json_path: Path = None):
        """
        Load default tags from JSON file
        
        Args:
            json_path: Path to default_tags.json (default: script dir)
        """
        if json_path is None:
            script_dir = Path(__file__).parent
            json_path = script_dir / "default_tags.json"
        
        if not json_path.exists():
            print(f"Warning: {json_path} not found, skipping default tags")
            return
        
        with open(json_path, 'r', encoding='utf-8') as f:
            default_tags = json.load(f)
        
        cursor = self.conn.cursor()
        
        for category, data in default_tags.items():
            color = data.get("color", None)
            tags = data.get("tags", [])
            
            for tag_name in tags:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO tags (name, category, color)
                        VALUES (?, ?, ?)
                    ''', (tag_name, category, color))
                except sqlite3.IntegrityError:
                    pass  # Tag already exists
        
        self.conn.commit()
        print(f"Loaded default tags from {json_path}")
    
    # ========================================================================
    # TAG OPERATIONS
    # ========================================================================
    
    def add_tag(self, tag_name: str, category: str = None, color: str = None) -> int:
        """Add new tag to database"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO tags (name, category, color)
            VALUES (?, ?, ?)
        ''', (tag_name, category, color))
        self.conn.commit()
        
        # Get tag ID
        cursor.execute('SELECT id FROM tags WHERE name = ?', (tag_name,))
        result = cursor.fetchone()
        return result[0] if result else cursor.lastrowid
    
    def get_all_tags(self) -> List[Dict]:
        """Get all tags grouped by category"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM tags ORDER BY category, name')
        
        tags = []
        for row in cursor.fetchall():
            tags.append({
                'id': row['id'],
                'name': row['name'],
                'category': row['category'],
                'color': row['color']
            })
        return tags
    
    def get_tags_by_category(self) -> Dict[str, List[Dict]]:
        """Get tags grouped by category"""
        tags = self.get_all_tags()
        grouped = {}
        
        for tag in tags:
            category = tag['category'] or 'Uncategorized'
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(tag)
        
        return grouped
    
    def get_tag_by_name(self, tag_name: str) -> Optional[Dict]:
        """Get tag by name"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM tags WHERE name = ?', (tag_name,))
        row = cursor.fetchone()
        
        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'category': row['category'],
                'color': row['color']
            }
        return None
    
    # ========================================================================
    # FILE METADATA OPERATIONS
    # ========================================================================
    
    def set_file_rating(self, file_path: str, rating: int):
        """Set rating for file (0-5 stars)"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO file_metadata (file_path, rating, date_modified)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(file_path) DO UPDATE SET
                rating = excluded.rating,
                date_modified = CURRENT_TIMESTAMP
        ''', (file_path, rating))
        self.conn.commit()
    
    def set_file_color(self, file_path: str, color: str):
        """Set color label for file"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO file_metadata (file_path, color_label, date_modified)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(file_path) DO UPDATE SET
                color_label = excluded.color_label,
                date_modified = CURRENT_TIMESTAMP
        ''', (file_path, color))
        self.conn.commit()
    
    def add_tag_to_file(self, file_path: str, tag_id: int):
        """Add tag to file"""
        cursor = self.conn.cursor()
        
        # Ensure file exists in file_metadata
        cursor.execute('''
            INSERT OR IGNORE INTO file_metadata (file_path)
            VALUES (?)
        ''', (file_path,))
        
        # Add tag relationship
        cursor.execute('''
            INSERT OR IGNORE INTO file_tags (file_path, tag_id)
            VALUES (?, ?)
        ''', (file_path, tag_id))
        
        self.conn.commit()
    
    def remove_tag_from_file(self, file_path: str, tag_id: int):
        """Remove tag from file"""
        cursor = self.conn.cursor()
        cursor.execute('''
            DELETE FROM file_tags
            WHERE file_path = ? AND tag_id = ?
        ''', (file_path, tag_id))
        self.conn.commit()
    
    def get_file_metadata(self, file_path: str) -> Optional[Dict]:
        """Get all metadata for a file"""
        cursor = self.conn.cursor()
        
        # Get basic metadata
        cursor.execute('''
            SELECT * FROM file_metadata WHERE file_path = ?
        ''', (file_path,))
        
        row = cursor.fetchone()
        if not row:
            # Return empty metadata if file not in database
            return {
                'file_path': file_path,
                'rating': 0,
                'color_label': None,
                'date_added': None,
                'date_modified': None,
                'tags': []
            }
        
        metadata = {
            'file_path': row['file_path'],
            'rating': row['rating'],
            'color_label': row['color_label'],
            'date_added': row['date_added'],
            'date_modified': row['date_modified']
        }
        
        # Get tags
        cursor.execute('''
            SELECT t.* FROM tags t
            JOIN file_tags ft ON t.id = ft.tag_id
            WHERE ft.file_path = ?
        ''', (file_path,))
        
        metadata['tags'] = []
        for tag_row in cursor.fetchall():
            metadata['tags'].append({
                'id': tag_row['id'],
                'name': tag_row['name'],
                'category': tag_row['category'],
                'color': tag_row['color']
            })
        
        return metadata
    
    # ========================================================================
    # SEARCH & FILTER
    # ========================================================================
    
    def search_files_by_tags(self, tag_ids: List[int], match_all: bool = False) -> List[str]:
        """
        Search files by tags
        
        Args:
            tag_ids: List of tag IDs to search for
            match_all: If True, file must have ALL tags; if False, ANY tag
        
        Returns:
            List of file paths
        """
        if not tag_ids:
            return []
        
        cursor = self.conn.cursor()
        
        if match_all:
            # File must have ALL tags
            placeholders = ','.join('?' * len(tag_ids))
            query = f'''
                SELECT file_path FROM file_tags
                WHERE tag_id IN ({placeholders})
                GROUP BY file_path
                HAVING COUNT(DISTINCT tag_id) = ?
            '''
            cursor.execute(query, tag_ids + [len(tag_ids)])
        else:
            # File must have ANY tag
            placeholders = ','.join('?' * len(tag_ids))
            query = f'''
                SELECT DISTINCT file_path FROM file_tags
                WHERE tag_id IN ({placeholders})
            '''
            cursor.execute(query, tag_ids)
        
        return [row[0] for row in cursor.fetchall()]
    
    def filter_files_by_rating(self, min_rating: int = 0, max_rating: int = 5) -> List[str]:
        """Get files with rating in range"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT file_path FROM file_metadata
            WHERE rating >= ? AND rating <= ?
        ''', (min_rating, max_rating))
        return [row[0] for row in cursor.fetchall()]
    
    def filter_files_by_color(self, colors: List[str]) -> List[str]:
        """Get files with specific color labels"""
        if not colors:
            return []
        
        cursor = self.conn.cursor()
        placeholders = ','.join('?' * len(colors))
        query = f'''
            SELECT file_path FROM file_metadata
            WHERE color_label IN ({placeholders})
        '''
        cursor.execute(query, colors)
        return [row[0] for row in cursor.fetchall()]
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def reset_database(self):
        """Reset entire tag database - clear all tags and file associations"""
        cursor = self.conn.cursor()
        
        # Clear all data
        cursor.execute('DELETE FROM file_tags')
        cursor.execute('DELETE FROM file_metadata')
        cursor.execute('DELETE FROM tags')
        
        # Reset autoincrement counters
        cursor.execute('DELETE FROM sqlite_sequence WHERE name IN ("file_metadata", "tags", "file_tags")')
        
        self.conn.commit()
        print("✓ Tag database reset - all tags and associations cleared")
    
    def clear_all_tag_assignments(self):
        """Clear all tag assignments but keep tag names"""
        cursor = self.conn.cursor()
        
        # Only clear file-tag relationships, keep tag names in 'tags' table
        cursor.execute('DELETE FROM file_tags')
        
        self.conn.commit()
        print("✓ Tag assignments cleared - tag names preserved")
    
    def load_default_tags(self):
        """Load default tags from default_tags.json"""
        import json
        import os
        
        # Find default_tags.json in same directory as this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_tags_path = os.path.join(current_dir, 'default_tags.json')
        
        if not os.path.exists(default_tags_path):
            print(f"Warning: default_tags.json not found at {default_tags_path}")
            return 0
        
        try:
            with open(default_tags_path, 'r', encoding='utf-8') as f:
                categories = json.load(f)
            
            added_count = 0
            cursor = self.conn.cursor()
            
            for category_name, category_data in categories.items():
                for tag_name in category_data.get('tags', []):
                    # Check if tag already exists
                    cursor.execute('SELECT id FROM tags WHERE name = ?', (tag_name,))
                    if cursor.fetchone() is None:
                        # Add new tag
                        cursor.execute(
                            'INSERT INTO tags (name, category) VALUES (?, ?)',
                            (tag_name, category_name)
                        )
                        added_count += 1
            
            self.conn.commit()
            print(f"✓ Loaded {added_count} default tags from {len(categories)} categories")
            return added_count
            
        except Exception as e:
            print(f"Error loading default tags: {e}")
            return 0
    
    def update_tag_name(self, tag_id: int, new_name: str) -> bool:
        """Update tag name"""
        cursor = self.conn.cursor()
        
        # Check if new name already exists (different tag)
        cursor.execute('SELECT id FROM tags WHERE name = ? AND id != ?', (new_name, tag_id))
        if cursor.fetchone():
            print(f"Error: Tag '{new_name}' already exists")
            return False
        
        cursor.execute('UPDATE tags SET name = ? WHERE id = ?', (new_name, tag_id))
        self.conn.commit()
        print(f"✓ Tag renamed to '{new_name}'")
        return True
    
    def move_tag_to_category(self, tag_id: int, new_category: str) -> bool:
        """Move tag to a different category"""
        cursor = self.conn.cursor()
        
        cursor.execute('UPDATE tags SET category = ? WHERE id = ?', (new_category, tag_id))
        self.conn.commit()
        print(f"✓ Tag moved to category '{new_category}'")
        return True
    
    def delete_tag(self, tag_id: int) -> bool:
        """Delete tag and all its file associations"""
        cursor = self.conn.cursor()
        
        # Delete file associations first
        cursor.execute('DELETE FROM file_tags WHERE tag_id = ?', (tag_id,))
        
        # Delete tag
        cursor.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
        
        self.conn.commit()
        print(f"✓ Tag deleted (ID: {tag_id})")
        return True
    
    def update_category_name(self, old_category: str, new_category: str) -> bool:
        """Update category name for all tags in that category"""
        cursor = self.conn.cursor()
        
        cursor.execute('UPDATE tags SET category = ? WHERE category = ?', (new_category, old_category))
        affected = cursor.rowcount
        
        self.conn.commit()
        print(f"✓ Category '{old_category}' renamed to '{new_category}' ({affected} tags updated)")
        return True
    
    def delete_category(self, category_name: str) -> bool:
        """Delete all tags in a category"""
        cursor = self.conn.cursor()
        
        # Get all tag IDs in this category
        cursor.execute('SELECT id FROM tags WHERE category = ?', (category_name,))
        tag_ids = [row[0] for row in cursor.fetchall()]
        
        if not tag_ids:
            print(f"No tags found in category '{category_name}'")
            return False
        
        # Delete file associations for all tags in category
        cursor.execute(f'DELETE FROM file_tags WHERE tag_id IN ({",".join("?" * len(tag_ids))})', tag_ids)
        
        # Delete all tags in category
        cursor.execute('DELETE FROM tags WHERE category = ?', (category_name,))
        
        self.conn.commit()
        print(f"✓ Category '{category_name}' deleted ({len(tag_ids)} tags removed)")
        return True
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Singleton instance
_metadata_manager = None

def get_metadata_manager() -> MetadataManager:
    """Get or create singleton MetadataManager instance"""
    global _metadata_manager
    if _metadata_manager is None:
        _metadata_manager = MetadataManager()
        
        # Load default tags on first init if database is empty
        cursor = _metadata_manager.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM tags')
        tag_count = cursor.fetchone()[0]
        
        if tag_count == 0:
            _metadata_manager.load_default_tags()
    
    return _metadata_manager
