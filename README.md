# Uma Exporter

English | [简体中文](README.zh-CN.md)

Uma Exporter is a desktop tool for browsing, inspecting, previewing, and exporting assets from *Uma Musume Pretty Derby* game data. It combines a responsive Dear PyGui interface, direct Unity asset inspection with UnityPy, and external export/preview helpers for more complex 3D content.

## Highlights

- Fast asset search backed by the game's `meta` database
- Logical-path browsing with physical hash lookup
- Unity object inspection for textures, meshes, animators, and more
- Real-time texture preview inside the app
- External 3D preview through `f3d`
- Forward and reverse dependency navigation
- Export support for textures, text assets, audio, meshes, and animator-driven assets
- English and Chinese UI support
- Support for encrypted and unencrypted databases/bundles

## Tech Stack

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) for environment and dependency management
- [Dear PyGui](https://github.com/hoffstadt/DearPyGui) for the desktop UI
- [UnityPy](https://github.com/K00L4ID/UnityPy) for Unity asset parsing
- [f3d](https://f3d.app/) for external 3D preview
- AssetStudioModCLI binaries in `as_cli/` for complex exports
- SQLite / SQLite3MC via `sqlite3` and `apsw-sqlite3mc`

## Features

### Asset Browsing

- Search by logical asset path
- Browse scene-oriented and prop-oriented views
- Jump between assets using navigation history

### Inspection

- View logical path, storage hash, file size, and physical location
- List Unity internal objects stored inside a bundle
- Inspect dependency relationships in both directions

### Preview

- Preview `Texture2D` assets directly in the UI
- Export temporary mesh/FBX data and preview it in a dedicated `f3d` process
- Drag assets for quick hover-based inspection workflows

### Export

- Export common Unity objects such as textures, text assets, audio, and meshes
- Use AssetStudioModCLI for animator/model-oriented exports when needed
- Export complex assets together with their dependency context

## Requirements

Before running the app, make sure you have:

- Python `3.14` or newer
- `uv` installed
- A valid *Uma Musume* data directory containing both `meta/` and `dat/`
- AssetStudioModCLI placed in `as_cli/`

The repository already expects the CLI tools to be available at paths like:

- `as_cli/AssetStudioModCLI`
- native libraries shipped alongside it in `as_cli/`

## Quick Start

### 1. Install dependencies

```bash
uv sync
```

### 2. Launch the application

```bash
uv run main.py
```

### 3. Configure your game data path

On first launch, open the **Settings** tab and set the root folder that contains:

- `meta`
- `dat`

Then choose the data region:

- `jp`
- `global`

Apply the settings to reload the database.

## Configuration

The app stores runtime settings in `config.json`.

Typical fields:

```json
{
  "base_path": "/path/to/umamusume/data",
  "language": "Auto",
  "region": "jp"
}
```

Notes:

- `base_path` must point to a directory containing both `meta/` and `dat/`
- `language` supports `Auto`, `English`, and `Chinese`
- `region` supports `jp` and `global`

## Project Structure

```text
.
├── main.py
├── as_cli/
├── src/
│   ├── constants.py
│   ├── database.py
│   ├── decryptor.py
│   ├── unity_logic.py
│   └── ui/
│       ├── i18n.py
│       ├── main_window.py
│       └── controllers/
├── pyproject.toml
└── config.json
```

## Architecture Overview

### UI Layer

`src/ui/main_window.py` contains `UmaExporterApp`, the main Dear PyGui controller. It manages:

- the application event loop
- navigation state and selection state
- background tasks via `ThreadPoolExecutor`
- UI-safe callbacks through a task queue
- the external `f3d` preview process

### Data Layer

`src/database.py` provides `UmaDatabase`, which:

- opens the game's `meta` database in read-only mode
- falls back to encrypted database handling when needed
- builds in-memory forward and reverse dependency maps
- resolves bundle hashes and decryption keys

### Unity / Export Layer

`src/unity_logic.py` handles:

- loading and decrypting bundles
- extracting Unity object metadata
- generating texture preview data
- exporting meshes and animator assets
- delegating complex exports to AssetStudioModCLI

## Development Notes

- Do not update Dear PyGui widgets from worker threads directly
- Queue UI updates and let the main thread apply them
- The `f3d` preview process should be cleaned up on exit
- Use logical names for display and physical hashes for data operations

## Packaging

The repository includes build-related files such as:

- `UmaExporter.spec`
- `setup.py`
- `justfile`

These can be adapted for local packaging workflows, but the main development path is running the app with `uv`.

## Troubleshooting

### Database not ready

Check that your configured path contains both `meta/` and `dat/`.

### No Unity objects found

Some entries may refer to bundles that are not present locally or could not be decrypted.

### 3D preview does not open

Check that:

- `f3d` is installed correctly in the environment
- AssetStudioModCLI binaries in `as_cli/` are executable
- the selected asset actually contains mesh or animator data

## Disclaimer

This project is a third-party tool intended for inspection and export workflows. Please make sure your usage complies with applicable laws, platform rules, and the game's terms of service.
