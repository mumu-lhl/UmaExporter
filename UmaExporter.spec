# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import glob
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

f3d_datas = collect_data_files('f3d')
f3d_binaries = collect_dynamic_libs('f3d')
f3d_hidden = collect_submodules('f3d')

unitypy_datas = collect_data_files('UnityPy')
unitypy_binaries = collect_dynamic_libs('UnityPy')
unitypy_hidden = collect_submodules('UnityPy')
unitypy_hidden += ['UnityPy.resources', 'UnityPy.helpers.Tpk', 'UnityPy.export']

fmod_datas = collect_data_files('fmod_toolkit')
fmod_binaries = collect_dynamic_libs('fmod_toolkit')
fmod_hidden = collect_submodules('fmod_toolkit')

import archspec
archspec_package_dir = os.path.dirname(archspec.__file__)
archspec_datas = [(archspec_package_dir, 'archspec')]

lz4_binaries = collect_dynamic_libs('lz4')
tex_binaries = collect_dynamic_libs('texture2ddecoder') + collect_dynamic_libs('astc_encoder') + collect_dynamic_libs('etcpak')

extension_files = []
for ext in ['*.so', '*.pyd']:
    for f in glob.glob(os.path.join('src', f'uma_decryptor{ext}')):
        extension_files.append((f, 'src'))
        extension_files.append((f, '.'))

datas = f3d_datas + unitypy_datas + fmod_datas + archspec_datas
binaries = f3d_binaries + unitypy_binaries + lz4_binaries + tex_binaries + fmod_binaries + extension_files
hiddenimports = f3d_hidden + unitypy_hidden + fmod_hidden + ['PIL._imaging', 'PIL._webp', 'PIL._avif', 'PIL._imagingft']

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'unittest', 'lib2to3', 
        'pydoc_data', 'test', 'idlelib'
    ],
    noarchive=False,
    optimize=1,
)

seen_binaries = set()
unique_binaries = []
for name, path, type in a.binaries:
    base_name = os.path.basename(name)
    if base_name == "libf3d.so" and "f3d/lib64" in name:
        unique_binaries.append((name, path, type))
        seen_binaries.add(base_name)
        continue
    if base_name not in seen_binaries:
        unique_binaries.append((name, path, type))
        seen_binaries.add(base_name)

a.binaries = unique_binaries

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='UmaExporter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True, 
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=False,
    upx_exclude=[
        'python314.dll', 
        'python3.dll', 
        'vcruntime140.dll', 
        'vcruntime140_1.dll',
        'msvcp140.dll', 
        'msvcp140_1.dll',
        'msvcp140_2.dll',
        'ucrtbase.dll', 
        'libf3d.dll',
        '_dearpygui.pyd'
    ],
    name='UmaExporter',
)
