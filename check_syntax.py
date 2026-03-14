import os
import ast

def check_syntax():
    base_dir = "src/ui"
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as file:
                    try:
                        ast.parse(file.read(), filename=path)
                    except SyntaxError as e:
                        print(f"SyntaxError in {path}: {e}")

if __name__ == "__main__":
    check_syntax()
