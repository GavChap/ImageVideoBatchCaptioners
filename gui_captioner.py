import sys
import os
import json
import requests
import shutil
import hashlib
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QProgressBar, QCheckBox, QComboBox, QGroupBox, QGridLayout, 
    QMessageBox, QInputDialog, QDialog, QFormLayout, QSlider
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPalette, QColor
import zipfile

from src.core_logic import extract_comfy_prompt, get_thumbnail_path
from src.workers import CaptionWorker, ImageLoader
from src.widgets import CaptionItem, ClickScrollArea

class OllamaCaptionerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("vLLM Image Captioner")
        self.setMinimumSize(1000, 800)
        self.is_processing = False
        self.image_items = {}
        self.current_cols = 0
        self.thumbnail_size = 280
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
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["vLLM", "llama.cpp", "Ollama"])
        self.backend_combo.currentTextChanged.connect(self.on_backend_changed)
        self.url_label = QLabel("vLLM URL:")
        self.url_input = QLineEdit("http://localhost:8000")
        btn_refresh = QPushButton("Refresh Models")
        btn_refresh.clicked.connect(self.load_models)
        conn_layout.addWidget(QLabel("Backend:"))
        conn_layout.addWidget(self.backend_combo)
        conn_layout.addWidget(self.url_label)
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

        # 3. System Prompt & Tags
        prompt_group = QGroupBox("System Prompt & Tags")
        prompt_layout = QVBoxLayout(prompt_group)

        history_layout = QHBoxLayout()
        self.prompt_history_combo = QComboBox()
        self.prompt_history_combo.setPlaceholderText("Prompt history...")
        self.prompt_history_combo.setSizePolicy(
            self.prompt_history_combo.sizePolicy().horizontalPolicy(),
            self.prompt_history_combo.sizePolicy().verticalPolicy()
        )
        self.prompt_history_combo.currentIndexChanged.connect(self.load_prompt_from_history)
        history_layout.addWidget(QLabel("History:"))
        history_layout.addWidget(self.prompt_history_combo)
        prompt_layout.addLayout(history_layout)

        self.prompt_text = QTextEdit()
        self.prompt_text.setMaximumHeight(60)

        tags_layout = QHBoxLayout()
        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("Prefix (e.g., '1girl, ')")
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("Suffix (e.g., ', highres')")
        tags_layout.addWidget(QLabel("Prefix:"))
        tags_layout.addWidget(self.prefix_input)
        tags_layout.addWidget(QLabel("Suffix:"))
        tags_layout.addWidget(self.suffix_input)

        prompt_layout.addWidget(self.prompt_text)
        prompt_layout.addLayout(tags_layout)
        main_layout.addWidget(prompt_group)

        # 4. Image Grid Area
        grid_group = QGroupBox("Images")
        grid_main_layout = QVBoxLayout(grid_group)
        
        # Grid Controls (Slider & Search/Replace)
        grid_controls = QHBoxLayout()
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(150, 600)
        self.size_slider.setValue(self.thumbnail_size)
        self.size_slider.setFixedWidth(200)
        self.size_slider.valueChanged.connect(self.update_thumbnail_sizes)
        
        btn_search_replace = QPushButton("Search and Replace")
        btn_search_replace.clicked.connect(self.show_search_replace)

        grid_controls.addWidget(QLabel("Thumbnail Size:"))
        grid_controls.addWidget(self.size_slider)
        grid_controls.addStretch()
        grid_controls.addWidget(btn_search_replace)
        grid_main_layout.addLayout(grid_controls)
        
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

        self.btn_find_dupes = QPushButton("Find Duplicates")
        self.btn_find_dupes.setFixedWidth(130)
        self.btn_find_dupes.setStyleSheet("background-color: #6a1b9a; color: white;")
        self.btn_find_dupes.clicked.connect(self.find_and_show_duplicates)
        bottom_controls.addWidget(self.btn_find_dupes)

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
        
        self.btn_export_zip = QPushButton("Export to Zip")
        self.btn_export_zip.setFixedWidth(120)
        self.btn_export_zip.clicked.connect(self.export_to_zip)
        bottom_controls.addWidget(self.btn_export_zip)
        
        self.btn_compile_prompts = QPushButton("Compile Unique Prompts")
        self.btn_compile_prompts.setFixedWidth(160)
        self.btn_compile_prompts.clicked.connect(self.compile_unique_prompts)
        bottom_controls.addWidget(self.btn_compile_prompts)
        
        main_layout.addLayout(bottom_controls)

        status_container = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.count_label = QLabel("Images: 0")
        self.count_label.setStyleSheet("font-weight: bold; color: #4fc3f7;")
        status_container.addWidget(self.status_label)
        status_container.addStretch()
        status_container.addWidget(self.count_label)
        main_layout.addLayout(status_container)

        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)

        self.btn_start = QPushButton("Start Captioning")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white;")
        self.btn_start.clicked.connect(self.toggle_processing)
        main_layout.addWidget(self.btn_start)

    def on_backend_changed(self, text):
        defaults = {
            "Ollama":    ("Ollama URL:",    "http://localhost:11434"),
            "vLLM":      ("vLLM URL:",      "http://localhost:8000"),
            "llama.cpp": ("llama.cpp URL:", "http://localhost:8080"),
        }
        label, url = defaults.get(text, ("URL:", ""))
        self.url_label.setText(label)
        self.url_input.setText(url)
        self.load_models()

    HISTORY_FILE = "prompt_history.json"
    MAX_HISTORY = 10

    def load_prompt_history(self):
        if os.path.exists(self.HISTORY_FILE):
            try:
                return json.loads(Path(self.HISTORY_FILE).read_text(encoding='utf-8'))
            except Exception:
                pass
        return []

    def save_prompt_to_history(self, prompt):
        prompt = prompt.strip()
        if not prompt:
            return
        history = self.load_prompt_history()
        # deduplicate, newest first
        history = [p for p in history if p != prompt]
        history.insert(0, prompt)
        history = history[:self.MAX_HISTORY]
        Path(self.HISTORY_FILE).write_text(json.dumps(history, indent=2), encoding='utf-8')
        self.refresh_prompt_history_combo()

    def refresh_prompt_history_combo(self):
        history = self.load_prompt_history()
        self.prompt_history_combo.blockSignals(True)
        self.prompt_history_combo.clear()
        for p in history:
            # show first 60 chars as label
            label = p[:60].replace('\n', ' ') + ('…' if len(p) > 60 else '')
            self.prompt_history_combo.addItem(label, userData=p)
        self.prompt_history_combo.setCurrentIndex(-1)
        self.prompt_history_combo.blockSignals(False)

    def load_prompt_from_history(self, index):
        if index < 0:
            return
        prompt = self.prompt_history_combo.itemData(index)
        if prompt:
            self.prompt_text.setPlainText(prompt)

    def load_models(self):
        backend = self.backend_combo.currentText()
        base = self.url_input.text().rstrip('/')
        try:
            if backend == "Ollama":
                resp = requests.get(f"{base}/api/tags", timeout=3)
                resp.raise_for_status()
                models = [m['name'] for m in resp.json().get('models', [])]
            else:
                resp = requests.get(f"{base}/v1/models", timeout=3)
                resp.raise_for_status()
                models = [m['id'] for m in resp.json().get('data', [])]
            self.model_combo.clear()
            self.model_combo.addItems(models)
            self.status_label.setText("Models loaded.")
        except requests.exceptions.RequestException:
            self.status_label.setText(f"Could not connect to {backend}. Is it running?")
            self.model_combo.clear()
        except Exception:
            self.status_label.setText("An unexpected error occurred loading models.")

    def load_default_prompt(self):
        default = "Your function is to generate an exacting and objective visual description."
        if os.path.exists("system.txt"):
            self.prompt_text.setPlainText(Path("system.txt").read_text(encoding='utf-8'))
        else:
            self.prompt_text.setPlainText(default)
        self.refresh_prompt_history_combo()

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
            self.count_label.setText("Images: 0")
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
            self.count_label.setText("Images: 0")
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
        item_width = self.thumbnail_size
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
            
            total = len(self.image_items)
            showing = len(sorted_items)
            if showing < total:
                self.count_label.setText(f"Showing {showing} of {total} images")
            else:
                self.count_label.setText(f"Images: {total}")
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
            item_width = self.thumbnail_size
            cols = max(1, (available_width - 30) // item_width)
            if cols != self.current_cols:
                self.update_grid_layout()

    def update_thumbnail_sizes(self, value):
        self.thumbnail_size = value
        for item in self.image_items.values():
            item.set_thumbnail_size(value - 30)  # Account for padding
        self.update_grid_layout()

    def show_search_replace(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Search and Replace")
        layout = QFormLayout(dialog)
        search_input = QLineEdit()
        replace_input = QLineEdit()
        btn_run = QPushButton("Replace All")
        
        layout.addRow("Search for:", search_input)
        layout.addRow("Replace with:", replace_input)
        layout.addRow(btn_run)
        
        def do_replace():
            search_text = search_input.text()
            replace_text = replace_input.text()
            if not search_text: return
            
            count = 0
            for item in self.image_items.values():
                current_text = item.caption_edit.toPlainText()
                if search_text in current_text:
                    new_text = current_text.replace(search_text, replace_text)
                    item.caption_edit.setPlainText(new_text)
                    count += 1
            self.status_label.setText(f"Replaced text in {count} captions.")
            dialog.accept()
            
        btn_run.clicked.connect(do_replace)
        dialog.exec()

    def export_to_zip(self):
        dir_path = self.dir_input.text()
        if not dir_path or not os.path.exists(dir_path):
            self.status_label.setText("Error: No directory selected.")
            return
            
        zip_path, _ = QFileDialog.getSaveFileName(self, "Export Zip File", "", "Zip Files (*.zip)")
        if not zip_path:
            return
            
        try:
            self.save_all_captions() # ensure all manual edits are saved
            self.status_label.setText("Creating zip file...")
            QApplication.processEvents()
            
            count = 0
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for img_path, item in self.image_items.items():
                    # Add image
                    arcname_img = Path(img_path).name
                    zipf.write(img_path, arcname_img)
                    
                    # Add text file if it exists
                    txt_path = Path(img_path).with_suffix(".txt")
                    if txt_path.exists():
                        arcname_txt = txt_path.name
                        zipf.write(txt_path, arcname_txt)
                    count += 1
                    
            self.status_label.setText(f"Exported {count} images/captions to {Path(zip_path).name}")
        except Exception as e:
            self.status_label.setText(f"Error exporting to zip: {e}")

    def compile_unique_prompts(self):
        dir_path = self.dir_input.text()
        if not dir_path or not os.path.exists(dir_path):
            self.status_label.setText("Error: No directory selected.")
            return
            
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Unique Prompts", "", "Text Files (*.txt)")
        if not save_path:
            return
            
        try:
            unique_hashes = set()
            unique_prompts = []
            for item in self.image_items.values():
                prompt = item.caption_edit.toPlainText().strip()
                if prompt:
                    # ensure one line per prompt
                    prompt = prompt.replace('\n', ' ').replace('\r', '')
                    
                    # normalize before hashing to deduplicate case/whitespace variations
                    normalized_prompt = " ".join(prompt.lower().split())
                    prompt_hash = hashlib.md5(normalized_prompt.encode('utf-8')).hexdigest()
                    
                    if prompt_hash not in unique_hashes:
                        unique_hashes.add(prompt_hash)
                        unique_prompts.append(prompt)
                    
            with open(save_path, 'w', encoding='utf-8') as f:
                for p in sorted(unique_prompts):
                    f.write(f"{p}\n")
                    
            self.status_label.setText(f"Saved {len(unique_prompts)} unique prompts to {Path(save_path).name}")
        except Exception as e:
            self.status_label.setText(f"Error saving prompts: {e}")

    def find_and_show_duplicates(self):
        if not self.image_items:
            self.status_label.setText("No images loaded.")
            return

        self.status_label.setText("Hashing images...")
        QApplication.processEvents()

        hash_map = {}
        for path in self.image_items:
            try:
                h = hashlib.md5(Path(path).read_bytes()).hexdigest()
                hash_map.setdefault(h, []).append(path)
            except Exception:
                pass

        groups = [paths for paths in hash_map.values() if len(paths) > 1]

        if not groups:
            self.status_label.setText("No duplicate images found.")
            return

        total_dupes = sum(len(g) - 1 for g in groups)
        self.status_label.setText(f"Found {total_dupes} duplicate(s) in {len(groups)} group(s).")
        self._show_dupe_dialog(groups)

    def _show_dupe_dialog(self, groups):
        from PyQt6.QtWidgets import QScrollArea as _SA, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Duplicate Images")
        dialog.setMinimumSize(600, 400)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Uncheck the copies you want to KEEP. Checked items will be deleted."))

        scroll = _SA()
        scroll.setWidgetResizable(True)
        container = QWidget()
        vbox = QVBoxLayout(container)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        checkboxes = []  # (QCheckBox, path)
        for i, group in enumerate(groups):
            vbox.addWidget(QLabel(f"<b>Group {i + 1}</b>"))
            for j, path in enumerate(group):
                cb = QCheckBox(Path(path).name)
                cb.setChecked(j > 0)  # keep first, mark rest for deletion
                cb.setToolTip(path)
                vbox.addWidget(cb)
                checkboxes.append((cb, path))
            vbox.addWidget(QLabel(""))  # spacer

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        to_delete = [path for cb, path in checkboxes if cb.isChecked()]
        count = 0
        for path in to_delete:
            try:
                os.remove(path)
                txt = Path(path).with_suffix(".txt")
                if txt.exists(): os.remove(txt)
                fav = Path(path).with_suffix(Path(path).suffix + ".fav")
                if fav.exists(): os.remove(fav)
                thumb = get_thumbnail_path(path)
                if thumb.exists(): os.remove(thumb)
                count += 1
            except Exception as e:
                self.status_label.setText(f"Error deleting {Path(path).name}: {e}")

        self.status_label.setText(f"Deleted {count} duplicate(s).")
        if count:
            self.load_images_to_grid()

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
        if not self.model_combo.currentText():
            backend = self.backend_combo.currentText()
            self.status_label.setText(f"Error: No model selected. Ensure {backend} is running and refresh.")
            return
            
        config = {
            'url': self.url_input.text(),
            'dir': self.dir_input.text(),
            'config_model': self.model_combo.currentText(),
            'prompt': self.prompt_text.toPlainText(),
            'prefix': self.prefix_input.text(),
            'suffix': self.suffix_input.text(),
            'overwrite': self.overwrite_cb.isChecked(),
            'backend': self.backend_combo.currentText().lower()
        }
        if not config['dir'] or not os.path.isdir(config['dir']):
            self.status_label.setText("Error: Check directory.")
            return
        self.save_prompt_to_history(config['prompt'])
        self.is_processing = True
        self.btn_start.setText("Stop Processing")
        self.btn_start.setStyleSheet("font-weight: bold; background-color: #c62828; color: white;")
        
        # Reset progress bar for processing
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        # Stop thumbnail loading if it's still running
        if hasattr(self, 'load_timer') and self.load_timer.isActive():
            self.load_timer.stop()
            self.status_label.setText("Stopped loading to start captioning.")

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
        if "Complete" in msg:
            self.progress_bar.setValue(100)

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