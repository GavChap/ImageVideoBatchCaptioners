import sys
import os
import base64
import requests
from pathlib import Path
from PIL import Image
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QProgressBar, QCheckBox, QComboBox, QGroupBox, QScrollArea,
    QGridLayout, QFrame, QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QSlider
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QPixmap, QImage, QIcon, QWheelEvent, QPainter
from PIL import Image
from PIL.ExifTags import TAGS


# --- Core Logic ---

def encode_image_to_base64(image_path):
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def get_thumbnail_path(image_path):
    img_path = Path(image_path)
    thumb_dir = img_path.parent / ".thumbnails"
    thumb_dir.mkdir(exist_ok=True)
    return thumb_dir / (img_path.name + ".tbn")


def ensure_thumbnail(image_path, size=(250, 200)):
    thumb_path = get_thumbnail_path(image_path)
    if thumb_path.exists():
        return str(thumb_path)
    
    try:
        # We use PIL for thumbnailing as it's often faster for raw file reading
        with Image.open(image_path) as img:
            img.thumbnail(size)
            # Save as a "non-image" format by using a custom extension 
            # while still using JPEG compression for efficiency
            img.save(thumb_path, "JPEG", quality=85)
        return str(thumb_path)
    except Exception as e:
        print(f"Thumbnail error for {image_path}: {e}")
        return image_path


