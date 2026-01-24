import sys
import os
import base64
import requests
from pathlib import Path
from PIL import Image
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QProgressBar, QCheckBox, QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QIcon


# --- Core Logic ---

def encode_image_to_base64(image_path):
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


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
                caption = generate_caption_api(self.config['url'], str(img_file), self.config['model'],
                                               self.config['prompt'])
                if caption and not caption.startswith("[ERROR]"):
                    txt_path.write_text(caption, encoding="utf-8")

            self.image_finished.emit(str(img_file), caption)

        self.finished.emit("Processing Stopped." if self.stop_requested else "Processing Complete!")


# --- Main Window ---

class OllamaCaptionerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ollama Image Captioner")
        self.setMinimumSize(900, 800)
        self.is_processing = False
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
        main_layout.addLayout(settings_layout)

        # 3. System Prompt
        prompt_group = QGroupBox("System Prompt")
        prompt_layout = QVBoxLayout(prompt_group)
        self.prompt_text = QTextEdit()
        self.prompt_text.setMaximumHeight(80)
        prompt_layout.addWidget(self.prompt_text)
        main_layout.addWidget(prompt_group)

        # 4. Monitor Area
        monitor_layout = QHBoxLayout()

        # Left Panel
        self.proc_group = QGroupBox("Currently Processing")
        self.proc_img_label = QLabel("Waiting...")
        self.proc_img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.proc_img_label.setStyleSheet("background: #2b2b2b; border-radius: 5px;")
        proc_vbox = QVBoxLayout(self.proc_group)
        proc_vbox.addWidget(self.proc_img_label)

        # Right Panel
        self.last_group = QGroupBox("Last Result")
        self.last_img_label = QLabel("None")
        self.last_img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.last_img_label.setStyleSheet("background: #2b2b2b; border-radius: 5px;")
        self.last_caption_text = QTextEdit()
        self.last_caption_text.setReadOnly(True)

        last_vbox = QVBoxLayout(self.last_group)
        last_vbox.addWidget(self.last_img_label, 1)
        last_vbox.addWidget(QLabel("Generated Caption:"))
        last_vbox.addWidget(self.last_caption_text, 1)

        monitor_layout.addWidget(self.proc_group)
        monitor_layout.addWidget(self.last_group)
        main_layout.addLayout(monitor_layout)

        # 5. Bottom Controls
        self.overwrite_cb = QCheckBox("Overwrite existing captions")
        main_layout.addWidget(self.overwrite_cb)

        self.status_label = QLabel("Ready")
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)

        self.btn_start = QPushButton("Start Captioning")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setStyleSheet("font-weight: bold;")
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
            'model': self.model_combo.currentText(),
            'prompt': self.prompt_text.toPlainText(),
            'overwrite': self.overwrite_cb.isChecked()
        }

        if not config['dir'] or not config['model']:
            self.status_label.setText("Error: Check directory and model.")
            return

        self.is_processing = True
        self.btn_start.setText("Stop Processing")
        self.worker = CaptionWorker(config)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.image_processing.connect(lambda p: self.set_preview(self.proc_img_label, p))
        self.worker.image_finished.connect(self.on_image_finished)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def set_preview(self, label, path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def on_image_finished(self, path, caption):
        self.set_preview(self.last_img_label, path)
        self.last_caption_text.setPlainText(caption)

    def update_progress(self, msg, val):
        self.status_label.setText(msg)
        self.progress_bar.setValue(val)

    def on_finished(self, msg):
        self.is_processing = False
        self.btn_start.setEnabled(True)
        self.btn_start.setText("Start Captioning")
        self.status_label.setText(msg)
        self.proc_img_label.clear()
        self.proc_img_label.setText("Done")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Cleaner look
    window = OllamaCaptionerApp()
    window.show()
    sys.exit(app.exec())