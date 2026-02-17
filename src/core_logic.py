import base64
import requests
import json
import os
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS

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
        with Image.open(image_path) as img:
            img.thumbnail(size)
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

def extract_comfy_prompt(image_path):
    try:
        with Image.open(image_path) as img:
            metadata = img.info
            if not metadata:
                return None

            if "prompt" in metadata:
                try:
                    prompt_data = json.loads(metadata["prompt"])
                    prompts = []
                    for node_id, node_info in prompt_data.items():
                        class_type = node_info.get("class_type", "")
                        inputs = node_info.get("inputs", {})
                        
                        if "CLIPTextEncode" in class_type:
                            for key in ["text", "text_g", "text_l", "string"]:
                                text = inputs.get(key)
                                if text and isinstance(text, str) and len(text.strip()) > 5:
                                    prompts.append(text.strip())
                    
                    if prompts:
                        unique_prompts = list(set(prompts))
                        unique_prompts.sort(key=len, reverse=True)
                        return "\n".join(unique_prompts)
                except Exception:
                    pass

            if "parameters" in metadata:
                params = metadata["parameters"]
                lines = params.split("\n")
                if lines:
                    return lines[0].strip()

            if "Description" in metadata:
                return metadata["Description"].strip()

    except Exception as e:
        print(f"Extraction error for {image_path}: {e}")
    return None
