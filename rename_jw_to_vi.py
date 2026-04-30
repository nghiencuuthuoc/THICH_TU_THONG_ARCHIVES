from pathlib import Path
import sys

def rename_jw_to_vi(root_dir: str = ".") -> None:
    root = Path(root_dir).resolve()
    count = 0

    for path in root.rglob("*"):
        if path.is_file() and ".jw." in path.name:
            new_name = path.name.replace(".jw.", ".vi.")
            new_path = path.with_name(new_name)

            if new_path.exists():
                print(f"SKIP (exists): {new_path}")
                continue

            path.rename(new_path)
            print(f"RENAMED: {path} -> {new_path}")
            count += 1

    print(f"\nDone. Total renamed: {count}")

if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    rename_jw_to_vi(target_dir)