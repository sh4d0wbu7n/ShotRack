from __future__ import annotations

import json
import os
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication, QMessageBox

from shotrack import settings
from shotrack.app import MainWindow
from shotrack.clipboard import file_drop_data
from shotrack.db import Database
from shotrack.media import (
    delete_scene_files_and_record, export_approved, import_take,
    move_take_to_bin, rebuild_take_paths, restore_take_from_bin,
)
from shotrack.utils import quoted_path

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".tmp" / "tests"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class TempTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def database(self, root):
        root.mkdir(exist_ok=True)
        db = Database(root / "project.db")
        self.addCleanup(db.close)
        return db

    def source(self):
        path = self.root / "source.png"
        Image.new("RGB", (32, 24), "red").save(path)
        return path


class ProjectTests(TempTests):
    def workflow(self, legacy):
        root = self.root / "project"
        root.mkdir()
        if legacy:
            # Actual 0.0.7 core schema, with no format metadata.
            conn = sqlite3.connect(root / "project.db")
            conn.executescript("""
                CREATE TABLE scenes(id INTEGER PRIMARY KEY, number INTEGER NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '');
                CREATE TABLE shots(id INTEGER PRIMARY KEY, scene_id INTEGER NOT NULL
                    REFERENCES scenes(id) ON DELETE CASCADE, number INTEGER NOT NULL,
                    description TEXT NOT NULL, UNIQUE(scene_id, number));
                CREATE TABLE takes(id INTEGER PRIMARY KEY, shot_id INTEGER NOT NULL
                    REFERENCES shots(id) ON DELETE CASCADE, take_number INTEGER NOT NULL,
                    media_type TEXT NOT NULL, original_name TEXT NOT NULL, media_path TEXT NOT NULL,
                    sidecar_path TEXT, thumbnail_path TEXT, stars INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'New', is_binned INTEGER NOT NULL DEFAULT 0,
                    exported_at TEXT, created_at TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
                    prompt TEXT NOT NULL DEFAULT '', UNIQUE(shot_id, take_number));
                INSERT INTO scenes VALUES(1, 1, 'Existing scene');
                INSERT INTO shots VALUES(1, 1, 10, 'old_shot');
                INSERT INTO takes VALUES(1, 1, 1, 'image', 'old.png',
                    'media/SC001/S0010/SC001_S0010_old_shot_TK_001.png', NULL, NULL,
                    5, 'Approved', 0, NULL, '2026-08-19T12:00:00', 'Model', 'Prompt');
            """)
            conn.commit()
            conn.close()
            old_file = root / "media/SC001/S0010/SC001_S0010_old_shot_TK_001.png"
            old_file.parent.mkdir(parents=True)
            Image.new("RGB", (16, 16), "blue").save(old_file)
        db = self.database(root)
        prefix = "SC001" if legacy else "SC0001"
        self.assertEqual(db.scene_digits, 3 if legacy else 4)
        if legacy:
            before = db.take(1)
            self.assertEqual(before.media_path, old_file.relative_to(root).as_posix())
            self.assertTrue(old_file.exists())
            self.assertEqual((before.stars, before.status, before.model, before.prompt),
                             (5, "Approved", "Model", "Prompt"))
            scene = db.scene(1)
        else:
            scene = db.create_scene()
        shot = db.create_shot(scene.id)
        self.assertEqual(shot.number, 20 if legacy else 10)
        db.update_shot(shot.id, 5, "custom")
        shot = db.shot(shot.id)
        take = import_take(db, root, shot, scene.number, [self.source()], "new model", "new prompt")
        self.assertTrue(take.media_path.startswith(f"media/{prefix}/S0005/{prefix}_S0005_"))
        db.add_comment(take.id, "Keep this")
        db.update_shot(shot.id, 11, "renamed")
        rebuild_take_paths(db, root, db.shot(shot.id), scene.number)
        take = db.take(take.id)
        self.assertTrue(take.media_path.startswith(f"media/{prefix}/S0011/"))
        self.assertTrue((root / take.media_path).is_file())
        move_take_to_bin(db, root, take)
        take = db.take(take.id)
        self.assertTrue(take.media_path.startswith(f"bin/{prefix}/S0011/"))
        self.assertEqual(take.is_binned, 1)
        restore_take_from_bin(db, root, take)
        take = db.take(take.id)
        self.assertEqual(take.is_binned, 0)
        self.assertTrue((root / take.thumbnail_path).is_file())
        self.assertEqual((take.model, take.prompt), ("new model", "new prompt"))
        self.assertEqual(db.comments(take.id)[0]["body"], "Keep this")
        db.update_take_review(take.id, 4, "Approved")
        self.assertEqual(export_approved(db, root, "rename"), 2 if legacy else 1)
        self.assertTrue(list((root / "exports/approved").glob(f"{prefix}_S0011*")))
        second = Database(root / "project.db")
        try:
            self.assertEqual(second.scene_digits, db.scene_digits)
            self.assertEqual(second.create_scene().number, 2)
        finally:
            second.close()
        delete_scene_files_and_record(db, root, scene.id)
        self.assertEqual(db.project_takes(True), [])
        self.assertFalse((root / "media" / prefix).exists())
        self.assertEqual(db.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_new_project_workflow(self):
        self.workflow(False)

    def test_007_project_workflow(self):
        self.workflow(True)

    def test_last_project_settings(self):
        db = self.database(self.root / "project")
        saved = self.root / "user-settings.json"
        with patch.object(settings, "SETTINGS_PATH", saved):
            settings.save_last_project(db.db_path.parent)
            self.assertEqual(settings.load_last_project(), db.db_path.parent)
            for invalid in ("[]", "null", '{"last_project": 12}', '{"last_project": ""}', "bad json"):
                saved.write_text(invalid)
                self.assertIsNone(settings.load_last_project())
            saved.write_text(json.dumps({"last_project": str(self.root)}))
            self.assertIsNone(settings.load_last_project())
        self.assertEqual(list(self.root.glob(".shotrack-*.tmp")), [])

    def test_path_quoting(self):
        for value in (r"C:\media\take.png", r"\\server\share\take.png", r"C:\media\café.png"):
            self.assertEqual(quoted_path(Path(value)), value)
        for value in (r"C:\media files\take.png", r"C:\media\a&b.png", r"C:\media\(take).png",
                      r"C:\media\$take.png", r"C:\media\a'b.png"):
            self.assertEqual(quoted_path(Path(value)), f'"{value}"')

    def test_windows_file_drop_layout(self):
        paths = [Path(r"C:\media files\café.png"), Path(r"\\server\share\take.mp4")]
        payload = file_drop_data(paths)
        self.assertEqual(struct.unpack("<IiiII", payload[:20]), (20, 0, 0, 0, 1))
        self.assertEqual(payload[20:].decode("utf-16-le"), "\0".join(map(str, paths)) + "\0\0")

    @unittest.skipUnless(os.name == "nt", "Windows Shell reader")
    def test_windows_shell_reads_file_list(self):
        import ctypes
        from ctypes import wintypes
        paths = [self.root / "spaces and café.png", Path(r"\\server\share\take.mp4")]
        payload = ctypes.create_string_buffer(file_drop_data(paths))
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell.DragQueryFileW.restype = wintypes.UINT
        self.assertEqual(shell.DragQueryFileW(ctypes.addressof(payload), 0xFFFFFFFF, None, 0), 2)
        for index, path in enumerate(paths):
            length = shell.DragQueryFileW(ctypes.addressof(payload), index, None, 0)
            name = ctypes.create_unicode_buffer(length + 1)
            shell.DragQueryFileW(ctypes.addressof(payload), index, name, length + 1)
            self.assertEqual(name.value, str(path))


class WindowTests(TempTests):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.settings_patch = patch.object(settings, "SETTINGS_PATH", self.root / "settings.json")
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_shot_editor_saves_any_number(self):
        root = self.root / "project"
        root.mkdir()
        self.window.load_project(root)
        self.window.add_scene()
        self.window.add_shot()
        self.assertEqual(self.window.shot_number.value(), 10)
        for number in (5, 11, 9999):
            self.window.shot_number.setValue(number)
            self.window.save_scene_shot()
            self.assertEqual(self.window.db.shot(self.window.current_shot_id).number, number)
        self.assertTrue(self.window.tree.topLevelItem(0).text(0).startswith("SC0001"))

    def test_settings_failure_does_not_block_open(self):
        root = self.root / "project"
        root.mkdir()
        with patch("shotrack.app.save_last_project", side_effect=PermissionError("read only")):
            self.window.load_project(root)
        self.assertIsNotNone(self.window.db)
        self.assertIn("could not remember", self.window.statusBar().currentMessage())

    def test_text_copy_uses_selected_text(self):
        self.window.detail_tabs.setCurrentIndex(1)
        self.window.show()
        self.window.activateWindow()
        self.window.scene_description.setEnabled(True)
        self.window.scene_description.setText("Selected text")
        self.window.scene_description.selectAll()
        self.window.scene_description.setFocus()
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), self.window.scene_description)
        self.window.copy_current_media_file()
        self.assertEqual(self.app.clipboard().text(), "Selected text")

    def test_project_switch_blocked_during_import(self):
        root = self.root / "project"
        self.window._import_thread = object()
        with patch.object(QMessageBox, "information") as info:
            self.window.load_project(root)
        self.window._import_thread = None
        info.assert_called_once()
        self.assertFalse(root.exists())

    def test_duplicate_shot_does_not_partially_rename_scene(self):
        root = self.root / "project"
        root.mkdir()
        self.window.load_project(root)
        self.window.add_scene()
        self.window.add_shot()
        self.window.add_shot()
        self.assertEqual(self.window.db.shot(self.window.current_shot_id).number, 20)
        self.window.scene_number.setValue(2)
        self.window.shot_number.setValue(10)
        with patch.object(QMessageBox, "critical") as error:
            self.window.save_scene_shot()
        error.assert_called_once()
        self.assertEqual(self.window.db.scene(self.window.current_scene_id).number, 1)
        self.assertEqual(self.window.db.shot(self.window.current_shot_id).number, 20)

    def test_automatic_shots_stay_within_editor_range(self):
        root = self.root / "project"
        root.mkdir()
        self.window.load_project(root)
        self.window.add_scene()
        self.window.add_shot()
        self.window.shot_number.setValue(9999)
        self.window.save_scene_shot()
        with patch.object(QMessageBox, "warning") as warning:
            self.window.add_shot()
        warning.assert_called_once()
        self.assertEqual(len(self.window.db.shots_for_scene(self.window.current_scene_id)), 1)


if __name__ == "__main__":
    unittest.main()
