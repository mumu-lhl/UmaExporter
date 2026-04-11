# Uma Exporter - Project Context

A high-performance desktop application built with Python and Dear PyGui for exploring, inspecting, and exporting assets from "Uma Musume Pretty Derby" game data.

## Project Overview

- **Purpose**: Provides a professional-grade interface to navigate logical game asset structures, inspect internal Unity objects (Textures, Meshes, Animators), and export them.
- **Main Technologies**:
    - **UI Framework**: [Dear PyGui](https://github.com/hoffstadt/DearPyGui) (GPU-accelerated, immediate-mode UI).
    - **Architecture**: Modular MVC (Model-View-Controller) with Service-based background processing.
    - **Asset Parsing**: [UnityPy](https://github.com/K00L4ID/UnityPy) for metadata/texture extraction; [AssetStudioModCLI](https://github.com/Razmoth/AssetStudioModCLI) for complex 3D/Animation exports.
    - **Performance**: [Cython](https://cython.org/) for critical path decryption (`uma_decryptor.pyx`).
    - **3D Rendering**: [f3d](https://f3d.app/) (Fast and minimalist 3D viewer) running as a managed subprocess.
    - **Runtime**: Python 3.14+ managed by `uv`.

## Architecture

The system follows Clean Architecture principles, organized into three layers:

### 1. Domain Layer (`src/core/`)
Pure business logic, zero UI dependencies.
- **`config.py`**: Application configuration and path resolution.
- **`database.py`**: SQLite-backed `UmaDatabase` for persistent metadata; in-memory bidirectional dependency graph for O(1) asset relationship traversal.
- **`decryptor.py`**: Pythonic wrapper around compiled **Cython extension** (`uma_decryptor.pyx`) for in-place game asset decryption.
- **`unity.py`**: Abstraction layer over `UnityPy` for extracting raw `Texture2D` data and metadata.
- **`i18n.py`**: Internationalization support (English/Chinese).

### 2. Application Services Layer (`src/services/`)
Reusable services independent of UI framework.
- **`f3d/`**: F3D 3D viewer worker (`worker.py`) and process management (`service.py`).
- **`thumbnail/`**: Thumbnail caching (`manager.py`) and async loading (`service.py`).
- **`translation/`**: Character name translation download and caching.

### 3. Presentation Layer (`src/ui/`)
Dear PyGui-based UI using MVC pattern.
- **Root Coordinator (`main_window.py`)**: `UmaExporterApp` initializes the application, manages global state, and orchestrates the main event loop (~570 lines).
- **Controllers (`controllers/`)**: Encapsulate distinct functional logic.
    - `PreviewController`: Asset inspector, texture loading, f3d integration.
    - `SearchController`: Async SQL queries and result filtering.
    - `DragController`: Drag-and-drop interactions (drag-to-preview).
    - `ExportController`: Export logic for assets and characters.
    - `SettingsController`: Settings management and cache operations.
    - `NavigationController`: Back/Forward history navigation.
    - `BatchController`: Batch thumbnail generation.
    - `ShortcutController`: Keyboard shortcuts.
- **UI Services (`services/`)**: DPG-aware wrappers (e.g., `database_service.py` bridges domain DB with UI task queue).
- **Views (`views/`)**: Define UI layout hierarchy, decoupled from logic.

## Key Features

- **Asynchronous Search**: Non-blocking SQL lookups with batched UI updates via `ui_tasks` queue.
- **Interactive Inspector**: Deep inspection of Unity bundles with type-aware context menus.
- **Hybrid 3D Preview**:
    - **Instant 2D**: Native DPG texture viewing.
    - **External 3D**: Seamless integration with `f3d` for viewing Meshes and Animations without bloating the main process.
- **Agent Skills Integration**:
    - The project uses specialized "Skills" (located in `.agents/skills/`) to define complex behaviors like "Scene Auto-Preview" and "Async UI Patterns". These serve as executable documentation and behavior guides.

## Development Conventions

- **Thread Safety**: **Strict Requirement.** DPG contexts are not thread-safe. Background threads (Services) must *never* call DPG functions directly. They must submit callbacks to `app.ui_tasks`, which the main thread drains every frame.
- **Cython Compilation**: Critical modules (`uma_decryptor`) must be compiled. Use `setup.py build_ext --inplace` or rely on the `uv` build environment.
- **Process Management**: Child processes (like f3d) are managed via `subprocess.Popen` with careful `stdin` communication to prevent zombie processes or deadlocks.
- **Asset Identification**: Use `hash` (physical filename) for backend operations and `name` (logical path) for UI presentation.

## Building and Running

- **Run Application**:
  ```bash
  uv run main.py
  ```
- **Setup**:
  1. Ensure `as_cli/ASExport` is present.
  2. Run `uv sync` to install dependencies.
  3. Ensure Cython modules are built (handled by `setup.py` if installing as package, or build manually for dev).
