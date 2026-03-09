import os
import sys

def launch_f3d_viewer_stdin():
    """Worker function for f3d viewer that reads paths from stdin.

    This avoids multiprocessing issues in compiled environments.
    """
    try:
        import f3d
    except ImportError:
        print("[F3D] Error: f3d module not found.")
        return

    current_mesh = None
    try:
        eng = f3d.Engine.create()
        scene = eng.scene
        interactor = eng.interactor
        window = eng.window

        eng.options.update({
            "model.scivis.cells": True,
            "model.scivis.enable": True,
            "model.scivis.array_name": "Colors",
            "model.scivis.component": 0,
            "ui.axis": True,
            "render.grid.enable": True,
            "render.light.intensity": 2.5,
            "render.hdri.ambient": True,
            "render.effect.tone_mapping": True,
        })

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
            # Use a small delay or ensure it's called after loading
            try:
                import time
                time.sleep(0.1) # Small delay to ensure model is processed
                interactor.trigger_command("set_camera isometric")
            except Exception as e:
                print(f"[F3D] Warning: Could not set isometric view: {e}")

            window.render()
            print(f"[F3D] Loaded: {path}")

        def timer_callback(t=None):
            # Non-blocking check for new paths from stdin
            # We use a simple protocol: one path per line
            import select
            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()
                if not line or line.strip() == "STOP":
                    return False
                update_scene(line)
            return True

        # Initial wait for first mesh
        line = sys.stdin.readline()
        if not line or line.strip() == "STOP":
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
