from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl, Qt, QSize
from PySide6.QtGui import QAction, QBrush, QColor, QDrag, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QMenu,
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

from .db import CanvasPlacement, Database, STATUSES, Take
from .media import (
    delete_scene_files_and_record,
    delete_shot_files_and_record,
    delete_take_files_and_record,
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


TAKE_MIME_TYPE = "application/x-shotrack-take-id"


class TakeList(QListWidget):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window = window
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.CopyAction)
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

    def startDrag(self, supported_actions) -> None:  # type: ignore[no-untyped-def]
        urls = []
        take_ids = []
        for item in self.selectedItems():
            take_id = item.data(Qt.UserRole)
            take = self.window.db.take(take_id) if self.window.db else None
            if take:
                take_ids.append(str(take.id))
                media = project_path(self.window.project_root_path(), take.media_path)
                if media and media.exists():
                    urls.append(QUrl.fromLocalFile(str(media)))
        if not urls and not take_ids:
            return
        mime_data = QMimeData()
        if urls:
            mime_data.setUrls(urls)
        if take_ids:
            mime_data.setData(TAKE_MIME_TYPE, ",".join(take_ids).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.CopyAction)


class ImportMetadataDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Generation Info")
        self.resize(520, 340)

        self.model = QLineEdit()
        self.model.setPlaceholderText("Model used for this take")
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("Prompt used for this take")
        self.prompt.setMinimumHeight(180)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.addRow("Model", self.model)
        form.addRow("Prompt", self.prompt)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self.model.text().strip(), self.prompt.toPlainText().strip()


