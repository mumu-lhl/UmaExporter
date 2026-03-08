# Set cross-platform variables
os-name := os()
nuitka-win-flags := if os-name == "windows" { "--clang" } else { "" }
nuitka-upx-flag := if os-name == "windows" { "--enable-plugin=upx" } else { "" }
data-sep := if os-name == "windows" { ";" } else { ":" }
cli-bin := if os-name == "windows" { "as_cli/AssetStudioModCLI.exe" } else { "as_cli/AssetStudioModCLI" }
cp-cmd := "uv run scripts/copy_dir.py"

# Install/Update Asset Studio CLI using uv
as-cli-setup:
    uv run python scripts/setup_as_cli.py

# Internal check for Asset Studio CLI: run setup if directory is missing or empty
check-as-cli:
    @uv run python -c "import os, sys; d='as_cli'; sys.exit(0 if os.path.exists(d) and os.listdir(d) else 1)" || just as-cli-setup

# Build Cython extension using uv environment
build-cython:
    uv run python setup.py build_ext --inplace

# Package the application using PyInstaller via uv
package: build-cython check-as-cli
    @echo "Packaging with PyInstaller..."
    uv run --with pyinstaller pyinstaller --noconfirm UmaExporter.spec
    @echo "Placing as_cli next to the binary..."
    {{cp-cmd}} as_cli dist/UmaExporter/as_cli
    {{cp-cmd}} README.md dist/UmaExporter/使用说明.txt
    @echo "Build complete! Check the 'dist/UmaExporter' directory."

# Package the application using Nuitka via uv
package-nuitka: build-cython check-as-cli
    @echo "Packaging with Nuitka..."
    uv run python -m nuitka \
        --standalone \
        --show-progress \
        --follow-imports \
        --assume-yes-for-downloads \
        --output-filename=UmaExporter \
        --enable-plugin=multiprocessing \
        --no-deployment-flag=self-execution \
        {{nuitka-upx-flag}} \
        --include-package-data=dearpygui \
        --include-package-data=f3d \
        --include-package-data=UnityPy \
        --include-package-data=fmod_toolkit \
        --output-dir=dist-nuitka \
        --no-pyi-file \
        --include-package=dearpygui \
        --include-package=f3d \
        --include-package=UnityPy \
        --include-package=fmod_toolkit \
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
    @if [ "{{os()}}" == "windows" ]; then \
        {{cli-bin}} {{args}}; \
    else \
        {{cli-bin}} {{args}}; \
    fi
