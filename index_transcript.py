#!/usr/bin/env python3
import argparse
import logging
import sys
from pathlib import Path

import requests

from noterizer_core import (
    add_log_level_arg,
    configure_logging,
    get_collection,
    index_transcript_file,
    load_profile,
    resolve_db_path,
)

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Index a transcript JSON file into the shared database.")
    add_log_level_arg(parser)
    parser.add_argument("transcript_json", help="Path to the transcript JSON file.")
    parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    parser.add_argument("--db-path", help="Override the database path.")
    return parser.parse_args()


def main():
    args = parse_args()
    configure_logging(args.log_level)
    transcript_path = Path(args.transcript_json).expanduser().resolve()

    if not transcript_path.exists():
        logger.error("Transcript file not found: %s", transcript_path)
        print(f"Error: file not found: {transcript_path}")
        return 1

    try:
        profile = load_profile(args.profile)
        collection = get_collection(
            resolve_db_path(profile, args.db_path),
            profile["database"]["collection"],
        )
        count = index_transcript_file(collection, transcript_path, profile["embedding_backend"])
    except (RuntimeError, ValueError, requests.RequestException) as exc:
        logger.exception("Transcript indexing failed for %s", transcript_path)
        print(f"Error: {exc}")
        return 1

    print(f"Indexed {count} transcript chunks into {resolve_db_path(profile, args.db_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
