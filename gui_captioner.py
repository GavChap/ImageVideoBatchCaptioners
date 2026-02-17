import sys
import os
import requests
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QProgressBar, QCheckBox, QComboBox, QGroupBox, QGridLayout, 
    QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPalette, QColor

from src.core_logic import extract_comfy_prompt, get_thumbnail_path
from src.workers import CaptionWorker, ImageLoader
from src.widgets import CaptionItem, ClickScrollArea

class OllamaCaptionerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ollama Image Captioner")
        self.setMinimumSize(1000, 800)
        self.is_processing = False
        self.image_items = {}
        self.current_cols = 0
        self.loading_queue = []
        self.setAcceptDrops(True)
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
        
        self.btn_extract_all = QPushButton("Extract All Prompts")
        self.btn_extract_all.setFixedWidth(150)
        self.btn_extract_all.clicked.connect(self.extract_all_metadata_prompts)
        bottom_controls.addWidget(self.btn_extract_all)
        
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
        if hasattr(self, 'loader_thread') and self.loader_thread.isRunning():
            self.loader_thread.terminate()
            self.loader_thread.wait()
        
        if hasattr(self, 'load_timer') and self.load_timer.isActive():
            self.load_timer.stop()

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
        self.progress_bar.setRange(0, 0)
        
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
        
        self.load_timer = QTimer()
        self.load_timer.timeout.connect(self.load_next_image_batch)
        self.load_timer.start(10)

    def load_next_image_batch(self):
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
            
            current = self.progress_bar.maximum() - len(self.loading_queue)
            self.progress_bar.setValue(current)
            self.status_label.setText(f"Loading thumbnails: {current}/{self.progress_bar.maximum()}")

        self.update_grid_layout()

    def update_grid_layout(self):
        if not self.image_items:
            return
            
        available_width = self.scroll_area.width()
        item_width = 280 
        cols = max(1, (available_width - 30) // item_width)
        self.current_cols = cols
        
        filtered_items = self.get_filtered_items()
        sorted_items = self.get_sorted_items(filtered_items)
        
        for path, item in self.image_items.items():
            if item in sorted_items:
                item.show()
            else:
                item.hide()

        self.grid_container.setUpdatesEnabled(False)
        try:
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
            items.sort(key=lambda x: (not x.fav_path.exists(), Path(x.image_path).name.lower()))
        return items

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'image_items') and self.image_items:
            available_width = self.scroll_area.width()
            item_width = 280 
            cols = max(1, (available_width - 30) // item_width)
            if cols != self.current_cols:
                self.update_grid_layout()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return
        files = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isfile(path):
                files.append(path)
            elif os.path.isdir(path):
                if not self.dir_input.text().strip():
                    self.dir_input.setText(path)
                    return
        if files:
            self.add_images_to_directory(files)

    def delete_image_item(self, image_path):
        reply = QMessageBox.question(self, 'Delete Confirmation', 
                                    f"Are you sure you want to delete {Path(image_path).name} and its caption?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(image_path)
                txt_path = Path(image_path).with_suffix(".txt")
                if txt_path.exists(): os.remove(txt_path)
                fav_path = Path(image_path).with_suffix(Path(image_path).suffix + ".fav")
                if fav_path.exists(): os.remove(fav_path)
                thumb_path = get_thumbnail_path(image_path)
                if thumb_path.exists(): os.remove(thumb_path)
                self.status_label.setText(f"Deleted: {Path(image_path).name}")
                self.load_images_to_grid()
            except Exception as e:
                self.status_label.setText(f"Error deleting: {e}")

    def upload_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Images to Upload", "", 
                                                "Images (*.png *.jpg *.jpeg *.webp)")
        if files:
            self.add_images_to_directory(files)

    def add_images_to_directory(self, files):
        dir_path = self.dir_input.text()
        if not dir_path or not os.path.exists(dir_path):
            self.status_label.setText("Error: Select a directory first.")
            return
        count = 0
        for f in files:
            p = Path(f)
            if p.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
                dest = Path(dir_path) / p.name
                if not dest.exists():
                    try:
                        shutil.copy(f, dest)
                        count += 1
                    except Exception as e:
                        print(f"Error copying {f}: {e}")
        if count > 0:
            self.status_label.setText(f"Uploaded {count} images.")
            self.load_images_to_grid()
        else:
            self.status_label.setText("No new images were uploaded.")

    def save_all_captions(self):
        for item in self.image_items.values():
            item.save_caption()
        self.status_label.setText("All captions saved.")

    def extract_all_metadata_prompts(self):
        count = 0
        for item in self.image_items.values():
            prompt = extract_comfy_prompt(item.image_path)
            if prompt:
                item.caption_edit.setPlainText(prompt)
                item.save_caption()
                count += 1
        self.status_label.setText(f"Extracted and saved prompts for {count} images.")

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