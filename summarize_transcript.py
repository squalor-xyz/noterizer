#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

import requests

from noterizer_core import generate_text, load_profile


DOMAIN_GLOSSARY = """
Known terminology:
- FEM = Front End Module, a hardware/product term. Do not treat FEM as a company unless the transcript explicitly says it is a company.
""".strip()


def load_transcript(path):
    data = json.loads(Path(path).read_text())

    lines = []

    for seg in data.get("segments", []):
        speaker = seg.get("speaker", "UNKNOWN")
        start = round(seg.get("start", 0), 1)
        end = round(seg.get("end", 0), 1)
        text = seg.get("text", "").strip()

        if text:
            lines.append(f"[{start}-{end}] {speaker}: {text}")

    return "\n".join(lines)


def build_prompt(transcript):
    return f"""
Generate durable reference notes from this transcript.

Primary goal: preserve concrete information. Do not turn the conversation into polished prose.

Output rules:
- Output Markdown only.
- Start with the heading `# Executive Summary`.
- Use bullets, not paragraphs, in every section.
- Use the exact section headings listed below, in the same order.
- If a section has nothing useful, write `- None stated.` and move on.
- Do not write any intro or outro text before or after the sections.

Content rules:
- Preserve exact facts over interpretation.
- Preserve product names, tool names, system names, acronyms, file/database/table names, numeric values, workflows, constraints, risks, and tradeoffs.
- Keep timestamps when they help.
- If a statement is ambiguous, mark it as uncertain instead of guessing.
- Do not infer relationships, ownership, intent, company names, or acronym expansions unless explicitly stated.
- Do not use generic summary phrases like "the discussion revolves around", "moving forward", or "in summary".
- Do not add narrative filler, conclusions, or assistant-style language.

Domain glossary:
{DOMAIN_GLOSSARY}

Terminology rules:
- If the transcript uses a term from the glossary, use the glossary meaning.
- Otherwise, do not expand acronyms unless the transcript explicitly expands them.
- If a term may be mis-transcribed or unclear, list it under `# Ambiguous / Unverified Terms`.

Section requirements:
- `# Executive Summary`: 3-5 bullets max.
- `# Key Facts`: concrete facts only.
- `# Main Topics Discussed`: specific topics, not generic labels.
- `# Technical Details`: exact implementation and workflow details.
- `# Architecture / System Ideas`: system structure, boundaries, integrations, data flow.
- `# Business / Product Details`: only if actually discussed.
- `# Constraints / Risks / Concerns`: include technical and process risks.
- `# Action Items`: include owner and due date only if stated.
- `# Decisions Made`: explicit decisions only.
- `# Open Questions`: unresolved questions only.
- `# Ambiguous / Unverified Terms`: unclear terms, possible transcription errors, unexpanded acronyms.
- `# People Mentioned`: names or speaker references only if useful.
- `# Chronological Timeline`: short timeline bullets with timestamps when useful.
- `# Important Quotes`: only unusually precise or important statements.
- `# Next Steps`: explicit next steps only.

Required headings:
# Executive Summary
# Key Facts
# Main Topics Discussed
# Technical Details
# Architecture / System Ideas
# Business / Product Details
# Constraints / Risks / Concerns
# Action Items
# Decisions Made
# Open Questions
# Ambiguous / Unverified Terms
# People Mentioned
# Chronological Timeline
# Important Quotes
# Next Steps

Transcript:

{transcript}
""".strip()


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize a WhisperX transcript JSON file.")
    parser.add_argument("transcript_json", help="Path to the transcript JSON file.")
    parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    parser.add_argument("--output", help="Output markdown path. Defaults beside the transcript JSON.")
    return parser.parse_args()


def main():
    args = parse_args()
    transcript_path = Path(args.transcript_json).expanduser().resolve()

    if not transcript_path.exists():
        print(f"Error: file not found: {transcript_path}")
        return 1

    profile = load_profile(args.profile)

    print("[0/4] Loading transcript...", flush=True)
    transcript = load_transcript(transcript_path)

    if not transcript.strip():
        print("Error: transcript contains no usable text.")
        return 1

    print(f"[0/4] Loaded transcript chars: {len(transcript):,}", flush=True)
    prompt = build_prompt(transcript)
    print(f"[0/4] Prompt chars: {len(prompt):,}", flush=True)
    print("[1/4] Generating summary...", flush=True)

    try:
        summary = generate_text(prompt, profile["summary_backend"])
    except requests.RequestException as exc:
        print(f"Error: {exc}")
        return 1

    out_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else transcript_path.with_suffix(".summary.md")
    )
    out_path.write_text(summary + "\n")
    print(f"[4/4] Writing notes to {out_path}", flush=True)
    print("[done]", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
