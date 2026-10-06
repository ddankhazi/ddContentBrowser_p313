# -*- coding: utf-8 -*-
"""
DD Content Browser - Asset Library (data layer)

Reads Megascans libraries into a per-library SQLite database and serves
fast, Bridge-style faceted filtering over it.

Sources, per configured library root - nothing is ever written into the
library itself:
  1. Bridge's own index, <Downloaded>/assetsData.json, when present: one
     file with every asset's metadata (a couple of seconds for ~19k assets);
  2. each asset folder's own JSON, for folders the index doesn't list - or
     for every folder, when there's no index at all;
  3. folders without any JSON still show up, typed by their category
     folder, just without tags.
Paths inside Bridge's index are never trusted - they're absolute paths of
whichever machine wrote it. Only the relative folder names are used, joined
onto the root the user configured.

The database is a rebuildable cache (utils.get_local_cache_dir()): one file
per library root, built into a temp file and swapped in at the end, so a
cancelled or failed build never leaves a half-written one behind.

Filtering runs in memory (LibraryDataset): every facet value is a bitmask
over the asset rows, so a filter change - result list plus live counts on
every chip - is a handful of integer ANDs and popcounts.

Plain Python + sqlite3, no Qt - the UI and its worker threads live in
asset_library_panel.py.
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCHEMA_VERSION = 1

# Asset types: key -> label, in display order. Keys are what the category
# tree's first level and the 'visible_types' setting use.
TYPE_LABELS = {
    '3d': '3D Assets',
    '3dplant': '3D Plants',
    'surface': 'Surfaces',
    'decal': 'Decals',
    'atlas': 'Atlases',
    'imperfection': 'Imperfections',
    'displacement': 'Displacements',
    'brush': 'Brushes',
    'other': 'Other',
}
# Brushes can't be imported into Maya - hidden unless switched on
DEFAULT_VISIBLE_TYPES = [t for t in TYPE_LABELS if t != 'brush']

# semanticTags.asset_type / Bridge 'type' / category folder name -> type key
_TYPE_ALIASES = {
    '3d asset': '3d', '3d': '3d', '3d assets': '3d',
    '3d plant': '3dplant', '3dplant': '3dplant', '3d plants': '3dplant',
    'surface': 'surface', 'surfaces': 'surface',
    'decal': 'decal', 'decals': 'decal',
    'atlas': 'atlas', 'atlases': 'atlas',
    'imperfection': 'imperfection', 'imperfections': 'imperfection',
    'displacement': 'displacement', 'displacements': 'displacement',
    'brush': 'brush', 'brushes': 'brush',
}

# Facets shown as chip groups, in panel order ('category' is the tree)
FACETS = [
    ('environment', 'Environment'),
    ('state', 'State'),
    ('color', 'Color'),
    ('size', 'Size'),
    ('subject', 'Subject'),
    ('placement', 'Interior / Exterior'),
    ('orientation', 'Orientation'),
    ('tileable', 'Tileable'),
    ('region', 'Region'),
]

_COLOR_PALETTE = ('black', 'brown', 'blue', 'gray', 'green', 'orange',
                  'pink', 'purple', 'red', 'white', 'yellow')

# Real-world size buckets (largest dimension, metres): (upper bound, key, label)
_SIZE_BUCKETS = [
    (0.25, 'xs', '< 0.25 m'),
    (0.5, 's', '0.25 - 0.5 m'),
    (1.0, 'm', '0.5 - 1 m'),
    (2.0, 'l', '1 - 2 m'),
    (4.0, 'xl', '2 - 4 m'),
    (8.0, 'xxl', '4 - 8 m'),
    (math.inf, 'huge', '> 8 m'),
]

# Small facets only keep values from a known vocabulary - the source data has
# typos and one-offs that would otherwise each become a chip of their own
_VOCABULARY = {
    'state': ('new', 'old', 'damaged'),
    'subject': ('manmade', 'nature', 'animal', 'human'),
    'placement': ('interior', 'exterior'),
    'orientation': ('floor', 'wall', 'ceiling', 'roof'),
    'tileable': ('yes', 'no'),
}
_FIXED_LABELS = {
    'subject': {'manmade': 'Man-made', 'nature': 'Nature', 'animal': 'Animal', 'human': 'Human'},
    'tileable': {'yes': 'Tileable', 'no': 'Not tileable'},
    'size': {key: label for _, key, label in _SIZE_BUCKETS},
}

# Downloaded/ subfolders that aren't asset categories (MetaHumans, UE assets)
_SKIP_CATEGORY_DIRS = {'dhi', 'uassets'}
_KNOWN_CATEGORY_DIRS = {'3d', '3dplant', 'surface', 'atlas', 'brush', 'decal',
                        'imperfection', 'displacement'}

_PREVIEW_EXTS = ('.png', '.jpg', '.jpeg')


class BuildCancelled(Exception):
    """Raised inside build_database() when its is_cancelled() turns True."""


# ============================================================================
# LIBRARY DETECTION / DATABASE LOCATION
# ============================================================================

def _child_dir(directory, name):
    """Case-insensitive child folder lookup (Linux/macOS are case-sensitive)."""
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.lower() == name and entry.is_dir():
                    return Path(entry.path)
    except OSError:
        pass
    return None


def _has_category_dirs(directory):
    try:
        with os.scandir(directory) as it:
            return any(e.name.lower() in _KNOWN_CATEGORY_DIRS and e.is_dir() for e in it)
    except OSError:
        return False


def detect_megascans_library(path):
    """
    Work out where a Megascans library's assets are, from whichever folder
    the user picked: the library root (holding Downloaded/ and usually a
    library.qms), the Downloaded folder itself, or a plain folder of
    category folders (3d, surface, ...) copied out of a library.

    Returns a dict: 'root' (Path), 'downloaded' (Path or None), 'index'
    (Path of Bridge's assetsData.json, or None) and 'error' (str or None).
    """
    result = {'root': Path(path) if path else None, 'downloaded': None, 'index': None, 'error': None}
    if not path:
        result['error'] = "No folder set"
        return result
    root = Path(os.path.expanduser(str(path)))
    result['root'] = root
    if not root.is_dir():
        result['error'] = "Folder not found"
        return result

    candidates = []
    if root.name.lower() != 'downloaded':
        downloaded = _child_dir(root, 'downloaded')
        if downloaded:
            candidates.append(downloaded)
    candidates.append(root)

    for candidate in candidates:
        index = candidate / 'assetsData.json'
        if index.is_file() or _has_category_dirs(candidate):
            result['downloaded'] = candidate
            result['index'] = index if index.is_file() else None
            return result

    result['error'] = ("No Megascans assets found here - expected a 'Downloaded' folder "
                       "or category folders like 3d / surface")
    return result


def _normalized_root(root):
    """One spelling per library: UNC -> mapped drive letter (see
    utils.to_maya_path), absolute, case-folded on Windows - so W:\\lib and
    \\\\server\\W\\lib are the same library for everyone."""
    path = os.path.expanduser(str(root))
    try:
        from .utils import to_maya_path
        path = to_maya_path(path)
    except Exception:
        pass
    return os.path.normcase(os.path.abspath(path))


def library_key(root):
    """Stable id of a library root - the same however the root is spelled."""
    return hashlib.sha1(_normalized_root(root).encode('utf-8')).hexdigest()[:10]


def same_library(a, b):
    return library_key(a) == library_key(b)


def _db_basename(root):
    slug = re.sub(r'[^0-9A-Za-z]+', '_', Path(_normalized_root(root)).name).strip('_')[:40] or 'library'
    return "megascans_{0}_{1}".format(slug, library_key(root))


def database_path(root):
    """The local database file of one library root (it may not exist yet)."""
    from .utils import get_local_cache_dir
    return get_local_cache_dir('asset_library') / (_db_basename(root) + ".db")


# ============================================================================
# METADATA NORMALIZATION
# ============================================================================

def _clean(value):
    """Lowercase, trimmed, inner whitespace collapsed - '' for non-strings."""
    if not isinstance(value, str):
        return ''
    return ' '.join(value.split()).lower()


def _as_list(value):
    """A tag field as a list of cleaned strings - the source mixes str and list."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for v in value:
        c = _clean(v)
        if c and c not in ('undefined', 'none', 'null'):
            out.append(c)
    return out


def _to_float(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        m = re.search(r'\d+(?:\.\d+)?', value)
        if m:
            f = float(m.group(0))
            return f if f > 0 else None
    return None


def _meta_value(data, key):
    for item in data.get('meta') or []:
        if isinstance(item, dict) and item.get('key') == key:
            return item.get('value')
    return None


def _asset_type(semantic, data, category_dir):
    for candidate in (semantic.get('asset_type'), data.get('type'),
                      (data.get('categories') or [None])[0], category_dir):
        key = _TYPE_ALIASES.get(_clean(candidate))
        if key:
            return key
    return 'other'


def _category_paths(asset_type, data):
    """
    Category tree values of one asset: 'type', 'type/sub', 'type/sub/sub2'.
    An asset can sit in several branches (assetCategories is a tree, e.g.
    {"3D asset": {"historical": {...}, "props": {"wheel": {}}}}). The
    tree's own first level is ignored - the type key replaces it, so the
    tree always matches the type the rest of the panel uses.
    """
    paths = set()
    tree = data.get('assetCategories')
    if isinstance(tree, dict) and tree:
        def walk(node, trail):
            if not isinstance(node, dict) or not node or len(trail) == 2:
                if trail:
                    paths.add(tuple(trail))
                return
            for key, child in node.items():
                name = _clean(key)
                if name:
                    walk(child, trail + [name])
        for child in tree.values():
            walk(child, [])
    if not paths:
        cats = _as_list(data.get('categories'))[1:3]
        if cats:
            paths.add(tuple(cats))

    values = {asset_type}
    for trail in paths:
        for depth in range(1, len(trail) + 1):
            values.add('/'.join((asset_type,) + trail[:depth]))
    return values


def _environment_values(semantic):
    out = set()
    for v in _as_list(semantic.get('environment')):
        v = re.sub(r'\s*biome$', '', v)
        v = {'fresh water': 'freshwater', 'tropical-jungle': 'tropical jungle'}.get(v, v)
        if v:
            out.add(v)
    return out


def _color_values(semantic, data):
    """Bridge's 11-colour palette. Free-text colours ('Dark Brown', ' grey')
    are reduced to their palette words; assets without semantic colours
    fall back to colour words among their plain tags (as Bridge does)."""
    def palette_words(values):
        found = set()
        for v in values:
            for word in re.split(r'[^a-z]+', v):
                word = 'gray' if word == 'grey' else word
                if word in _COLOR_PALETTE:
                    found.add(word)
        return found
    colors = palette_words(_as_list(semantic.get('color')))
    if not colors:
        colors = palette_words([t for t in _as_list(data.get('tags')) if ' ' not in t])
    return colors


def _size_m(semantic, data):
    """Largest real-world dimension in metres, or None."""
    size = _to_float(semantic.get('maxSize'))
    if size:
        return size
    scan_area = _meta_value(data, 'scanArea')
    if isinstance(scan_area, str):
        numbers = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', scan_area)]
        if numbers and max(numbers) > 0:
            return max(numbers)
    dims = [_to_float(_meta_value(data, key)) for key in ('length', 'width', 'height')]
    dims = [d for d in dims if d]
    return max(dims) if dims else None


def _size_bucket(size):
    if not size:
        return None
    for upper, key, _ in _SIZE_BUCKETS:
        if size < upper:
            return key
    return None


def _region_values(semantic, data):
    region = _clean(semantic.get('region'))
    if not region:
        legacy = data.get('environment')
        if isinstance(legacy, dict):
            region = _clean(legacy.get('region'))
    if not region or region in ('undefined', 'none', 'custom') or region.isdigit():
        return set()
    return {{'austrailia': 'australia'}.get(region, region)}


def _vocab(facet, values):
    allowed = _VOCABULARY[facet]
    return {v for v in values if v in allowed}


def parse_asset(data, rel, category_dir):
    """
    One asset's record from its Megascans metadata (a Bridge index entry and
    an asset's own <id>.json share the fields used here). `data` may be None
    for a folder without any JSON. Returns a dict with name, asset_id, type,
    size_m, search (lowercase search text), facets {facet: set(values)} and
    has_meta.
    """
    folder_name = rel.rsplit('/', 1)[-1]
    if not isinstance(data, dict):
        asset_type = _TYPE_ALIASES.get(_clean(category_dir), 'other')
        return {
            'name': folder_name, 'asset_id': '', 'type': asset_type, 'size_m': None,
            'search': _clean(folder_name), 'facets': {'category': {asset_type}}, 'has_meta': False,
        }

    semantic = data.get('semanticTags')
    if not isinstance(semantic, dict):
        semantic = {}
    name = (data.get('name') or semantic.get('name') or folder_name)
    name = ' '.join(str(name).split())
    asset_id = str(data.get('id') or data.get('asset') or '')
    asset_type = _asset_type(semantic, data, category_dir)
    size = _size_m(semantic, data)

    facets = {
        'category': _category_paths(asset_type, data),
        'environment': _environment_values(semantic),
        'state': _vocab('state', _as_list(semantic.get('state'))),
        'color': _color_values(semantic, data),
        'subject': _vocab('subject', {v.replace('-', '').replace(' ', '')
                                      for v in _as_list(semantic.get('subject_matter'))}),
        'placement': _vocab('placement', _as_list(semantic.get('interior_exterior'))),
        'orientation': _vocab('orientation', _as_list(semantic.get('orientation'))),
        'region': _region_values(semantic, data),
    }
    bucket = _size_bucket(size)
    if bucket:
        facets['size'] = {bucket}
    tileable = _meta_value(data, 'tileable')
    if isinstance(tileable, str):
        tileable = {'true': True, 'false': False}.get(tileable.strip().lower())
    if isinstance(tileable, bool):
        facets['tileable'] = {'yes' if tileable else 'no'}

    words = [name, asset_id, folder_name]
    for key in ('tags', 'categories'):
        words += _as_list(data.get(key))
    for key in ('contains', 'theme', 'descriptive', 'latin_name', 'collection',
                'country', 'region', 'city'):
        words += _as_list(semantic.get(key))
    pack = data.get('pack')
    if isinstance(pack, dict):
        words += _as_list(pack.get('name'))
    words += [v.replace('/', ' ') for v in facets['category']]
    search = ' '.join(_clean(w) for w in words if w)

    return {
        'name': name, 'asset_id': asset_id, 'type': asset_type, 'size_m': size,
        'search': search, 'facets': {k: v for k, v in facets.items() if v}, 'has_meta': True,
    }


def type_from_folder_name(name):
    """Asset type of a Megascans category folder name ('3d', 'surface',
    'atlas', ...), or None."""
    return _TYPE_ALIASES.get(_clean(name))


def value_label(facet, value):
    """Display label of a facet value."""
    if facet == 'category':
        parts = value.split('/')
        if len(parts) == 1:
            return TYPE_LABELS.get(value, value.title())
        return parts[-1].title()
    if facet == 'type':
        return TYPE_LABELS.get(value, value.title())
    if facet == 'color':
        return value.title()
    fixed = _FIXED_LABELS.get(facet)
    if fixed and value in fixed:
        return fixed[value]
    return value.title()


def sort_values(facet, values):
    """Stable display order of a facet's values (never by count - chips
    jumping around on every click would be unusable)."""
    if facet == 'size':
        order = {key: i for i, (_, key, _) in enumerate(_SIZE_BUCKETS)}
    elif facet == 'color':
        order = {c: i for i, c in enumerate(_COLOR_PALETTE)}
    elif facet in _VOCABULARY:
        order = {v: i for i, v in enumerate(_VOCABULARY[facet])}
    else:
        return sorted(values, key=lambda v: value_label(facet, v).lower())
    return sorted(values, key=lambda v: (order.get(v, len(order)), v))


# ============================================================================
# BUILD
# ============================================================================

def _list_asset_folders(downloaded, is_cancelled):
    """
    Every asset folder under the category folders of `downloaded`:
    {rel.lower(): (rel, abs_path, mtime, category_dir)}, plus the category
    folders' own mtimes (for the staleness check).

    Asset folder mtimes come with the listing (os.scandir hands them out on
    Windows without a stat per folder - ~20k stats over a network drive
    would take minutes). That's the parent's cached copy of the value,
    which can lag right after a folder's contents changed - fine for
    downloaded assets, which don't. The few category folders, whose mtime
    is how a change is detected, are stat'ed for the real value.
    """
    folders = {}
    dir_mtimes = {}
    loose_files = {}  # category -> file names sitting in the category folder itself
    with os.scandir(downloaded) as it:
        categories = [e for e in it if e.is_dir() and not e.name.startswith('.')
                      and e.name.lower() not in _SKIP_CATEGORY_DIRS]
    for cat in sorted(categories, key=lambda e: e.name.lower()):
        try:
            dir_mtimes[cat.name] = os.stat(cat.path).st_mtime
            files = loose_files.setdefault(cat.name, [])
            with os.scandir(cat.path) as it:
                for entry in it:
                    if is_cancelled():
                        raise BuildCancelled()
                    if entry.name.startswith('.'):
                        continue
                    if not entry.is_dir():
                        files.append(entry.name)
                        continue
                    rel = cat.name + '/' + entry.name
                    folders[rel.lower()] = (rel, str(Path(entry.path)), entry.stat().st_mtime, cat.name)
        except OSError as e:
            print("[AssetLibrary] Could not list {0}: {1}".format(cat.path, e))
            loose_files.pop(cat.name, None)  # never offer an incomplete listing for it
    return folders, dir_mtimes, loose_files


def _read_asset_folder(abs_path, rel):
    """(metadata dict or None, preview path relative to Downloaded or None)
    of one asset folder, read from its own files."""
    try:
        with os.scandir(abs_path) as it:
            files = [e.name for e in it if e.is_file()]
    except OSError:
        return None, None

    preview = None
    for name in sorted(files, key=lambda n: (not n.lower().endswith('_preview.png'), n.lower())):
        stem, ext = os.path.splitext(name.lower())
        if ext in _PREVIEW_EXTS and stem.endswith('preview'):
            preview = rel + '/' + name
            break

    folder_id = rel.rsplit('/', 1)[-1].rsplit('_', 1)[-1].lower()
    jsons = [n for n in files if n.lower().endswith('.json')]
    jsons.sort(key=lambda n: (os.path.splitext(n)[0].lower() != folder_id, n.lower()))
    for name in jsons:
        try:
            with open(os.path.join(abs_path, name), 'r', encoding='utf-8', errors='replace') as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and ('semanticTags' in data or 'categories' in data or 'id' in data):
            return data, preview
    return None, preview


_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE assets (
    id INTEGER PRIMARY KEY,
    rel TEXT NOT NULL,          -- folder, relative to the Downloaded folder ('/' separated)
    asset_id TEXT,
    name TEXT,
    type TEXT,
    preview TEXT,               -- preview image, relative to the Downloaded folder
    mtime REAL,                 -- folder mtime from the directory listing (thumbnail cache key)
    size_m REAL,
    search TEXT,
    has_meta INTEGER
);
CREATE TABLE facets (asset INTEGER, facet TEXT, value TEXT);
-- Files sitting directly in a category folder (zips, loose previews, ...):
-- with the asset folders, that's the category folder's complete listing,
-- which normal browsing then takes from here (see LibraryDataset.dir_listing)
CREATE TABLE category_files (category TEXT, name TEXT);
"""


def build_database(root, db_path=None, progress=None, is_cancelled=None, use_index=True, workers=16):
    """
    (Re)build the database of one Megascans library root. Blocking - run it
    on a worker thread. `progress(phase, done, total)` is called now and
    then; `is_cancelled()` is polled, and makes the build stop with
    BuildCancelled (the old database stays untouched).

    Returns a summary dict (counts, source, seconds). Raises ValueError for
    a folder that isn't a Megascans library.
    """
    progress = progress or (lambda phase, done, total: None)
    is_cancelled = is_cancelled or (lambda: False)
    started = time.time()

    detected = detect_megascans_library(root)
    if detected['error']:
        raise ValueError(detected['error'])
    downloaded = detected['downloaded']
    index = detected['index'] if use_index else None
    db_path = Path(db_path) if db_path else database_path(root)

    progress("Scanning folders", 0, 0)
    folders, dir_mtimes, loose_files = _list_asset_folders(str(downloaded), is_cancelled)

    records = {}  # rel.lower() -> record
    index_missing = 0
    index_stat = None
    if index is not None:
        progress("Reading Bridge index", 0, 0)
        index_stat = index.stat()
        with open(index, 'r', encoding='utf-8', errors='replace') as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            entries = []
        for i, entry in enumerate(entries):
            if i % 500 == 0:
                if is_cancelled():
                    raise BuildCancelled()
                progress("Reading Bridge index", i, len(entries))
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), list):
                continue
            rel = '/'.join(str(p) for p in entry['path'])
            key = rel.lower()
            if key in records:
                continue
            folder = folders.get(key)
            if folder is None:
                index_missing += 1  # listed by Bridge but gone from disk
                continue
            rel, abs_path, mtime, category_dir = folder
            record = parse_asset(entry, rel, category_dir)
            preview = entry.get('preview')
            preview = '/'.join(str(p) for p in preview) if isinstance(preview, list) else None
            record.update(rel=rel, mtime=mtime,
                          preview=preview if preview and preview.lower().startswith(key + '/') else None)
            records[key] = record

    # Folders the index doesn't know (or all of them, without an index)
    todo = [f for key, f in folders.items() if key not in records]
    from_json = 0
    if todo:
        total = len(todo)
        progress("Reading asset files", 0, total)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [(f, pool.submit(_read_asset_folder, f[1], f[0])) for f in todo]
            for done, (folder, future) in enumerate(futures, 1):
                if is_cancelled():
                    for _, fut in futures:
                        fut.cancel()
                    raise BuildCancelled()
                rel, abs_path, mtime, category_dir = folder
                data, preview = future.result()
                record = parse_asset(data, rel, category_dir)
                record.update(rel=rel, mtime=mtime, preview=preview)
                records[rel.lower()] = record
                from_json += 1 if record['has_meta'] else 0
                if done % 50 == 0 or done == total:
                    progress("Reading asset files", done, total)

    if is_cancelled():
        raise BuildCancelled()
    progress("Writing database", 0, 0)
    ordered = sorted(records.values(), key=lambda r: r['rel'].lower())
    summary = {
        'assets': len(ordered),
        'from_index': len(ordered) - len(todo),
        'from_json': from_json,
        'without_meta': sum(1 for r in ordered if not r['has_meta']),
        'index_missing': index_missing,
        'source': 'bridge_index' if index is not None else 'asset_files',
        'seconds': round(time.time() - started, 1),
    }
    try:
        downloaded_rel = os.path.relpath(str(downloaded), str(detected['root']))
    except ValueError:
        downloaded_rel = None
    meta = {
        'schema_version': SCHEMA_VERSION,
        'root': str(root),
        'downloaded': str(downloaded),
        # Shared databases are read on other machines, where the library may
        # be spelled differently - they join this onto their own root
        'downloaded_rel': downloaded_rel,
        'built_at': time.time(),
        'index_mtime': index_stat.st_mtime if index_stat else None,
        'index_size': index_stat.st_size if index_stat else None,
        'dir_mtimes': dir_mtimes,
        # Category folders whose complete listing is in category_files +
        # assets (normal browsing may take it from here - see dir_listing)
        'listed_categories': sorted(loose_files),
        'summary': summary,
    }
    _write_database(db_path, ordered, meta, loose_files)
    return summary


def _write_database(db_path, records, meta, loose_files=None):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + '.tmp')
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(str(tmp))
    try:
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO assets (id, rel, asset_id, name, type, preview, mtime, size_m, search, has_meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(i, r['rel'], r['asset_id'], r['name'], r['type'], r['preview'], r['mtime'],
              r['size_m'], r['search'], int(r['has_meta'])) for i, r in enumerate(records)])
        con.executemany(
            "INSERT INTO facets (asset, facet, value) VALUES (?, ?, ?)",
            [(i, facet, value) for i, r in enumerate(records)
             for facet, values in r['facets'].items() for value in values])
        con.executemany(
            "INSERT INTO category_files (category, name) VALUES (?, ?)",
            [(cat, name) for cat, names in (loose_files or {}).items() for name in names])
        con.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                        [(k, json.dumps(v)) for k, v in meta.items()])
        con.commit()
    finally:
        con.close()
    # Windows refuses to replace a file another thread/process has open
    # right now (the panel loading the old database) - give it a moment
    for attempt in range(20):
        try:
            os.replace(str(tmp), str(db_path))
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.25)


# ============================================================================
# DATABASE STATUS
# ============================================================================

def read_database_meta(db_path):
    """The meta table of a database as a dict, or None (missing, unreadable,
    or written by an incompatible version - those need a rebuild)."""
    db_path = Path(db_path)
    if not db_path.is_file():
        return None
    try:
        con = sqlite3.connect(str(db_path))
        try:
            rows = con.execute("SELECT key, value FROM meta").fetchall()
        finally:
            con.close()
        meta = {k: json.loads(v) for k, v in rows}
    except (sqlite3.Error, ValueError):
        return None
    if meta.get('schema_version') != SCHEMA_VERSION:
        return None
    return meta


def is_database_stale(root, meta, detected=None):
    """
    Cheap check whether a library changed since its database was built:
    Bridge's index file (time/size) and the category folders' own mtimes
    (a folder's mtime changes when an asset folder is added or removed).
    A few stats - no per-asset work. `detected` can pass in an existing
    detect_megascans_library() result.
    """
    detected = detected or detect_megascans_library(root)
    if detected['error'] or not meta:
        return True
    index = detected['index']
    if index is not None:
        try:
            st = index.stat()
        except OSError:
            return True
        if meta.get('index_mtime') != st.st_mtime or meta.get('index_size') != st.st_size:
            return True
    elif meta.get('index_mtime') is not None:
        return True
    current = {}
    try:
        with os.scandir(str(detected['downloaded'])) as it:
            for e in it:
                if e.is_dir() and not e.name.startswith('.') and e.name.lower() not in _SKIP_CATEGORY_DIRS:
                    # Real stat, not the listing's cached copy (see _list_asset_folders)
                    current[e.name] = os.stat(e.path).st_mtime
    except OSError:
        return True
    return current != (meta.get('dir_mtimes') or {})


def delete_database(root):
    """Remove one library's local database (and a leftover temp file). A
    file being read right now (Windows won't delete it) is retried briefly."""
    path = database_path(root)
    for p in (path, path.with_name(path.name + '.tmp')):
        for attempt in range(20):
            try:
                if p.exists():
                    p.unlink()
                break
            except PermissionError:
                time.sleep(0.25)
            except OSError as e:
                print("[AssetLibrary] Could not delete {0}: {1}".format(p, e))
                break
        else:
            print("[AssetLibrary] Could not delete {0} (in use)".format(p))


# ============================================================================
# SHARED DATABASE (optional, one per team)
# ============================================================================
#
# A shared folder everyone can reach holds finished, never-modified database
# snapshots plus a small manifest naming the current one per library:
#
#   <shared folder>/ddContentBrowser/asset_library/
#       manifest.json                      {"libraries": {key: entry}}
#       megascans_<slug>_<key>_<stamp>.db  snapshots (old ones get cleaned up)
#       .publish.lock                      while someone is publishing
#
# SQLite over SMB isn't safe to read while someone writes it, so nobody ever
# does: a new snapshot is built locally, copied up under a new name, and only
# then does the manifest (replaced in one step) point to it. Readers copy the
# current snapshot into their local cache once and read it from there.
# A library is either shared or local - never both (see AssetLibraryService).

MANIFEST_NAME = 'manifest.json'
_LOCK_NAME = '.publish.lock'
_LOCK_STALE_SECONDS = 30 * 60   # a publish that died long ago doesn't block forever
_SNAPSHOTS_KEPT = 2             # current + previous (someone may still be copying it)


class SharedFolderError(Exception):
    """The shared folder can't be used (missing, not writable, locked, ...)."""


def shared_dir(shared_folder):
    return Path(shared_folder) / 'ddContentBrowser' / 'asset_library'


def shared_cache_dir():
    from .utils import get_local_cache_dir
    return get_local_cache_dir('asset_library', 'shared')


def read_manifest(shared_folder):
    """{'libraries': {key: entry}} - empty when nothing is shared yet. Raises
    OSError when the shared folder can't be reached."""
    folder = Path(shared_folder)
    if not folder.is_dir():
        raise OSError("Shared folder not reachable: {0}".format(folder))
    path = shared_dir(shared_folder) / MANIFEST_NAME
    if not path.is_file():
        return {'libraries': {}}
    with open(path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    if not isinstance(manifest, dict) or not isinstance(manifest.get('libraries'), dict):
        return {'libraries': {}}
    return manifest


def read_manifest_cached(shared_folder):
    """
    (manifest, error): the shared manifest, kept as a local copy too - when
    the shared folder can't be reached, the last copy read from that same
    folder stands in for it (error says why), so the shared libraries stay
    usable from their downloaded snapshots.
    """
    cache = shared_cache_dir() / 'manifest.json'
    try:
        manifest = read_manifest(shared_folder)
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            with open(cache, 'w', encoding='utf-8') as f:
                json.dump({'shared_folder': str(shared_folder), 'manifest': manifest}, f)
        except OSError:
            pass
        return manifest, None
    except (OSError, ValueError) as e:
        error = str(e)
    try:
        with open(cache, 'r', encoding='utf-8') as f:
            cached = json.load(f)
        if os.path.normcase(str(cached.get('shared_folder'))) == os.path.normcase(str(shared_folder)):
            return cached.get('manifest') or {'libraries': {}}, error
    except (OSError, ValueError, AttributeError):
        pass
    return {'libraries': {}}, error


def effective_libraries(manifest, local_roots):
    """
    The libraries in use: every shared one (from the manifest) first, then
    the user's own local ones that aren't shared - a library is never both.
    A shared library uses this machine's spelling of its root when the user
    has it in their own list too. Returns [{'root', 'key', 'mode', 'entry'}].
    """
    out, seen = [], set()
    local_keys = [(r, library_key(r)) for r in local_roots]
    for key, entry in ((manifest or {}).get('libraries') or {}).items():
        root = next((r for r, k in local_keys if k == key), entry.get('root'))
        out.append({'root': root, 'key': key, 'mode': 'shared', 'entry': entry})
        seen.add(key)
    for root, key in local_keys:
        if key not in seen:
            out.append({'root': root, 'key': key, 'mode': 'local', 'entry': None})
            seen.add(key)
    return out


def _replace_with_retry(src, dst, attempts=20):
    """os.replace that waits out a reader holding dst open (Windows)."""
    for attempt in range(attempts):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25)


def _write_manifest(shared_folder, manifest):
    folder = shared_dir(shared_folder)
    tmp = folder / (MANIFEST_NAME + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    _replace_with_retry(tmp, folder / MANIFEST_NAME)


def _who():
    import getpass
    import socket
    try:
        user = getpass.getuser()
    except Exception:
        user = '?'
    return "{0}@{1}".format(user, socket.gethostname())


class SharedLock:
    """Exclusive publish lock in the shared folder (a file created with
    O_EXCL). One taken more than _LOCK_STALE_SECONDS ago is considered dead
    and taken over."""

    def __init__(self, shared_folder):
        self.path = shared_dir(shared_folder) / _LOCK_NAME
        self.held = False

    def __enter__(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise SharedFolderError("No write access to the shared folder ({0})".format(e))
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                holder, since = self._holder()
                if since and time.time() - since > _LOCK_STALE_SECONDS:
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                raise SharedFolderError("{0} is updating the shared database right now (since {1})".format(
                    holder or "someone", time.strftime("%H:%M", time.localtime(since)) if since else "?"))
            except OSError as e:
                raise SharedFolderError("No write access to the shared folder ({0})".format(e))
            with os.fdopen(fd, 'w') as f:
                json.dump({'who': _who(), 'since': time.time()}, f)
            self.held = True
            return self
        raise SharedFolderError("Could not take the shared database lock")

    def _holder(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                info = json.load(f)
            return info.get('who'), float(info.get('since') or 0)
        except (OSError, ValueError, TypeError):
            try:
                return None, self.path.stat().st_mtime
            except OSError:
                return None, None

    def __exit__(self, *exc):
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.held = False
        return False


def publish_database(local_db, root, shared_folder):
    """
    Upload a finished local database as the shared one of `root`: copy it up
    under a new snapshot name, then point the manifest at it, then clean up
    older snapshots. Call it holding a SharedLock. Returns the manifest entry.
    """
    meta = read_database_meta(local_db)
    if meta is None:
        raise ValueError("Not a valid library database: {0}".format(local_db))
    key = library_key(root)
    folder = shared_dir(shared_folder)
    name = "{0}_{1}.db".format(_db_basename(root), time.strftime("%Y%m%d-%H%M%S"))
    tmp = folder / (name + '.tmp')
    shutil_copy(local_db, tmp)
    _replace_with_retry(tmp, folder / name)

    manifest = read_manifest(shared_folder)
    entry = {
        'root': str(root),
        'db': name,
        'published_at': time.time(),
        'published_by': _who(),
        'summary': meta.get('summary') or {},
    }
    manifest['libraries'][key] = entry
    _write_manifest(shared_folder, manifest)
    _cleanup_snapshots(folder, _db_basename(root), keep=name)
    return entry


def unpublish(root, shared_folder):
    """Stop sharing `root`: drop it from the manifest (for everyone) and
    remove its snapshots. Call it holding a SharedLock."""
    manifest = read_manifest(shared_folder)
    manifest['libraries'].pop(library_key(root), None)
    _write_manifest(shared_folder, manifest)
    _cleanup_snapshots(shared_dir(shared_folder), _db_basename(root), keep=None, keep_count=0)


def _cleanup_snapshots(folder, basename, keep, keep_count=_SNAPSHOTS_KEPT):
    """Delete all but the newest `keep_count` snapshots of one library (the
    one named `keep` always stays). Files someone has open just stay for now."""
    try:
        snapshots = sorted((p for p in folder.glob(basename + "_*.db")), key=lambda p: p.name, reverse=True)
    except OSError:
        return
    kept = 0
    for p in snapshots:
        if p.name == keep or kept < keep_count:
            kept += 1
            continue
        try:
            p.unlink()
        except OSError:
            pass


def sync_shared_snapshot(root, entry, shared_folder):
    """
    Local copy of a library's current shared snapshot: downloaded once (the
    snapshot never changes - a new one gets a new name), read locally ever
    after. Returns its path, or raises OSError when it can't be fetched.
    """
    cache = shared_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    name = entry.get('db') or ''
    local = cache / name
    if not name or os.sep in name or '/' in name:
        raise OSError("Bad snapshot name in the shared manifest: {0!r}".format(name))
    if not local.is_file():
        tmp = cache / (name + '.tmp')
        shutil_copy(shared_dir(shared_folder) / name, tmp)
        _replace_with_retry(tmp, local)
    # Older downloaded snapshots of this library aren't needed any more
    for p in cache.glob(_db_basename(root) + "_*.db"):
        if p.name != name:
            try:
                p.unlink()
            except OSError:
                pass
    return local


def cached_shared_snapshot(root):
    """The newest snapshot of `root` already downloaded, or None - used when
    the shared folder can't be reached (offline, VPN down, ...)."""
    try:
        snapshots = sorted(shared_cache_dir().glob(_db_basename(root) + "_*.db"), key=lambda p: p.name)
    except OSError:
        return None
    return snapshots[-1] if snapshots else None


def delete_cached_snapshots(root):
    """Remove this machine's downloaded copies of a shared library (they're
    downloaded again on the next load)."""
    try:
        for p in shared_cache_dir().glob(_db_basename(root) + "_*.db"):
            try:
                p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def shutil_copy(src, dst):
    import shutil
    shutil.copyfile(str(src), str(dst))


def is_writable_dir(folder):
    """Whether files can be created in the existing folder `folder` (tries
    it with a probe file - os.access is unreliable on network shares)."""
    folder = Path(folder)
    probe = folder / ".ddcb_write_test_{0}".format(os.getpid())
    try:
        if not folder.is_dir():
            return False
        with open(probe, 'w') as f:
            f.write('x')
        probe.unlink()
        return True
    except OSError:
        return False


# ============================================================================
# SITE DEFAULTS (per installation, e.g. a studio's network-deployed copy)
# ============================================================================
#
# site_defaults.json next to this module holds defaults for everyone running
# this installation of the tool - e.g. the shared database folder. It's not
# part of the open-source distribution; a user's own settings win over it.

def site_defaults_path():
    return Path(__file__).resolve().parent / 'site_defaults.json'


def read_site_defaults():
    path = site_defaults_path()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_site_default(category, key, value):
    """Set (value not None) or clear one site default. Raises OSError when
    the tool's folder isn't writable."""
    data = read_site_defaults()
    section = data.setdefault(category, {})
    if value is None:
        section.pop(key, None)
        if not section:
            data.pop(category, None)
    else:
        section[key] = value
    path = site_defaults_path()
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    _replace_with_retry(tmp, path)


# ============================================================================
# IN-MEMORY DATASET + FACETED QUERY
# ============================================================================

def _bits_from_indices(indices, n_bytes):
    buf = bytearray(n_bytes)
    for i in indices:
        buf[i >> 3] |= 1 << (i & 7)
    return int.from_bytes(bytes(buf), 'little')


def _indices_from_bits(mask, n_bytes):
    out = []
    for byte_index, byte in enumerate(mask.to_bytes(n_bytes, 'little')):
        if byte:
            base = byte_index << 3
            for bit in range(8):
                if byte >> bit & 1:
                    out.append(base + bit)
    return out


class LibraryDataset:
    """
    All built libraries' assets in memory, with one bitmask per facet value.
    Built once per (re)load on a worker thread; queries are read-only.
    """

    def __init__(self):
        self.paths = []      # absolute asset folder path (str)
        self.names = []
        self.ids = []        # Megascans asset id ('' if unknown)
        self.types = []
        self.previews = []   # absolute preview path (str) or None
        self.mtimes = []
        self.sizes = []
        self.searches = []
        self.libraries = []  # [{'root', 'meta', 'count'}]
        self.bits = {}       # facet -> {value: int bitmask}
        self._pending = {}   # facet -> {value: [row indices]} until finalize()
        self._n_bytes = 0
        self._search_cache = (None, 0)
        # Category folders, for normal browsing (see dir_listing):
        # normalized folder path -> {'dir_mtime', 'files' (None: no listing), 'rows', 'folders'}
        self._dirs = {}

    def __len__(self):
        return len(self.paths)

    def add_database(self, root, db_path):
        """Append one library's assets. Returns its row count, or None if
        the database is missing/incompatible."""
        meta = read_database_meta(db_path)
        if meta is None:
            return None
        # The library's own spelling of the root on this machine, never the
        # builder's (a shared database was built somewhere else)
        if meta.get('downloaded_rel') is not None:
            base_dir = Path(os.path.normpath(os.path.join(str(root), meta['downloaded_rel'])))
        else:
            base_dir = Path(meta.get('downloaded') or detect_megascans_library(root)['downloaded'] or root)
        offset = len(self.paths)
        # This library's category folders, keyed the way dir_listing() looks
        # them up (one path normalization per category, not per asset)
        cat_dirs = {}
        for cat, mtime in (meta.get('dir_mtimes') or {}).items():
            entry = {'dir_mtime': mtime, 'files': None, 'rows': []}
            cat_dirs[cat] = entry
            self._dirs[_normalized_root(base_dir / cat)] = entry
        con = sqlite3.connect(str(db_path))
        try:
            id_to_row = {}
            for asset_id, rel, name, a_type, preview, mtime, size, search, megascans_id in con.execute(
                    "SELECT id, rel, name, type, preview, mtime, size_m, search, asset_id FROM assets ORDER BY id"):
                row = len(self.paths)
                id_to_row[asset_id] = row
                cat_entry = cat_dirs.get(rel.split('/', 1)[0])
                if cat_entry is not None:
                    cat_entry['rows'].append(row)
                self.paths.append(str(base_dir.joinpath(*rel.split('/'))))
                self.names.append(name or rel.rsplit('/', 1)[-1])
                self.ids.append(megascans_id or '')
                self.types.append(a_type)
                self.previews.append(str(base_dir.joinpath(*preview.split('/'))) if preview else None)
                self.mtimes.append(mtime or 0.0)
                self.sizes.append(size)
                self.searches.append(search or '')
            for asset_id, facet, value in con.execute("SELECT asset, facet, value FROM facets"):
                row = id_to_row.get(asset_id)
                if row is not None:
                    self._pending.setdefault(facet, {}).setdefault(value, []).append(row)
            # Complete category listings - databases built before they were
            # recorded have no such table (asset folders' previews still work)
            listed = set(meta.get('listed_categories') or [])
            try:
                loose = {}
                for cat, name in con.execute("SELECT category, name FROM category_files"):
                    loose.setdefault(cat, []).append(name)
                for cat in listed:
                    if cat in cat_dirs:
                        cat_dirs[cat]['files'] = loose.get(cat, [])
            except sqlite3.Error:
                pass
        finally:
            con.close()
        count = len(self.paths) - offset
        self.libraries.append({'root': str(root), 'meta': meta, 'count': count})
        return count

    def dir_listing(self, directory):
        """
        What the database knows about a library category folder (e.g.
        .../Downloaded/3d), or None for any other folder:
          'dir_mtime' - the folder's mtime when the database was built; equal
                        to the current one = its listing hasn't changed since
          'files'     - names of the files in it (None: no complete listing)
          'folders'   - {asset folder name lower: (name, preview path or None, mtime)}
        Used by normal browsing to skip the directory scan and the per-folder
        preview search (see FileSystemModel.library_lookup).
        """
        entry = self._dirs.get(_normalized_root(directory))
        if entry is None:
            return None
        if 'folders' not in entry:
            folders = {}
            for row in entry['rows']:
                name = os.path.basename(self.paths[row])
                folders[name.lower()] = (name, self.previews[row], self.mtimes[row])
            entry['folders'] = folders
        return entry

    def asset_info(self, folder):
        """What the database knows about one asset folder - {'type', 'name',
        'id', 'size_m'} - or None if it isn't a library asset. No disk access."""
        folder = os.path.normpath(str(folder))
        entry = self._dirs.get(_normalized_root(os.path.dirname(folder)))
        if entry is None:
            return None
        if 'by_name' not in entry:
            entry['by_name'] = {os.path.basename(self.paths[row]).lower(): row for row in entry['rows']}
        row = entry['by_name'].get(os.path.basename(folder).lower())
        if row is None:
            return None
        return {'type': self.types[row], 'name': self.names[row], 'id': self.ids[row], 'size_m': self.sizes[row]}

    def finalize(self):
        """Turn the collected row lists into bitmasks (call once, after the
        last add_database())."""
        self._n_bytes = (len(self.paths) + 7) // 8 or 1
        self.bits = {facet: {value: _bits_from_indices(rows, self._n_bytes) for value, rows in values.items()}
                     for facet, values in self._pending.items()}
        self._pending = {}

    def values(self, facet):
        return list(self.bits.get(facet, {}).keys())

    def _search_mask(self, text):
        """Rows whose search text contains every word of `text`."""
        tokens = [t for t in _clean(text).split(' ') if t]
        if not tokens:
            return None
        if self._search_cache[0] == tokens:
            return self._search_cache[1]
        rows = [i for i, s in enumerate(self.searches) if all(t in s for t in tokens)]
        mask = _bits_from_indices(rows, self._n_bytes)
        self._search_cache = (tokens, mask)
        return mask

    def query(self, selections, search_text='', visible_types=None):
        """
        Faceted query. `selections` is {facet: set(values)}: OR within a
        facet, AND across facets ('category' values are tree nodes - a node
        matches its whole subtree). `visible_types` limits the asset types
        (None = all).

        Returns (result_mask, counts) - counts is {facet: {value: n}}, the
        number of results a value would have with the other facets'
        selections applied but its own facet's ignored (what a chip shows).
        """
        category_bits = self.bits.get('category', {})
        if visible_types is None:
            base = (1 << len(self.paths)) - 1
        else:
            base = 0
            for t in visible_types:
                base |= category_bits.get(t, 0)
        search = self._search_mask(search_text)
        if search is not None:
            base &= search

        facet_masks = {}
        for facet, values in selections.items():
            if not values:
                continue
            mask = 0
            for v in values:
                mask |= self.bits.get(facet, {}).get(v, 0)
            facet_masks[facet] = mask

        result = base
        for mask in facet_masks.values():
            result &= mask

        counts = {}
        for facet, value_bits in self.bits.items():
            others = base
            for other, mask in facet_masks.items():
                if other != facet:
                    others &= mask
            counts[facet] = {v: (others & b).bit_count() for v, b in value_bits.items()}
        return result, counts

    def rows(self, mask):
        return _indices_from_bits(mask, self._n_bytes)
