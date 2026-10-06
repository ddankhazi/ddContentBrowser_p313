# -*- coding: utf-8 -*-
"""
DD Content Browser - Asset Library panel

The "Asset Library" tab (Bridge-style tag filtering of Megascans libraries),
the "Asset Library Settings" dialog, and AssetLibraryService - the one
object both of them talk to, which owns the settings, the background
database builds and the in-memory dataset. Data handling itself is in
asset_library.py.

Author: ddankhazi
License: MIT
"""

import os
import time
import traceback
from pathlib import Path

try:
    from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                   QLineEdit, QToolButton, QScrollArea, QFrame, QTreeWidget,
                                   QTreeWidgetItem, QStackedWidget, QProgressBar, QDialog,
                                   QListWidget, QListWidgetItem, QGroupBox, QCheckBox,
                                   QGridLayout, QFileDialog, QMessageBox, QAbstractItemView,
                                   QSizePolicy)
    from PySide6.QtCore import Qt, Signal, QObject, QThread, QTimer, QUrl
    from PySide6.QtGui import QFont, QDesktopServices, QColor
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                   QLineEdit, QToolButton, QScrollArea, QFrame, QTreeWidget,
                                   QTreeWidgetItem, QStackedWidget, QProgressBar, QDialog,
                                   QListWidget, QListWidgetItem, QGroupBox, QCheckBox,
                                   QGridLayout, QFileDialog, QMessageBox, QAbstractItemView,
                                   QSizePolicy)
    from PySide2.QtCore import Qt, Signal, QObject, QThread, QTimer, QUrl
    from PySide2.QtGui import QFont, QDesktopServices, QColor
    PYSIDE_VERSION = 2

from . import asset_library as al
from .widgets import FlowLayout

# UI Font - Default value (can be overridden by browser at runtime)
UI_FONT = "Segoe UI"

DEBUG_MODE = False

# Facet sections open by default (the rest start collapsed)
_OPEN_SECTIONS = {'category', 'environment', 'state', 'color', 'size'}


def _fmt(n):
    """18894 -> '18 894' (thin, locale-independent grouping)."""
    return "{:,}".format(n).replace(',', ' ')


def _summary_text(summary):
    parts = ["{0} assets".format(_fmt(summary.get('assets', 0)))]
    if summary.get('source') == 'bridge_index':
        if summary.get('from_json'):
            parts.append("{0} read from their own JSON".format(_fmt(summary['from_json'])))
    else:
        parts.append("read from the asset files (no Bridge index)")
    if summary.get('without_meta'):
        parts.append("{0} without metadata".format(_fmt(summary['without_meta'])))
    parts.append("{0} s".format(summary.get('seconds', 0)))
    return " · ".join(parts)


# ============================================================================
# SERVICE (settings + background work)
# ============================================================================

class _JobThread(QThread):
    """
    One database job on a worker thread:
      'build_local'   - (re)build a local library's database
      'build_shared'  - (re)build a shared library's database and publish it
      'share'         - make a local library shared: publish its existing
                        database (or build one first)
      'unshare'       - stop sharing a library for everyone; the user keeps it
                        as a local library (the downloaded snapshot becomes
                        its local database)
      'remove_shared' - stop sharing and drop it altogether
    """

    progress = Signal(str, str, int, int)  # root, phase, done, total
    done = Signal(str, str, bool, str)     # action, root, ok, message

    def __init__(self, action, root, shared_folder, parent=None):
        super().__init__(parent)
        self.action = action
        self.root = root
        self.shared_folder = shared_folder
        self._cancel = False
        self._last_emit = 0.0

    def cancel(self):
        self._cancel = True

    def _progress(self, phase, done, total):
        now = time.time()
        if done == 0 or done == total or now - self._last_emit > 0.1:
            self._last_emit = now
            self.progress.emit(self.root, phase, done, total)

    def _build(self, db_path=None):
        return al.build_database(self.root, db_path=db_path, progress=self._progress,
                                 is_cancelled=lambda: self._cancel)

    def _publish(self, db_file):
        """Publish db_file as the library's shared snapshot. The file then
        becomes this machine's downloaded copy - no download right after."""
        self._progress("Publishing to the shared folder", 0, 0)
        entry = al.publish_database(db_file, self.root, self.shared_folder)
        cache = al.shared_cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        if os.path.normcase(str(db_file)) == os.path.normcase(str(al.database_path(self.root))):
            # The user's local database (being shared): copied, not moved -
            # a load may be reading it right now; it's deleted afterwards
            al.shutil_copy(db_file, cache / entry['db'])
        else:
            os.replace(str(db_file), str(cache / entry['db']))
        return entry

    def run(self):
        try:
            if self.action == 'build_local':
                message = _summary_text(self._build())
            elif self.action in ('build_shared', 'share'):
                with al.SharedLock(self.shared_folder):
                    local = al.database_path(self.root)
                    local_meta = al.read_database_meta(local) if self.action == 'share' else None
                    # Reused as is only if it carries the root-relative layout
                    # others need (databases from before sharing existed don't)
                    if local_meta is not None and local_meta.get('downloaded_rel') is not None:
                        db_file, summary = local, local_meta.get('summary') or {}
                    else:
                        db_file = al.shared_cache_dir() / ("building_{0}.db".format(al.library_key(self.root)))
                        db_file.parent.mkdir(parents=True, exist_ok=True)
                        summary = self._build(db_file)
                    self._publish(db_file)
                al.delete_database(self.root)  # never a local database next to the shared one
                message = "Shared · " + _summary_text(summary)
            elif self.action in ('unshare', 'remove_shared'):
                with al.SharedLock(self.shared_folder):
                    if self.action == 'unshare':
                        snapshot = al.cached_shared_snapshot(self.root)
                        if snapshot is not None:
                            target = al.database_path(self.root)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            al.shutil_copy(snapshot, target)
                    al.unpublish(self.root, self.shared_folder)
                message = "No longer shared" + (" - kept as a local library" if self.action == 'unshare' else "")
            else:
                raise ValueError("Unknown job: {0}".format(self.action))
            self.done.emit(self.action, self.root, True, message)
        except al.BuildCancelled:
            self.done.emit(self.action, self.root, False, "Cancelled")
        except al.SharedFolderError as e:
            self.done.emit(self.action, self.root, False, str(e))
        except Exception as e:
            traceback.print_exc()
            self.done.emit(self.action, self.root, False, "Failed: {0}".format(e))


