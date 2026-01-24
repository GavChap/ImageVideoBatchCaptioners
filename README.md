# Ollama Image Captioner

This project allows you to caption images using a local Ollama instance. It provides a command-line interface for processing images in a directory or from a queue file.

## Installation

1.  **Install Python:** Ensure you have Python 3.12.3 or later installed.

2.  **Install Dependencies:**
    ```bash
    pip install requests pillow tqdm
    ```

3.  **Install Ollama:** Follow the instructions at <https://ollama.com/> to install Ollama. Ensure it is running on `http://localhost:11434`.

4.  **Install PyTorch (for Qwen3-VL):** The Qwen3-VL model requires PyTorch. Follow the instructions at <https://pytorch.org/get-started/locally/> to install the appropriate version based on your system.

## Requirements Files

The project includes two `requirements.txt` files:

*   `image_requirements.txt`: Contains the minimum requirements for running the core image processing logic.
*   `video_requirements.txt`:  Contains the additional requirements for running the Qwen3-VL model.

## Usage

### Running the Application

The project includes two primary ways to run the image captioning process:

1.  **Image Processing (Single Directory):**

    ```bash
    python gui_captioner.py
    ```
2.  **Video Processing (Qwen3 only):**

    ```bash
    python gui_video_qwencaptioner.py
    ```

## Supported Image Formats

The script currently supports the following image formats: PNG, JPG, JPEG, and WEBP.

## Troubleshooting

*   **Ollama Not Running:**  Ensure that Ollama is running on `http://localhost:11434`.
*   **Connection Errors:** Check your network connection and that Ollama is accessible.
*   **Model Not Found:** Verify that the specified model is available in Ollama using `ollama list`.

## Credits

This project uses the Qwen3-VL model from HuggingFace.  Refer to the model card for details: [https://huggingface.co/Qwen/Qwen3-VL-32B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-32B-Instruct)