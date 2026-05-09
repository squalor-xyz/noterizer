#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from pathlib import Path

import requests

from run_whisperx import build_command
from summarize_transcript import build_prompt, load_transcript


DEFAULT_PROFILE = {
    "services": {
        "ollama_generate_url": "http://localhost:11434/api/generate",
        "ollama_embeddings_url": "http://localhost:11434/api/embeddings",
        "ollama_chat_url": "http://localhost:11434/api/chat",
    },
    "database": {
        "path": "./noterizer_db",
        "collection": "memory",
    },
    "models": {
        "summary": "qwen2.5:14b",
        "query": "qwen2.5:14b",
        "embedding": "nomic-embed-text",
        "vision": "minicpm-v",
    },
    "audio": {
        "transcripts_dirname": "transcripts",
        "summaries_dirname": "summaries",
        "transcript_output": "json",
        "index": "both",
    },
    "image": {
        "notes_dirname": "notes",
        "index": True,
    },
    "query": {
        "type": "any",
        "results": 10,
    },
}

PROFILES_DIR = Path(__file__).with_name("profiles")

IMAGE_PROMPT = """
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Unified CLI for audio transcription, summarization, indexing, image OCR, and query."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audio_parser = subparsers.add_parser(
        "audio",
        help="Transcribe audio, summarize it, and optionally index transcript/summary data.",
    )
    audio_parser.add_argument("audio_file", help="Path to the audio file.")
    audio_parser.add_argument(
        "--profile",
        default="default",
        help="Profile name from profiles/ or path to a profile JSON file.",
    )
    audio_parser.add_argument(
        "--transcripts-dir",
        help="Directory for WhisperX outputs. Defaults to <audio dir>/transcripts.",
    )
    audio_parser.add_argument(
        "--summaries-dir",
        help="Directory for markdown summaries. Defaults to <audio dir>/summaries.",
    )
    audio_parser.add_argument(
        "--transcript-output",
        choices=["json", "all"],
        default=None,
        help="WhisperX output format. Use 'all' only if you also want extra transcript formats.",
    )
    audio_parser.add_argument(
        "--index",
        choices=["none", "transcript", "summary", "both"],
        default=None,
        help="What to index into the shared database after processing.",
    )
    audio_parser.add_argument(
        "--db-path",
        help="Path to the shared Chroma database.",
    )

    image_parser = subparsers.add_parser(
        "image",
        help="OCR an image into markdown and optionally index it.",
    )
    image_parser.add_argument("image_file", help="Path to the image file.")
    image_parser.add_argument(
        "--profile",
        default="default",
        help="Profile name from profiles/ or path to a profile JSON file.",
    )
    image_parser.add_argument(
        "--notes-dir",
        help="Directory for OCR markdown notes. Defaults to <image dir>/notes.",
    )
    image_parser.add_argument(
        "--no-index",
        action="store_true",
        help="Skip indexing the OCR markdown output.",
    )
    image_parser.add_argument(
        "--db-path",
        help="Path to the shared Chroma database.",
    )

    query_parser = subparsers.add_parser(
        "query",
        help="Query indexed transcript, summary, and image-note content together.",
    )
    query_parser.add_argument("question", help="Question to ask over indexed data.")
    query_parser.add_argument(
        "--profile",
        default="default",
        help="Profile name from profiles/ or path to a profile JSON file.",
    )
    query_parser.add_argument(
        "--type",
        choices=["any", "transcript", "summary", "image_note"],
        default=None,
        help="Restrict retrieval to one content type.",
    )
    query_parser.add_argument(
        "--results",
        type=int,
        default=None,
        help="Number of retrieved chunks to use as context.",
    )
    query_parser.add_argument(
        "--db-path",
        help="Path to the shared Chroma database.",
    )

    return parser.parse_args()


def merge_dicts(base, override):
    merged = dict(base)

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value

    return merged


def resolve_profile_path(profile_value):
    candidate = Path(profile_value).expanduser()

    if candidate.suffix == ".json" or candidate.exists():
        return candidate.resolve()

    return (PROFILES_DIR / f"{profile_value}.json").resolve()


def load_profile(profile_value):
    profile_path = resolve_profile_path(profile_value)

    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    profile_data = json.loads(profile_path.read_text())
    profile = merge_dicts(DEFAULT_PROFILE, profile_data)
    profile["_profile_path"] = str(profile_path)
    return profile


def ensure_exists(path, label):
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def default_child_dir(path, child_name):
    return (path.parent / child_name).resolve()


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcript_json_path(audio_path, transcripts_dir):
    return transcripts_dir / f"{audio_path.stem}.json"


def summary_markdown_path(audio_path, summaries_dir):
    return summaries_dir / f"{audio_path.stem}.summary.md"


def note_markdown_path(image_path, notes_dir):
    return notes_dir / f"{image_path.stem}.note.md"


def run_command(command):
    import subprocess

    print("Running:")
    print(" ".join(command), flush=True)
    result = subprocess.run(command)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}")


def generate_text(prompt, model, url):
    response = requests.post(
        url,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=600,
    )
    response.raise_for_status()
    return response.json()["response"].strip()


def write_summary(transcript_path, output_path, profile):
    print("[summary] Loading transcript...", flush=True)
    transcript = load_transcript(transcript_path)

    if not transcript.strip():
        raise ValueError("Transcript contains no usable text.")

    prompt = build_prompt(transcript)
    print("[summary] Generating summary...", flush=True)
    summary = generate_text(
        prompt,
        profile["models"]["summary"],
        profile["services"]["ollama_generate_url"],
    )
    output_path.write_text(summary + "\n")

    print(f"[summary] Wrote {output_path}", flush=True)


def encode_image(image_path):
    import base64

    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def extract_note(image_path, profile):
    response = requests.post(
        profile["services"]["ollama_chat_url"],
        json={
            "model": profile["models"]["vision"],
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": IMAGE_PROMPT,
                    "images": [encode_image(image_path)],
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


def embed(text):
    raise RuntimeError("embed() requires a profile-aware call path.")


def embed_text(text, profile):
    response = requests.post(
        profile["services"]["ollama_embeddings_url"],
        json={"model": profile["models"]["embedding"], "prompt": text},
        timeout=600,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def get_collection(db_path, collection_name):
    try:
        import chromadb
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "chromadb is not installed. Install it before using indexing or query features."
        ) from exc

    client = chromadb.PersistentClient(path=str(db_path))
    return client.get_or_create_collection(collection_name)


def stable_id(source_path, content_type, key):
    raw = f"{source_path}|{content_type}|{key}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def clear_existing_docs(collection, source_path, content_type):
    try:
        existing = collection.get(
            where={"source_path": source_path, "content_type": content_type},
            include=[],
        )
    except Exception:
        return

    ids = existing.get("ids", [])
    if ids:
        collection.delete(ids=ids)


def chunk_markdown_sections(text):
    sections = []
    current_heading = "Document"
    current_lines = []

    for line in text.splitlines():
        if line.startswith("#"):
            if current_lines:
                body = "\n".join(current_lines).strip()
                if body:
                    sections.append((current_heading, body))
            current_heading = line.lstrip("#").strip() or "Document"
            current_lines = [line]
            continue

        current_lines.append(line)

    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_heading, body))

    return sections


def index_transcript_file(collection, transcript_path, profile):
    data = json.loads(transcript_path.read_text())
    source_path = str(transcript_path.resolve())
    clear_existing_docs(collection, source_path, "transcript")

    ids = []
    documents = []
    metadatas = []

    for idx, seg in enumerate(data.get("segments", [])):
        text = seg.get("text", "").strip()
        if not text:
            continue

        speaker = seg.get("speaker", "UNKNOWN")
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))
        doc = f"{speaker} [{start:.1f}-{end:.1f}]: {text}"

        ids.append(stable_id(source_path, "transcript", str(idx)))
        documents.append(doc)
        metadatas.append(
            {
                "content_type": "transcript",
                "source_name": transcript_path.name,
                "source_path": source_path,
                "speaker": speaker,
                "start": start,
                "end": end,
            }
        )

    if not documents:
        print(f"[index] No transcript segments found in {transcript_path}", flush=True)
        return 0

    embeddings = [embed_text(doc, profile) for doc in documents]
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    print(f"[index] Indexed {len(documents)} transcript chunks from {transcript_path.name}", flush=True)
    return len(documents)


def index_markdown_file(collection, markdown_path, content_type, profile):
    text = markdown_path.read_text().strip()
    source_path = str(markdown_path.resolve())
    clear_existing_docs(collection, source_path, content_type)

    sections = chunk_markdown_sections(text)
    if not sections:
        print(f"[index] No markdown content found in {markdown_path}", flush=True)
        return 0

    ids = []
    documents = []
    metadatas = []

    for idx, (heading, body) in enumerate(sections):
        doc = body
        ids.append(stable_id(source_path, content_type, str(idx)))
        documents.append(doc)
        metadatas.append(
            {
                "content_type": content_type,
                "source_name": markdown_path.name,
                "source_path": source_path,
                "section": heading,
            }
        )

    embeddings = [embed_text(doc, profile) for doc in documents]
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    print(f"[index] Indexed {len(documents)} {content_type} chunks from {markdown_path.name}", flush=True)
    return len(documents)


def format_context_item(doc, meta):
    label = f"Source: {meta['source_name']} | Type: {meta['content_type']}"

    if meta["content_type"] == "transcript":
        label += f" | Time: {meta.get('start', 0):.1f}-{meta.get('end', 0):.1f}"
        speaker = meta.get("speaker")
        if speaker:
            label += f" | Speaker: {speaker}"
    else:
        section = meta.get("section")
        if section:
            label += f" | Section: {section}"

    return f"{label}\n{doc}"


def resolve_db_path(args, profile):
    if args.db_path:
        return Path(args.db_path).expanduser().resolve()

    return Path(profile["database"]["path"]).expanduser().resolve()


def query_collection(args, profile):
    collection = get_collection(
        resolve_db_path(args, profile),
        profile["database"]["collection"],
    )
    query_type = args.type or profile["query"]["type"]
    where = None if query_type == "any" else {"content_type": query_type}
    result_count = args.results or profile["query"]["results"]

    results = collection.query(
        query_embeddings=[embed_text(args.question, profile)],
        n_results=result_count,
        where=where,
    )

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]

    if not docs:
        print("No indexed documents matched the query.")
        return 1

    context = "\n\n".join(format_context_item(doc, meta) for doc, meta in zip(docs, metas))

    prompt = f"""