class _LoadThread(QThread):
    """Reads the shared manifest (if any), syncs the shared snapshots, and
    loads every library's database into one LibraryDataset."""

    loaded = Signal(object, object)  # dataset, info dict (see run)

    def __init__(self, shared_folder, local_roots, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.local_roots = list(local_roots)

    def run(self):
        info = {'shared_folder': self.shared_folder, 'manifest': None, 'shared_error': None,
                'stale': [], 'missing': [], 'unreachable': []}
        if self.shared_folder:
            info['manifest'], info['shared_error'] = al.read_manifest_cached(self.shared_folder)
        dataset = al.LibraryDataset()
        for lib in al.effective_libraries(info['manifest'], self.local_roots):
            root = lib['root']
            try:
                if lib['mode'] == 'shared':
                    al.delete_database(root)  # a library is never both shared and local
                    try:
                        db = al.sync_shared_snapshot(root, lib['entry'], self.shared_folder)
                    except OSError as e:
                        db = al.cached_shared_snapshot(root)  # offline: last downloaded copy
                        if db is None:
                            print("[AssetLibrary] Shared database of {0} not available: {1}".format(root, e))
                            info['missing'].append(root)
                            continue
                else:
                    db = al.database_path(root)
                if dataset.add_database(root, db) is None:
                    info['missing'].append(root)
                    continue
                detected = al.detect_megascans_library(root)
                if detected['error']:
                    info['unreachable'].append(root)  # keep its assets, just can't check it
                elif al.is_database_stale(root, dataset.libraries[-1]['meta'], detected):
                    info['stale'].append(root)
            except Exception as e:
                print("[AssetLibrary] Could not load the database of {0}: {1}".format(root, e))
                info['missing'].append(root)
        dataset.finalize()
        self.loaded.emit(dataset, info)


class AssetLibraryService(QObject):
    """
    Settings, database jobs and the loaded dataset of the Asset Library,
    shared by the panel and the settings dialog. Jobs run one at a time on a
    worker thread; loading runs on another.

    A library is local (database in this user's cache) or shared (one
    database in the shared folder, used by everyone who has that folder set
    - see asset_library.py) - never both: the shared one wins, and a local
    database of a shared library is deleted.
    """

    build_progress = Signal(str, str, int, int)  # root, phase, done, total
    build_finished = Signal(str, bool, str)      # root, ok, message
    building_changed = Signal(bool)
    loading_changed = Signal(bool)
    dataset_loaded = Signal(object)
    config_changed = Signal()

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings = settings_manager
        self.dataset = None
        self.manifest = None       # last shared manifest read (None: no shared folder)
        self.shared_error = None   # why the shared folder couldn't be read, if it couldn't
        self.stale_roots = set()
        self.missing_roots = set()
        self.unreachable_roots = set()
        self.last_results = {}     # root -> (ok, message) of its last job this session
        self._job = None
        self._queue = []           # [(action, root)]
        self._load_thread = None
        self._reload_pending = False

    # ---- settings ----------------------------------------------------------

    def local_roots(self):
        roots = self.settings.get('asset_library', 'megascans_roots', []) or []
        return [r for r in roots if isinstance(r, str) and r.strip()]

    def set_local_roots(self, roots, reload=True):
        self.settings.set('asset_library', 'megascans_roots', list(roots))
        if reload:
            self.config_changed.emit()
            self.reload()

    def add_local_root(self, root, reload=True):
        if not any(al.same_library(r, root) for r in self.local_roots()):
            self.set_local_roots(self.local_roots() + [root], reload)

    def remove_local_root(self, root, reload=True):
        self.set_local_roots([r for r in self.local_roots() if not al.same_library(r, root)], reload)

    def site_shared_folder(self):
        """This installation's default shared folder (site_defaults.json)."""
        return (al.read_site_defaults().get('asset_library') or {}).get('shared_folder') or None

    def shared_folder_setting(self):
        """The user's own setting: None = follow the default, '' = off, else a path."""
        return self.settings.get('asset_library', 'shared_folder', None)

    def shared_folder(self):
        """The shared folder in effect, or None."""
        own = self.shared_folder_setting()
        if own is None:
            return self.site_shared_folder()
        return own or None

    def set_shared_folder(self, value):
        self.settings.set('asset_library', 'shared_folder', value)
        self.manifest = None
        self.shared_error = None
        self.refresh_manifest()
        self.config_changed.emit()
        self.reload()

    def set_site_shared_folder(self, folder):
        """Write (or with None, clear) the installation default. Raises OSError."""
        al.write_site_default('asset_library', 'shared_folder', folder or None)
        self.refresh_manifest()
        self.config_changed.emit()
        self.reload()

    def visible_types(self):
        types = self.settings.get('asset_library', 'visible_types', None)
        return [t for t in types if t in al.TYPE_LABELS] if isinstance(types, list) else list(al.DEFAULT_VISIBLE_TYPES)

    def set_visible_types(self, types):
        self.settings.set('asset_library', 'visible_types', [t for t in al.TYPE_LABELS if t in types])
        self.config_changed.emit()

    def auto_update(self):
        return bool(self.settings.get('asset_library', 'auto_update', False))

    def set_auto_update(self, on):
        self.settings.set('asset_library', 'auto_update', bool(on))

    # ---- libraries ---------------------------------------------------------

    def refresh_manifest(self):
        """Re-read the shared manifest now (a small file - the settings dialog
        calls this when it opens)."""
        folder = self.shared_folder()
        if folder:
            self.manifest, self.shared_error = al.read_manifest_cached(folder)
        else:
            self.manifest, self.shared_error = None, None

    def libraries(self):
        """[{'root', 'key', 'mode': 'shared'|'local', 'entry'}] - see
        asset_library.effective_libraries()."""
        return al.effective_libraries(self.manifest, self.local_roots())

    def roots(self):
        return [lib['root'] for lib in self.libraries()]

    def library(self, root):
        key = al.library_key(root)
        return next((lib for lib in self.libraries() if lib['key'] == key), None)

    def is_shared(self, root):
        lib = self.library(root)
        return lib is not None and lib['mode'] == 'shared'

    def lookup_dir(self, directory):
        """Database knowledge of a library category folder for normal browsing
        (LibraryDataset.dir_listing), or None. Cheap - no disk access."""
        dataset = self.dataset
        return dataset.dir_listing(directory) if dataset is not None else None

    def asset_info(self, folder):
        """Type/name/id of a library asset folder (LibraryDataset.asset_info), or None."""
        dataset = self.dataset
        return dataset.asset_info(folder) if dataset is not None else None

    def library_status(self, lib):
        """Detection result + database info of one library (a few file stats)."""
        status = {'detected': al.detect_megascans_library(lib['root']), 'stale': lib['root'] in self.stale_roots}
        if lib['mode'] == 'shared':
            entry = lib['entry'] or {}
            status.update(summary=entry.get('summary') or {}, built_at=entry.get('published_at'),
                          built_by=entry.get('published_by'), built=bool(entry.get('db')))
        else:
            meta = al.read_database_meta(al.database_path(lib['root']))
            status.update(summary=(meta or {}).get('summary') or {}, built_at=(meta or {}).get('built_at'),
                          built_by=None, built=meta is not None)
        return status

    # ---- jobs --------------------------------------------------------------

    def is_building(self):
        return self._job is not None

    def building_root(self):
        return self._job.root if self._job is not None else None

    def build(self, roots):
        """Build/update databases - a shared library's is published again."""
        for root in roots:
            self._enqueue('build_shared' if self.is_shared(root) else 'build_local', root)

    def make_shared(self, roots):
        for root in roots:
            self._enqueue('share', root)

    def stop_sharing(self, roots):
        for root in roots:
            self._enqueue('unshare', root)

    def remove_shared(self, roots):
        for root in roots:
            self._enqueue('remove_shared', root)

    def _enqueue(self, action, root):
        if action != 'build_local' and not self.shared_folder():
            self.last_results[root] = (False, "No shared folder set")
            self.build_finished.emit(root, False, "No shared folder set")
            return
        if (action, root) in self._queue or root == self.building_root():
            return
        self._queue.append((action, root))
        if self._job is None:
            self._start_next_job()

    def cancel_build(self):
        self._queue = []
        if self._job is not None:
            self._job.cancel()

    def _start_next_job(self):
        if not self._queue:
            self.building_changed.emit(False)
            self.reload()
            return
        action, root = self._queue.pop(0)
        job = _JobThread(action, root, self.shared_folder(), self)
        job.progress.connect(self.build_progress)
        job.done.connect(self._on_job_done)
        self._job = job
        self.building_changed.emit(True)
        job.start()

    def _on_job_done(self, action, root, ok, message):
        job = self._job
        self._job = None
        if job is not None:
            job.wait()
            job.deleteLater()
        self.last_results[root] = (ok, message)
        if ok:
            self.stale_roots.discard(root)
            self.missing_roots.discard(root)
            if action == 'unshare':
                self.add_local_root(root, reload=False)   # the user keeps it, as a local one
            elif action == 'remove_shared':
                self.remove_local_root(root, reload=False)
            if action != 'build_local':
                self.refresh_manifest()
                self.config_changed.emit()
        elif message == "Cancelled":
            self._queue = []
        print("[AssetLibrary] {0}: {1}".format(root, message))
        self.build_finished.emit(root, ok, message)
        self._start_next_job()

    # ---- loading -----------------------------------------------------------

    def is_loading(self):
        return self._load_thread is not None

    def has_libraries_configured(self):
        return bool(self.local_roots() or self.shared_folder())

    def ensure_loaded(self):
        if self.dataset is None and self._load_thread is None:
            self.reload()

    def reload(self):
        """(Re)load in the background: shared manifest + snapshots, every database."""
        if self._job is not None:
            return  # the job queue reloads once it's done - no reading files a job is writing
        if self._load_thread is not None:
            self._reload_pending = True
            return
        thread = _LoadThread(self.shared_folder(), self.local_roots(), self)
        thread.loaded.connect(self._on_loaded)
        self._load_thread = thread
        self.loading_changed.emit(True)
        thread.start()

    def _on_loaded(self, dataset, info):
        thread = self._load_thread
        self._load_thread = None
        if thread is not None:
            thread.wait()
            thread.deleteLater()
        if self._reload_pending:
            self._reload_pending = False
            self.reload()
            return
        if info['shared_folder'] == self.shared_folder():
            self.manifest, self.shared_error = info['manifest'], info['shared_error']
        self.dataset = dataset
        self.stale_roots = set(info['stale'])
        self.missing_roots = set(info['missing'])
        self.unreachable_roots = set(info['unreachable'])
        self.loading_changed.emit(False)
        self.dataset_loaded.emit(dataset)
        # Auto-update rebuilds only libraries that already have a database -
        # a first build is always the user's call (it can take a while)
        if self.stale_roots and self.auto_update() and not self.is_building():
            self.build([r for r in self.roots() if r in self.stale_roots])

    def shutdown(self, timeout_ms=15000):
        """Stop background work (browser closing)."""
        self.cancel_build()
        for thread in (self._job, self._load_thread):
            if thread is not None:
                thread.wait(timeout_ms)


# ============================================================================
# PANEL
# ============================================================================

_PANEL_STYLE = """
QToolButton[chip="true"] {
    border: 1px solid #555; border-radius: 9px; padding: 1px 8px;
    background: #3a3a3a; color: #cfcfcf;
}
QToolButton[chip="true"]:hover { border-color: #808080; }
QToolButton[chip="true"]:checked { background: #4b7daa; border-color: #5a8dba; color: white; }
QToolButton[chip="true"]:disabled { color: #666; border-color: #444; background: #333; }
QPushButton[section="true"] {
    border: none; background: transparent; font-weight: bold; text-align: left; padding: 3px 2px;
}
QPushButton[section="true"]:hover { color: white; }
"""


class _Section(QWidget):
    """Collapsible section: bold header button + body."""

    def __init__(self, title, expanded=True, parent=None):
        super().__init__(parent)
        self.title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)
        # Flat QPushButton, not QToolButton: Maya's style always centers a
        # tool button's text, ignoring text-align
        self.header = QPushButton()
        self.header.setProperty('section', True)
        self.header.setFlat(True)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.clicked.connect(self.toggle)
        layout.addWidget(self.header)
        self.body = QWidget()
        layout.addWidget(self.body)
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.body.setVisible(expanded)
        self.set_title_suffix('')

    def set_title_suffix(self, suffix):
        arrow = "▾" if self.expanded else "▸"
        self.header.setText("{0} {1}{2}".format(arrow, self.title, suffix))

    def toggle(self):
        self.set_expanded(not self.expanded)


