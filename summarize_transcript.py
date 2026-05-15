#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

import requests

from noterizer_core import generate_text, load_profile


DOMAIN_GLOSSARY = """
Known terminology:
- FEM = Front End Module, a hardware/product term. Do not treat FEM as a company unless the transcript explicitly says it is a company.
""".strip()

REQUIRED_HEADINGS = [
    "# Executive Summary",
    "# Key Facts",
    "# Main Topics Discussed",
    "# Technical Details",
    "# Architecture / System Ideas",
    "# Business / Product Details",
    "# Constraints / Risks / Concerns",
    "# Action Items",
    "# Decisions Made",
    "# Open Questions",
    "# Ambiguous / Unverified Terms",
    "# People Mentioned",
    "# Chronological Timeline",
    "# Important Quotes",
    "# Next Steps",
]

CLOSING_PHRASES = {
    "thank you",
    "thank you guys",
    "thank you everybody",
    "thanks",
    "thanks guys",
    "thanks everybody",
    "bye",
    "goodbye",
    "okay",
    "ok",
    "all right",
    "alright",
    "cool",
    "amen",
    "right",
}


def normalize_text(value):
    return re.sub(r"[^a-z0-9 ]+", "", value.lower()).strip()


def is_trivial_closing_segment(text):
    normalized = normalize_text(text)
    if not normalized:
        return True
    if normalized in CLOSING_PHRASES:
        return True
    if len(normalized.split()) <= 4 and normalized.startswith(("thank you", "thanks")):
        return True
    return False


def load_transcript(path):
    data = json.loads(Path(path).read_text())
    segments = data.get("segments", [])

    while segments and is_trivial_closing_segment(segments[-1].get("text", "").strip()):
        segments = segments[:-1]

    lines = []

    for seg in segments:
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


def validate_summary(summary):
    errors = []
    stripped = summary.strip()

    if not stripped.startswith(REQUIRED_HEADINGS[0]):
        errors.append("summary does not start with '# Executive Summary'")

    positions = []
    for heading in REQUIRED_HEADINGS:
        index = stripped.find(heading)
        if index == -1:
            errors.append(f"missing required heading: {heading}")
        else:
            positions.append(index)

    if positions and positions != sorted(positions):
        errors.append("required headings are out of order")

    heading_count = sum(1 for line in stripped.splitlines() if line.startswith("# "))
    if heading_count < len(REQUIRED_HEADINGS):
        errors.append("summary contains too few section headings")

    first_nonempty = next((line.strip() for line in stripped.splitlines() if line.strip()), "")
    if first_nonempty and first_nonempty != REQUIRED_HEADINGS[0]:
        errors.append("summary begins with prose instead of the required heading")

    return errors


def build_repair_prompt(transcript, invalid_summary, errors):
    error_list = "\n".join(f"- {error}" for error in errors)
    headings = "\n".join(REQUIRED_HEADINGS)
    return f"""
Rewrite the invalid summary below so it strictly follows the required format.

Return Markdown only.
Do not add any intro or outro text.
Start with `# Executive Summary`.
Use bullets in every section.
Use these exact headings in this exact order:
{headings}

Validation errors in the invalid summary:
{error_list}

Invalid summary:
{invalid_summary}

Transcript:
{transcript}
""".strip()


def generate_summary_markdown(transcript, backend):
    summary = generate_text(build_prompt(transcript), backend)
    errors = validate_summary(summary)

    if not errors:
        return summary

    print("[summary] Validation failed. Retrying with repair prompt...", flush=True)
    repaired_summary = generate_text(
        build_repair_prompt(transcript, summary, errors),
        backend,
    )
    repaired_errors = validate_summary(repaired_summary)

    if repaired_errors:
        joined_errors = "; ".join(repaired_errors)
        raise ValueError(f"Summary validation failed after retry: {joined_errors}")

    return repaired_summary


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
        summary = generate_summary_markdown(transcript, profile["summary_backend"])
    except (ValueError, requests.RequestException) as exc:
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
