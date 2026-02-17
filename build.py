import os
import sys
import shutil
import subprocess
import platform

def build():
    # 1. Configuration
    app_name = "OllamaCaptioner"
    entry_point = "gui_captioner.py"
    bin_dir = "bin"
    dist_dir = "dist"
    build_dir = "build"
    
    # Determine extension based on OS
    system = platform.system().lower()
    ext = ".exe" if system == "windows" else ""
    target_name = f"{app_name}{ext}"

    print(f"--- Starting Build for {platform.system()} ---")

    # 2. Ensure PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("Error: PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 3. Clean previous builds
    for folder in [dist_dir, build_dir]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            
    if not os.path.exists(bin_dir):
        os.makedirs(bin_dir)

    # 4. Run PyInstaller
    # --onefile: Single executable
    # --noconsole: No terminal window for GUI
    # --add-data: Include system.txt (mapping is 'source:dest' on Linux/Mac, 'source;dest' on Windows)
    sep = ";" if system == "windows" else ":"
    
    # Check if system.txt exists; if not, create a default one or skip
    data_args = []
    if os.path.exists("system.txt"):
        data_args = ["--add-data", f"system.txt{sep}."]
    else:
        print("Warning: system.txt not found, skipping --add-data")

    cmd = [
        "pyinstaller",
        "--noconsole",
        "--onefile",
        f"--name={app_name}"
    ] + data_args + [entry_point]

    print(f"Running command: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error: {e}")
        return

    # 5. Move to /bin
    source_path = os.path.join(dist_dir, target_name)
    best_target_path = os.path.join(bin_dir, target_name)
    
    if os.path.exists(source_path):
        if os.path.exists(best_target_path):
            os.remove(best_target_path)
        shutil.move(source_path, best_target_path)
        print(f"\nSUCCESS! Executable is ready at: {best_target_path}")
    else:
        print(f"\nError: Executable not found at {source_path}")

    # 6. Cleanup temp files
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    spec_file = f"{app_name}.spec"
    if os.path.exists(spec_file):
        os.remove(spec_file)

if __name__ == "__main__":
    build()
