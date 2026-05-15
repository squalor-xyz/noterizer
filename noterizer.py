#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import requests

from run_whisperx import build_command
from summarize_transcript import build_prompt, load_transcript

from noterizer_core import (
    available_profiles,
    default_child_dir,
    embed_text,
    ensure_dir,
    ensure_exists,
    extract_note,
    format_context_item,
    generate_text,
    get_collection,
    index_markdown_file,
    index_transcript_file,
    load_profile,
    note_markdown_path,
    resolve_db_path,
    summary_markdown_path,
    transcript_json_path,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Unified CLI for audio transcription, summarization, indexing, image OCR, and query."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audio_parser = subparsers.add_parser(
        "audio",
        help="Transcribe audio, summarize it, and optionally index transcript and summary data.",
    )
    audio_parser.add_argument("audio_file", help="Path to the audio file.")
    audio_parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    audio_parser.add_argument("--transcripts-dir", help="Directory for WhisperX outputs.")
    audio_parser.add_argument("--summaries-dir", help="Directory for markdown summaries.")
    audio_parser.add_argument(
        "--transcript-output",
        choices=["json", "all"],
        default=None,
        help="WhisperX output format. Defaults to the active profile.",
    )
    audio_parser.add_argument(
        "--index",
        choices=["none", "transcript", "summary", "both"],
        default=None,
        help="What to index after processing. Defaults to the active profile.",
    )
    audio_parser.add_argument("--db-path", help="Override the database path.")

    image_parser = subparsers.add_parser(
        "image",
        help="OCR an image into markdown and optionally index it.",
    )
    image_parser.add_argument("image_file", help="Path to the image file.")
    image_parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    image_parser.add_argument("--notes-dir", help="Directory for OCR markdown notes.")
    image_parser.add_argument("--no-index", action="store_true", help="Skip indexing the OCR output.")
    image_parser.add_argument("--db-path", help="Override the database path.")

    query_parser = subparsers.add_parser(
        "query",
        help="Query indexed transcript, summary, and image-note content together.",
    )
    query_parser.add_argument("question", help="Question to ask over indexed data.")
    query_parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    query_parser.add_argument(
        "--type",
        choices=["any", "transcript", "summary", "image_note"],
        default=None,
        help="Restrict retrieval to one content type.",
    )
    query_parser.add_argument("--results", type=int, default=None, help="Number of retrieval results.")
    query_parser.add_argument("--db-path", help="Override the database path.")

    profiles_parser = subparsers.add_parser(
        "profiles",
        help="List bundled profile names.",
    )
    profiles_parser.add_argument("--verbose", action="store_true", help="Show profile paths.")

    return parser.parse_args()


def run_command(command):
    import shlex
    import subprocess

    print("Running:")
    print(" ".join(shlex.quote(part) for part in command), flush=True)
    result = subprocess.run(command)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}")


def write_summary(transcript_path, output_path, profile):
    print("[summary] Loading transcript...", flush=True)
    transcript = load_transcript(transcript_path)

    if not transcript.strip():
        raise ValueError("Transcript contains no usable text.")

    prompt = build_prompt(transcript)
    print("[summary] Generating summary...", flush=True)
    summary = generate_text(prompt, profile["summary_backend"])
    output_path.write_text(summary + "\n")
    print(f"[summary] Wrote {output_path}", flush=True)


def query_collection(args, profile):
    collection = get_collection(
        resolve_db_path(profile, args.db_path),
        profile["database"]["collection"],
    )
    query_type = args.type or profile["query"]["type"]
    result_count = args.results or profile["query"]["results"]
    where = None if query_type == "any" else {"content_type": query_type}

    results = collection.query(
        query_embeddings=[embed_text(args.question, profile["embedding_backend"])],
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

    print(generate_text(prompt, profile["query_backend"]))
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
        resolve_db_path(profile, args.db_path),
        profile["database"]["collection"],
    )

    if index_mode in {"transcript", "both"}:
        index_transcript_file(collection, transcript_path, profile["embedding_backend"])

    if index_mode in {"summary", "both"}:
        index_markdown_file(collection, summary_path, "summary", profile["embedding_backend"])

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
    note = extract_note(image_path, profile["vision_backend"])

    note_path = note_markdown_path(image_path, notes_dir)
    note_path.write_text(note + "\n")
    print(f"[image] Wrote {note_path}", flush=True)

    if args.no_index or not profile["image"]["index"]:
        return 0

    collection = get_collection(
        resolve_db_path(profile, args.db_path),
        profile["database"]["collection"],
    )
    index_markdown_file(collection, note_path, "image_note", profile["embedding_backend"])
    return 0


def list_profiles(verbose):
    profiles = available_profiles()
    if not profiles:
        print("No bundled profiles found.")
        return 1

    for name in profiles:
        if verbose:
            profile = load_profile(name)
            print(f"{name}\t{profile['_profile_path']}")
        else:
            print(name)

    return 0


def main():
    args = parse_args()

    try:
        if args.command == "profiles":
            return list_profiles(args.verbose)

        profile = load_profile(args.profile)

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
