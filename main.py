from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (
    QAction, QColor, QImage, QKeySequence, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QSlider,
    QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QSplitter, QSpinBox, QToolBar, QColorDialog, QComboBox,
    QInputDialog, QStyle,
)


APP_NAME = "うごピク PC"
PROJECT_EXT = ".ugopichu"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg)"


def natural_key(path: Path):
    """Sort digit runs numerically: frame_2 before frame_10."""
    return [
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", path.name)
    ]


@dataclass
class Frame:
    image: QImage
    name: str = "Frame"


@dataclass
class AudioClip:
    path: str
    start_ms: int = 0
    volume: float = 1.0


@dataclass
class Project:
    fps: int = 12
    frames: list[Frame] = field(default_factory=list)
    audio: list[AudioClip] = field(default_factory=list)


class DrawingCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 320)
        self.setMouseTracking(True)
        self.current_image = QImage(640, 480, QImage.Format_ARGB32)
        self.current_image.fill(Qt.white)
        self.previous_image: Optional[QImage] = None
        self.onion_enabled = True
        self.tool = "pen"
        self.pen_color = QColor("#202020")
        self.pen_width = 4
        self.last_point: Optional[QPointF] = None
        self.dirty_callback = None

    def set_image(self, image: QImage):
        if image.isNull():
            image = QImage(640, 480, QImage.Format_ARGB32)
            image.fill(Qt.white)
        self.current_image = image.copy()
        self.update()

    def image(self) -> QImage:
        return self.current_image.copy()

    def clear(self):
        self.current_image.fill(Qt.white)
        self.update()
        self._changed()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#343840"))
        target = self._target_rect()
        painter.fillRect(target, Qt.white)
        if self.onion_enabled and self.previous_image is not None:
            painter.setOpacity(0.22)
            painter.drawImage(target, self.previous_image)
            painter.setOpacity(1.0)
        painter.drawImage(target, self.current_image)
        painter.setPen(QPen(QColor("#858a94"), 1))
        painter.drawRect(target)

    def _target_rect(self) -> QRectF:
        iw, ih = self.current_image.width(), self.current_image.height()
        scale = min((self.width() - 24) / iw, (self.height() - 24) / ih)
        w, h = iw * scale, ih * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _image_point(self, point: QPointF) -> QPointF:
        target = self._target_rect()
        return QPointF(
            (point.x() - target.x()) * self.current_image.width() / target.width(),
            (point.y() - target.y()) * self.current_image.height() / target.height(),
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._target_rect().contains(event.position()):
            self.last_point = self._image_point(event.position())

    def mouseMoveEvent(self, event):
        if self.last_point is None or not (event.buttons() & Qt.LeftButton):
            return
        point = self._image_point(event.position())
        color = Qt.white if self.tool == "eraser" else self.pen_color
        width = self.pen_width * (3 if self.tool == "eraser" else 1)
        painter = QPainter(self.current_image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawLine(self.last_point, point)
        painter.end()
        self.last_point = point
        self.update()
        self._changed()

    def mouseReleaseEvent(self, event):
        self.last_point = None

    def _changed(self):
        if self.dirty_callback:
            self.dirty_callback()


class AudioTimeline(QWidget):
    """Simple time-based BGM lane. Audio clips are positioned in milliseconds."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.clips: list[AudioClip] = []
        self.setMinimumHeight(82)
        self.setMaximumHeight(110)

    def add_audio(self, path: str):
        self.clips.append(AudioClip(path=path))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#252932"))
        painter.setPen(QColor("#cbd0d9"))
        painter.drawText(10, 18, "🎵 BGM TIMELINE")
        lane = QRectF(10, 28, self.width() - 20, 42)
        painter.fillRect(lane, QColor("#191d24"))
        for clip in self.clips:
            name = Path(clip.path).name
            x = lane.x() + min(clip.start_ms / 100, lane.width() - 30)
            w = max(90, min(240, len(name) * 7 + 25))
            rect = QRectF(x, lane.y() + 5, min(w, lane.right() - x), 30)
            painter.setBrush(QColor("#287f82"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(Qt.white)
            painter.drawText(rect.adjusted(7, 0, -4, 0), Qt.AlignVCenter, name)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 800)
        self.project = Project()
        self.current_index = 0
        self.hidden_stage = 0
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self.next_frame)
        self._build_ui()
        self.new_frame()

    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #2e323a; color: #f0f1f3; }
            QPushButton, QComboBox, QSpinBox {
                background: #414752; border: 1px solid #555d6b;
                border-radius: 5px; padding: 6px 10px;
            }
            QPushButton:hover { background: #505968; }
            QListWidget { background: #22262d; border: 1px solid #454b56; }
            QToolBar { background: #252932; border: none; spacing: 5px; }
            QSlider::groove:horizontal { height: 5px; background: #555d6b; }
            QSlider::handle:horizontal { background: #61b5b2; width: 13px; margin: -5px 0; border-radius: 6px; }
        """)
        toolbar = QToolBar("Tools")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        for label, callback in [
            ("New", self.new_project), ("Open", self.open_project),
            ("Save", self.save_project), ("Import BGM", self.import_audio),
        ]:
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)

        splitter = QSplitter(Qt.Horizontal)
        self.frame_list = QListWidget()
        self.frame_list.setMinimumWidth(150)
        self.frame_list.currentRowChanged.connect(self.select_frame)
        splitter.addWidget(self.frame_list)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        tool_row = QHBoxLayout()
        self.pen_button = QPushButton("✎ Pen")
        self.pen_button.clicked.connect(lambda: self.set_tool("pen"))
        self.eraser_button = QPushButton("⌫ Eraser")
        self.eraser_button.clicked.connect(lambda: self.set_tool("eraser"))
        color_button = QPushButton("Color")
        color_button.clicked.connect(self.choose_color)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.canvas_clear)
        self.onion_button = QPushButton("Onion: ON")
        self.onion_button.setCheckable(True)
        self.onion_button.setChecked(True)
        self.onion_button.clicked.connect(self.toggle_onion)
        for widget in [self.pen_button, self.eraser_button, color_button, clear_button, self.onion_button]:
            tool_row.addWidget(widget)
        tool_row.addStretch()
        center_layout.addLayout(tool_row)

        self.canvas = DrawingCanvas()
        self.canvas.dirty_callback = self.mark_current_frame
        center_layout.addWidget(self.canvas, 1)

        controls = QHBoxLayout()
        for label, callback in [
            ("＋ Frame", self.new_frame), ("Duplicate", self.duplicate_frame),
            ("Delete", self.delete_frame), ("◀", self.previous_frame),
            ("▶ Play", self.toggle_playback), ("▶|", self.next_frame),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        controls.addWidget(QLabel("FPS"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(self.project.fps)
        self.fps_spin.valueChanged.connect(self.set_fps)
        controls.addWidget(self.fps_spin)
        center_layout.addLayout(controls)
        splitter.addWidget(center)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 900])

        right = QWidget()
        right.setMinimumWidth(170)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Frame properties"))
        self.frame_info = QLabel("Frame 1")
        right_layout.addWidget(self.frame_info)
        right_layout.addWidget(QLabel("Canvas: 640 × 480"))
        right_layout.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([170, 900, 180])

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(splitter, 1)
        self.audio_timeline = AudioTimeline()
        layout.addWidget(self.audio_timeline)
        self.setCentralWidget(root)

        self._shortcuts()

    def _shortcuts(self):
        # Hidden sequence: Ctrl+M, then Ctrl+L.
        self.shortcut_m = QAction(self)
        self.shortcut_m.setShortcut(QKeySequence("Ctrl+M"))
        self.shortcut_m.triggered.connect(self.arm_hidden_menu)
        self.addAction(self.shortcut_m)
        self.shortcut_l = QAction(self)
        self.shortcut_l.setShortcut(QKeySequence("Ctrl+L"))
        self.shortcut_l.triggered.connect(self.open_sequence_importer)
        self.addAction(self.shortcut_l)

    def arm_hidden_menu(self):
        self.hidden_stage = 1
        QTimer.singleShot(3000, self.clear_hidden_stage)

    def clear_hidden_stage(self):
        self.hidden_stage = 0

    def open_sequence_importer(self):
        if self.hidden_stage != 1:
            return
        self.hidden_stage = 0
        files, _ = QFileDialog.getOpenFileNames(
            self, "連番画像を読み込む", "", IMAGE_FILTER
        )
        if not files:
            return
        paths = sorted((Path(p) for p in files), key=natural_key)
        imported = 0
        for path in paths:
            try:
                with Image.open(path) as pil:
                    rgba = pil.convert("RGBA")
                    data = rgba.tobytes("raw", "RGBA")
                    qimage = QImage(
                        data, rgba.width, rgba.height, rgba.width * 4,
                        QImage.Format_RGBA8888
                    ).copy()
                self.project.frames.append(Frame(qimage, path.name))
                imported += 1
            except Exception as exc:
                QMessageBox.warning(self, "読み込みエラー", f"{path.name}\n{exc}")
        self.refresh_frames()
        if imported:
            self.frame_list.setCurrentRow(len(self.project.frames) - imported)
            self.statusBar().showMessage(f"{imported} 枚の画像をフレームとして追加しました", 5000)

    def new_frame(self):
        image = QImage(640, 480, QImage.Format_ARGB32)
        image.fill(Qt.white)
        self.project.frames.append(Frame(image, f"Frame {len(self.project.frames) + 1}"))
        self.refresh_frames()
        self.frame_list.setCurrentRow(len(self.project.frames) - 1)

    def duplicate_frame(self):
        if not self.project.frames:
            return
        frame = self.project.frames[self.current_index]
        self.project.frames.insert(self.current_index + 1, Frame(frame.image.copy(), f"Frame copy"))
        self.refresh_frames()
        self.frame_list.setCurrentRow(self.current_index + 1)

    def delete_frame(self):
        if len(self.project.frames) <= 1:
            QMessageBox.information(self, APP_NAME, "最後の1フレームは削除できません。")
            return
        del self.project.frames[self.current_index]
        self.current_index = max(0, min(self.current_index, len(self.project.frames) - 1))
        self.refresh_frames()
        self.frame_list.setCurrentRow(self.current_index)

    def refresh_frames(self):
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        for index, frame in enumerate(self.project.frames):
            item = QListWidgetItem(f"{index + 1:03d}  {frame.name}")
            self.frame_list.addItem(item)
        self.frame_list.blockSignals(False)
        if self.project.frames:
            self.show_frame(self.current_index)

    def select_frame(self, index):
        if 0 <= index < len(self.project.frames):
            self.current_index = index
            self.show_frame(index)

    def show_frame(self, index):
        frame = self.project.frames[index]
        self.canvas.previous_image = (
            self.project.frames[index - 1].image if index > 0 else None
        )
        self.canvas.set_image(frame.image)
        self.frame_info.setText(f"Frame {index + 1} / {len(self.project.frames)}")
        self.canvas.update()

    def mark_current_frame(self):
        if self.project.frames and 0 <= self.current_index < len(self.project.frames):
            self.project.frames[self.current_index].image = self.canvas.image()

    def canvas_clear(self):
        self.canvas.clear()

    def set_tool(self, tool):
        self.canvas.tool = tool

    def choose_color(self):
        color = QColorDialog.getColor(self.canvas.pen_color, self, "ペンの色")
        if color.isValid():
            self.canvas.pen_color = color
            self.canvas.tool = "pen"

    def toggle_onion(self, checked):
        self.canvas.onion_enabled = checked
        self.onion_button.setText("Onion: ON" if checked else "Onion: OFF")
        self.canvas.update()

    def set_fps(self, value):
        self.project.fps = value
        if self.play_timer.isActive():
            self.play_timer.start(round(1000 / value))

    def toggle_playback(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
            return
        self.play_timer.start(round(1000 / self.project.fps))

    def next_frame(self):
        if not self.project.frames:
            return
        index = (self.current_index + 1) % len(self.project.frames)
        self.frame_list.setCurrentRow(index)

    def previous_frame(self):
        if self.project.frames:
            self.frame_list.setCurrentRow((self.current_index - 1) % len(self.project.frames))

    def import_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "BGMを読み込む", "", "Audio (*.mp3 *.wav *.ogg *.flac *.m4a)"
        )
        if path:
            self.project.audio.append(AudioClip(path))
            self.audio_timeline.add_audio(path)

    def new_project(self):
        answer = QMessageBox.question(self, APP_NAME, "現在のプロジェクトを破棄して新規作成しますか？")
        if answer != QMessageBox.Yes:
            return
        self.play_timer.stop()
        self.project = Project()
        self.audio_timeline.clips.clear()
        self.audio_timeline.update()
        self.frame_list.clear()
        self.new_frame()
        self.fps_spin.setValue(12)

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "プロジェクトを保存", "untitled" + PROJECT_EXT,
            f"Ugopichu Project (*{PROJECT_EXT})"
        )
        if not path:
            return
        self.mark_current_frame()
        frames_dir = Path(path).with_suffix("").with_name(Path(path).stem + "_assets")
        frames_dir.mkdir(parents=True, exist_ok=True)
        frame_entries = []
        for i, frame in enumerate(self.project.frames):
            asset = frames_dir / f"frame_{i:05d}.png"
            if not frame.image.save(str(asset), "PNG"):
                raise OSError(f"Could not save {asset}")
            frame_entries.append({"name": frame.name, "file": str(asset.name)})
        data = {
            "version": 1, "fps": self.project.fps, "frames_dir": frames_dir.name,
            "frames": frame_entries, "audio": [asdict(a) for a in self.project.audio],
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.statusBar().showMessage(f"保存しました: {path}", 5000)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "プロジェクトを開く", "", f"Ugopichu Project (*{PROJECT_EXT})"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            base = Path(path).parent / data.get("frames_dir", "")
            frames = []
            for entry in data["frames"]:
                image = QImage(str(base / entry["file"]))
                if image.isNull():
                    raise ValueError(f"画像を開けません: {entry['file']}")
                frames.append(Frame(image, entry.get("name", "Frame")))
            if not frames:
                raise ValueError("フレームがありません")
            self.project = Project(
                fps=int(data.get("fps", 12)), frames=frames,
                audio=[AudioClip(**a) for a in data.get("audio", [])]
            )
            self.current_index = 0
            self.fps_spin.setValue(self.project.fps)
            self.audio_timeline.clips = list(self.project.audio)
            self.audio_timeline.update()
            self.refresh_frames()
            self.frame_list.setCurrentRow(0)
        except Exception as exc:
            QMessageBox.critical(self, "読み込みエラー", str(exc))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
