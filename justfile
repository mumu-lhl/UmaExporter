# Set cross-platform variables
os-name := os()
nuitka-win-flags := if os-name == "windows" { "--clang" } else { "" }
nuitka-upx-flag := if os-name == "macos" { "" } else { "--enable-plugin=upx" }
data-sep := if os-name == "windows" { ";" } else { ":" }
cli-bin := if os-name == "windows" { "as_cli/AssetStudioModCLI.exe" } else { "as_cli/AssetStudioModCLI" }
cp-cmd := "uv run scripts/copy_dir.py"
archspec-path := `uv run python -c "import archspec, os; print(os.path.dirname(archspec.__file__))"`

# Install/Update Asset Studio CLI using uv
as-cli-setup:
    uv run python scripts/setup_as_cli.py

# Internal check for Asset Studio CLI: run setup if directory is missing or empty
check-as-cli:
    @uv run python -c "import os, sys; d='as_cli'; sys.exit(0 if os.path.exists(d) and os.listdir(d) else 1)" || just as-cli-setup

# Build Cython extension using uv environment (skip if exists)
build-cython:
    @uv run python -c "import glob, os; exit(0 if glob.glob('src/uma_decryptor*.so') or glob.glob('src/uma_decryptor*.pyd') else 1)" || uv run python setup.py build_ext --inplace

# Package the application using PyInstaller via uv
package: build-cython check-as-cli
    @echo "Packaging with PyInstaller..."
    uv run --with pyinstaller pyinstaller --noconfirm UmaExporter.spec
    @echo "Placing as_cli next to the binary..."
    {{cp-cmd}} as_cli dist/UmaExporter/as_cli
    {{cp-cmd}} README.md dist/UmaExporter/使用说明.txt
    @echo "Build complete! Check the 'dist/UmaExporter' directory."

# Debug package using Nuitka (FASTEST)
debug-nuitka: build-cython check-as-cli
    @echo "Packaging with Nuitka (DEBUG/FAST)..."
    uv run nuitka \
        --standalone \
        --show-progress \
        --clang \
        --follow-imports \
        --assume-yes-for-downloads \
        --output-filename=UmaExporter \
        --no-deployment-flag=self-execution \
        --lto=no \
        --include-package-data=dearpygui \
        --include-package-data=f3d \
        --include-package-data=UnityPy \
        --include-package-data=fmod_toolkit \
        --include-data-dir="{{archspec-path}}/json"=ar \
        --output-dir=dist-debug \
        --no-pyi-file \
        --include-package=dearpygui \
        --include-package=f3d \
        --include-package=UnityPy \
        --include-package=fmod_toolkit \
        --include-package=archspec \
        --include-package=astc_encoder \
        --include-package=texture2ddecoder \
        --include-package=etcpak \
        --include-package=pyfmodex \
        --include-package=PIL \
        --include-package=numpy \
        --include-package=apsw \
        --include-module=src.uma_decryptor \
        --nofollow-import-to=tkinter \
        --nofollow-import-to=matplotlib \
        --nofollow-import-to=unittest \
        {{nuitka-win-flags}} \
        main.py
    @echo "Placing as_cli next to the binary..."
    {{cp-cmd}} as_cli dist-debug/main.dist/as_cli
    @echo "Debug build complete! Run: ./dist-debug/main.dist/UmaExporter"

# Package the application using Nuitka via uv
package-nuitka: build-cython check-as-cli
    @echo "Packaging with Nuitka..."
    uv run nuitka \
        --standalone \
        --show-progress \
        --follow-imports \
        --assume-yes-for-downloads \
        --output-filename=UmaExporter \
        --no-deployment-flag=self-execution \
        {{nuitka-upx-flag}} \
        --include-package-data=dearpygui \
        --include-package-data=f3d \
        --include-package-data=UnityPy \
        --include-package-data=fmod_toolkit \
        --include-data-dir="{{archspec-path}}/json"=ar \
        --output-dir=dist-nuitka \
        --no-pyi-file \
        --include-package=dearpygui \
        --include-package=f3d \
        --include-package=UnityPy \
        --include-package=fmod_toolkit \
        --include-package=archspec \
        --include-package=astc_encoder \
        --include-package=texture2ddecoder \
        --include-package=etcpak \
        --include-package=pyfmodex \
        --include-package=ctypes \
        --include-module=ctypes._layout \
        --include-package=PIL \
        --include-package=numpy \
        --include-package=apsw \
        --include-module=src.uma_decryptor \
        --windows-disable-console \
        --nofollow-import-to=tkinter \
        --nofollow-import-to=matplotlib \
        --nofollow-import-to=unittest \
        {{nuitka-win-flags}} \
        main.py
    @echo "Placing as_cli next to the binary..."
    {{cp-cmd}} as_cli dist-nuitka/main.dist/as_cli
    {{cp-cmd}} README.md dist-nuitka/main.dist/使用说明.txt
    @echo "Build complete! Check the 'dist-nuitka/main.dist' directory."


# Run Asset Studio CLI
as-cli *args:
    {{cli-bin}} {{args}}