def generate_caption_api(base_url, image_path, model, system_prompt):
    base_url = base_url.rstrip("/")
    url = f"{base_url}/api/generate"
    image_base64 = encode_image_to_base64(image_path)

    if not image_base64:
        return "[ERROR] Image encoding failed."

    payload = {
        "model": model,
        "prompt": f"{system_prompt}\n\nDescribe this image in detail.",
        "images": [image_base64],
        "stream": False
    }

    try:
        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        return f"[ERROR] {str(e)}"


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
        self.table.setStyleSheet("QTableWidget { background-color: #1e1e1e; color: #e0e0e0; border: none; }")
        
        layout.addWidget(self.table)

        self.load_exif(image_path)

    def load_exif(self, image_path):
        try:
            with Image.open(image_path) as img:
                info = img.getexif()
                if not info:
                    self.add_row("Info", "No EXIF data found.")
                    return

                for tag_id, value in info.items():
                    tag = TAGS.get(tag_id, tag_id)
                    self.add_row(str(tag), str(value))
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
        
        # Scroll area for panning
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet("background-color: #000;")
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setCursor(Qt.CursorShape.OpenHandCursor)
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area)
        
        # Controls
        controls = QHBoxLayout()
        
        btn_zoom_out = QPushButton("-")
        btn_zoom_out.setFixedWidth(30)
        btn_zoom_out.clicked.connect(lambda: self.adjust_zoom(0.9))
        
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 500) # 10% to 500%
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
        
        # Snap Buttons
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
        
        # Initial fit-to-window zoom calculation
        window_size = self.scroll_area.size()
        w_ratio = (window_size.width() - 20) / self.original_pixmap.width()
        h_ratio = (window_size.height() - 20) / self.original_pixmap.height()
        fit_zoom = min(w_ratio, h_ratio, 1.0)
        
        self.set_zoom(fit_zoom)

    def set_zoom(self, level):
        self.zoom_factor = level
        # Clamp zoom
        self.zoom_factor = max(0.1, min(self.zoom_factor, 10.0))
        self.update_image()
        self.update_labels()

    def adjust_zoom(self, factor):
        self.zoom_factor *= factor
        # Clamp zoom
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
        # Block signals to prevent recursion when setting slider value
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
            # Check if we are clicking near the scroll area
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
        self.setFixedWidth(270) # Set fixed width to prevent box stretching
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.update_style()
        
        layout = QVBoxLayout(self)
        
        # Header with Fav and Delete Buttons
        header_layout = QHBoxLayout()
        self.btn_fav = QPushButton("☆")
        self.btn_fav.setFixedSize(24, 24)
        self.btn_fav.setStyleSheet("background: transparent; color: #ffca28; font-size: 18px; border: none;")
        self.btn_fav.clicked.connect(self.toggle_favorite)
        
        self.full_filename = Path(image_path).name
        self.file_label = QLabel(self.full_filename)
        self.file_label.setStyleSheet("color: #888; font-size: 10px;")
        self.file_label.setToolTip(self.full_filename) # Show full name on hover
        
        self.btn_info = QPushButton("ⓘ")
        self.btn_info.setFixedSize(24, 24)
        self.btn_info.setStyleSheet("background: transparent; color: #2196f3; font-size: 16px; border: none;")
        self.btn_info.clicked.connect(self.show_exif)

        btn_delete = QPushButton("✕")
        btn_delete.setFixedSize(20, 20)
        btn_delete.setStyleSheet("background: #c62828; color: white; border-radius: 10px; font-weight: bold;")
        btn_delete.clicked.connect(self.request_delete)
        
        header_layout.addWidget(self.btn_fav)
        header_layout.addWidget(self.file_label)
        header_layout.addStretch()
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
        # Use cached thumbnail if available, otherwise create it
        display_path = ensure_thumbnail(self.image_path)
        pixmap = QPixmap(display_path)
        
        if not pixmap.isNull():
            self.image_label.setPixmap(
                pixmap.scaled(250, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            # Fallback to original if thumbnail failed
            pixmap = QPixmap(self.image_path)
            if not pixmap.isNull():
                self.image_label.setPixmap(
                    pixmap.scaled(250, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Elide filename if it's too long
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

    def save_caption(self):
        txt_path = Path(self.image_path).with_suffix(".txt")
        caption = self.caption_edit.toPlainText().strip()
        if caption:
            try:
                txt_path.write_text(caption, encoding='utf-8')
            except Exception as e:
                print(f"Error saving {txt_path}: {e}")


# --- Worker Thread ---

class CaptionWorker(QThread):
    progress_update = pyqtSignal(str, int)
    image_processing = pyqtSignal(str)
    image_finished = pyqtSignal(str, str)
    finished = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.stop_requested = False

    def run(self):
        img_dir = Path(self.config['dir'])
        images = [f for f in img_dir.iterdir() if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]]
        images.sort()
        total = len(images)

        if total == 0:
            self.finished.emit("No images found.")
            return

        for i, img_file in enumerate(images):
            if self.stop_requested: break

            self.progress_update.emit(f"Processing {i + 1}/{total}: {img_file.name}", int((i / total) * 100))
            self.image_processing.emit(str(img_file))

            txt_path = img_file.with_suffix(".txt")

            if txt_path.exists() and not self.config['overwrite']:
                caption = txt_path.read_text(encoding='utf-8')
            else:
                caption = generate_caption_api(self.config['url'], str(img_file), self.config['config_model'],
                                               self.config['prompt'])
                if caption and not caption.startswith("[ERROR]"):
                    txt_path.write_text(caption, encoding="utf-8")

            self.image_finished.emit(str(img_file), caption)

        self.finished.emit("Processing Stopped." if self.stop_requested else "Processing Complete!")


class ImageLoader(QThread):
    finished = pyqtSignal(list)
    progress = pyqtSignal(int, int)

    def __init__(self, dir_path):
        super().__init__()
        self.dir_path = dir_path

    def run(self):
        img_dir = Path(self.dir_path)
        if not img_dir.exists() or not img_dir.is_dir():
            self.finished.emit([])
            return

        # Fast scan
        images = [f for f in img_dir.iterdir() if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]]
        images.sort()
        self.finished.emit(images)


# --- Main Window ---

class OllamaCaptionerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ollama Image Captioner")
        self.setMinimumSize(1000, 800)
        self.is_processing = False
        self.image_items = {}
        self.current_cols = 0
        self.loading_queue = []
        self.init_ui()
        self.load_models()
        self.load_default_prompt()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 1. Connection Settings
        conn_group = QGroupBox("Connection Settings")
        conn_layout = QHBoxLayout(conn_group)
        self.url_input = QLineEdit("http://localhost:11434")
        btn_refresh = QPushButton("Refresh Models")
        btn_refresh.clicked.connect(self.load_models)
        conn_layout.addWidget(QLabel("Ollama URL:"))
        conn_layout.addWidget(self.url_input)
        conn_layout.addWidget(btn_refresh)
        main_layout.addWidget(conn_group)

        # 2. Directory & Model
        settings_layout = QHBoxLayout()
        dir_group = QGroupBox("Image Directory")
        dir_layout = QHBoxLayout(dir_group)
        self.dir_input = QLineEdit()
        self.dir_input.textChanged.connect(self.load_images_to_grid)
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(btn_browse)

        model_group = QGroupBox("Model")
        model_layout = QVBoxLayout(model_group)
        self.model_combo = QComboBox()
        model_layout.addWidget(self.model_combo)

        settings_layout.addWidget(dir_group, 2)
        settings_layout.addWidget(model_group, 1)

        sort_group = QGroupBox("Sort By")
        sort_layout = QVBoxLayout(sort_group)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            "Name (A-Z)", 
            "Name (Z-A)", 
            "Newest First", 
            "Oldest First", 
            "Favorites First"
        ])
        self.sort_combo.currentIndexChanged.connect(self.update_grid_layout)
        sort_layout.addWidget(self.sort_combo)
        settings_layout.addWidget(sort_group, 1)

        search_group = QGroupBox("Search")
        search_layout = QVBoxLayout(search_group)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search filenames or captions...")
        self.search_input.textChanged.connect(self.update_grid_layout)
        search_layout.addWidget(self.search_input)
        settings_layout.addWidget(search_group, 2)

        main_layout.addLayout(settings_layout)

        # 3. System Prompt
        prompt_group = QGroupBox("System Prompt")
        prompt_layout = QVBoxLayout(prompt_group)
        self.prompt_text = QTextEdit()
        self.prompt_text.setMaximumHeight(80)
        prompt_layout.addWidget(self.prompt_text)
        main_layout.addWidget(prompt_group)

        # 4. Image Grid Area
        grid_group = QGroupBox("Images")
        grid_main_layout = QVBoxLayout(grid_group)
        
        self.scroll_area = ClickScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #1e1e1e; }")
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(15)
        self.scroll_area.setWidget(self.grid_container)
        
        grid_main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(grid_group, 1)

        # 5. Bottom Controls
        bottom_controls = QHBoxLayout()
        
        self.overwrite_cb = QCheckBox("Overwrite existing captions")
        bottom_controls.addWidget(self.overwrite_cb)
        
        bottom_controls.addStretch()
        
        self.btn_upload = QPushButton("Upload Images")
        self.btn_upload.setFixedWidth(150)
        self.btn_upload.setStyleSheet("background-color: #1976d2; color: white;")
        self.btn_upload.clicked.connect(self.upload_images)
        bottom_controls.addWidget(self.btn_upload)

        self.btn_save_all = QPushButton("Save All Captions")
        self.btn_save_all.setFixedWidth(150)
        self.btn_save_all.clicked.connect(self.save_all_captions)
        bottom_controls.addWidget(self.btn_save_all)
        
        main_layout.addLayout(bottom_controls)

        self.status_label = QLabel("Ready")
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)

        self.btn_start = QPushButton("Start Captioning")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white;")
        self.btn_start.clicked.connect(self.toggle_processing)
        main_layout.addWidget(self.btn_start)

    # --- Logic ---

    def load_models(self):
        try:
            resp = requests.get(f"{self.url_input.text().rstrip('/')}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = [m['name'] for m in resp.json().get('models', [])]
                self.model_combo.clear()
                self.model_combo.addItems(models)
                self.status_label.setText("Models loaded.")
        except:
            self.status_label.setText("Could not connect to Ollama.")

    def load_default_prompt(self):
        default = "Your function is to generate an exacting and objective visual description."
        if os.path.exists("system.txt"):
            self.prompt_text.setPlainText(Path("system.txt").read_text(encoding='utf-8'))
        else:
            self.prompt_text.setPlainText(default)

    def browse_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Image Directory")
        if dir_path:
            self.dir_input.setText(dir_path)

    def load_images_to_grid(self):
        # Stop any current loads
        if hasattr(self, 'loader_thread') and self.loader_thread.isRunning():
            self.loader_thread.terminate()
            self.loader_thread.wait()
        
        if hasattr(self, 'load_timer') and self.load_timer.isActive():
            self.load_timer.stop()

        # Clear existing
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        self.image_items = {}
        self.current_cols = 0 
        self.loading_queue = []

        dir_path = self.dir_input.text()
        if not dir_path or not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            self.status_label.setText("Ready")
            self.progress_bar.setValue(0)
            return

        self.status_label.setText("Scanning directory...")
        self.progress_bar.setRange(0, 0) # Pulse mode
        
        self.loader_thread = ImageLoader(dir_path)
        self.loader_thread.finished.connect(self.start_incremental_load)
        self.loader_thread.start()

    def start_incremental_load(self, images):
        if not images:
            self.status_label.setText("No images found.")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            return

        self.loading_queue = images
        self.progress_bar.setRange(0, len(images))
        self.progress_bar.setValue(0)
        
        from PyQt6.QtCore import QTimer
        self.load_timer = QTimer()
        self.load_timer.timeout.connect(self.load_next_image_batch)
        self.load_timer.start(10) # 10ms interval for smooth UI

    def load_next_image_batch(self):
        # Load in small batches to keep UI responsive
        batch_size = 3
        for _ in range(batch_size):
            if not self.loading_queue:
                self.load_timer.stop()
                self.status_label.setText(f"Loaded {len(self.image_items)} images.")
                self.update_grid_layout()
                return

            img_file = self.loading_queue.pop(0)
            item = CaptionItem(str(img_file))
            item.delete_requested.connect(self.delete_image_item)
            self.image_items[str(img_file)] = item
            
            # Update progress
            current = self.progress_bar.maximum() - len(self.loading_queue)
            self.progress_bar.setValue(current)
            self.status_label.setText(f"Loading thumbnails: {current}/{self.progress_bar.maximum()}")

        # Update layout occasionally during load
        self.update_grid_layout()

    def update_grid_layout(self):
        if not self.image_items:
            return
            
        available_width = self.scroll_area.width()
        # Item width is ~250 (image) + margins/padding
        item_width = 280 
        cols = max(1, (available_width - 30) // item_width)
        
        # We always refresh if current_cols is 0 (first load)
        # However, if the sort changes, we need to re-add items even if cols is the same.
        # So we'll force a refresh by clearing and re-adding if needed, 
        # or just re-add (addWidget on existing widgets moves them).

        self.current_cols = cols
        
        # Filter and Sort items
        filtered_items = self.get_filtered_items()
        sorted_items = self.get_sorted_items(filtered_items)
        
        # Hide/Show based on filter
        for path, item in self.image_items.items():
            if item in sorted_items:
                item.show()
            else:
                item.hide()

        # Block signals briefly to prevent excessive layout updates
        self.grid_container.setUpdatesEnabled(False)
        try:
            # Clear layout first (widgets are still owned by grid_container)
            while self.grid_layout.count():
                self.grid_layout.takeAt(0)

            for i, item in enumerate(sorted_items):
                self.grid_layout.addWidget(item, i // cols, i % cols)
        finally:
            self.grid_container.setUpdatesEnabled(True)

    def get_filtered_items(self):
        query = self.search_input.text().lower().strip()
        if not query:
            return list(self.image_items.values())
            
        filtered = []
        for path, item in self.image_items.items():
            filename = Path(path).name.lower()
            caption = item.caption_edit.toPlainText().lower()
            if query in filename or query in caption:
                filtered.append(item)
        return filtered

    def get_sorted_items(self, items):
        sort_mode = self.sort_combo.currentText()
        
        if sort_mode == "Name (A-Z)":
            items.sort(key=lambda x: Path(x.image_path).name.lower())
        elif sort_mode == "Name (Z-A)":
            items.sort(key=lambda x: Path(x.image_path).name.lower(), reverse=True)
        elif sort_mode == "Newest First":
            items.sort(key=lambda x: os.path.getmtime(x.image_path), reverse=True)
        elif sort_mode == "Oldest First":
            items.sort(key=lambda x: os.path.getmtime(x.image_path))
        elif sort_mode == "Favorites First":
            # Favorites (existence of .fav file) should come first
            items.sort(key=lambda x: (not x.fav_path.exists(), Path(x.image_path).name.lower()))
            
        return items

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Use a slight delay or check if items exist
        if hasattr(self, 'image_items') and self.image_items:
            # We don't check self.current_cols here because resize might just be a small adjustment
            # but update_grid_layout has its own check if needed.
            # Actually, we SHOULD update even if cols are same because width might have changed? 
            # No, if cols are same, items don't move.
            available_width = self.scroll_area.width()
            item_width = 280 
            cols = max(1, (available_width - 30) // item_width)
            if cols != self.current_cols:
                self.update_grid_layout()

    def delete_image_item(self, image_path):
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, 'Delete Confirmation', 
                                    f"Are you sure you want to delete {Path(image_path).name} and its caption?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Delete image
                os.remove(image_path)
                # Delete caption if exists
                txt_path = Path(image_path).with_suffix(".txt")
                if txt_path.exists():
                    os.remove(txt_path)
                
                # Delete favorite marker if exists
                fav_path = Path(image_path).with_suffix(Path(image_path).suffix + ".fav")
                if fav_path.exists():
                    os.remove(fav_path)
                
                # Delete cached thumbnail
                thumb_path = get_thumbnail_path(image_path)
                if thumb_path.exists():
                    os.remove(thumb_path)

                self.status_label.setText(f"Deleted: {Path(image_path).name}")
                self.load_images_to_grid() # Refresh
            except Exception as e:
                self.status_label.setText(f"Error deleting: {e}")

    def upload_images(self):
        dir_path = self.dir_input.text()
        if not dir_path or not os.path.exists(dir_path):
            self.status_label.setText("Error: Select a directory first.")
            return

        files, _ = QFileDialog.getOpenFileNames(self, "Select Images to Upload", "", 
                                                "Images (*.png *.jpg *.jpeg *.webp)")
        if files:
            import shutil
            count = 0
            for f in files:
                dest = Path(dir_path) / Path(f).name
                if not dest.exists():
                    shutil.copy(f, dest)
                    count += 1
            
            self.status_label.setText(f"Uploaded {count} images.")
            self.load_images_to_grid() # Refresh

    def save_all_captions(self):
        for item in self.image_items.values():
            item.save_caption()
        self.status_label.setText("All captions saved.")

    def toggle_processing(self):
        if self.is_processing:
            self.worker.stop_requested = True
            self.btn_start.setEnabled(False)
            self.btn_start.setText("Stopping...")
        else:
            self.start_processing()

    def start_processing(self):
        config = {
            'url': self.url_input.text(),
            'dir': self.dir_input.text(),
            'config_model': self.model_combo.currentText(),
            'prompt': self.prompt_text.toPlainText(),
            'overwrite': self.overwrite_cb.isChecked()
        }

        if not config['dir'] or not config['config_model']:
            self.status_label.setText("Error: Check directory and model.")
            return

        self.is_processing = True
        self.btn_start.setText("Stop Processing")
        self.btn_start.setStyleSheet("font-weight: bold; background-color: #c62828; color: white;")
        self.worker = CaptionWorker(config)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.image_finished.connect(self.on_image_finished)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_image_finished(self, path, caption):
        if path in self.image_items:
            self.image_items[path].caption_edit.setPlainText(caption)
            # Scroll to current item if possible? Maybe not needed.

    def update_progress(self, msg, val):
        self.status_label.setText(msg)
        self.progress_bar.setValue(val)

    def on_finished(self, msg):
        self.is_processing = False
        self.btn_start.setEnabled(True)
        self.btn_start.setText("Start Captioning")
        self.btn_start.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white;")
        self.status_label.setText(msg)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion") 
    
    # Dark Mode Palette
    from PyQt6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(palette)

    window = OllamaCaptionerApp()
    window.show()
    sys.exit(app.exec())