import os
import sys


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


def launch_f3d_viewer_stdin():
    """Worker function for f3d viewer that reads paths from stdin.

    This avoids multiprocessing issues in compiled environments.
    """
    try:
        import f3d
    except ImportError:
        print("[F3D] Error: f3d module not found.")
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
                "model.scivis.cells": True,
                "model.scivis.enable": True,
                "model.scivis.array_name": "Colors",
                "model.scivis.component": 0,
                "ui.axis": True,
                "render.grid.enable": True,
                "render.light.intensity": 2.5,
                "render.hdri.ambient": True,
                "render.effect.tone_mapping": True,
            }
        )

        def update_scene(path):
            nonlocal current_mesh
            path = path.strip()
            if not path:
                return
            if current_mesh and os.path.exists(current_mesh):
                try:
                    os.remove(current_mesh)
                except:
                    pass
            current_mesh = path
            scene.clear()
            scene.add(path)

            # Set to Isometric view (similar to pressing '9')
            try:
                import time

                time.sleep(0.1)  # Small delay to ensure model is processed
                interactor.trigger_command("set_camera isometric")
            except Exception as e:
                print(f"[F3D] Warning: Could not set isometric view: {e}")

            window.render()
            print(f"[F3D] Loaded: {path}")

        def timer_callback(t=None):
            # Non-blocking check for new paths from the queue
            try:
                while not input_queue.empty():
                    line = input_queue.get_nowait()
                    if line == "STOP":
                        return False
                    update_scene(line)
            except queue.Empty:
                pass
            return True

        # Initial wait for first mesh (via the queue)
        line = input_queue.get(timeout=30)  # Wait up to 30s for first load
        if not line or line == "STOP":
            return

        update_scene(line)
        interactor.start(0.1, timer_callback)

    except Exception as e:
        print(f"F3D Viewer Error: {e}")
    finally:
        if current_mesh and os.path.exists(current_mesh):
            try:
                os.remove(current_mesh)
            except:
                pass
        print("[F3D] Viewer exiting.")
