from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from .core_logic import generate_caption_api

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

            # Calculate progress percentage (0 to 100)
            progress = int((i / total) * 100)
            self.progress_update.emit(f"Processing {i + 1}/{total}: {img_file.name}", progress)
            self.image_processing.emit(str(img_file))

            txt_path = img_file.with_suffix(".txt")

            if txt_path.exists() and not self.config['overwrite']:
                caption = txt_path.read_text(encoding='utf-8')
            else:
                caption = generate_caption_api(self.config['url'], str(img_file), self.config['config_model'],
                                               self.config['prompt'], self.config.get('backend', 'vllm'))
                if caption and caption.startswith("[ERROR]"):
                    self.finished.emit(f"Error during processing: {caption}")
                    return
                
                # Apply Prefix and Suffix
                prefix = self.config.get('prefix', '').strip()
                suffix = self.config.get('suffix', '').strip()
                
                final_caption = caption
                if prefix:
                    final_caption = f"{prefix} {final_caption}".strip()
                if suffix:
                    final_caption = f"{final_caption} {suffix}".strip()
                    
                if final_caption:
                    txt_path.write_text(final_caption, encoding="utf-8")
                    caption = final_caption # for UI update

            self.image_finished.emit(str(img_file), caption)

        if not self.stop_requested:
            self.progress_update.emit("Processing Complete!", 100)
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

        images = [f for f in img_dir.iterdir() if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]]
        images.sort()
        self.finished.emit(images)
