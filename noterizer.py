#!/usr/bin/env python3
import argparse
import glob
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter

import requests

from run_whisperx import build_command
from summarize_transcript import build_prompt, generate_summary_markdown, load_transcript, resolve_summary_format

from noterizer_core import (
    add_log_level_arg,
    available_profiles,
    configure_logging,
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
    transcript_srt_path,
    unload_profile_ollama_models,
)

logger = logging.getLogger(__name__)

SOURCE_DATE_RE = re.compile(r"^(?P<stamp>\d{6}|\d{8})_")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Unified CLI for audio transcription, summarization, indexing, image OCR, and query."
    )
    add_log_level_arg(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audio_parser = subparsers.add_parser(
        "audio",
        help="Transcribe audio, summarize it, and optionally index transcript and summary data.",
    )
    audio_parser.add_argument(
        "audio_files",
        nargs="+",
        help="One or more audio file paths or glob patterns.",
    )
    audio_parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    audio_parser.add_argument("--transcripts-dir", help="Directory for WhisperX outputs.")
    audio_parser.add_argument("--summaries-dir", help="Directory for markdown summaries.")
    audio_parser.add_argument(
        "--transcript-output",
        choices=["json", "both", "all"],
        default=None,
        help="WhisperX transcript outputs to keep. Defaults to the active profile.",
    )
    audio_parser.add_argument(
        "--index",
        choices=["none", "transcript", "summary", "both"],
        default=None,
        help="What to index after processing. Defaults to the active profile.",
    )
    audio_parser.add_argument(
        "--overwrite",
        choices=["none", "transcript", "summary", "both"],
        nargs="?",
        const="both",
        default="none",
        help="Overwrite existing outputs. Transcript overwrite also regenerates the summary.",
    )
    audio_parser.add_argument("--db-path", help="Override the database path.")
    audio_parser.add_argument(
        "--summary-format",
        choices=["auto", "meeting", "presentation"],
        default=None,
        help="Summary template to use. Defaults to the active profile, with auto-detection supported.",
    )

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
    query_parser.add_argument("--source", type=int, help="Restrict retrieval to one listed source number.")
    query_parser.add_argument("--source-name", help="Restrict retrieval to one exact source filename.")
    query_parser.add_argument(
        "--date",
        help="Restrict retrieval to sources whose filenames begin with YYMMDD, YYYYMMDD, or YYYY-MM-DD.",
    )
    query_parser.add_argument("--db-path", help="Override the database path.")

    query_list_parser = subparsers.add_parser(
        "query-list",
        help="List indexed sources that can be targeted by query filters.",
    )
    query_list_parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    query_list_parser.add_argument(
        "--type",
        choices=["any", "transcript", "summary", "image_note"],
        default="summary",
        help="Restrict listing to one content type. Defaults to summaries.",
    )
    query_list_parser.add_argument(
        "--date",
        help="Restrict listing to sources whose filenames begin with YYMMDD, YYYYMMDD, or YYYY-MM-DD.",
    )
    query_list_parser.add_argument("--db-path", help="Override the database path.")

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
    started = perf_counter()
    result = subprocess.run(command)
    duration = perf_counter() - started
    logger.info("Command completed in %.2fs: %s", duration, command)
    if result.returncode != 0:
        logger.error("Command failed with exit code %s: %s", result.returncode, command)
        raise RuntimeError(f"Command failed with exit code {result.returncode}")


def expected_transcript_paths(audio_path, transcripts_dir, transcript_output):
    json_path = transcript_json_path(audio_path, transcripts_dir)
    srt_path = transcript_srt_path(audio_path, transcripts_dir)

    if transcript_output == "json":
        return [json_path]
    if transcript_output in {"both", "all"}:
        return [json_path, srt_path]

    raise ValueError(f"Unsupported transcript output: {transcript_output}")


def run_transcription(audio_path, transcripts_dir, transcript_output):
    started = perf_counter()
    if transcript_output == "both":
        for output_type in ("json", "srt"):
            run_command(build_command(audio_path, transcripts_dir, output_type))
        logger.info("Completed transcription outputs in %.2fs: %s", perf_counter() - started, audio_path)
        return

    run_command(build_command(audio_path, transcripts_dir, transcript_output))
    logger.info("Completed transcription in %.2fs: %s", perf_counter() - started, audio_path)


def write_summary(transcript_path, output_path, profile):
    print("[summary] Loading transcript...", flush=True)
    started = perf_counter()
    transcript, transcript_source, transcript_lines = load_transcript(transcript_path)
    logger.info("Loaded transcript for summarization in %.2fs: %s", perf_counter() - started, transcript_path)

    if not transcript.strip():
        raise ValueError("Transcript contains no usable text.")

    if transcript_source == "srt":
        transcript_source_path = transcript_path.with_suffix(".srt")
        logger.info("Using transcript source for summarization: srt (%s)", transcript_source_path)
        print(
            f"[summary] Using transcript source for summarization: srt ({transcript_source_path})",
            flush=True,
        )
    else:
        logger.info("Using transcript source for summarization: json (%s)", transcript_path)
        print(
            f"[summary] Using transcript source for summarization: json ({transcript_path})",
            flush=True,
        )

    requested_format = profile["summary"]["format"]
    template_name, detected = resolve_summary_format(
        requested_format,
        transcript_lines,
        transcript_path,
    )
    logger.info(
        "Using summary format %s (%s)",
        template_name,
        "auto-detected" if detected else "explicit/profile default",
    )
    print(
        f"[summary] Using summary format: {template_name}"
        + (" (auto-detected)" if detected else ""),
        flush=True,
    )

    prompt = build_prompt(transcript, template_name)
    print("[summary] Generating summary...", flush=True)
    started = perf_counter()
    summary, _, _ = generate_summary_markdown(
        transcript,
        profile["summary_backend"],
        requested_format,
        transcript_lines,
        transcript_path,
    )
    logger.info("Generated summary in %.2fs: %s", perf_counter() - started, transcript_path)
    started = perf_counter()
    output_path.write_text(summary + "\n")
    logger.info("Wrote summary file in %.2fs: %s", perf_counter() - started, output_path)
    print(f"[summary] Wrote {output_path}", flush=True)


def query_collection(args, profile):
    started = perf_counter()
    collection = get_collection(
        resolve_db_path(profile, args.db_path),
        profile["database"]["collection"],
    )
    query_type = args.type or profile["query"]["type"]
    sources = list_indexed_sources(collection, query_type, getattr(args, "date", None))
    selected_source = resolve_selected_source(args, sources)
    result_count = args.results or profile["query"]["results"]
    if (args.date or args.source or args.source_name) and not sources:
        print("No indexed sources matched the current query filters.")
        return 1

    source_scope = [selected_source] if selected_source else (sources if args.date else None)
    where = build_query_where(query_type, source_scope)

    embed_started = perf_counter()
    query_embedding = embed_text(args.question, profile["embedding_backend"])
    logger.info("Computed query embedding in %.2fs", perf_counter() - embed_started)

    retrieval_started = perf_counter()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=result_count,
        where=where,
    )
    logger.info(
        "Retrieved query candidates in %.2fs (%s sources in scope)",
        perf_counter() - retrieval_started,
        len(source_scope) if source_scope is not None else "all",
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

    answer_started = perf_counter()
    print(generate_text(prompt, profile["query_backend"]))
    logger.info(
        "Generated final query answer in %.2fs (total query time %.2fs)",
        perf_counter() - answer_started,
        perf_counter() - started,
    )
    return 0


def normalize_source_date(value):
    if not value:
        return None

    value = value.strip()

    for fmt in ("%Y-%m-%d", "%Y%m%d", "%y%m%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(
        "Date filter must be in YYYY-MM-DD, YYYYMMDD, or YYMMDD format."
    )


def infer_source_date(source_name):
    match = SOURCE_DATE_RE.match(source_name)
    if not match:
        return None

    stamp = match.group("stamp")
    fmt = "%y%m%d" if len(stamp) == 6 else "%Y%m%d"
    try:
        return datetime.strptime(stamp, fmt).strftime("%Y-%m-%d")
    except ValueError:
        return None


def matches_date_filter(source_name, normalized_date):
    if not normalized_date:
        return True
    return infer_source_date(source_name) == normalized_date


def dedupe_sources(metadatas):
    sources = {}

    for meta in metadatas:
        source_path = meta.get("source_path")
        source_name = meta.get("source_name")
        content_type = meta.get("content_type")
        if not source_path or not source_name or not content_type:
            continue

        key = (source_path, content_type)
        if key in sources:
            continue

        sources[key] = {
            "source_path": source_path,
            "source_name": source_name,
            "content_type": content_type,
            "source_date": infer_source_date(source_name),
        }

    return list(sources.values())


def source_sort_key(source):
    return (
        source.get("source_date") or "0000-00-00",
        source["source_name"],
        source["content_type"],
    )


def list_indexed_sources(collection, query_type, date_filter=None):
    normalized_date = normalize_source_date(date_filter) if date_filter else None
    where = None if query_type == "any" else {"content_type": query_type}
    try:
        results = collection.get(where=where, include=["metadatas"])
    except TypeError:
        results = collection.get(where=where)

    metadatas = results.get("metadatas") or []
    sources = [
        source
        for source in dedupe_sources(metadatas)
        if matches_date_filter(source["source_name"], normalized_date)
    ]
    sources.sort(key=source_sort_key)

    for index, source in enumerate(sources, start=1):
        source["index"] = index

    return sources


def resolve_selected_source(args, sources):
    if args.source and args.source_name:
        raise ValueError("Use only one of --source or --source-name.")

    if args.source_name:
        for source in sources:
            if source["source_name"] == args.source_name:
                return source
        raise ValueError(f"No indexed source matched --source-name {args.source_name!r}.")

    if args.source is None:
        return None

    if args.source < 1 or args.source > len(sources):
        raise ValueError(
            f"--source must be between 1 and {len(sources)} for the current filter set."
        )

    return sources[args.source - 1]


def build_query_where(query_type, selected_sources=None):
    clauses = []

    if query_type != "any":
        clauses.append({"content_type": query_type})

    if selected_sources:
        source_path_clauses = [{"source_path": source["source_path"]} for source in selected_sources]
        if len(source_path_clauses) == 1:
            clauses.append(source_path_clauses[0])
        else:
            clauses.append({"$or": source_path_clauses})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def list_query_sources(args, profile):
    started = perf_counter()
    collection = get_collection(
        resolve_db_path(profile, args.db_path),
        profile["database"]["collection"],
    )
    sources = list_indexed_sources(collection, args.type, args.date)

    if not sources:
        print("No indexed sources matched the current filters.")
        return 1

    for source in sources:
        date_label = source["source_date"] or "unknown-date"
        print(
            f"{source['index']:>3}. [{source['content_type']}] {date_label} {source['source_name']}"
        )

    logger.info("Listed %s indexed sources in %.2fs", len(sources), perf_counter() - started)

    return 0


def expand_audio_inputs(audio_inputs):
    audio_paths = []
    seen = set()

    for value in audio_inputs:
        matches = glob.glob(str(Path(value).expanduser()))
        resolved_matches = (
            [Path(match).resolve() for match in matches]
            if matches
            else [Path(value).expanduser().resolve()]
        )

        for path in resolved_matches:
            path_key = str(path)
            if path_key in seen:
                continue
            seen.add(path_key)
            audio_paths.append(path)

    return audio_paths


def run_audio_file(args, profile, audio_path):
    file_started = perf_counter()
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

    transcript_path = transcript_json_path(audio_path, transcripts_dir)
    required_transcript_paths = expected_transcript_paths(audio_path, transcripts_dir, transcript_output)
    summary_path = summary_markdown_path(audio_path, summaries_dir)
    overwrite_transcript = args.overwrite in {"transcript", "both"}
    overwrite_summary = args.overwrite in {"summary", "both"} or overwrite_transcript
    if args.summary_format:
        profile = {**profile, "summary": {**profile["summary"], "format": args.summary_format}}

    if all(path.exists() for path in required_transcript_paths) and not overwrite_transcript:
        print(f"[audio] Reusing transcript {transcript_path}", flush=True)
    else:
        if any(path.exists() for path in required_transcript_paths) and overwrite_transcript:
            print(f"[audio] Overwriting transcript outputs for {audio_path.name}", flush=True)
        print("[audio] Unloading Ollama models before WhisperX...", flush=True)
        started = perf_counter()
        unload_profile_ollama_models(profile)
        logger.info("Unloaded Ollama models in %.2fs before transcription", perf_counter() - started)
        run_transcription(audio_path, transcripts_dir, transcript_output)
        ensure_exists(transcript_path, "Transcript JSON")
        for path in required_transcript_paths:
            ensure_exists(path, "Transcript output")

    if summary_path.exists() and not overwrite_summary:
        print(f"[audio] Reusing summary {summary_path}", flush=True)
    else:
        if summary_path.exists() and overwrite_summary:
            print(f"[audio] Overwriting summary {summary_path}", flush=True)
        write_summary(transcript_path, summary_path, profile)

    if index_mode == "none":
        return 0

    collection = get_collection(
        resolve_db_path(profile, args.db_path),
        profile["database"]["collection"],
    )

    if index_mode in {"transcript", "both"}:
        started = perf_counter()
        index_transcript_file(collection, transcript_path, profile["embedding_backend"])
        logger.info("Indexed transcript in %.2fs: %s", perf_counter() - started, transcript_path)

    if index_mode in {"summary", "both"}:
        started = perf_counter()
        index_markdown_file(collection, summary_path, "summary", profile["embedding_backend"])
        logger.info("Indexed summary in %.2fs: %s", perf_counter() - started, summary_path)

    logger.info("Completed audio pipeline in %.2fs: %s", perf_counter() - file_started, audio_path)

    return 0


def run_audio_pipeline(args, profile):
    audio_paths = expand_audio_inputs(args.audio_files)
    exit_code = 0

    for index, audio_path in enumerate(audio_paths, start=1):
        if len(audio_paths) > 1:
            print(f"[audio] File {index}/{len(audio_paths)}: {audio_path}", flush=True)

        try:
            run_audio_file(args, profile, audio_path)
        except (FileNotFoundError, RuntimeError, ValueError, requests.RequestException) as exc:
            print(f"Error processing {audio_path}: {exc}", file=sys.stderr)
            exit_code = 1

    return exit_code


def run_image_pipeline(args, profile):
    started = perf_counter()
    image_path = Path(args.image_file).expanduser().resolve()
    ensure_exists(image_path, "Image file")

    notes_dir = ensure_dir(
        Path(args.notes_dir).expanduser().resolve()
        if args.notes_dir
        else default_child_dir(image_path, profile["image"]["notes_dirname"])
    )

    print(f"[image] Processing {image_path}", flush=True)
    ocr_started = perf_counter()
    note = extract_note(image_path, profile["vision_backend"])
    logger.info("Completed OCR in %.2fs: %s", perf_counter() - ocr_started, image_path)

    note_path = note_markdown_path(image_path, notes_dir)
    note_path.write_text(note + "\n")
    print(f"[image] Wrote {note_path}", flush=True)

    if args.no_index or not profile["image"]["index"]:
        return 0

    collection = get_collection(
        resolve_db_path(profile, args.db_path),
        profile["database"]["collection"],
    )
    index_started = perf_counter()
    index_markdown_file(collection, note_path, "image_note", profile["embedding_backend"])
    logger.info("Indexed image note in %.2fs: %s", perf_counter() - index_started, note_path)
    logger.info("Completed image pipeline in %.2fs: %s", perf_counter() - started, image_path)
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
    configure_logging(args.log_level)

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
        if args.command == "query-list":
            return list_query_sources(args, profile)
    except (FileNotFoundError, RuntimeError, ValueError, requests.RequestException) as exc:
        logger.exception("Top-level noterizer failure")
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    logger.error("Unknown command reached main dispatch: %s", args.command)
    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
