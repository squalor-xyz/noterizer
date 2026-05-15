#!/usr/bin/env python3
import argparse
import sys

import requests

from noterizer_core import (
    embed_text,
    format_context_item,
    generate_text,
    get_collection,
    load_profile,
    resolve_db_path,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Query the shared Noterizer database.")
    parser.add_argument("question", help="Question to ask.")
    parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    parser.add_argument("--db-path", help="Override the database path.")
    parser.add_argument(
        "--type",
        choices=["any", "transcript", "summary", "image_note"],
        default=None,
        help="Restrict retrieval to one content type.",
    )
    parser.add_argument("--results", type=int, default=None, help="Number of retrieved chunks.")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        profile = load_profile(args.profile)
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
    except (RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"Error: {exc}")
        return 1

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

    try:
        print(generate_text(prompt, profile["query_backend"]))
    except requests.RequestException as exc:
        print(f"Error: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
