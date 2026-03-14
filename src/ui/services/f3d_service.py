import subprocess
import threading
import sys
import os

class F3dService:
    def __init__(self):
        self.f3d_process = None
        self.f3d_lock = threading.Lock()

    def ensure_f3d_viewer(self):
        """Ensure the f3d viewer process is running via subprocess"""
        with self.f3d_lock:
            if self.f3d_process is None or self.f3d_process.poll() is not None:
                # Get the path to the current executable (works for Nuitka, PyInstaller, and raw Python)
                executable = sys.executable

                args = [executable]
                # If running from source, main.py is the second argument
                if not (getattr(sys, "frozen", False) or "__compiled__" in globals()):
                    # We assume main.py is in the current directory or executable path
                    main_py = os.path.abspath(sys.argv[0])
                    args = [executable, main_py]

                args.append("--f3d-viewer")

                self.f3d_process = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1, # Line buffered
                    # On Windows, hide the console window
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                )

                # Thread to pipe stdout and stderr to the main terminal
                def log_pipe(pipe, label):
                    try:
                        for line in iter(pipe.readline, ""):
                            if line:
                                print(f"{label}: {line.strip()}", flush=True)
                        pipe.close()
                    except:
                        pass

                threading.Thread(target=log_pipe, args=(self.f3d_process.stdout, "[F3D-OUT]"), daemon=True).start()
                threading.Thread(target=log_pipe, args=(self.f3d_process.stderr, "[F3D-ERR]"), daemon=True).start()

    def load_mesh(self, fbx_path):
        self.ensure_f3d_viewer()
        if self.f3d_process and self.f3d_process.poll() is None:
            try:
                self.f3d_process.stdin.write(f"{fbx_path}\\n")
                self.f3d_process.stdin.flush()
            except Exception as e:
                print(f"Failed to send mesh to F3D viewer: {e}")

    def cleanup(self):
        if self.f3d_process and self.f3d_process.poll() is None:
            try:
                self.f3d_process.stdin.write("STOP\\n")
                self.f3d_process.stdin.flush()
                self.f3d_process.wait(timeout=1)
            except:
                self.f3d_process.terminate()