class AssetLibraryPanel(QWidget):
    """
    The "Asset Library" tab. Filter changes are shown in the browser's file
    list right away (show_results); the browser tells the panel when the
    user leaves that view (set_view_active(False)).
    """

    show_results = Signal(object, str)  # [(folder path, name, preview, mtime)], breadcrumb label
    open_settings_requested = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.dataset = None
        self.selections = {}   # facet -> set(values)
        self.view_active = False
        self._chips = {}       # facet -> {value: QToolButton}
        self._sections = {}    # facet -> _Section
        self._tree_items = {}  # category value -> QTreeWidgetItem
        self._result_mask = 0
        self._total = 0

        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(120)
        self._emit_timer.timeout.connect(self._emit_results)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(lambda: self._refresh(emit=True))

        self._build_ui()

        service.dataset_loaded.connect(self._on_dataset_loaded)
        service.loading_changed.connect(lambda _loading: self._update_page())
        service.building_changed.connect(self._on_building_changed)
        service.build_progress.connect(self._on_build_progress)
        service.build_finished.connect(lambda *_: self._update_page())
        service.config_changed.connect(self._on_config_changed)
        self._update_page()

    # ---- UI ----------------------------------------------------------------

    def _build_ui(self):
        self.setStyleSheet(_PANEL_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        # Message page: setup / not built / loading
        message_page = QWidget()
        mlayout = QVBoxLayout(message_page)
        mlayout.addStretch()
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet("color: #aaa;")
        mlayout.addWidget(self.message_label)
        brow = QHBoxLayout()
        brow.addStretch()
        self.message_button = QPushButton()
        self.message_button.clicked.connect(self._on_message_button)
        brow.addWidget(self.message_button)
        self.message_settings_button = QPushButton("Settings...")
        self.message_settings_button.clicked.connect(self.open_settings_requested)
        brow.addWidget(self.message_settings_button)
        brow.addStretch()
        mlayout.addLayout(brow)
        mlayout.addStretch()
        self.stack.addWidget(message_page)

        # Main page
        main_page = QWidget()
        main = QVBoxLayout(main_page)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(4)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search names, tags...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _text: self._search_timer.start())
        search_row.addWidget(self.search_edit, 1)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip("Clear every filter and the search")
        self.clear_button.clicked.connect(self.clear_filters)
        search_row.addWidget(self.clear_button)
        main.addLayout(search_row)

        info_row = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #aaa;")
        info_row.addWidget(self.count_label, 1)
        self.show_button = QPushButton("Show")
        self.show_button.setToolTip("Show the matching assets in the file list")
        self.show_button.clicked.connect(self._emit_results)
        info_row.addWidget(self.show_button)
        main.addLayout(info_row)

        self.notice_frame = QFrame()
        self.notice_frame.setStyleSheet("QFrame { background: #4a4030; border-radius: 3px; }")
        nlayout = QHBoxLayout(self.notice_frame)
        nlayout.setContentsMargins(6, 3, 3, 3)
        self.notice_label = QLabel()
        self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet("background: transparent;")
        nlayout.addWidget(self.notice_label, 1)
        self.notice_button = QPushButton("Update")
        self.notice_button.clicked.connect(self._on_notice_button)
        nlayout.addWidget(self.notice_button)
        self.notice_frame.hide()
        main.addWidget(self.notice_frame)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 4, 0)
        self.content_layout.setSpacing(2)
        self.content_layout.addStretch()
        scroll.setWidget(self.content)
        main.addWidget(scroll, 1)
        self.stack.addWidget(main_page)

        # Build progress (shown on every page while a build runs)
        self.progress_frame = QWidget()
        playout = QVBoxLayout(self.progress_frame)
        playout.setContentsMargins(0, 0, 0, 0)
        playout.setSpacing(2)
        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #aaa; font-size: 10px;")
        playout.addWidget(self.progress_label)
        prow = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(14)
        self.progress_bar.setTextVisible(False)
        prow.addWidget(self.progress_bar, 1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.service.cancel_build)
        prow.addWidget(cancel)
        playout.addLayout(prow)
        self.progress_frame.hide()
        layout.addWidget(self.progress_frame)

    def _clear_content(self):
        while self.content_layout.count() > 1:  # keep the trailing stretch
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._chips = {}
        self._sections = {}
        self._tree_items = {}

    def _build_filters(self):
        """(Re)create the category tree and chip sections for the dataset."""
        self._clear_content()
        ds = self.dataset
        visible = set(self.service.visible_types())
        insert_at = 0

        # Category tree
        section = _Section("Category", 'category' in _OPEN_SECTIONS)
        body = QVBoxLayout(section.body)
        body.setContentsMargins(12, 0, 0, 4)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemClicked.connect(self._on_tree_clicked)
        # Height follows the visible rows (see _fit_tree_height)
        self.tree.itemExpanded.connect(lambda _item: self._fit_tree_height())
        self.tree.itemCollapsed.connect(lambda _item: self._fit_tree_height())
        body.addWidget(self.tree)
        values = ds.values('category')
        for value in sorted(values, key=lambda v: (v.count('/'), al.value_label('category', v).lower())):
            parts = value.split('/')
            if parts[0] not in visible:
                continue
            if len(parts) == 1:
                item = QTreeWidgetItem(self.tree)
            else:
                parent = self._tree_items.get('/'.join(parts[:-1]))
                if parent is None:
                    continue
                item = QTreeWidgetItem(parent)
            item.setData(0, Qt.UserRole, value)
            self._tree_items[value] = item
        # Types in their own fixed order, not alphabetically
        order = {t: i for i, t in enumerate(al.TYPE_LABELS)}
        tops = [self.tree.takeTopLevelItem(0) for _ in range(self.tree.topLevelItemCount())]
        for item in sorted(tops, key=lambda it: order.get(it.data(0, Qt.UserRole), 99)):
            self.tree.addTopLevelItem(item)
        self._sections['category'] = section
        self.content_layout.insertWidget(insert_at, section)
        insert_at += 1

        # Chip sections
        for facet, title in al.FACETS:
            values = ds.values(facet)
            if not values:
                continue
            section = _Section(title, facet in _OPEN_SECTIONS)
            flow = FlowLayout(section.body, margin=0, hSpacing=4, vSpacing=4)
            flow.setContentsMargins(12, 0, 0, 4)  # chips indented under the header text
            chips = {}
            for value in al.sort_values(facet, values):
                chip = QToolButton()
                chip.setProperty('chip', True)
                chip.setCheckable(True)
                chip.setCursor(Qt.PointingHandCursor)
                chip.setChecked(value in self.selections.get(facet, ()))
                chip.toggled.connect(lambda checked, f=facet, v=value: self._on_chip_toggled(f, v, checked))
                flow.addWidget(chip)
                chips[value] = chip
            self._chips[facet] = chips
            self._sections[facet] = section
            self.content_layout.insertWidget(insert_at, section)
            insert_at += 1

    def _fit_tree_height(self, min_rows=3, max_rows=14):
        """Size the category tree to its visible rows - no empty box under a
        short tree, a scrollbar only past max_rows."""
        tree = getattr(self, 'tree', None)
        if tree is None:
            return

        def visible_rows(parent):
            n = 0
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.isHidden():
                    continue
                n += 1
                if child.isExpanded():
                    n += visible_rows(child)
            return n

        rows = visible_rows(tree.invisibleRootItem())
        row_height = tree.sizeHintForRow(0)
        if row_height <= 0:
            row_height = tree.fontMetrics().height() + 4
        rows = max(min_rows, min(max_rows, rows))
        tree.setFixedHeight(rows * row_height + 2 * tree.frameWidth() + 4)

    def _update_page(self):
        """Pick the page/notice for the current state."""
        svc = self.service
        roots = svc.roots()
        self.progress_frame.setVisible(svc.is_building())

        if not roots:
            if svc.shared_folder() and (svc.is_loading() or svc.dataset is None):
                # Shared libraries only show up once the shared manifest is read
                self._show_message("Loading the library database...", None, None)
                return
            self._show_message("Set up a Megascans library to browse it by its tags.",
                               "Asset Library Settings...", 'settings')
            return
        if self.dataset is None:
            if svc.is_loading() or svc.dataset is None:
                self._show_message("Loading the library database...", None, None)
            return
        if not self.dataset.libraries:
            if svc.is_building():
                self._show_message("Building the library database...", None, None)
            else:
                self._show_message("The library database hasn't been built yet. Building it reads the "
                                   "library's metadata once - later starts load it in a moment.",
                                   "Build Database", 'build_missing')
            return

        self.stack.setCurrentIndex(1)
        notes, action = [], None
        if svc.missing_roots:
            notes.append("{0} of your libraries has no database yet.".format(len(svc.missing_roots))
                         if len(svc.missing_roots) == 1 else
                         "{0} of your libraries have no database yet.".format(len(svc.missing_roots)))
            action = ('build_missing', "Build")
        if svc.stale_roots:
            shared = any(svc.is_shared(r) for r in svc.stale_roots)
            notes.append("The library changed since its {0}database was built.".format("shared " if shared else ""))
            action = action or ('build_stale', "Update")
        if svc.unreachable_roots:
            notes.append("Library not reachable: " + ", ".join(sorted(svc.unreachable_roots)))
        if svc.shared_error:
            notes.append("Shared folder not reachable - using the last downloaded copy.")
        failed = [msg for root, (ok, msg) in svc.last_results.items()
                  if not ok and msg != "Cancelled" and root in svc.roots()]
        if failed:
            notes.append("Last update failed: " + failed[-1])
        self.notice_frame.setVisible(bool(notes))
        self.notice_label.setText(" ".join(notes))
        self.notice_button.setVisible(action is not None and not svc.is_building())
        self._notice_action = action[0] if action else None
        if action:
            self.notice_button.setText(action[1])

    def _show_message(self, text, button_text, action):
        self.stack.setCurrentIndex(0)
        self.message_label.setText(text)
        self._message_action = action
        self.message_button.setVisible(bool(button_text) and not self.service.is_building())
        if button_text:
            self.message_button.setText(button_text)
        self.message_settings_button.setVisible(action != 'settings')

    def _on_message_button(self):
        action = getattr(self, '_message_action', None)
        if action == 'settings':
            self.open_settings_requested.emit()
        elif action == 'build_missing':
            self._build_missing()

    def _on_notice_button(self):
        action = getattr(self, '_notice_action', None)
        if action == 'build_missing':
            self._build_missing()
        elif action == 'build_stale':
            self.service.last_results.clear()
            self.service.build([r for r in self.service.roots() if r in self.service.stale_roots])

    def _build_missing(self):
        svc = self.service
        built = {lib['root'] for lib in (self.dataset.libraries if self.dataset else [])}
        svc.build([r for r in svc.roots() if r not in built])
        svc.last_results.clear()  # a fresh attempt - don't keep showing the old failure

    def showEvent(self, event):
        super().showEvent(event)
        self.service.ensure_loaded()

    # ---- service events ----------------------------------------------------

    def _on_dataset_loaded(self, dataset):
        self.dataset = dataset
        # Keep selections that still exist
        self.selections = {f: {v for v in vals if v in dataset.bits.get(f, {})}
                           for f, vals in self.selections.items()}
        self._build_filters()
        self._refresh(emit=self.view_active)
        self._update_page()

    def _on_config_changed(self):
        if self.dataset is None:
            self._update_page()
            return
        visible = set(self.service.visible_types())
        cat = self.selections.get('category')
        if cat and next(iter(cat)).split('/')[0] not in visible:
            self.selections.pop('category', None)
        self._build_filters()
        self._refresh(emit=self.view_active)
        self._update_page()

    def _on_building_changed(self, building):
        self.progress_frame.setVisible(building)
        self._update_page()

    def _on_build_progress(self, root, phase, done, total):
        name = Path(root).name or root
        if total:
            self.progress_label.setText("{0}: {1} {2} / {3}".format(name, phase, _fmt(done), _fmt(total)))
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)
        else:
            self.progress_label.setText("{0}: {1}...".format(name, phase))
            self.progress_bar.setRange(0, 0)  # busy indicator

    # ---- filtering ---------------------------------------------------------

    def _on_chip_toggled(self, facet, value, checked):
        values = self.selections.setdefault(facet, set())
        if checked:
            values.add(value)
        else:
            values.discard(value)
        self._refresh(emit=True)

    def _on_tree_clicked(self, item, _column):
        value = item.data(0, Qt.UserRole)
        if self.selections.get('category') == {value}:
            self.selections.pop('category', None)  # click the selected node again: deselect
            self.tree.clearSelection()
        else:
            self.selections['category'] = {value}
        self._refresh(emit=True)

    def clear_filters(self):
        self.selections = {}
        for chips in self._chips.values():
            for chip in chips.values():
                chip.blockSignals(True)
                chip.setChecked(False)
                chip.blockSignals(False)
        if hasattr(self, 'tree'):
            self.tree.clearSelection()
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._refresh(emit=self.view_active)

    def _refresh(self, emit):
        """Run the query, update every count, and (debounced) the results."""
        ds = self.dataset
        if ds is None or not ds.libraries:
            return
        visible = self.service.visible_types()
        mask, counts = ds.query(self.selections, self.search_edit.text(), visible)
        self._result_mask = mask
        total = 0
        for t in visible:
            total |= ds.bits.get('category', {}).get(t, 0)
        self._total = total.bit_count()

        # Tree: hide branches with nothing in them (unless selected)
        selected_cat = next(iter(self.selections.get('category') or []), None)
        cat_counts = counts.get('category', {})
        for value, item in self._tree_items.items():
            n = cat_counts.get(value, 0)
            item.setText(0, "{0}  ({1})".format(al.value_label('category', value), _fmt(n)))
            item.setHidden(n == 0 and value != selected_cat and not (selected_cat or '').startswith(value + '/'))
        if selected_cat in self._tree_items:
            self._tree_items[selected_cat].setSelected(True)
        self._fit_tree_height()

        # Chips: live counts, empty ones disabled (selected ones stay usable)
        for facet, chips in self._chips.items():
            fc = counts.get(facet, {})
            selected = self.selections.get(facet, set())
            for value, chip in chips.items():
                n = fc.get(value, 0)
                chip.setText("{0}  {1}".format(al.value_label(facet, value), _fmt(n)))
                chip.setEnabled(n > 0 or value in selected)
            section = self._sections.get(facet)
            if section:
                section.set_title_suffix("  ({0})".format(len(selected)) if selected else "")
        if 'category' in self._sections:
            self._sections['category'].set_title_suffix(
                "  ({0})".format(al.value_label('category', selected_cat)) if selected_cat else "")

        self.count_label.setText("{0} of {1} assets".format(_fmt(mask.bit_count()), _fmt(self._total)))
        self.show_button.setVisible(not self.view_active)
        if emit:
            self._emit_timer.start()

    def _summary_label(self, count):
        """Breadcrumb text: 'Asset Library › 3D Plants › Fern · Forest, Old · "x"   (12)'."""
        path = ["Asset Library"]
        cat = next(iter(self.selections.get('category') or []), None)
        if cat:
            pieces = cat.split('/')
            path += [al.value_label('category', '/'.join(pieces[:i + 1])) for i in range(len(pieces))]
        parts = [" › ".join(path)]
        facet_labels = []
        for facet, _title in al.FACETS:
            for value in al.sort_values(facet, self.selections.get(facet, ())):
                facet_labels.append(al.value_label(facet, value))
        if facet_labels:
            shown = facet_labels[:4]
            more = len(facet_labels) - len(shown)
            parts.append(", ".join(shown) + (" +{0}".format(more) if more > 0 else ""))
        text = self.search_edit.text().strip()
        if text:
            parts.append('"{0}"'.format(text))
        return "{0}   ({1})".format(" · ".join(parts), _fmt(count))

    def _emit_results(self):
        ds = self.dataset
        if ds is None or not ds.libraries:
            return
        rows = ds.rows(self._result_mask)
        entries = [(ds.paths[i], ds.names[i], ds.previews[i], ds.mtimes[i]) for i in rows]
        self.view_active = True
        self.show_button.setVisible(False)
        self.show_results.emit(entries, self._summary_label(len(entries)))

    def set_view_active(self, active):
        """Called by the browser when its Asset Library view is entered/left."""
        self.view_active = active
        self.show_button.setVisible(not active and self.dataset is not None)


