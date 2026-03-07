import shutil
import sys
from pathlib import Path

def copy_dir(src, dst):
    src = Path(src)
    dst = Path(dst)
    
    if not src.exists():
        print(f"Source {src} does not exist")
        sys.exit(1)
        
    # Ensure parent of destination exists
    dst.parent.mkdir(parents=True, exist_ok=True)
    
    if src.is_dir():
        if dst.exists() and not dst.is_dir():
            print(f"Destination {dst} exists and is not a directory")
            sys.exit(1)
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python copy_dir.py <src> <dst>")
        sys.exit(1)
    copy_dir(sys.argv[1], sys.argv[2])
