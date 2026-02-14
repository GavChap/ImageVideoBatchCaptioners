import os
import sys
import json
import base64
import argparse
from pathlib import Path
import requests  # Use requests for direct API calls
from tqdm import tqdm

def encode_image_to_base64(image_path):
    """Encodes an image file to a base64 string."""
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        tqdm.write(f"[ERROR] Could not read or encode image {image_path}: {e}")
        return None

def generate_caption(image_path, model, system_prompt):
    """
    Generates a caption for a given image using a local Ollama model's native API.
    """
    # Use Ollama's native /api/generate endpoint
    url = "http://localhost:11434/api/generate"
    
    image_base64 = encode_image_to_base64(image_path)
    if not image_base64:
        return "[ERROR] Image encoding failed."
        
    # Combine system prompt and user instruction into a single prompt string
    full_prompt = f"{system_prompt}\n\nDescribe this image in detail."

    # Construct the payload for the native Ollama API
    payload = {
        "model": model,
        "prompt": full_prompt,
        "images": [image_base64],
        "stream": False  # Get the full response at once
    }

    try:
        # Make a POST request to the Ollama server
        # Add a timeout to prevent the script from hanging indefinitely
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        
        # Parse the JSON response and extract the caption
        response_data = response.json()
        caption = response_data.get("response", "").strip()

        if not caption:
             tqdm.write(f"[WARNING] Model returned an empty caption for {image_path}")
             return "[ERROR] Empty caption returned."

        return caption

    except requests.exceptions.RequestException as e:
        tqdm.write(f"[ERROR] Could not connect to or communicate with Ollama server: {e}")
        tqdm.write("Please ensure Ollama is running and the model is available.")
        return "[ERROR] Connection to Ollama failed."
    except Exception as e:
        tqdm.write(f"[ERROR] An unexpected error occurred while generating caption for {image_path}: {e}")
        return "[ERROR] An unknown error occurred."


def process_directory(directory, model, system_prompt):
    """Processes all images in a given directory."""
    img_dir = Path(directory)

    if not img_dir.exists() or not img_dir.is_dir():
        tqdm.write(f"[SKIP] Invalid directory: {directory}")
        return

    images = [f for f in img_dir.iterdir() if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]]

    if not images:
        tqdm.write(f"[INFO] No images found in {directory}")
        return

    with tqdm(total=len(images), desc=f"Captioning ({img_dir.name})", unit="img") as pbar:
        for img_file in images:
            txt_path = img_file.with_suffix(".txt")

            if txt_path.exists():
                pbar.set_description(f"Skipping {img_file.name}")
                pbar.update(1)
                continue
            
            pbar.set_description(f"Captioning {img_file.name}")
            caption = generate_caption(str(img_file), model, system_prompt)
            
            if caption and not caption.startswith("[ERROR]"):
                try:
                    txt_path.write_text(caption, encoding="utf-8")
                except Exception as e:
                    tqdm.write(f"[ERROR] Failed to write caption file for {img_file.name}: {e}")

            pbar.update(1)

def main():
    """Main function to parse arguments and start the captioning process."""
    parser = argparse.ArgumentParser(description="Image captioning using a local Ollama instance.")
    parser.add_argument("--queue", help="Path to a JSON file with a queue of directories to process.")
    parser.add_argument("--directory", help="Path to a single directory of images.")
    parser.add_argument("--model", default="llava:latest", help="Model name available in Ollama (e.g., 'llava').")
    parser.add_argument(
        "--system",
        default="Your function is to generate an exacting and objective visual description for an AI art generator, constrained to a single paragraph of no more than three sentences. Specify the artistic style and medium, then articulate the composition, lighting, color story, and prevailing mood. If a dominant figure is present, inventory their distinct characteristics including physical build, complexion, and posture. You must also meticulously account for any digital overlays or post-processing effects, such as cinematic bars or filters, and for any 'text', you are required to quote its content directly and describe its font and position on the canvas. All subjective interpretation, meta-commentary, and extraneous remarks are to be excluded, delivering only the core English description.",
        help="System prompt to guide the captioning style. Can be a string or a path to a .txt file."
    )
    args = parser.parse_args()

    # Determine the system prompt
    system_prompt = args.system
    if os.path.isfile(args.system):
        try:
            with open(args.system, "r", encoding="utf-8") as f:
                system_prompt = f.read().strip()
        except Exception as e:
            print(f"Failed to read system prompt file: {e}")
            sys.exit(1)

    if args.queue:
        try:
            with open(args.queue, "r", encoding="utf-8") as f:
                job_queue = json.load(f)
        except Exception as e:
            print(f"Failed to load queue file: {e}")
            sys.exit(1)

        for job in job_queue:
            directory = job.get("directory")
            model = job.get("model", args.model)
            # Allow job-specific system prompt, otherwise use the one from args
            job_system_prompt = job.get("system", system_prompt)
            
            if os.path.isfile(job_system_prompt):
                 with open(job_system_prompt, "r", encoding="utf-8") as f:
                    job_system_prompt = f.read().strip()

            if not directory:
                tqdm.write("[SKIP] Job missing 'directory' field.")
                continue
            process_directory(directory, model, job_system_prompt)

    elif args.directory:
        process_directory(args.directory, args.model, system_prompt)

    else:
        print("Error: You must specify either the --queue or --directory argument.")
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()

