# Uma Exporter - Project Context

A high-performance desktop application built with Python and Dear PyGui for exploring, inspecting, and exporting assets from "Uma Musume Pretty Derby" game data.

## Project Overview

- **Purpose**: Provides a professional-grade interface to navigate logical game asset structures, inspect internal Unity objects (Textures, Meshes, Animators), and export them.
- **Main Technologies**:
    - **UI Framework**: [Dear PyGui](https://github.com/hoffstadt/DearPyGui) (GPU-accelerated, immediate-mode UI).
    - **Asset Parsing**: [UnityPy](https://github.com/K00L4ID/UnityPy) for metadata/texture extraction; [AssetStudioModCLI](https://github.com/Razmoth/AssetStudioModCLI) for complex 3D/Animation exports.
    - **3D Rendering**: [f3d](https://f3d.app/) (Fast and minimalist 3D viewer) running as a separate process.
    - **Data Layer**: SQLite (mapping asset names to physical hashes) with an in-memory dependency graph for instant lookups.
    - **Runtime**: Python 3.14+ managed by `uv`.

## Architecture

The system follows a multi-threaded, multi-process architecture to ensure UI responsiveness:

1.  **Presentation Layer (`src/ui/main_window.py`)**:
    - `UmaExporterApp`: The core controller. Manages the DPG event loop, navigation history, and UI state.
    - **Concurrency**: Uses a `ThreadPoolExecutor` for background I/O and a thread-safe `Queue` (`ui_tasks`) to schedule UI updates on the main thread.
    - **3D Preview**: Spawns a dedicated `multiprocessing.Process` to run `f3d`, preventing rendering overhead from blocking the main UI.

2.  **Logic Layer (`src/unity_logic.py`)**:
    - `UnityLogic`: Handles bridge logic. It extracts `Texture2D` directly for live preview and delegates complex FBX/Animator exports to the `as_cli/` binaries.
    - Converts raw texture data to `numpy` arrays for high-speed Dear PyGui texture registry updates.

3.  **Data Layer (`src/database.py` & `src/constants.py`)**:
    - `UmaDatabase`: Indexes the game's `meta` database. Builds a bidirectional dependency map (Forward/Reverse) during initialization for O(1) navigation between related assets.
    - `Config`: Manages path resolution for game data and CLI tools.

## Key Features

- **Asynchronous Search**: Fast SQL-based lookup with live-updating results via the task queue.
- **Interactive Inspector**: Lists all internal Unity objects within a bundle with type-specific actions.
- **Hybrid 3D Preview**: 
    - Real-time 2D texture previews in DPG.
    - One-click 3D preview in an external `f3d` window for Meshes/Models.
- **Advanced UX (Skills)**:
    - **Drag-to-Inspect**: Drag an asset to hover over other UI elements to trigger auto-previews.
    - **Middle-Mouse Navigation**: Fluid canvas-style scrolling and interaction.
- **Deep Export**: Supports exporting logical assets and their entire dependency tree (e.g., character models with textures and animations) using specialized CLI tools.

## Development Conventions

- **Thread Safety**: **Crucial.** Never modify DPG items directly from a background thread. Always push a callback to `self.ui_tasks` and let `_drain_ui_tasks` handle it in the main loop.
- **Process Management**: The `f3d` viewer process must be monitored and cleaned up on application exit to avoid orphaned windows.
- **CLI Integration**: AssetStudio operations are non-blocking. Use temporary directories for intermediate files and clean up after successful export/preview.
- **Asset Identification**: Use the physical `hash` (physical path) for data operations and the `name` (logical path) for UI display.

## Building and Running

The project utilizes `uv` for modern, reproducible dependency management.

- **Run Application**:
  ```bash
  uv run main.py
  ```
- **Setup**:
  1. Ensure `as_cli/ASExport` (AssetStudioModCLI) is present and executable.
  2. Run `uv sync` to install all dependencies (including `numpy`, `unitypy`, `dearpygui`, etc.).
  3. Configure game data paths in `config.json` (auto-generated on first run).