Answer the question using only the indexed excerpts below.

If the answer is not in the excerpts, say:
"I don't see that in the indexed data."

When useful, cite the source filename and timestamp or section.

Question:
{args.question}

Indexed excerpts:
{context}
""".strip()

    print(generate_text(
        prompt,
        profile["models"]["query"],
        profile["services"]["ollama_generate_url"],
    ))
    return 0


def run_audio_pipeline(args, profile):
    audio_path = Path(args.audio_file).expanduser().resolve()
    ensure_exists(audio_path, "Audio file")

    transcript_output = args.transcript_output or profile["audio"]["transcript_output"]
    index_mode = args.index or profile["audio"]["index"]
    transcripts_dir = ensure_dir(
        Path(args.transcripts_dir).expanduser().resolve()
        if args.transcripts_dir
        else default_child_dir(audio_path, profile["audio"]["transcripts_dirname"])
    )
    summaries_dir = ensure_dir(
        Path(args.summaries_dir).expanduser().resolve()
        if args.summaries_dir
        else default_child_dir(audio_path, profile["audio"]["summaries_dirname"])
    )

    command = build_command(audio_path, transcripts_dir, transcript_output)
    run_command(command)

    transcript_path = transcript_json_path(audio_path, transcripts_dir)
    ensure_exists(transcript_path, "Transcript JSON")

    summary_path = summary_markdown_path(audio_path, summaries_dir)
    write_summary(transcript_path, summary_path, profile)

    if index_mode == "none":
        return 0

    collection = get_collection(
        resolve_db_path(args, profile),
        profile["database"]["collection"],
    )

    if index_mode in {"transcript", "both"}:
        index_transcript_file(collection, transcript_path, profile)

    if index_mode in {"summary", "both"}:
        index_markdown_file(collection, summary_path, "summary", profile)

    return 0


def run_image_pipeline(args, profile):
    image_path = Path(args.image_file).expanduser().resolve()
    ensure_exists(image_path, "Image file")

    notes_dir = ensure_dir(
        Path(args.notes_dir).expanduser().resolve()
        if args.notes_dir
        else default_child_dir(image_path, profile["image"]["notes_dirname"])
    )

    print(f"[image] Processing {image_path}", flush=True)
    note = extract_note(image_path, profile)

    note_path = note_markdown_path(image_path, notes_dir)
    note_path.write_text(note + "\n")
    print(f"[image] Wrote {note_path}", flush=True)

    if args.no_index or not profile["image"]["index"]:
        return 0

    collection = get_collection(
        resolve_db_path(args, profile),
        profile["database"]["collection"],
    )
    index_markdown_file(collection, note_path, "image_note", profile)
    return 0


def main():
    args = parse_args()
    profile = load_profile(args.profile)

    try:
        if args.command == "audio":
            return run_audio_pipeline(args, profile)
        if args.command == "image":
            return run_image_pipeline(args, profile)
        if args.command == "query":
            return query_collection(args, profile)
    except (FileNotFoundError, RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
