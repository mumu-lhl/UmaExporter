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

The system utilizes a specialized MVC pattern optimized for Dear PyGui's immediate mode paradigm, ensuring responsiveness even during heavy I/O.

### 1. Presentation Layer (MVC)
- **Root Coordinator (`src/ui/main_window.py`)**: `UmaExporterApp` initializes the application, manages global state (navigation history, specialized stores), and orchestrates the main event loop.
- **Controllers (`src/ui/controllers/`)**: Encapsulate distinct functional logic.
    - `PreviewController`: Manages the asset inspector, texture loading, and f3d integration.
    - `SearchController`: Handles asynchronous SQL queries and result filtering.
    - `DragController`: Implements complex drag-and-drop interactions (e.g., drag-to-preview).
    - **Mixin Pattern**: Shared behaviors (like navigation or preview helpers) are composed via Mixins (`preview_mixin.py`).
- **Services (`src/ui/services/`)**: Handle long-running background tasks to keep the main thread free.
    - `ThumbnailService`: Asynchronously loads, resizes, and caches textures using `ThreadPoolExecutor`.
    - `F3dService`: Manages the lifecycle of the external 3D viewer process.
- **Views (`src/ui/views/`)**: Define UI layout and hierarchy, decoupling rendering code from logic.

### 2. Core Logic & Data
- **High-Performance Decryption**:
    - Game assets are decrypted in-place using a compiled **Cython extension** (`src/uma_decryptor.pyx`) to minimize memory overhead and CPU usage.
    - `src/decryptor.py` provides a Pythonic wrapper for the low-level Cython routines.
- **Unity Logic (`src/unity_logic.py`)**: Abstraction layer over `UnityPy` for extracting raw `Texture2D` data and metadata.
- **Thumbnail Manager (`src/thumbnail_manager.py`)**: Global cache for asset thumbnails, preventing redundant processing.
- **Data Layer (`src/database.py`)**:
    - SQLite-backed `UmaDatabase` for persistent metadata.
    - In-memory bidirectional dependency graph for O(1) asset relationship traversal.

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
