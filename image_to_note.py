#!/usr/bin/env python3
import argparse
from pathlib import Path

import requests

from noterizer_core import default_child_dir, ensure_dir, extract_note, load_profile, note_markdown_path


def parse_args():
    parser = argparse.ArgumentParser(description="OCR an image into markdown.")
    parser.add_argument("image_file", help="Path to the image file.")
    parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    parser.add_argument("--output", help="Output markdown path.")
    parser.add_argument("--notes-dir", help="Directory for generated notes.")
    return parser.parse_args()


def main():
    args = parse_args()
    image_path = Path(args.image_file).expanduser().resolve()

    if not image_path.exists():
        print(f"File not found: {image_path}")
        return 1

    profile = load_profile(args.profile)

    print(f"[1/2] Processing image: {image_path}", flush=True)

    try:
        note = extract_note(image_path, profile["vision_backend"])
    except requests.RequestException as exc:
        print(f"Error: {exc}")
        return 1

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
    elif args.notes_dir:
        notes_dir = ensure_dir(Path(args.notes_dir).expanduser().resolve())
        out_path = note_markdown_path(image_path, notes_dir)
    else:
        notes_dir = ensure_dir(default_child_dir(image_path, profile["image"]["notes_dirname"]))
        out_path = note_markdown_path(image_path, notes_dir)

    out_path.write_text(note + "\n")

    print(f"[2/2] Wrote {out_path}", flush=True)
    print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
