import os
import sys
import torch
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout,
                             QWidget, QFileDialog, QTextEdit, QLabel, QProgressBar, QComboBox)
from PyQt6.QtCore import QThread, pyqtSignal
from transformers import Qwen3VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info

# Qwen3-VL Model List
MODELS = {
    "Qwen3-VL-4B (Edge/Efficient)": "Qwen/Qwen3-VL-4B-Instruct",
    "Qwen3-VL-8B (Balanced)": "Qwen/Qwen3-VL-8B-Instruct",
    "Qwen3-VL-32B (Frontier)": "Qwen/Qwen3-VL-32B-Instruct"
}


class CaptionWorker(QThread):
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, folder_path, prompt, model_id):
        super().__init__()
        self.folder_path = folder_path
        self.prompt = prompt
        self.model_id = model_id

    def run(self):
        try:
            self.log.emit(f"🚀 Initializing Qwen3-VL Loader...")

            # Using the native Qwen3 class to resolve RoPE errors
            model = Qwen3VLForConditionalGeneration.from_pretrained(
                self.model_id,
                torch_dtype="auto",
                device_map="auto"
            )
            processor = AutoProcessor.from_pretrained(self.model_id)

            # File scanning
            video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.webm')
            files = [f for f in os.listdir(self.folder_path) if f.lower().endswith(video_extensions)]
            total = len(files)

            if total == 0:
                self.log.emit("⚠️ Error: No video files found.")
                return

            for i, filename in enumerate(files):
                video_path = os.path.join(self.folder_path, filename)
                self.log.emit(f"🎥 [{i + 1}/{total}] Captioning: {filename}")

                messages = [{
                    "role": "user",
                    "content": [
                        {
                            "type": "video",
                            "video": f"file://{video_path}",
                            "fps": 1.0
                        },
                        {"type": "text", "text": self.prompt},
                    ],
                }]

                # Qwen3 specific processing
                text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                image_inputs, video_inputs = process_vision_info(messages)

                inputs = processor(
                    text=[text],
                    images=image_inputs,
                    videos=video_inputs,
                    padding=True,
                    return_tensors="pt"
                ).to(model.device)

                # Generation
                generated_ids = model.generate(**inputs, max_new_tokens=512)

                # Input Trimming to remove prompt/timestamps
                input_len = inputs.input_ids.shape[1]
                generated_ids_trimmed = [
                    out_ids[input_len:] for out_ids in generated_ids
                ]

                output_text = processor.batch_decode(
                    generated_ids_trimmed,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False
                )[0]

                # Save Clean Output
                output_path = os.path.splitext(video_path)[0] + ".txt"
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(output_text.strip())

                self.progress.emit(i + 1, total)

            self.log.emit("\n✨ Batch processing complete.")

        except Exception as e:
            self.log.emit(f"\n❌ Error: {str(e)}")
        finally:
            self.finished.emit()


class CaptionerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qwen3-VL Video Captioner")
        self.setMinimumSize(650, 500)

        layout = QVBoxLayout()

        layout.addWidget(QLabel("<b>1. Qwen3 Model:</b>"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(MODELS.keys())
        layout.addWidget(self.model_combo)

        layout.addWidget(QLabel("<b>2. Folder:</b>"))
        self.btn_select = QPushButton("📂 Select Video Folder")
        self.btn_select.clicked.connect(self.select_folder)
        layout.addWidget(self.btn_select)
        self.lbl_path = QLabel("None")

        layout.addWidget(QLabel("<b>3. Prompt:</b>"))
        self.txt_prompt = QTextEdit()
        self.txt_prompt.setText("Describe this video in detail.")
        self.txt_prompt.setMaximumHeight(60)
        layout.addWidget(self.txt_prompt)

        self.btn_start = QPushButton("🚀 Run Qwen3-VL Batch")
        self.btn_start.clicked.connect(self.start_process)
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet("padding: 10px; background: #2c3e50; color: white;")
        layout.addWidget(self.btn_start)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background: black; color: #00ff00;")
        layout.addWidget(self.log_output)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.folder_path = ""

    def select_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            self.folder_path = path
            self.lbl_path.setText(path)
            self.btn_start.setEnabled(True)

    def start_process(self):
        self.btn_start.setEnabled(False)
        model_id = MODELS[self.model_combo.currentText()]
        self.worker = CaptionWorker(self.folder_path, self.txt_prompt.toPlainText(), model_id)
        self.worker.progress.connect(lambda c, t: (self.progress_bar.setMaximum(t), self.progress_bar.setValue(c)))
        self.worker.log.connect(lambda m: self.log_output.append(m))
        self.worker.finished.connect(lambda: self.btn_start.setEnabled(True))
        self.worker.start()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CaptionerApp()
    window.show()
    sys.exit(app.exec())