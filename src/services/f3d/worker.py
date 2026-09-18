import os
import sys
import json


THUMBNAIL_RESULT_PREFIX = "F3D_THUMBNAIL_RESULT "


def _worker_log(message):
    """Write worker diagnostics without crashing on invalid windowed handles."""
    seen = set()
    for stream in (sys.stdout, sys.stderr):
        if stream is None or id(stream) in seen:
            continue
        seen.add(id(stream))
        try:
            print(message, file=stream, flush=True)
            return
        except (AttributeError, OSError, ValueError):
            continue


def generate_thumbnail(model_path, output_path, engine=None):
    """Generates a thumbnail image for a 3D model using f3d.

    If engine is provided, it reuses it for faster performance.
    """
    try:
        if engine is None:
            import f3d

            # Create engine in offscreen (headless) mode
            engine = f3d.Engine.create(offscreen=True)

        scene = engine.scene
        window = engine.window

        # Configure options for better look
        engine.options.update(
            {
                "render.light.intensity": 2.5,
                "render.hdri.ambient": True,
                "render.effect.tone_mapping": True,
                "ui.axis": False,
                "render.background.color": [0.1, 0.1, 0.1],  # Dark grey
            }
        )

        scene.clear()
        scene.add(model_path)

        # Access camera from window
        cam = window.camera
        cam.reset_to_bounds()
        cam.azimuth(45)
        cam.elevation(30)

        window.render()
        img = window.render_to_image()
        img.save(output_path)

        return True
    except Exception as e:
        print(f"[F3D] Thumbnail generation error: {e}")
        return False


def launch_f3d_thumbnail_worker_stdin():
    """Render thumbnail requests in a process isolated from the GUI."""
    engine = None
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "STOP":
            break

        success = False
        try:
            request = json.loads(line)
            if engine is None:
                import f3d

                engine = f3d.Engine.create(offscreen=True)
            success = generate_thumbnail(
                request["model_path"], request["output_path"], engine=engine
            )
        except Exception as error:
            _worker_log(f"[F3D] Thumbnail worker error: {error}")

        print(
            THUMBNAIL_RESULT_PREFIX + json.dumps({"success": bool(success)}),
            flush=True,
        )


def launch_f3d_viewer_stdin():
    """Worker function for f3d viewer that reads paths from stdin.

    This avoids multiprocessing issues in compiled environments.
    """
    try:
        import f3d
    except ImportError:
        _worker_log("[F3D] Error: f3d module not found.")
        return

    import threading
    import queue

    input_queue = queue.Queue()

    def stdin_reader():
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            input_queue.put(line.strip())
            if line.strip() == "STOP":
                break

    # Start the background thread for stdin
    reader_thread = threading.Thread(target=stdin_reader, daemon=True)
    reader_thread.start()

    current_mesh = None
    try:
        eng = f3d.Engine.create()
        scene = eng.scene
        interactor = eng.interactor
        window = eng.window

        eng.options.update(
            {
                "ui.axis": True,
                "render.grid.enable": True,
                "render.light.intensity": 3.5,
                "render.hdri.ambient": True,
                "render.effect.tone_mapping": True,
                "render.background.color": [0.22, 0.22, 0.25],
            }
        )

        try:
            window.set_window_name("UmaExporter - 3D Viewer (Press ESC or Q to Exit)")
            for key_name in ["Escape", "q", "Q"]:
                try:
                    b = f3d.InteractionBind(
                        f3d.InteractionBind.ModifierKeys.NONE, key_name
                    )
                    try:
                        interactor.remove_binding(b)
                    except Exception:
                        pass
                    interactor.add_binding(b, "stop_interactor", "General")
                except Exception:
                    pass
        except Exception as e:
            _worker_log(
                f"[F3D] Warning: Could not configure window title or exit bindings: {e}"
            )

        def update_scene(path):
            nonlocal current_mesh
            path = path.strip()
            if not path:
                return

            paths = [
                p.strip()
                for p in path.split(";")
                if p.strip() and os.path.exists(p.strip())
            ]
            if not paths:
                return

            current_mesh = paths[0] if len(paths) == 1 else None
            scene.clear()
            loaded_count = 0
            for p in paths:
                try:
                    scene.add(p)
                    loaded_count += 1
                except Exception as ex:
                    _worker_log(f"[F3D] Warning: Failed to add {p}: {ex}")

            if loaded_count == 0:
                _worker_log("[F3D] Warning: No valid models could be added to scene.")
                return

            try:
                cam = window.camera
                cam.reset_to_bounds()
                cam.azimuth(25)
                cam.elevation(15)
            except Exception as e:
                _worker_log(f"[F3D] Warning: Could not adjust camera: {e}")

            window.render()
            _worker_log(f"[F3D] Loaded {loaded_count} model(s): {path}")

        def timer_callback(t=None):
            # Check if parent process / stdin reader is still alive
            try:
                if not reader_thread.is_alive():
                    interactor.stop()
                    return
                while not input_queue.empty():
                    line = input_queue.get_nowait()
                    if line == "STOP":
                        interactor.stop()
                        return
                    update_scene(line)
            except Exception:
                pass

        # Initial wait for first mesh (loop until receiving mesh or stdin closed/STOP)
        line = None
        while True:
            try:
                line = input_queue.get(timeout=0.5)
                if not line or line == "STOP":
                    return
                break
            except queue.Empty:
                if not reader_thread.is_alive():
                    return

        update_scene(line)
        interactor.start(0.1, timer_callback)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback

        _worker_log(f"F3D Viewer Error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        if current_mesh and os.path.exists(current_mesh):
            try:
                os.remove(current_mesh)
            except:
                pass
        _worker_log("[F3D] Viewer exiting.")
