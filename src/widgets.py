from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QScrollArea, QFrame, QDialog, QTableWidget, 
    QTableWidgetItem, QHeaderView, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QPixmap, QImage, QIcon, QWheelEvent, QPainter
from PIL import Image
from PIL.ExifTags import TAGS
from .core_logic import extract_comfy_prompt, ensure_thumbnail, get_thumbnail_path

class ExifDialog(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"EXIF Data - {Path(image_path).name}")
        self.setMinimumSize(500, 600)
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Tag", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet("QTableWidget { background-color: #1e1e1e; color: #e0e0e0; border: none; }")
        
        layout.addWidget(self.table)
        self.load_exif(image_path)

    def load_exif(self, image_path):
        extracted = extract_comfy_prompt(image_path)
        if extracted:
            self.add_row("EXTRACTED PROMPT", extracted)

        try:
            with Image.open(image_path) as img:
                info = img.getexif()
                if not info:
                    if not extracted:
                        self.add_row("Info", "No EXIF or Metadata found.")
                else:
                    for tag_id, value in info.items():
                        tag = TAGS.get(tag_id, tag_id)
                        self.add_row(str(tag), str(value))
                
                for key, value in img.info.items():
                    if isinstance(value, (str, int, float, bool)):
                        self.add_row(f"Meta: {key}", str(value))
                    elif key == "prompt" or key == "workflow":
                        val_str = str(value)
                        if len(val_str) > 100:
                            val_str = val_str[:100] + "..."
                        self.add_row(f"Meta: {key}", val_str)
        except Exception as e:
            self.add_row("Error", str(e))

    def add_row(self, tag, value):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(tag))
        self.table.setItem(row, 1, QTableWidgetItem(value))

class ImagePreviewDialog(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Preview - {Path(image_path).name}")
        self.setMinimumSize(800, 600)
        self.image_path = image_path
        self.zoom_factor = 1.0
        self.last_mouse_pos = None
        
        layout = QVBoxLayout(self)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet("background-color: #000;")
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setCursor(Qt.CursorShape.OpenHandCursor)
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area)
        
        controls = QHBoxLayout()
        btn_zoom_out = QPushButton("-")
        btn_zoom_out.setFixedWidth(30)
        btn_zoom_out.clicked.connect(lambda: self.adjust_zoom(0.9))
        
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 500)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(200)
        self.zoom_slider.valueChanged.connect(self.slider_zoom)
        
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedWidth(30)
        btn_zoom_in.clicked.connect(lambda: self.adjust_zoom(1.1))
        
        btn_reset = QPushButton("Reset / Fit")
        btn_reset.clicked.connect(self.reset_zoom)
        
        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(50)
        
        controls.addStretch()
        controls.addWidget(btn_zoom_out)
        controls.addWidget(self.zoom_slider)
        controls.addWidget(btn_zoom_in)
        controls.addWidget(btn_reset)
        controls.addWidget(self.zoom_label)
        controls.addStretch()
        layout.addLayout(controls)
        
        snap_layout = QHBoxLayout()
        snap_layout.addStretch()
        snap_layout.addWidget(QLabel("Snap to:"))
        for level in [50, 100, 150, 200]:
            btn = QPushButton(f"{level}%")
            btn.setFixedWidth(50)
            btn.clicked.connect(lambda checked, l=level: self.set_zoom(l/100.0))
            snap_layout.addWidget(btn)
        snap_layout.addStretch()
        layout.addLayout(snap_layout)
        
        self.original_pixmap = QPixmap(image_path)
        self.reset_zoom()

    def reset_zoom(self):
        if self.original_pixmap.isNull(): return
        window_size = self.scroll_area.size()
        w_ratio = (window_size.width() - 20) / self.original_pixmap.width()
        h_ratio = (window_size.height() - 20) / self.original_pixmap.height()
        fit_zoom = min(w_ratio, h_ratio, 1.0)
        self.set_zoom(fit_zoom)

    def set_zoom(self, level):
        self.zoom_factor = level
        self.zoom_factor = max(0.1, min(self.zoom_factor, 10.0))
        self.update_image()
        self.update_labels()

    def adjust_zoom(self, factor):
        self.zoom_factor *= factor
        self.zoom_factor = max(0.1, min(self.zoom_factor, 10.0))
        self.update_image()
        self.update_labels()

    def slider_zoom(self, value):
        self.zoom_factor = value / 100.0
        self.update_image()
        self.zoom_label.setText(f"{int(self.zoom_factor * 100)}%")

    def update_image(self):
        if self.original_pixmap.isNull(): return
        new_width = int(self.original_pixmap.width() * self.zoom_factor)
        new_height = int(self.original_pixmap.height() * self.zoom_factor)
        scaled = self.original_pixmap.scaled(
            new_width, new_height, 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled)

    def update_labels(self):
        self.zoom_label.setText(f"{int(self.zoom_factor * 100)}%")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(self.zoom_factor * 100))
        self.zoom_slider.blockSignals(False)

    def wheelEvent(self, event: QWheelEvent):
        if event.angleDelta().y() > 0:
            self.adjust_zoom(1.1)
        else:
            self.adjust_zoom(0.9)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.scroll_area.geometry().contains(event.pos()):
                self.last_mouse_pos = event.globalPosition().toPoint()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.image_label.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is not None:
            current_pos = event.globalPosition().toPoint()
            delta = current_pos - self.last_mouse_pos
            self.last_mouse_pos = current_pos
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())

    def mouseReleaseEvent(self, event):
        self.last_mouse_pos = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.image_label.setCursor(Qt.CursorShape.OpenHandCursor)

class ClickScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_mouse_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.last_mouse_pos = event.globalPosition().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is not None:
            current_pos = event.globalPosition().toPoint()
            delta = current_pos - self.last_mouse_pos
            self.last_mouse_pos = current_pos
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.last_mouse_pos = None
            self.viewport().unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

class CaptionItem(QFrame):
    delete_requested = pyqtSignal(str)

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.fav_path = Path(image_path).with_suffix(Path(image_path).suffix + ".fav")
        self.setFixedWidth(270)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.update_style()
        
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        self.btn_fav = QPushButton("☆")
        self.btn_fav.setFixedSize(24, 24)
        self.btn_fav.setStyleSheet("background: transparent; color: #ffca28; font-size: 18px; border: none;")
        self.btn_fav.clicked.connect(self.toggle_favorite)
        
        self.full_filename = Path(image_path).name
        self.file_label = QLabel(self.full_filename)
        self.file_label.setStyleSheet("color: #888; font-size: 10px;")
        self.file_label.setToolTip(self.full_filename)
        
        self.btn_info = QPushButton("ⓘ")
        self.btn_info.setFixedSize(24, 24)
        self.btn_info.setStyleSheet("background: transparent; color: #2196f3; font-size: 16px; border: none;")
        self.btn_info.clicked.connect(self.show_exif)

        self.btn_magic = QPushButton("🪄")
        self.btn_magic.setFixedSize(24, 24)
        self.btn_magic.setStyleSheet("background: transparent; color: #9c27b0; font-size: 16px; border: none;")
        self.btn_magic.setToolTip("Extract prompt from metadata")
        self.btn_magic.clicked.connect(self.extract_metadata_prompt)

        btn_delete = QPushButton("✕")
        btn_delete.setFixedSize(20, 20)
        btn_delete.setStyleSheet("background: #c62828; color: white; border-radius: 10px; font-weight: bold;")
        btn_delete.clicked.connect(self.request_delete)
        
        header_layout.addWidget(self.btn_fav)
        header_layout.addWidget(self.file_label)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_magic)
        header_layout.addWidget(self.btn_info)
        header_layout.addWidget(btn_delete)
        layout.addLayout(header_layout)

        self.image_label = QLabel()
        self.image_label.setFixedSize(250, 200)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.image_label.setStyleSheet("background: #1e1e1e; border-radius: 4px;")
        self.image_label.mousePressEvent = self.on_image_click
        
        self.caption_edit = QTextEdit()
        self.caption_edit.setPlaceholderText("Caption...")
        self.caption_edit.setMinimumHeight(60)
        self.caption_edit.setMaximumHeight(100)
        self.caption_edit.setStyleSheet("background: #1e1e1e; color: #e0e0e0; border: none; padding: 4px;")
        
        layout.addWidget(self.image_label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.caption_edit)
        
        self.load_image()
        self.load_existing_caption()
        self.load_favorite_state()

    def update_style(self):
        is_fav = self.fav_path.exists()
        border_color = "#ffca28" if is_fav else "#3d3d3d"
        self.setStyleSheet(f"CaptionItem {{ background-color: #2b2b2b; border-radius: 8px; border: 2px solid {border_color}; }}")

    def toggle_favorite(self):
        if self.fav_path.exists():
            self.fav_path.unlink()
            self.btn_fav.setText("☆")
        else:
            self.fav_path.touch()
            self.btn_fav.setText("★")
        self.update_style()

    def load_favorite_state(self):
        if self.fav_path.exists():
            self.btn_fav.setText("★")
        else:
            self.btn_fav.setText("☆")
        self.update_style()

    def on_image_click(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            dialog = ImagePreviewDialog(self.image_path, self)
            dialog.exec()

    def load_image(self):
        display_path = ensure_thumbnail(self.image_path)
        pixmap = QPixmap(display_path)
        
        if not pixmap.isNull():
            self.image_label.setPixmap(
                pixmap.scaled(250, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            pixmap = QPixmap(self.image_path)
            if not pixmap.isNull():
                self.image_label.setPixmap(
                    pixmap.scaled(250, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        metrics = self.file_label.fontMetrics()
        elided = metrics.elidedText(self.full_filename, Qt.TextElideMode.ElideMiddle, self.file_label.width())
        self.file_label.setText(elided)

    def load_existing_caption(self):
        txt_path = Path(self.image_path).with_suffix(".txt")
        if txt_path.exists():
            try:
                self.caption_edit.setPlainText(txt_path.read_text(encoding='utf-8'))
            except Exception:
                pass

    def request_delete(self):
        self.delete_requested.emit(self.image_path)

    def show_exif(self):
        dialog = ExifDialog(self.image_path, self)
        dialog.exec()

    def extract_metadata_prompt(self):
        prompt = extract_comfy_prompt(self.image_path)
        if prompt:
            self.caption_edit.setPlainText(prompt)
            self.save_caption()

    def save_caption(self):
        txt_path = Path(self.image_path).with_suffix(".txt")
        caption = self.caption_edit.toPlainText().strip()
        if caption:
            try:
                txt_path.write_text(caption, encoding='utf-8')
            except Exception as e:
                print(f"Error saving {txt_path}: {e}")
