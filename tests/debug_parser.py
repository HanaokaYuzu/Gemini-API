import argparse
import io
import os
import reprlib
import sys
from typing import Any
from typing import Optional

import orjson as json

from gemini_webapi.utils.parsing import extract_json_from_response

# Ensure UTF-8 on all platforms
if sys.stdin.encoding != "utf-8":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_path = os.path.join(project_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

MAXSTRING = 123

c_repr = reprlib.Repr(maxstring=MAXSTRING)


def print_tree(data: Any, indent: str = "", path: Optional[list[Any]] = None):
    """
    Detailed tree visualization of JSON data.
    """
    if path is None:
        path = []

    if isinstance(data, list):
        print(f"{indent}[] (length: {len(data)})")
        for i, item in enumerate(data):
            new_path = path + [i]
            print(f"{indent}  path (length: {len(new_path)}): {new_path}")
            print_tree(item, indent + "    ", new_path)
    elif isinstance(data, dict):
        print(f"{indent}{{}} (keys: {len(data)})")
        for key, value in data.items():
            new_path = path + [key]
            print(f"{indent}  ['{key}'] path (length: {len(new_path)}): {new_path}")
            print_tree(value, indent + "    ", new_path)
    elif isinstance(data, str) and (
        data.strip().startswith("[") or data.strip().startswith("{")
    ):
        try:
            parsed = json.loads(data)
            print(f"{indent}string(JSON) ->")
            print_tree(parsed, indent + "  ", path)
        except json.JSONDecodeError:
            val_str = data
            print(f"{indent}value: {c_repr.repr(val_str)} ({type(data).__name__})")
    else:
        val_str = str(data)
        print(f"{indent}value: {c_repr.repr(val_str)} ({type(data).__name__})")


def main():
    parser = argparse.ArgumentParser(description="Analyze Gemini response structure.")
    parser.add_argument("file", help="Path to the response file (e.g., tmp/debug.log)")

    args = parser.parse_args()
    file_path = os.path.abspath(args.file)

    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    print(f"--- Analyzing: {file_path} ---")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        parsed_data = extract_json_from_response(content)

        print(f"Found {len(parsed_data)} frames/objects.")

        separate_frames = "#" * MAXSTRING
        for i, frame in enumerate(parsed_data):
            print(f"\n{separate_frames}")
            print(f"\n[FRAME {i}]")
            print_tree(frame)

    except Exception as e:
        print(f"Error parsing response: {e}")


if __name__ == "__main__":
    main()
