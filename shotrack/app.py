from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QSize
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QSlider,
    QStackedWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .db import Database, STATUSES, Take
from .media import (
    ensure_project_dirs,
    export_approved,
    import_take,
    move_take_to_bin,
    rebuild_take_paths,
    restore_take_from_bin,
)
from . import __version__
from .settings import load_last_project, save_last_project
from .utils import project_path, scene_code, shot_code, snake_case


class TakeList(QListWidget):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window = window
        self.setAcceptDrops(True)
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(180, 104))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSpacing(10)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.window.import_paths(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"ShotRack {__version__}")
        self.resize(1280, 760)
        self.setAcceptDrops(True)
        self.project_root: Path | None = None
        self.db: Database | None = None
        self.current_scene_id: int | None = None
        self.current_shot_id: int | None = None
        self.current_take_id: int | None = None
        self._building_ui = False

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemSelectionChanged.connect(self.on_tree_selection)

        self.take_list = TakeList(self)
        self.take_list.itemSelectionChanged.connect(self.on_take_selection)

        self.preview_label = QLabel("Open or create a project.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(210)
        self.preview_label.setStyleSheet("background:#20242b;color:#e9ecef;border:1px solid #444b55;")

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(210)
        self.video_widget.setStyleSheet("background:#111418;")

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.playbackStateChanged.connect(self.on_playback_state_changed)

        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview_label)
        self.preview_stack.addWidget(self.video_widget)

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_playback)
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.seek_playback)
        self.time_label = QLabel("00:00 / 00:00")

        self.title_label = QLabel("No take selected")
        self.title_label.setWordWrap(True)

        self.stars = QSpinBox()
        self.stars.setRange(0, 5)
        self.stars.valueChanged.connect(self.save_review)

        self.status = QComboBox()
        self.status.addItems(STATUSES)
        self.status.currentTextChanged.connect(self.save_review)

        self.comments = QListWidget()
        self.comment_edit = QTextEdit()
        self.comment_edit.setPlaceholderText("Add comment...")
        self.comment_edit.setFixedHeight(82)
        self.add_comment_button = QPushButton("Add Comment")
        self.add_comment_button.clicked.connect(self.add_comment)

        self.open_media_button = QPushButton("Open Media")
        self.open_media_button.clicked.connect(self.open_media)
        self.open_sidecar_button = QPushButton("Open Workflow PNG")
        self.open_sidecar_button.clicked.connect(self.open_sidecar)
        self.bin_button = QPushButton("Move to Bin")
        self.bin_button.clicked.connect(self.bin_current_take)

        self.scene_number = QSpinBox()
        self.scene_number.setRange(1, 999)
        self.shot_number = QSpinBox()
        self.shot_number.setRange(10, 9990)
        self.shot_number.setSingleStep(10)
        self.shot_description = QLineEdit()
        self.shot_description.setPlaceholderText("human_description")
        self.save_shot_button = QPushButton("Save Scene/Shot")
        self.save_shot_button.clicked.connect(self.save_scene_shot)

        self.bin_list = QListWidget()
        self.restore_button = QPushButton("Restore Selected")
        self.restore_button.clicked.connect(self.restore_selected_take)

        self.build_layout()
        self.build_actions()
        self.update_enabled_state()

    def build_layout(self) -> None:
        splitter = QSplitter()
        splitter.addWidget(self.tree)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.addWidget(QLabel("Takes"))
        center_layout.addWidget(self.take_list, 1)
        splitter.addWidget(center)

        right_tabs = QTabWidget()
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.addWidget(self.preview_stack)
        playback_row = QHBoxLayout()
        playback_row.addWidget(self.play_button)
        playback_row.addWidget(self.stop_button)
        playback_row.addWidget(self.position_slider, 1)
        playback_row.addWidget(self.time_label)
        details_layout.addLayout(playback_row)
        details_layout.addWidget(self.title_label)

        form = QFormLayout()
        form.addRow("Stars", self.stars)
        form.addRow("Status", self.status)
        details_layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addWidget(self.open_media_button)
        button_row.addWidget(self.open_sidecar_button)
        details_layout.addLayout(button_row)
        details_layout.addWidget(self.bin_button)
        details_layout.addWidget(QLabel("Comments"))
        details_layout.addWidget(self.comments, 1)
        details_layout.addWidget(self.comment_edit)
        details_layout.addWidget(self.add_comment_button)
        right_tabs.addTab(details, "Take")

        shot_editor = QWidget()
        shot_layout = QFormLayout(shot_editor)
        shot_layout.addRow("Scene", self.scene_number)
        shot_layout.addRow("Shot", self.shot_number)
        shot_layout.addRow("Description", self.shot_description)
        shot_layout.addRow(self.save_shot_button)
        right_tabs.addTab(shot_editor, "Shot")

        bin_tab = QWidget()
        bin_layout = QVBoxLayout(bin_tab)
        bin_layout.addWidget(self.bin_list)
        bin_layout.addWidget(self.restore_button)
        right_tabs.addTab(bin_tab, "Bin")

        splitter.addWidget(right_tabs)
        splitter.setSizes([250, 610, 420])
        self.setCentralWidget(splitter)

    def build_actions(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)

        new_project = QAction("New Project", self)
        new_project.triggered.connect(self.new_project)
        toolbar.addAction(new_project)

        open_project = QAction("Open Project", self)
        open_project.triggered.connect(self.open_project)
        toolbar.addAction(open_project)

        add_scene = QAction("Add Scene", self)
        add_scene.triggered.connect(self.add_scene)
        toolbar.addAction(add_scene)

        add_shot = QAction("Add Shot", self)
        add_shot.triggered.connect(self.add_shot)
        toolbar.addAction(add_shot)

        import_media = QAction("Import Media", self)
        import_media.triggered.connect(self.choose_import_files)
        toolbar.addAction(import_media)

        export = QAction("Export Approved", self)
        export.triggered.connect(self.export_approved)
        toolbar.addAction(export)

        for key in range(1, 6):
            action = QAction(str(key), self)
            action.setShortcut(QKeySequence(str(key)))
            action.triggered.connect(lambda checked=False, value=key: self.set_stars(value))
            self.addAction(action)

        shortcuts = {
            "A": "Approved",
            "R": "Rejected",
            "N": "Needs Fix",
        }
        for key, status in shortcuts.items():
            action = QAction(status, self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(lambda checked=False, value=status: self.set_status(value))
            self.addAction(action)

        prev_action = QAction("Previous Take", self)
        prev_action.setShortcut(QKeySequence(Qt.Key_Left))
        prev_action.triggered.connect(lambda: self.select_relative_take(-1))
        self.addAction(prev_action)

        next_action = QAction("Next Take", self)
        next_action.setShortcut(QKeySequence(Qt.Key_Right))
        next_action.triggered.connect(lambda: self.select_relative_take(1))
        self.addAction(next_action)

    def update_enabled_state(self) -> None:
        has_project = self.db is not None
        has_shot = self.current_shot_id is not None
        has_take = self.current_take_id is not None
        for widget in [
            self.take_list,
            self.scene_number,
            self.shot_number,
            self.shot_description,
            self.save_shot_button,
        ]:
            widget.setEnabled(has_project and has_shot)
        for widget in [
            self.stars,
            self.status,
            self.comment_edit,
            self.add_comment_button,
            self.open_media_button,
            self.bin_button,
            self.play_button,
            self.stop_button,
            self.position_slider,
        ]:
            widget.setEnabled(has_take)
        take = self.current_take()
        self.open_sidecar_button.setEnabled(bool(take and take.sidecar_path))
        can_play = bool(take and take.media_type in {"video", "audio"})
        self.play_button.setEnabled(can_play)
        self.stop_button.setEnabled(can_play)
        self.position_slider.setEnabled(can_play)
        self.restore_button.setEnabled(has_project)

    def new_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose New Project Folder")
        if not folder:
            return
        root = Path(folder)
        if any(root.iterdir()):
            reply = QMessageBox.question(
                self,
                "Use Non-empty Folder?",
                "This folder is not empty. Create a ShotRack project here?",
            )
            if reply != QMessageBox.Yes:
                return
        self.load_project(root)

    def open_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open ShotRack Project Folder")
        if folder:
            self.load_project(Path(folder))

    def load_project(self, root: Path) -> None:
        ensure_project_dirs(root)
        if self.db:
            self.db.close()
        self.project_root = root
        self.db = Database(root / "project.db")
        save_last_project(root)
        self.current_scene_id = None
        self.current_shot_id = None
        self.current_take_id = None
        self.setWindowTitle(f"ShotRack {__version__} - {root.name}")
        self.refresh_all()

    def refresh_all(self) -> None:
        self.refresh_tree()
        self.refresh_takes()
        self.refresh_bin()
        self.update_enabled_state()

    def refresh_tree(self) -> None:
        self.tree.clear()
        if not self.db:
            return
        for scene in self.db.scenes():
            scene_item = QTreeWidgetItem([scene_code(scene.number)])
            scene_item.setData(0, Qt.UserRole, ("scene", scene.id))
            self.tree.addTopLevelItem(scene_item)
            for shot in self.db.shots_for_scene(scene.id):
                label = f"{shot_code(shot.number)}  {shot.description}"
                shot_item = QTreeWidgetItem([label])
                shot_item.setData(0, Qt.UserRole, ("shot", shot.id))
                scene_item.addChild(shot_item)
                if shot.id == self.current_shot_id:
                    self.tree.setCurrentItem(shot_item)
            scene_item.setExpanded(True)

    def refresh_takes(self) -> None:
        selected_take_id = self.current_take_id
        self.take_list.blockSignals(True)
        self.take_list.clear()
        if not self.db or not self.current_shot_id:
            self.take_list.blockSignals(False)
            return
        selected_item = None
        for take in self.db.takes_for_shot(self.current_shot_id):
            label = f"TK_{take.take_number:03d}\n{take.status}\n{'*' * take.stars}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, take.id)
            thumb = project_path(self.project_root_path(), take.thumbnail_path)
            if thumb and thumb.exists():
                item.setIcon(QIcon(str(thumb)))
            self.take_list.addItem(item)
            if take.id == selected_take_id:
                selected_item = item
        if selected_item is not None:
            self.take_list.setCurrentItem(selected_item)
            self.current_take_id = selected_take_id
        else:
            self.current_take_id = None
        self.take_list.blockSignals(False)
        self.refresh_take_detail()

    def refresh_bin(self) -> None:
        self.bin_list.clear()
        if not self.db:
            return
        for take in self.db.binned_takes():
            item = QListWidgetItem(Path(take.media_path).name)
            item.setData(Qt.UserRole, take.id)
            self.bin_list.addItem(item)

    def on_tree_selection(self) -> None:
        item = self.tree.currentItem()
        if not item:
            return
        kind, item_id = item.data(0, Qt.UserRole)
        if kind == "scene":
            self.current_scene_id = item_id
            self.current_shot_id = None
            self.current_take_id = None
        elif kind == "shot":
            self.current_shot_id = item_id
            shot = self.db.shot(item_id) if self.db else None
            self.current_scene_id = shot.scene_id if shot else None
            self.current_take_id = None
            self.populate_shot_editor()
        self.refresh_takes()
        self.update_enabled_state()

    def on_take_selection(self) -> None:
        item = self.take_list.currentItem()
        self.current_take_id = item.data(Qt.UserRole) if item else None
        self.refresh_take_detail()
        self.update_enabled_state()

    def populate_shot_editor(self) -> None:
        if not self.db or not self.current_shot_id:
            return
        shot = self.db.shot(self.current_shot_id)
        scene = self.db.scene(shot.scene_id)
        self._building_ui = True
        self.scene_number.setValue(scene.number)
        self.shot_number.setValue(shot.number)
        self.shot_description.setText(shot.description)
        self._building_ui = False

    def refresh_take_detail(self) -> None:
        take = self.current_take()
        self._building_ui = True
        self.comments.clear()
        self.stop_playback(reset_source=False)
        if not take:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("No take selected")
            self.preview_stack.setCurrentWidget(self.preview_label)
            self.player.setSource(QUrl())
            self.title_label.setText("No take selected")
            self.stars.setValue(0)
            self.status.setCurrentText("New")
            self._building_ui = False
            return
        self.title_label.setText(Path(take.media_path).name)
        self.stars.setValue(take.stars)
        self.status.setCurrentText(take.status)
        media = project_path(self.project_root_path(), take.media_path)
        if take.media_type in {"video", "audio"} and media and media.exists():
            self.preview_stack.setCurrentWidget(self.video_widget)
            self.player.setSource(QUrl.fromLocalFile(str(media)))
            if take.media_type == "audio":
                self.video_widget.hide()
                self.preview_label.setPixmap(QPixmap())
                self.preview_label.setText("AUDIO")
                self.preview_stack.setCurrentWidget(self.preview_label)
            else:
                self.video_widget.show()
        else:
            self.player.setSource(QUrl())
            self.preview_stack.setCurrentWidget(self.preview_label)
            thumb = project_path(self.project_root_path(), take.thumbnail_path)
            if thumb and thumb.exists():
                pixmap = QPixmap(str(thumb)).scaled(
                    self.preview_label.width(),
                    220,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.preview_label.setPixmap(pixmap)
                self.preview_label.setText("")
            else:
                self.preview_label.setPixmap(QPixmap())
                self.preview_label.setText(take.media_type.upper())
        if self.db:
            for comment in self.db.comments(take.id):
                self.comments.addItem(f"{comment['created_at']}  {comment['body']}")
        self._building_ui = False

    def add_scene(self) -> None:
        if not self.db:
            QMessageBox.information(self, "No Project", "Create or open a project first.")
            return
        scene = self.db.create_scene()
        self.current_scene_id = scene.id
        self.current_shot_id = None
        self.refresh_tree()

    def add_shot(self) -> None:
        if not self.db:
            QMessageBox.information(self, "No Project", "Create or open a project first.")
            return
        scene_id = self.current_scene_id
        if scene_id is None:
            scene = self.db.create_scene()
            scene_id = scene.id
            self.current_scene_id = scene_id
        shot = self.db.create_shot(scene_id)
        self.current_shot_id = shot.id
        self.current_take_id = None
        self.refresh_tree()
        self.populate_shot_editor()
        self.refresh_takes()

    def save_scene_shot(self) -> None:
        if not self.db or not self.current_shot_id:
            return
        shot = self.db.shot(self.current_shot_id)
        old_scene = self.db.scene(shot.scene_id)
        new_scene_number = self.scene_number.value()
        new_shot_number = self.shot_number.value()
        description = snake_case(self.shot_description.text())
        try:
            self.db.update_scene_number(old_scene.id, new_scene_number)
            self.db.update_shot(self.current_shot_id, new_shot_number, description)
            updated_shot = self.db.shot(self.current_shot_id)
            rebuild_take_paths(self.db, self.project_root_path(), updated_shot, new_scene_number)
        except Exception as exc:
            QMessageBox.critical(self, "Rename Failed", str(exc))
        self.refresh_all()

    def import_paths(self, paths: list[Path]) -> None:
        if not self.db or not self.current_shot_id:
            QMessageBox.information(self, "No Shot Selected", "Select a shot before importing.")
            return
        missing = [str(path) for path in paths if not path.exists()]
        if missing:
            QMessageBox.warning(self, "Missing File", "\n".join(missing))
            return
        try:
            shot = self.db.shot(self.current_shot_id)
            scene = self.db.scene(shot.scene_id)
            take = import_take(self.db, self.project_root_path(), shot, scene.number, paths)
            self.current_take_id = take.id
            self.refresh_takes()
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", str(exc))

    def choose_import_files(self) -> None:
        if not self.db or not self.current_shot_id:
            QMessageBox.information(self, "No Shot Selected", "Select a shot before importing.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Media",
            "",
            "Media or sidecar files (*.*)",
        )
        if files:
            self.import_paths([Path(file) for file in files])

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.import_paths(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def save_review(self) -> None:
        if self._building_ui or not self.db or not self.current_take_id:
            return
        self.db.update_take_review(
            self.current_take_id,
            self.stars.value(),
            self.status.currentText(),
        )
        self.refresh_takes()

    def add_comment(self) -> None:
        body = self.comment_edit.toPlainText().strip()
        if not body or not self.db or not self.current_take_id:
            return
        self.db.add_comment(self.current_take_id, body)
        self.comment_edit.clear()
        self.refresh_take_detail()

    def open_media(self) -> None:
        take = self.current_take()
        if not take:
            return
        self.open_path(project_path(self.project_root_path(), take.media_path))

    def open_sidecar(self) -> None:
        take = self.current_take()
        if not take:
            return
        self.open_folder_selecting(project_path(self.project_root_path(), take.sidecar_path))

    def open_path(self, path: Path | None) -> None:
        if not path or not path.exists():
            QMessageBox.warning(self, "Missing File", "The file does not exist.")
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def open_folder_selecting(self, path: Path | None) -> None:
        if not path or not path.exists():
            QMessageBox.warning(self, "Missing File", "The file does not exist.")
            return
        subprocess.Popen(["explorer", "/select,", str(path)])

    def bin_current_take(self) -> None:
        take = self.current_take()
        if not self.db or not take:
            return
        reply = QMessageBox.question(self, "Move to Bin", "Move this take to the project bin?")
        if reply != QMessageBox.Yes:
            return
        try:
            move_take_to_bin(self.db, self.project_root_path(), take)
            self.current_take_id = None
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Move Failed", str(exc))

    def restore_selected_take(self) -> None:
        if not self.db:
            return
        item = self.bin_list.currentItem()
        if not item:
            return
        take = self.db.take(item.data(Qt.UserRole))
        try:
            restore_take_from_bin(self.db, self.project_root_path(), take)
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Restore Failed", str(exc))

    def export_approved(self) -> None:
        if not self.db:
            QMessageBox.information(self, "No Project", "Create or open a project first.")
            return
        approved = self.db.approved_takes()
        if not approved:
            QMessageBox.information(self, "Nothing to Export", "No approved takes found.")
            return
        conflict_mode = self.choose_export_conflict_mode()
        if not conflict_mode:
            return
        try:
            count = export_approved(self.db, self.project_root_path(), conflict_mode)
            QMessageBox.information(self, "Export Complete", f"Exported {count} approved take(s).")
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def choose_export_conflict_mode(self) -> str | None:
        modes = ["rename", "overwrite", "skip", "cancel"]
        mode, ok = QInputDialog.getItem(
            self,
            "Export Conflicts",
            "If an export file already exists:",
            modes,
            0,
            False,
        )
        if not ok or mode == "cancel":
            return None
        return mode

    def current_take(self) -> Take | None:
        if not self.db or not self.current_take_id:
            return None
        return self.db.take(self.current_take_id)

    def project_root_path(self) -> Path:
        if not self.project_root:
            raise RuntimeError("No project is open.")
        return self.project_root

    def set_stars(self, value: int) -> None:
        if self.current_take_id:
            self.stars.setValue(value)

    def set_status(self, value: str) -> None:
        if self.current_take_id:
            self.status.setCurrentText(value)

    def select_relative_take(self, offset: int) -> None:
        row = self.take_list.currentRow()
        if row < 0 and self.take_list.count():
            self.take_list.setCurrentRow(0)
            return
        target = row + offset
        if 0 <= target < self.take_list.count():
            self.take_list.setCurrentRow(target)

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop_playback(self, reset_source: bool = True) -> None:
        self.player.stop()
        if reset_source:
            self.player.setSource(QUrl())
            self.position_slider.setRange(0, 0)
            self.time_label.setText("00:00 / 00:00")

    def seek_playback(self, position: int) -> None:
        self.player.setPosition(position)

    def on_duration_changed(self, duration: int) -> None:
        self.position_slider.setRange(0, duration)
        self.update_time_label(self.player.position(), duration)

    def on_position_changed(self, position: int) -> None:
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position)
        self.update_time_label(position, self.player.duration())

    def on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_button.setText("Pause" if state == QMediaPlayer.PlayingState else "Play")

    def update_time_label(self, position: int, duration: int) -> None:
        self.time_label.setText(f"{format_ms(position)} / {format_ms(duration)}")


def format_ms(value: int) -> str:
    seconds = max(0, value // 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ShotRack")
    app.setApplicationVersion(__version__)
    window = MainWindow()
    last_project = load_last_project()
    if last_project:
        try:
            window.load_project(last_project)
        except Exception as exc:
            QMessageBox.warning(window, "Open Last Project Failed", str(exc))
    window.show()
    return app.exec()
