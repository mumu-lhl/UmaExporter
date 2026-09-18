import subprocess
import threading
import sys
import os
import json
import queue
from pathlib import Path

from src.services.f3d.worker import THUMBNAIL_RESULT_PREFIX


class F3dService:
    def __init__(self):
        self.f3d_process = None
        self.f3d_lock = threading.Lock()
        self._load_callbacks = []
        self._callbacks_lock = threading.Lock()

    def ensure_f3d_viewer(self):
        """Ensure the f3d viewer process is running via subprocess"""
        with self.f3d_lock:
            if self.f3d_process is None or self.f3d_process.poll() is not None:
                # Get the path to the current executable (works for Nuitka, PyInstaller, and raw Python)
                executable = sys.executable

                args = [executable]
                # If running from source, main.py is the second argument
                if not (getattr(sys, "frozen", False) or "__compiled__" in globals()):
                    project_root = Path(__file__).resolve().parents[3]
                    main_py = str(project_root / "main.py")
                    if not os.path.exists(main_py):
                        main_py = os.path.abspath(sys.argv[0])
                    args = [executable, main_py]

                args.append("--f3d-viewer")

                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"

                self.f3d_process = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                    bufsize=1,  # Line buffered
                    env=env,
                    # On Windows, hide the console window
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )

                # Thread to pipe stdout and stderr to the main terminal
                def log_pipe(pipe, label):
                    try:
                        for line in iter(pipe.readline, ""):
                            if line:
                                line_str = line.strip()
                                if line_str.startswith("F3D_SCENE_LOADED"):
                                    parts = line_str.split()
                                    count = (
                                        int(parts[1])
                                        if len(parts) > 1 and parts[1].isdigit()
                                        else 1
                                    )
                                    self._notify_loaded(True, count)
                                elif line_str.startswith("F3D_SCENE_FAILED"):
                                    self._notify_loaded(False, 0)
                                else:
                                    print(f"{label}: {line_str}", flush=True)
                        pipe.close()
                    except:
                        pass
                    finally:
                        self._notify_loaded(False, 0)

                threading.Thread(
                    target=log_pipe,
                    args=(self.f3d_process.stdout, "[F3D-OUT]"),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=log_pipe,
                    args=(self.f3d_process.stderr, "[F3D-ERR]"),
                    daemon=True,
                ).start()

    def _notify_loaded(self, success, count):
        with self._callbacks_lock:
            cbs = list(self._load_callbacks)
            self._load_callbacks.clear()
        for cb in cbs:
            try:
                cb(success, count)
            except Exception as e:
                print(f"Error in F3D on_loaded callback: {e}", flush=True)

    def load_mesh(self, fbx_path, on_loaded=None):
        self.ensure_f3d_viewer()
        if on_loaded:
            with self._callbacks_lock:
                self._load_callbacks.append(on_loaded)
        if self.f3d_process and self.f3d_process.poll() is None:
            try:
                self.f3d_process.stdin.write(f"{fbx_path}\n")
                self.f3d_process.stdin.flush()
            except Exception as e:
                print(f"Failed to send mesh to F3D viewer: {e}")
                self._notify_loaded(False, 0)
        else:
            self._notify_loaded(False, 0)

    def cleanup(self):
        if self.f3d_process and self.f3d_process.poll() is None:
            try:
                self.f3d_process.stdin.write("STOP\\n")
                self.f3d_process.stdin.flush()
                self.f3d_process.wait(timeout=1)
            except:
                self.f3d_process.terminate()


class F3dThumbnailWorker:
    """Persistent F3D thumbnail subprocess with crash isolation."""

    def __init__(self, timeout=120):
        self.timeout = timeout
        self.process = None
        self.responses = None
        self.lock = threading.Lock()

    def _start(self):
        project_root = Path(__file__).resolve().parents[3]
        args = [
            sys.executable,
            str(project_root / "main.py"),
            "--f3d-thumbnail-worker",
        ]
        self.responses = queue.Queue()
        self.process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=project_root,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        def read_stdout(process, responses):
            try:
                for line in iter(process.stdout.readline, ""):
                    if not line.startswith(THUMBNAIL_RESULT_PREFIX):
                        continue
                    try:
                        payload = json.loads(line[len(THUMBNAIL_RESULT_PREFIX) :])
                        responses.put(bool(payload.get("success")))
                    except (TypeError, ValueError):
                        responses.put(False)
            finally:
                responses.put(None)

        def read_stderr(process):
            try:
                for line in iter(process.stderr.readline, ""):
                    if line:
                        print(f"[F3D-THUMBNAIL] {line.strip()}", flush=True)
            except (AttributeError, OSError, ValueError):
                pass

        threading.Thread(
            target=read_stdout,
            args=(self.process, self.responses),
            daemon=True,
        ).start()
        threading.Thread(
            target=read_stderr,
            args=(self.process,),
            daemon=True,
        ).start()

    def _ensure_running(self):
        if self.process is None or self.process.poll() is not None:
            self.close()
            self._start()

    def generate(self, model_path, output_path):
        with self.lock:
            self._ensure_running()
            request = json.dumps(
                {
                    "model_path": os.fspath(model_path),
                    "output_path": os.fspath(output_path),
                }
            )
            try:
                self.process.stdin.write(request + "\n")
                self.process.stdin.flush()
                result = self.responses.get(timeout=self.timeout)
            except (AttributeError, BrokenPipeError, OSError, queue.Empty):
                self.close()
                return False

            if result is None:
                self.close()
                return False
            return result

    def close(self):
        process = self.process
        self.process = None
        self.responses = None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.stdin.write("STOP\n")
                process.stdin.flush()
                process.wait(timeout=2)
        except (AttributeError, BrokenPipeError, OSError, subprocess.TimeoutExpired):
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    stream.close()
                except (AttributeError, OSError, ValueError):
                    pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
