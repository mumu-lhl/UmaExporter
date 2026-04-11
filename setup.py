from setuptools import setup, Extension
from Cython.Build import cythonize

extensions = [
    Extension(
        "uma_decryptor",
        ["src/core/uma_decryptor.pyx"],
    )
]

setup(
    name="uma_decryptor",
    ext_modules=cythonize(extensions, language_level="3"),
)