# ============================================================================
# SETTINGS DIALOG
# ============================================================================

class AssetLibrarySettingsDialog(QDialog):
    """
    Settings > Asset Library Settings: the Megascans libraries and their
    databases (build/update/delete), sharing a library's database with
    everyone, the shared folder, and what the panel shows. Changes apply
    right away - jobs run in the background and keep going after the dialog
    is closed (the panel shows their progress).
    """

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Asset Library Settings")
        self.resize(720, 880)
        self._build_ui()
        service.refresh_manifest()
        self._refresh_all()
        self._update_build_ui(service.is_building())

        service.build_progress.connect(self._on_build_progress)
        service.build_finished.connect(self._on_build_finished)
        service.building_changed.connect(self._update_build_ui)
        service.dataset_loaded.connect(self._on_dataset_loaded)
        service.config_changed.connect(self._refresh_all)

    def _on_dataset_loaded(self, _dataset):
        self._refresh_all()

    def _refresh_all(self):
        self._refresh_list()
        self._refresh_shared_folder()

    def _info(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #888; font-size: 10px;")
        return label

    def _build_ui(self):
        # Everything but the Close button scrolls - the groups keep their
        # natural size instead of getting squeezed in a small window
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # ---- Libraries -------------------------------------------------------
        libs = QGroupBox("Megascans Libraries")
        llayout = QVBoxLayout(libs)
        llayout.addWidget(self._info(
            "ℹ The Megascans libraries you browse in the Asset Library tab: the library's root folder "
            "(the one holding 'Downloaded'), the Downloaded folder itself, or any folder of category "
            "folders (3d, surface, 3dplant, ...). Nothing is ever changed in them."))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setMinimumHeight(120)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        llayout.addWidget(self.list)
        brow = QHBoxLayout()
        add_btn = QPushButton("Add...")
        add_btn.clicked.connect(self._add_root)
        brow.addWidget(add_btn)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_selected)
        brow.addWidget(self.remove_btn)
        brow.addStretch()
        self.build_btn = QPushButton("Build / Update Database")
        self.build_btn.setToolTip("Build or update the database of the selected libraries (all, if none is "
                                  "selected) - a shared one is published again for everyone")
        self.build_btn.clicked.connect(self._build_selected)
        brow.addWidget(self.build_btn)
        llayout.addLayout(brow)

        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #aaa;")
        llayout.addWidget(self.progress_label)
        prow = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumHeight(14)
        prow.addWidget(self.progress_bar, 1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.service.cancel_build)
        prow.addWidget(self.cancel_btn)
        llayout.addLayout(prow)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        llayout.addWidget(self.result_label)
        layout.addWidget(libs)

        # ---- Sharing (the selected library) ----------------------------------
        sharing = QGroupBox("Sharing")
        shlayout = QVBoxLayout(sharing)
        shlayout.addWidget(self._info(
            "ℹ A shared library's database is built once and stored in a folder everyone can reach - "
            "everyone using that shared folder gets the library automatically, without building it. "
            "A local library's database is only on this machine, only for you."))
        srow = QHBoxLayout()
        self.share_status = QLabel()
        self.share_status.setWordWrap(True)
        srow.addWidget(self.share_status, 1)
        self.share_btn = QPushButton()
        self.share_btn.clicked.connect(self._on_share_button)
        srow.addWidget(self.share_btn)
        shlayout.addLayout(srow)
        layout.addWidget(sharing)

        # ---- Shared folder -----------------------------------------------------
        folder_box = QGroupBox("Shared Libraries Are Read From")
        flayout = QVBoxLayout(folder_box)
        flayout.addWidget(self._info(
            "ℹ The folder holding the shared databases (in its 'ddContentBrowser' subfolder) - not a "
            "library itself. Every library shared there shows up for you automatically. Set by "
            "'Share with Everyone...' too."))
        frow = QHBoxLayout()
        self.shared_edit = QLineEdit()
        self.shared_edit.setReadOnly(True)
        self.shared_edit.setPlaceholderText("No shared folder - only your own local libraries")
        frow.addWidget(self.shared_edit, 1)
        change = QPushButton("Change...")
        change.clicked.connect(self._browse_shared)
        frow.addWidget(change)
        self.shared_off_btn = QPushButton("Turn Off")
        self.shared_off_btn.setToolTip("Don't read shared libraries (only your own local ones)")
        self.shared_off_btn.clicked.connect(lambda: self.service.set_shared_folder(''))
        frow.addWidget(self.shared_off_btn)
        self.shared_default_btn = QPushButton("Use Default")
        self.shared_default_btn.setToolTip("Use this installation's default shared folder")
        self.shared_default_btn.clicked.connect(lambda: self.service.set_shared_folder(None))
        frow.addWidget(self.shared_default_btn)
        flayout.addLayout(frow)
        self.shared_status = QLabel()
        self.shared_status.setWordWrap(True)
        flayout.addWidget(self.shared_status)
        drow = QHBoxLayout()
        self.site_label = QLabel()
        self.site_label.setWordWrap(True)
        self.site_label.setStyleSheet("color: #888; font-size: 10px;")
        drow.addWidget(self.site_label, 1)
        self.site_btn = QPushButton()
        self.site_btn.clicked.connect(self._toggle_site_default)
        drow.addWidget(self.site_btn)
        flayout.addLayout(drow)
        layout.addWidget(folder_box)

        # ---- Types -----------------------------------------------------------
        types = QGroupBox("Show Asset Types")
        tlayout = QGridLayout(types)
        visible = set(self.service.visible_types())
        self.type_checks = {}
        for i, (key, label) in enumerate(al.TYPE_LABELS.items()):
            cb = QCheckBox(label)
            cb.setChecked(key in visible)
            cb.toggled.connect(self._save_types)
            tlayout.addWidget(cb, i // 3, i % 3)
            self.type_checks[key] = cb
        tlayout.addWidget(self._info("ℹ Brushes are off by default - they can't be imported into Maya."),
                          (len(al.TYPE_LABELS) + 2) // 3, 0, 1, 3)
        layout.addWidget(types)

        # ---- Local database --------------------------------------------------
        db = QGroupBox("Database")
        dlayout = QVBoxLayout(db)
        self.auto_update_cb = QCheckBox("Update a library's database automatically when the library changed")
        self.auto_update_cb.setChecked(self.service.auto_update())
        self.auto_update_cb.toggled.connect(self.service.set_auto_update)
        dlayout.addWidget(self.auto_update_cb)
        dlayout.addWidget(self._info(
            "ℹ Off: a changed library (e.g. new assets downloaded) is only reported in the Asset Library "
            "tab, with an Update button. A shared library's update is published for everyone. Databases "
            "and downloaded copies are a local cache - deleting them never changes the library."))
        self.location_label = QLabel()
        self.location_label.setWordWrap(True)
        self.location_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dlayout.addWidget(self.location_label)
        orow = QHBoxLayout()
        open_btn = QPushButton("Open Folder")
        open_btn.clicked.connect(self._open_folder)
        orow.addWidget(open_btn)
        self.delete_btn = QPushButton("Delete Local Copy")
        self.delete_btn.setToolTip("Delete this machine's database / downloaded copy of the selected "
                                   "libraries (all, if none is selected). A shared one is downloaded again.")
        self.delete_btn.clicked.connect(self._delete_selected)
        orow.addWidget(self.delete_btn)
        orow.addStretch()
        dlayout.addLayout(orow)
        layout.addWidget(db)
        layout.addStretch()

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        outer.addLayout(close_row)

    # ---- library list ------------------------------------------------------

    def _status_text(self, lib):
        st = self.service.library_status(lib)
        icon = "🌐 Shared with everyone" if lib['mode'] == 'shared' else "💻 Local (only you)"
        if st['detected']['error']:
            return "{0} · ⚠ {1}".format(icon, st['detected']['error'])
        if not st['built']:
            source = ("Bridge index found" if st['detected']['index'] else
                      "no Bridge index - metadata read from the asset files")
            return "{0} · database not built yet · {1}".format(icon, source)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st['built_at'] or 0))
        text = "{0} · {1} assets · {2} {3}".format(icon, _fmt(st['summary'].get('assets', 0)),
                                                    "published" if lib['mode'] == 'shared' else "built", when)
        if st['built_by']:
            text += " by " + st['built_by']
        if st['stale']:
            text += " · ⚠ library changed since - update"
        return text

    def _refresh_list(self):
        selected = {item.data(Qt.UserRole) for item in self.list.selectedItems()}
        libs = self.service.libraries()
        self.list.blockSignals(True)
        self.list.clear()
        for lib in libs:
            item = QListWidgetItem("{0}\n    {1}".format(lib['root'], self._status_text(lib)))
            item.setData(Qt.UserRole, lib['root'])
            self.list.addItem(item)
            # Keep the selection; with a single library, just select it
            item.setSelected(lib['root'] in selected or len(libs) == 1)
        self.list.blockSignals(False)
        self._update_location()
        self._on_selection_changed()

    def _selected_libs(self, default_all=False):
        roots = {item.data(Qt.UserRole) for item in self.list.selectedItems()}
        libs = self.service.libraries()
        chosen = [lib for lib in libs if lib['root'] in roots]
        return chosen if (chosen or not default_all) else libs

    def _on_selection_changed(self):
        sel = self._selected_libs()
        building = self.service.is_building()
        self.remove_btn.setEnabled(bool(sel) and not building)
        self.build_btn.setEnabled(not building)

        # Sharing box: what the selection is, and the one thing to do about it
        modes = {lib['mode'] for lib in sel}
        self._share_action = None
        if not sel:
            self.share_status.setText("Select a library above.")
        elif len(modes) > 1:
            self.share_status.setText("Select only local or only shared libraries.")
        elif modes == {'local'}:
            self.share_status.setText("💻 Local - its database is on this machine, only you use it.")
            self._share_action = 'share'
        else:
            folder = self.service.shared_folder() or "?"
            self.share_status.setText("🌐 Shared with everyone - its database is in\n{0}".format(
                al.shared_dir(folder)))
            self._share_action = 'unshare'
        self.share_btn.setText("Stop Sharing..." if self._share_action == 'unshare' else "Share with Everyone...")
        self.share_btn.setEnabled(self._share_action is not None and not building)

    def _add_root(self):
        svc = self.service
        start = svc.roots()[-1] if svc.roots() else ""
        folder = QFileDialog.getExistingDirectory(self, "Select a Megascans Library Folder", start)
        if not folder:
            return
        folder = os.path.normpath(folder)
        detected = al.detect_megascans_library(folder)
        if detected['error']:
            QMessageBox.warning(self, "Not a Megascans Library", "{0}\n\n{1}".format(folder, detected['error']))
            return
        existing = svc.library(folder)
        if existing is not None:
            QMessageBox.information(self, "Add Library", "This library is already in the list{0}:\n\n{1}".format(
                " (shared)" if existing['mode'] == 'shared' else "", existing['root']))
            return
        svc.add_local_root(folder, reload=False)
        slow_note = ("Bridge's index was found - building takes a few seconds." if detected['index'] else
                     "No Bridge index - every asset's own metadata file is read once, which can take a "
                     "few minutes for a large library on a network drive.")
        if QMessageBox.question(self, "Build Database", "Build the database of this library now?\n\n"
                                "{0}\n\n{1}\n\n(To share it with everyone, use 'Share with Everyone...' "
                                "afterwards.)".format(folder, slow_note),
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            svc.build([folder])
        svc.config_changed.emit()

    def _remove_selected(self):
        libs = self._selected_libs()
        if not libs:
            return
        shared = [lib['root'] for lib in libs if lib['mode'] == 'shared']
        local = [lib['root'] for lib in libs if lib['mode'] == 'local']
        text = "Remove from the Asset Library? The library folders themselves are not touched.\n"
        if local:
            text += "\nLocal (only you):\n" + "\n".join(local) + "\n"
        if shared:
            text += "\nShared - removed for EVERYONE using the shared folder:\n" + "\n".join(shared) + "\n"
        if QMessageBox.question(self, "Remove Library", text, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for root in local:
            al.delete_database(root)
            self.service.remove_local_root(root, reload=False)
        if shared:
            self.service.remove_shared(shared)
        self.service.config_changed.emit()
        if not shared:
            self.service.reload()

    # ---- sharing -----------------------------------------------------------

    def _on_share_button(self):
        if self._share_action == 'share':
            self._share_selected()
        elif self._share_action == 'unshare':
            self._unshare_selected()

    def _ask_shared_location(self, library_root):
        """Where to keep shared databases, when no shared folder is set yet.
        Suggests the library's own folder."""
        box = QMessageBox(self)
        box.setWindowTitle("Share with Everyone")
        box.setText("Where should the shared database be stored? It has to be a folder everyone can reach "
                    "and you can write to - a 'ddContentBrowser' subfolder is created in it.\n\n"
                    "Suggested: the library's own folder\n{0}".format(library_root))
        use_lib = box.addButton("Use the Library Folder", QMessageBox.AcceptRole)
        other = box.addButton("Choose Another Folder...", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(use_lib)
        box.exec_()
        if box.clickedButton() is use_lib:
            folder = str(al.detect_megascans_library(library_root)['root'] or library_root)
        elif box.clickedButton() is other:
            folder = QFileDialog.getExistingDirectory(self, "Select the Shared Folder", library_root)
            if not folder:
                return None
            folder = os.path.normpath(folder)
        else:
            return None
        if not al.is_writable_dir(folder):
            QMessageBox.warning(self, "Share with Everyone",
                                "You can't create files in this folder:\n{0}\n\nChoose a folder you have "
                                "write access to.".format(folder))
            return None
        return folder

    def _share_selected(self):
        svc = self.service
        roots = [lib['root'] for lib in self._selected_libs() if lib['mode'] == 'local']
        if not roots:
            return
        folder = svc.shared_folder()
        if not folder or svc.shared_error:
            folder = self._ask_shared_location(roots[0])
            if not folder:
                return
            svc.set_shared_folder(folder)
        elif QMessageBox.question(
                self, "Share with Everyone",
                "Share these libraries with everyone using the shared folder\n{0}?\n\n{1}\n\nTheir database "
                "is published there; your local one is replaced by it.".format(folder, "\n".join(roots)),
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        svc.make_shared(roots)
        self._offer_site_default(folder)

    def _offer_site_default(self, folder):
        """After sharing: offer making the shared folder everyone's default,
        so colleagues get the library without setting anything up."""
        svc = self.service
        site = svc.site_shared_folder()
        if site and os.path.normcase(site) == os.path.normcase(folder):
            return
        if not al.is_writable_dir(al.site_defaults_path().parent):
            return
        if QMessageBox.question(
                self, "Default for Everyone",
                "Make this shared folder the default for everyone who runs this installation of the tool?\n\n"
                "{0}\n\nYour colleagues then get the shared library automatically, without setting anything "
                "up (anyone can still change it in their own settings). Written to:\n{1}".format(
                    folder, al.site_defaults_path()),
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                svc.set_site_shared_folder(folder)
                svc.set_shared_folder(None)  # follow the default from now on
            except OSError as e:
                QMessageBox.warning(self, "Default for Everyone", "Could not write the default:\n{0}".format(e))

    def _unshare_selected(self):
        roots = [lib['root'] for lib in self._selected_libs() if lib['mode'] == 'shared']
        if roots and QMessageBox.question(
                self, "Stop Sharing",
                "Stop sharing these libraries? They disappear for EVERYONE else using the shared folder; "
                "you keep them as local libraries.\n\n" + "\n".join(roots),
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.service.stop_sharing(roots)

    # ---- shared folder -----------------------------------------------------

    def _refresh_shared_folder(self):
        svc = self.service
        folder = svc.shared_folder()
        own = svc.shared_folder_setting()
        site = svc.site_shared_folder()
        self.shared_edit.setText(folder or "")

        if folder is None:
            text = ("Turned off - only your own local libraries." if own == '' else
                    "Not set - only your own local libraries. Sharing a library sets it.")
        else:
            source = "this installation's default" if own is None else "your own setting"
            if svc.shared_error:
                text = "⚠ Not reachable - using the last downloaded copies ({0}).".format(source)
            else:
                count = len((svc.manifest or {}).get('libraries') or {})
                writable = al.is_writable_dir(folder)
                text = "✓ {0} shared librar{1} · {2} · {3}".format(
                    count, "y" if count == 1 else "ies",
                    "you can update them" if writable else "read only for you (no write access)", source)
        self.shared_status.setText(text)
        self.shared_off_btn.setEnabled(own != '')
        self.shared_default_btn.setEnabled(own is not None and bool(site))

        self.site_label.setText("Default for everyone running this installation: {0}".format(site or "none"))
        if site and folder and os.path.normcase(site) == os.path.normcase(folder):
            self.site_btn.setText("Remove Default for Everyone")
            self.site_btn.setEnabled(True)
        else:
            self.site_btn.setText("Make Default for Everyone")
            self.site_btn.setEnabled(bool(folder))
        self.site_btn.setToolTip("Everyone who starts the tool from this installation uses this shared "
                                 "folder without setting it up. Written to:\n{0}".format(al.site_defaults_path()))

    def _browse_shared(self):
        start = self.service.shared_folder() or ""
        folder = QFileDialog.getExistingDirectory(self, "Select the Shared Folder", start)
        if folder:
            self.service.set_shared_folder(os.path.normpath(folder))

    def _toggle_site_default(self):
        svc = self.service
        site, folder = svc.site_shared_folder(), svc.shared_folder()
        removing = bool(site and folder and os.path.normcase(site) == os.path.normcase(folder))
        question = ("Remove the default shared folder for everyone running this installation?" if removing else
                    "Make this the default shared folder for everyone running this installation of the tool?"
                    "\n\n{0}".format(folder))
        if QMessageBox.question(self, "Default for Everyone", question + "\n\nWritten to:\n{0}".format(
                al.site_defaults_path()), QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            svc.set_site_shared_folder(None if removing else folder)
            if not removing and svc.shared_folder_setting():
                svc.set_shared_folder(None)  # follow the default from now on
        except OSError as e:
            QMessageBox.warning(self, "Default for Everyone", "Could not write the default:\n{0}".format(e))

    # ---- local cache -------------------------------------------------------

    def _build_selected(self):
        roots = [lib['root'] for lib in self._selected_libs(default_all=True)]
        if roots:
            self.service.build(roots)

    def _delete_selected(self):
        libs = self._selected_libs(default_all=True)
        if not libs:
            return
        if self.service.building_root() in [lib['root'] for lib in libs]:
            QMessageBox.information(self, "Delete Local Copy", "Wait for (or cancel) the running job first.")
            return
        if QMessageBox.question(
                self, "Delete Local Copy",
                "Delete this machine's database / downloaded copy of these libraries? A local library has to "
                "be built again; a shared one is just downloaded again.\n\n" +
                "\n".join(lib['root'] for lib in libs), QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for lib in libs:
            if lib['mode'] == 'shared':
                al.delete_cached_snapshots(lib['root'])
            else:
                al.delete_database(lib['root'])
        self.service.reload()
        self._refresh_list()

    def _update_location(self):
        from .utils import get_local_cache_dir
        folder = get_local_cache_dir('asset_library')
        size = 0
        try:
            size = sum(p.stat().st_size for p in folder.rglob('*.db'))
        except OSError:
            pass
        self.location_label.setText("Local cache: {0}   ({1:.1f} MB)".format(folder, size / (1024 * 1024)))

    def _open_folder(self):
        from .utils import get_local_cache_dir
        folder = get_local_cache_dir('asset_library')
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ---- jobs --------------------------------------------------------------

    def _update_build_ui(self, building):
        self.progress_bar.setVisible(building)
        self.cancel_btn.setVisible(building)
        self.progress_label.setVisible(building)
        if not building:
            self._refresh_list()
        self._on_selection_changed()

    def _on_build_progress(self, root, phase, done, total):
        name = Path(root).name or root
        if total:
            self.progress_label.setText("{0}: {1} {2} / {3}".format(name, phase, _fmt(done), _fmt(total)))
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)
        else:
            self.progress_label.setText("{0}: {1}...".format(name, phase))
            self.progress_bar.setRange(0, 0)

    def _on_build_finished(self, root, ok, message):
        self.result_label.setText("{0} {1}: {2}".format("✓" if ok else "⚠", Path(root).name or root, message))
        self._refresh_list()

    def _save_types(self):
        self.service.set_visible_types([k for k, cb in self.type_checks.items() if cb.isChecked()])