class CanvasView(QGraphicsView):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window = window
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setRenderHint(QPainter.Antialiasing)
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(-3000, -3000, 6000, 6000)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(TAKE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(TAKE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not event.mimeData().hasFormat(TAKE_MIME_TYPE):
            super().dropEvent(event)
            return
        raw_ids = bytes(event.mimeData().data(TAKE_MIME_TYPE)).decode("utf-8")
        scene_pos = self.mapToScene(event.position().toPoint())
        for index, raw_id in enumerate(raw_ids.split(",")):
            if raw_id.strip().isdigit():
                self.window.add_take_to_canvas(
                    int(raw_id),
                    scene_pos.x() + index * 28,
                    scene_pos.y() + index * 28,
                )
        event.acceptProposedAction()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().mouseReleaseEvent(event)
        self.window.save_canvas_layout()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        item = self.itemAt(event.position().toPoint())
        while item and item.data(0) is None and item.parentItem():
            item = item.parentItem()
        if item and item.data(0) is not None:
            self.window.open_take_media(int(item.data(0)))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() in {Qt.Key_Delete, Qt.Key_Backspace}:
            self.window.delete_selected_canvas_items()
            event.accept()
            return
        super().keyPressEvent(event)


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
        self.tree.setObjectName("sceneTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.itemSelectionChanged.connect(self.on_tree_selection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)

        self.take_list = TakeList(self)
        self.take_list.setObjectName("takeGrid")
        self.take_list.itemSelectionChanged.connect(self.on_take_selection)
        self.take_list.itemDoubleClicked.connect(lambda _item: self.open_media())
        self.take_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.take_list.customContextMenuRequested.connect(self.show_take_context_menu)

        self.preview_label = QLabel("Open or create a project.")
        self.preview_label.setObjectName("previewSurface")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(190)

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("previewSurface")
        self.video_widget.setMinimumHeight(190)

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
        self.play_button.setObjectName("primaryButton")
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("secondaryButton")
        self.stop_button.clicked.connect(self.stop_playback)
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.seek_playback)
        self.time_label = QLabel("00:00 / 00:00")

        self.title_label = QLabel("No take selected")
        self.title_label.setObjectName("assetTitle")
        self.title_label.setWordWrap(True)

        self.stars = QSpinBox()
        self.stars.setRange(0, 5)
        self.stars.valueChanged.connect(self.save_review)

        self.status = QComboBox()
        self.status.addItems(STATUSES)
        self.status.currentTextChanged.connect(self.save_review)

        self.model = QLineEdit()
        self.model.setPlaceholderText("Model used")
        self.prompt = QTextEdit()
        self.prompt.setObjectName("promptEdit")
        self.prompt.setPlaceholderText("Prompt used")
        self.prompt.setFixedHeight(92)
        self.save_generation_button = QPushButton("Save Generation Info")
        self.save_generation_button.setObjectName("primaryButton")
        self.save_generation_button.clicked.connect(self.save_generation_info)

        self.comments = QListWidget()
        self.comments.setObjectName("commentList")
        self.comments.setMinimumHeight(170)
        self.comments.setWordWrap(True)
        self.comment_edit = QTextEdit()
        self.comment_edit.setObjectName("commentEdit")
        self.comment_edit.setPlaceholderText("Add comment...")
        self.comment_edit.setFixedHeight(58)
        self.add_comment_button = QPushButton("Add Comment")
        self.add_comment_button.setObjectName("primaryButton")
        self.add_comment_button.clicked.connect(self.add_comment)

        self.open_media_button = QPushButton("Open Media")
        self.open_media_button.setObjectName("secondaryButton")
        self.open_media_button.clicked.connect(self.open_media)
        self.open_sidecar_button = QPushButton("Open PNG/Image")
        self.open_sidecar_button.setObjectName("secondaryButton")
        self.open_sidecar_button.clicked.connect(self.open_sidecar)
        self.add_canvas_button = QPushButton("Add to Canvas")
        self.add_canvas_button.setObjectName("primaryButton")
        self.add_canvas_button.clicked.connect(self.add_current_take_to_canvas)
        self.bin_button = QPushButton("Move to Bin")
        self.bin_button.setObjectName("secondaryButton")
        self.bin_button.clicked.connect(self.bin_current_take)
        self.delete_take_button = QPushButton("Delete Asset")
        self.delete_take_button.setObjectName("dangerButton")
        self.delete_take_button.clicked.connect(self.delete_current_take)

        self.scene_number = QSpinBox()
        self.scene_number.setRange(1, 999)
        self.scene_description = QLineEdit()
        self.scene_description.setPlaceholderText("scene_description")
        self.shot_number = QSpinBox()
        self.shot_number.setRange(10, 9990)
        self.shot_number.setSingleStep(10)
        self.shot_description = QLineEdit()
        self.shot_description.setPlaceholderText("human_description")
        self.save_shot_button = QPushButton("Save Scene/Shot")
        self.save_shot_button.setObjectName("primaryButton")
        self.save_shot_button.clicked.connect(self.save_scene_shot)
        self.delete_scene_button = QPushButton("Delete Scene")
        self.delete_scene_button.setObjectName("dangerButton")
        self.delete_scene_button.clicked.connect(self.delete_current_scene)
        self.delete_shot_button = QPushButton("Delete Shot")
        self.delete_shot_button.setObjectName("dangerButton")
        self.delete_shot_button.clicked.connect(self.delete_current_shot)
        self.open_scene_folder_button = QPushButton("Open Scene Folder")
        self.open_scene_folder_button.setObjectName("secondaryButton")
        self.open_scene_folder_button.clicked.connect(self.open_scene_folder)

        self.bin_list = QListWidget()
        self.bin_list.setObjectName("binList")
        self.restore_button = QPushButton("Restore Selected")
        self.restore_button.setObjectName("primaryButton")
        self.restore_button.clicked.connect(self.restore_selected_take)

        self.canvas_view = CanvasView(self)
        self.canvas_view.setObjectName("overviewCanvas")
        self.canvas_scene = self.canvas_view.scene()

        self.build_layout()
        self.build_actions()
        self.apply_theme()
        self.update_enabled_state()

    def build_layout(self) -> None:
        splitter = QSplitter()
        splitter.setObjectName("mainSplitter")
        splitter.addWidget(self.tree)

        center = QWidget()
        center.setObjectName("assetPanel")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 14, 16, 16)
        center_layout.setSpacing(12)
        center_layout.addWidget(self.section_label("Takes"))
        center_layout.addWidget(self.take_list, 1)
        splitter.addWidget(center)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.setObjectName("detailTabs")
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(16, 16, 16, 16)
        details_layout.setSpacing(12)
        details_layout.addWidget(self.preview_stack)
        playback_row = QHBoxLayout()
        playback_row.setSpacing(8)
        playback_row.addWidget(self.play_button)
        playback_row.addWidget(self.stop_button)
        playback_row.addWidget(self.position_slider, 1)
        playback_row.addWidget(self.time_label)
        details_layout.addLayout(playback_row)
        details_layout.addWidget(self.title_label)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Stars", self.stars)
        form.addRow("Status", self.status)
        form.addRow("Model", self.model)
        form.addRow("Prompt", self.prompt)
        details_layout.addLayout(form)
        details_layout.addWidget(self.save_generation_button)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self.open_media_button)
        button_row.addWidget(self.open_sidecar_button)
        button_row.addWidget(self.add_canvas_button)
        details_layout.addLayout(button_row)
        manage_row = QHBoxLayout()
        manage_row.setSpacing(8)
        manage_row.addWidget(self.bin_button)
        manage_row.addWidget(self.delete_take_button)
        details_layout.addLayout(manage_row)
        details_layout.addWidget(self.section_label("Comments"))
        details_layout.addWidget(self.comments, 1)
        details_layout.addWidget(self.comment_edit)
        details_layout.addWidget(self.add_comment_button)
        self.detail_tabs.addTab(details, "Take")

        shot_editor = QWidget()
        shot_layout = QFormLayout(shot_editor)
        shot_layout.setContentsMargins(16, 18, 16, 16)
        shot_layout.setHorizontalSpacing(14)
        shot_layout.setVerticalSpacing(12)
        shot_layout.addRow("Scene", self.scene_number)
        shot_layout.addRow("Scene Description", self.scene_description)
        shot_layout.addRow("Shot", self.shot_number)
        shot_layout.addRow("Description", self.shot_description)
        shot_layout.addRow(self.save_shot_button)
        shot_layout.addRow(self.open_scene_folder_button)
        shot_layout.addRow(self.delete_shot_button)
        shot_layout.addRow(self.delete_scene_button)
        self.detail_tabs.addTab(shot_editor, "Shot")

        bin_tab = QWidget()
        bin_layout = QVBoxLayout(bin_tab)
        bin_layout.setContentsMargins(16, 16, 16, 16)
        bin_layout.setSpacing(12)
        bin_layout.addWidget(self.bin_list)
        bin_layout.addWidget(self.restore_button)
        self.detail_tabs.addTab(bin_tab, "Bin")

        canvas_tab = QWidget()
        canvas_layout = QVBoxLayout(canvas_tab)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.addWidget(self.canvas_view)
        self.detail_tabs.addTab(canvas_tab, "Canvas")

        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([280, 610, 430])
        self.setCentralWidget(splitter)

    def build_actions(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
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

        self.open_scene_folder_action = QAction("Open Scene Folder", self)
        self.open_scene_folder_action.triggered.connect(self.open_scene_folder)
        toolbar.addAction(self.open_scene_folder_action)

        delete_scene = QAction("Delete Scene", self)
        delete_scene.triggered.connect(self.delete_current_scene)
        toolbar.addAction(delete_scene)

        delete_shot = QAction("Delete Shot", self)
        delete_shot.triggered.connect(self.delete_current_shot)
        toolbar.addAction(delete_shot)

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

    def section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def apply_theme(self) -> None:
        QApplication.instance().setStyleSheet(
            """
            QMainWindow {
                background: #181916;
                color: #f1f0e8;
                font-family: "Segoe UI";
                font-size: 10pt;
            }
            QToolBar#mainToolbar {
                background: #20211d;
                border: 0;
                border-bottom: 1px solid #383a32;
                spacing: 6px;
                padding: 8px 10px;
            }
            QToolButton {
                background: #2b2d27;
                color: #f1f0e8;
                border: 1px solid #41443b;
                border-radius: 6px;
                padding: 7px 10px;
            }
            QToolButton:hover {
                background: #36392f;
                border-color: #6f7f4f;
            }
            QSplitter::handle {
                background: #2c2e28;
            }
            QSplitter::handle:horizontal {
                width: 2px;
            }
            QTreeWidget#sceneTree,
            QListWidget#takeGrid,
            QListWidget#binList,
            QListWidget,
            QGraphicsView#overviewCanvas {
                background: #20211d;
                color: #f1f0e8;
                border: 1px solid #383a32;
                border-radius: 8px;
                outline: 0;
                padding: 6px;
            }
            QTreeWidget#sceneTree {
                border-radius: 0;
                border-left: 0;
                border-top: 0;
                border-bottom: 0;
                padding: 10px 8px;
            }
            QTreeWidget::item,
            QListWidget::item {
                border-radius: 6px;
                padding: 7px;
                margin: 2px;
            }
            QListWidget#takeGrid::item {
                background: #282a24;
                border: 1px solid #383a32;
                padding: 8px;
                margin: 4px;
            }
            QTreeWidget::item:selected,
            QListWidget::item:selected {
                background: #4d6b3c;
                color: #ffffff;
                border: 1px solid #7f9f5f;
            }
            QTreeWidget::item:hover,
            QListWidget::item:hover {
                background: #32352c;
            }
            QWidget#assetPanel {
                background: #181916;
            }
            QLabel#sectionLabel {
                color: #b8c0a4;
                font-size: 9pt;
                font-weight: 700;
                letter-spacing: 0;
                text-transform: uppercase;
            }
            QLabel#assetTitle {
                color: #f6f4ea;
                font-size: 11pt;
                font-weight: 700;
                padding: 2px 0 6px 0;
            }
            QLabel#previewSurface,
            QVideoWidget#previewSurface {
                background: #10110f;
                color: #c9c7ba;
                border: 1px solid #45483c;
                border-radius: 8px;
            }
            QTabWidget::pane {
                background: #20211d;
                border: 1px solid #383a32;
                border-right: 0;
                border-top: 0;
            }
            QTabBar::tab {
                background: #252721;
                color: #b8c0a4;
                border: 1px solid #383a32;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 9px 16px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                background: #303329;
                color: #ffffff;
                border-bottom-color: #303329;
            }
            QLineEdit,
            QTextEdit,
            QComboBox,
            QSpinBox {
                background: #141511;
                color: #f1f0e8;
                border: 1px solid #45483c;
                border-radius: 6px;
                padding: 6px 8px;
                selection-background-color: #6f8f47;
            }
            QTextEdit {
                min-height: 48px;
            }
            QTextEdit#promptEdit {
                min-height: 82px;
            }
            QListWidget#commentList {
                min-height: 170px;
            }
            QListWidget#commentList::item {
                background: #282a24;
                border: 1px solid #383a32;
                border-radius: 6px;
                padding: 0;
                margin: 4px 2px;
            }
            QListWidget#commentList::item:selected {
                background: #303329;
                border-color: #6f8f47;
            }
            QLabel#commentTimestamp {
                color: #b8c0a4;
                font-size: 8pt;
            }
            QLabel#commentBody {
                color: #f6f4ea;
                font-size: 10pt;
            }
            QLineEdit:focus,
            QTextEdit:focus,
            QComboBox:focus,
            QSpinBox:focus {
                border-color: #8fae68;
            }
            QPushButton {
                min-height: 24px;
                border-radius: 6px;
                padding: 4px 8px;
                font-weight: 600;
            }
            QPushButton#primaryButton {
                background: #6f8f47;
                color: #ffffff;
                border: 1px solid #8dad60;
            }
            QPushButton#primaryButton:hover {
                background: #7d9d55;
            }
            QPushButton#secondaryButton {
                background: #2b2d27;
                color: #f1f0e8;
                border: 1px solid #45483c;
            }
            QPushButton#secondaryButton:hover {
                background: #373a31;
            }
            QPushButton#dangerButton {
                background: #3b2524;
                color: #ffd8d4;
                border: 1px solid #79433f;
            }
            QPushButton#dangerButton:hover {
                background: #4b2d2b;
            }
            QPushButton:disabled,
            QToolButton:disabled,
            QLineEdit:disabled,
            QTextEdit:disabled,
            QComboBox:disabled,
            QSpinBox:disabled {
                color: #6f7166;
                background: #20211d;
                border-color: #303229;
            }
            QSlider::groove:horizontal {
                height: 5px;
                background: #3a3d34;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #d2a64b;
                border: 1px solid #f0c76e;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QMenu {
                background: #24261f;
                color: #f1f0e8;
                border: 1px solid #45483c;
                border-radius: 6px;
                padding: 5px;
            }
            QMenu::item {
                padding: 7px 22px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #4d6b3c;
            }
            """
        )

    def update_enabled_state(self) -> None:
        has_project = self.db is not None
        has_scene = self.current_scene_id is not None
        has_shot = self.current_shot_id is not None
        has_take = self.current_take_id is not None
        for widget in [
            self.take_list,
        ]:
            widget.setEnabled(has_project and has_shot)
        for widget in [
            self.scene_number,
            self.scene_description,
            self.delete_scene_button,
            self.save_shot_button,
            self.open_scene_folder_button,
        ]:
            widget.setEnabled(has_project and has_scene)
        self.open_scene_folder_action.setEnabled(has_project and has_scene)
        for widget in [
            self.shot_number,
            self.shot_description,
            self.delete_shot_button,
        ]:
            widget.setEnabled(has_project and has_shot)
        for widget in [
            self.stars,
            self.status,
            self.model,
            self.prompt,
            self.save_generation_button,
            self.comment_edit,
            self.add_comment_button,
            self.open_media_button,
            self.add_canvas_button,
            self.bin_button,
            self.delete_take_button,
            self.play_button,
            self.stop_button,
            self.position_slider,
        ]:
            widget.setEnabled(has_take)
        self.canvas_view.setEnabled(has_project)
        take = self.current_take()
        self.open_sidecar_button.setEnabled(bool(take and (take.sidecar_path or take.media_type == "image")))
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
        self.refresh_canvas()
        self.update_enabled_state()

    def refresh_tree(self) -> None:
        self.tree.clear()
        if not self.db:
            return
        for scene in self.db.scenes():
            scene_label = scene_code(scene.number)
            if scene.description:
                scene_label = f"{scene_label}  {scene.description}"
            scene_item = QTreeWidgetItem([scene_label])
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
            comment_count = self.db.comment_count(take.id)
            comment_marker = f"\nComments: {comment_count}" if comment_count else ""
            label = (
                f"TK_{take.take_number:03d}  {asset_type_label(take)}\n"
                f"{take.status}\n"
                f"{'*' * take.stars}{comment_marker}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, take.id)
            if take.status == "Approved":
                item.setBackground(QBrush(QColor("#1f7a3a")))
                item.setForeground(QBrush(QColor("#ffffff")))
            elif comment_count:
                item.setBackground(QBrush(QColor("#3a4658")))
            thumb = project_path(self.project_root_path(), take.thumbnail_path)
            if thumb and thumb.exists():
                item.setIcon(
                    make_take_icon(
                        thumb,
                        take.status == "Approved",
                        comment_count > 0,
                        take.media_type,
                    )
                )
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
            self.populate_scene_editor()
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

    def show_tree_context_menu(self, position) -> None:  # type: ignore[no-untyped-def]
        if not self.db:
            return
        item = self.tree.itemAt(position)
        menu = QMenu(self)
        add_scene = menu.addAction("Add Scene")
        add_scene.triggered.connect(self.add_scene)
        if item:
            self.tree.setCurrentItem(item)
            kind, _item_id = item.data(0, Qt.UserRole)
            if kind == "scene":
                add_shot = menu.addAction("Add Shot")
                add_shot.triggered.connect(self.add_shot)
                menu.addSeparator()
                delete_scene = menu.addAction("Delete Scene")
                delete_scene.triggered.connect(self.delete_current_scene)
            elif kind == "shot":
                import_media = menu.addAction("Import Media")
                import_media.triggered.connect(self.choose_import_files)
                menu.addSeparator()
                delete_shot = menu.addAction("Delete Shot")
                delete_shot.triggered.connect(self.delete_current_shot)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def show_take_context_menu(self, position) -> None:  # type: ignore[no-untyped-def]
        if not self.db:
            return
        item = self.take_list.itemAt(position)
        if not item:
            return
        self.take_list.setCurrentItem(item)
        take = self.current_take()
        if not take:
            return
        menu = QMenu(self)
        open_media = menu.addAction("Open Media")
        open_media.triggered.connect(self.open_media)
        open_sidecar = menu.addAction("Open PNG/Image")
        open_sidecar.setEnabled(bool(take.sidecar_path or take.media_type == "image"))
        open_sidecar.triggered.connect(self.open_sidecar)
        add_canvas = menu.addAction("Add to Canvas")
        add_canvas.triggered.connect(self.add_current_take_to_canvas)
        menu.addSeparator()
        move_to_bin = menu.addAction("Move to Bin")
        move_to_bin.triggered.connect(self.bin_current_take)
        delete_asset = menu.addAction("Delete Asset")
        delete_asset.triggered.connect(self.delete_current_take)
        menu.exec(self.take_list.viewport().mapToGlobal(position))

    def populate_shot_editor(self) -> None:
        if not self.db or not self.current_shot_id:
            return
        shot = self.db.shot(self.current_shot_id)
        scene = self.db.scene(shot.scene_id)
        self._building_ui = True
        self.scene_number.setValue(scene.number)
        self.scene_description.setText(scene.description)
        self.shot_number.setValue(shot.number)
        self.shot_description.setText(shot.description)
        self._building_ui = False

    def populate_scene_editor(self) -> None:
        if not self.db or not self.current_scene_id:
            return
        scene = self.db.scene(self.current_scene_id)
        self._building_ui = True
        self.scene_number.setValue(scene.number)
        self.scene_description.setText(scene.description)
        self.shot_number.setValue(10)
        self.shot_description.clear()
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
            self.model.clear()
            self.prompt.clear()
            self._building_ui = False
            return
        self.title_label.setText(Path(take.media_path).name)
        self.stars.setValue(take.stars)
        self.status.setCurrentText(take.status)
        self.model.setText(take.model)
        self.prompt.setPlainText(take.prompt)
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
                body = str(comment["body"])
                item = QListWidgetItem()
                item.setSizeHint(QSize(0, comment_item_height(body)))
                item.setToolTip(body)
                self.comments.addItem(item)
                self.comments.setItemWidget(
                    item,
                    self.comment_item_widget(str(comment["created_at"]), body),
                )
        self._building_ui = False

    def comment_item_widget(self, created_at: str, body: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        timestamp = QLabel(created_at)
        timestamp.setObjectName("commentTimestamp")
        timestamp.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content = QLabel(body)
        content.setObjectName("commentBody")
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(timestamp)
        layout.addWidget(content)
        return widget

    def add_scene(self) -> None:
        if not self.db:
            QMessageBox.information(self, "No Project", "Create or open a project first.")
            return
        scene = self.db.create_scene()
        self.current_scene_id = scene.id
        self.current_shot_id = None
        self.current_take_id = None
        self.refresh_tree()
        self.populate_scene_editor()
        self.update_enabled_state()

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
        if not self.db or not self.current_scene_id:
            return
        new_scene_number = self.scene_number.value()
        scene_description = self.scene_description.text().strip()
        try:
            self.db.update_scene(self.current_scene_id, new_scene_number, scene_description)
            if self.current_shot_id:
                new_shot_number = self.shot_number.value()
                description = snake_case(self.shot_description.text())
                self.db.update_shot(self.current_shot_id, new_shot_number, description)
            for shot in self.db.shots_for_scene(self.current_scene_id):
                rebuild_take_paths(self.db, self.project_root_path(), shot, new_scene_number)
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
        dialog = ImportMetadataDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        model, prompt = dialog.values()
        try:
            shot = self.db.shot(self.current_shot_id)
            scene = self.db.scene(shot.scene_id)
            take = import_take(
                self.db,
                self.project_root_path(),
                shot,
                scene.number,
                paths,
                model,
                prompt,
            )
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

    def save_generation_info(self) -> None:
        if self._building_ui or not self.db or not self.current_take_id:
            return
        self.db.update_take_generation(
            self.current_take_id,
            self.model.text().strip(),
            self.prompt.toPlainText().strip(),
        )
        self.refresh_takes()

    def add_comment(self) -> None:
        body = self.comment_edit.toPlainText().strip()
        if not body or not self.db or not self.current_take_id:
            return
        self.db.add_comment(self.current_take_id, body)
        self.comment_edit.clear()
        self.refresh_takes()
        self.refresh_take_detail()

    def open_media(self) -> None:
        take = self.current_take()
        if not take:
            return
        self.open_take_media(take.id)

    def open_take_media(self, take_id: int) -> None:
        if not self.db:
            return
        take = self.db.take(take_id)
        self.open_path(project_path(self.project_root_path(), take.media_path))

    def open_sidecar(self) -> None:
        take = self.current_take()
        if not take:
            return
        if take.sidecar_path:
            self.open_folder_selecting(project_path(self.project_root_path(), take.sidecar_path))
            return
        if take.media_type == "image":
            self.open_folder_selecting(project_path(self.project_root_path(), take.media_path))

    def open_scene_folder(self) -> None:
        if not self.db or not self.current_scene_id:
            return
        scene = self.db.scene(self.current_scene_id)
        folder = self.project_root_path() / "media" / scene_code(scene.number)
        folder.mkdir(parents=True, exist_ok=True)
        self.open_folder(folder)

    def open_path(self, path: Path | None) -> None:
        if not path or not path.exists():
            QMessageBox.warning(self, "Missing File", "The file does not exist.")
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def open_folder(self, path: Path | None) -> None:
        if not path or not path.exists():
            QMessageBox.warning(self, "Missing Folder", "The folder does not exist.")
            return
        subprocess.Popen(["explorer", str(path)])

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

    def delete_current_take(self) -> None:
        take = self.current_take()
        if not self.db or not take:
            return
        reply = QMessageBox.question(
            self,
            "Delete Asset",
            "Permanently delete this asset from the database and filesystem?",
        )
        if reply != QMessageBox.Yes:
            return
        try:
            delete_take_files_and_record(self.db, self.project_root_path(), take)
            self.current_take_id = None
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Delete Failed", str(exc))

    def delete_current_shot(self) -> None:
        if not self.db or not self.current_shot_id:
            return
        shot = self.db.shot(self.current_shot_id)
        scene = self.db.scene(shot.scene_id)
        reply = QMessageBox.question(
            self,
            "Delete Shot",
            f"Permanently delete {scene_code(scene.number)} {shot_code(shot.number)} and all of its assets?",
        )
        if reply != QMessageBox.Yes:
            return
        try:
            delete_shot_files_and_record(self.db, self.project_root_path(), shot, scene.number)
            self.current_shot_id = None
            self.current_take_id = None
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Delete Failed", str(exc))

    def delete_current_scene(self) -> None:
        if not self.db or not self.current_scene_id:
            return
        scene = self.db.scene(self.current_scene_id)
        reply = QMessageBox.question(
            self,
            "Delete Scene",
            f"Permanently delete {scene_code(scene.number)} and all shots/assets in it?",
        )
        if reply != QMessageBox.Yes:
            return
        try:
            delete_scene_files_and_record(self.db, self.project_root_path(), scene.id)
            self.current_scene_id = None
            self.current_shot_id = None
            self.current_take_id = None
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Delete Failed", str(exc))

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

    def refresh_canvas(self) -> None:
        self.canvas_scene.clear()
        if not self.db:
            return
        for placement in self.db.canvas_items():
            try:
                take = self.db.take(placement.take_id)
            except Exception:
                continue
            self.add_canvas_graphics_item(placement, take)

    def add_take_to_canvas(self, take_id: int, x: float, y: float) -> None:
        if not self.db:
            return
        take = self.db.take(take_id)
        placement = self.db.add_canvas_item(take.id, x, y)
        self.refresh_canvas()
        self.focus_canvas_item(placement.id)

    def add_current_take_to_canvas(self) -> None:
        take = self.current_take()
        if not self.db or not take:
            return
        existing = self.db.canvas_item_for_take(take.id)
        if existing:
            self.detail_tabs.setCurrentWidget(self.canvas_view.parentWidget())
            self.focus_canvas_item(existing.id)
            return
        center = self.canvas_view.mapToScene(self.canvas_view.viewport().rect().center())
        offset = len(self.db.canvas_items()) * 24
        placement = self.db.add_canvas_item(take.id, center.x() + offset, center.y() + offset)
        self.refresh_canvas()
        self.detail_tabs.setCurrentWidget(self.canvas_view.parentWidget())
        self.focus_canvas_item(placement.id)

    def focus_canvas_item(self, placement_id: int) -> None:
        for item in self.canvas_scene.items():
            if item.data(1) == placement_id:
                self.canvas_scene.clearSelection()
                item.setSelected(True)
                self.canvas_view.centerOn(item)
                break

    def add_canvas_graphics_item(self, placement: CanvasPlacement, take: Take) -> None:
        thumb = project_path(self.project_root_path(), take.thumbnail_path)
        pixmap = QPixmap(str(thumb)) if thumb and thumb.exists() else QPixmap()
        if pixmap.isNull():
            pixmap = placeholder_pixmap(take.media_type)
        pixmap = pixmap.scaled(
            int(placement.width),
            int(placement.height),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        item = QGraphicsPixmapItem(pixmap)
        item.setPos(placement.x, placement.y)
        item.setData(0, take.id)
        item.setData(1, placement.id)
        item.setFlag(QGraphicsItem.ItemIsMovable, True)
        item.setFlag(QGraphicsItem.ItemIsSelectable, True)
        item.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        item.setToolTip(f"{Path(take.media_path).name}\nDouble-click to open")
        label = QGraphicsTextItem(f"TK_{take.take_number:03d}  {asset_type_label(take)}", item)
        label.setDefaultTextColor(QColor("#f6f4ea"))
        label.setPos(0, pixmap.height() + 4)
        self.canvas_scene.addItem(item)

    def save_canvas_layout(self) -> None:
        if not self.db:
            return
        for item in self.canvas_scene.items():
            placement_id = item.data(1)
            take_id = item.data(0)
            if placement_id is None or take_id is None or item.parentItem() is not None:
                continue
            rect = item.boundingRect()
            self.db.update_canvas_item(
                int(placement_id),
                item.pos().x(),
                item.pos().y(),
                rect.width(),
                rect.height(),
            )

    def delete_selected_canvas_items(self) -> None:
        if not self.db:
            return
        deleted = False
        for item in list(self.canvas_scene.selectedItems()):
            placement_id = item.data(1)
            if placement_id is None:
                continue
            self.db.delete_canvas_item(int(placement_id))
            deleted = True
        if deleted:
            self.refresh_canvas()

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


def comment_item_height(body: str) -> int:
    return min(150, max(68, 58 + (len(body) // 48) * 18))


def asset_type_label(take: Take) -> str:
    labels = {
        "audio": "AUDIO",
        "video": "VIDEO",
        "image": "IMAGE",
    }
    return labels.get(take.media_type, take.media_type.upper() or "FILE")


def make_take_icon(thumb: Path, approved: bool, has_comment: bool, media_type: str) -> QIcon:
    pixmap = QPixmap(str(thumb)).scaled(180, 104, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    canvas = QPixmap(180, 104)
    canvas.fill(QColor("#20242b"))

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    x = (canvas.width() - pixmap.width()) // 2
    y = (canvas.height() - pixmap.height()) // 2
    painter.drawPixmap(x, y, pixmap)
    badge_text, badge_color = asset_badge(media_type)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(badge_color)))
    painter.drawRoundedRect(8, 8, 54, 20, 5, 5)
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(8)
    painter.setFont(font)
    painter.drawText(8, 8, 54, 20, Qt.AlignCenter, badge_text)
    if approved:
        pen = QPen(QColor("#27ae60"))
        pen.setWidth(5)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(2, 2, canvas.width() - 5, canvas.height() - 5)
    if has_comment:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#ffd166")))
        painter.drawEllipse(canvas.width() - 28, 8, 18, 18)
        painter.setPen(QColor("#111418"))
        painter.drawText(canvas.width() - 28, 8, 18, 18, Qt.AlignCenter, "C")
    painter.end()
    return QIcon(canvas)


def placeholder_pixmap(media_type: str) -> QPixmap:
    canvas = QPixmap(240, 135)
    canvas.fill(QColor("#2b3038"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#5b6472")))
    painter.drawRect(0, 0, canvas.width() - 1, canvas.height() - 1)
    painter.setPen(QColor("#f1f3f5"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(18)
    painter.setFont(font)
    painter.drawText(canvas.rect(), Qt.AlignCenter, asset_badge(media_type)[0])
    painter.end()
    return canvas


def asset_badge(media_type: str) -> tuple[str, str]:
    badges = {
        "audio": ("AUD", "#7864d8"),
        "video": ("VID", "#2d80b3"),
        "image": ("IMG", "#c46a27"),
    }
    return badges.get(media_type, ("FILE", "#69707a"))


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
