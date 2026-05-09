#!/usr/bin/env python3
import base64
import sys
from pathlib import Path

import requests


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "minicpm-v"

PROMPT = """
Perform OCR extraction on this handwritten note.

Rules:
- Extract text as literally as possible.
- Preserve line breaks and structure.
- Do NOT summarize.
- Do NOT interpret.
- Do NOT rewrite.
- Do NOT infer missing words.
- If text is unclear, write [unclear].
- Preserve technical terms exactly.
- Preserve arrows, bullets, indentation, and labels.
- Output Markdown only.
""".strip()


def encode_image(path):
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def extract_note(image_path):
    image_b64 = encode_image(image_path)

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT,
                    "images": [image_b64],
                }
            ],
            "options": {
                "temperature": 0.0,
            },
        },
        timeout=600,
    )

    response.raise_for_status()
    return response.json()["message"]["content"].strip()


def main():
    if len(sys.argv) < 2:
        print("Usage: python image_to_note.py notes.jpg")
        sys.exit(1)

    image_path = Path(sys.argv[1])

    if not image_path.exists():
        print(f"File not found: {image_path}")
        sys.exit(1)

    print(f"[1/2] Processing image: {image_path}", flush=True)

    note = extract_note(image_path)

    out_path = image_path.with_suffix(".note.md")
    out_path.write_text(note + "\n")

    print(f"[2/2] Wrote {out_path}", flush=True)
    print(note)


if __name__ == "__main__":
    main()
