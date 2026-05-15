#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

import requests

from noterizer_core import generate_text, load_profile


DOMAIN_GLOSSARY = """
Known terminology:
- FEM = Front End Module, a hardware/product term. Do not treat FEM as a company unless the transcript explicitly says it is a company.
- PVT may refer to R&S PVT360A equipment or to the test term "Power VS Time". Do not choose between these meanings unless the transcript context makes it clear.
- RVTM = Requirements Verification and Traceability Matrix.
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

CHUNK_NOTE_HEADINGS = REQUIRED_HEADINGS[1:]
CHUNK_TARGET_CHARS = 8000
DIRECT_SUMMARY_MAX_CHARS = 12000

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


def load_transcript_lines(path):
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

    return lines


def load_transcript(path):
    return "\n".join(load_transcript_lines(path))


def chunk_transcript_lines(lines, target_chars=CHUNK_TARGET_CHARS):
    if not lines:
        return []

    chunks = []
    current_lines = []
    current_chars = 0

    for line in lines:
        line_chars = len(line) + 1
        if current_lines and current_chars + line_chars > target_chars:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_chars = line_chars
            continue

        current_lines.append(line)
        current_chars += line_chars

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


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
- Do not upgrade suggestions, proposals, or ideas into decisions or commitments.
- Do not invent action items or next steps that were not explicitly assigned, requested, or agreed.
- Never mention chunk numbers, chunk boundaries, or intermediate processing in the final output.
- In `# People Mentioned`, include only actual people explicitly named or speaker labels. Do not include tool names, product names, or inferred identities.

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
- `# Action Items`: include only explicit tasks, requests, or follow-ups. If no clear task exists, write `- None stated.`
- `# Decisions Made`: explicit decisions only. Do not include proposals, open ideas, or "should" statements.
- `# Open Questions`: unresolved questions only.
- `# Ambiguous / Unverified Terms`: unclear terms, possible transcription errors, unexpanded acronyms.
- `# People Mentioned`: names or speaker references only if useful. Do not infer real identities from speaker labels.
- `# Chronological Timeline`: short timeline bullets with timestamps when useful.
- `# Important Quotes`: only unusually precise or important statements.
- `# Next Steps`: explicit next steps only. Do not infer likely next steps from discussion context.

Required headings:
{chr(10).join(REQUIRED_HEADINGS)}

Transcript:

{transcript}
""".strip()


def build_chunk_prompt(chunk_text, chunk_index, total_chunks):
    return f"""
Generate dense extraction notes for transcript chunk {chunk_index} of {total_chunks}.

This is an intermediate step. Do not write an executive summary and do not write polished prose.

Output rules:
- Output Markdown only.
- Use bullets only.
- Use the exact headings listed below, in the same order.
- If a section has nothing useful, write `- None stated.`
- Preserve exact facts, names, acronyms, values, timestamps, workflows, constraints, and quotes from this chunk only.
- Do not guess meanings or relationships.
- For `# Action Items`, include only explicit tasks, requests, or follow-ups from this chunk.
- For `# Decisions Made`, include only explicit decisions from this chunk.
- For `# Next Steps`, include only explicit next steps from this chunk.
- For `# People Mentioned`, include only actual people explicitly named or speaker labels from this chunk.
- Do not mention chunk numbers or chunk boundaries inside the section content.

Domain glossary:
{DOMAIN_GLOSSARY}

Required headings:
{chr(10).join(CHUNK_NOTE_HEADINGS)}

Transcript chunk {chunk_index}/{total_chunks}:

{chunk_text}
""".strip()


def build_merge_prompt(chunk_notes):
    joined_notes = "\n\n".join(
        f"## Chunk {index}\n{notes}" for index, notes in enumerate(chunk_notes, start=1)
    )
    return f"""
Merge the chunk notes below into one final transcript summary.

Output rules:
- Output Markdown only.
- Start with `# Executive Summary`.
- Use bullets, not paragraphs, in every section.
- Use the exact headings listed below, in the same order.
- If a section has nothing useful, write `- None stated.`
- Do not add any intro or outro text.
- Preserve concrete details from the chunk notes. Do not invent facts that are not present in the notes.
- Never mention chunk numbers, chunk ranges, or phrases like "in chunk 3" in the final summary.
- Remove any intermediate-processing references from the final output.
- For `# Decisions Made`, keep only explicit decisions. Drop proposals, ideas, or suggestions.
- For `# Action Items`, keep only explicit tasks, requests, or follow-ups.
- For `# Next Steps`, keep only explicit next steps. Do not infer likely future work.
- For `# People Mentioned`, include only actual people explicitly named or speaker labels. Do not infer identities from speaker labels and do not include tools or products.
- For `# Ambiguous / Unverified Terms`, prefer raw transcript terms over guessed expansions unless the Domain glossary explicitly defines them.
- When uncertain whether something is a decision or action item, omit it or place it under `# Open Questions` or `# Main Topics Discussed`.

Domain glossary:
{DOMAIN_GLOSSARY}

Required headings:
{chr(10).join(REQUIRED_HEADINGS)}

Chunk notes:

{joined_notes}
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


def build_repair_prompt(invalid_summary, errors):
    error_list = "\n".join(f"- {error}" for error in errors)
    headings = "\n".join(REQUIRED_HEADINGS)
    return f"""
Rewrite the invalid summary below so it strictly follows the required format.

Only use facts already present in the invalid summary.
Do not add new facts.
Return Markdown only.
Do not add any intro or outro text.
Start with `# Executive Summary`.
Use bullets in every section.
Remove any references to chunk numbers, chunk boundaries, or intermediate processing.
Do not convert proposals or suggestions into decisions.
Do not convert implications into action items or next steps.
In `# People Mentioned`, include only actual people explicitly named or speaker labels. Do not infer identities and do not include tools or products.
In `# Ambiguous / Unverified Terms`, keep raw terms unless the Domain glossary explicitly defines the meaning.
Use these exact headings in this exact order:
{headings}

Validation errors in the invalid summary:
{error_list}

Invalid summary:
{invalid_summary}
""".strip()


def build_notes_recovery_prompt(chunk_notes, errors):
    error_list = "\n".join(f"- {error}" for error in errors)
    joined_notes = "\n\n".join(
        f"## Chunk {index}\n{notes}" for index, notes in enumerate(chunk_notes, start=1)
    )
    return f"""
Create a valid final transcript summary from the chunk notes below.

Return Markdown only.
Do not add any intro or outro text.
Start with `# Executive Summary`.
Use bullets in every section.
Never mention chunk numbers, chunk boundaries, or intermediate processing in the final output.
Do not convert proposals or suggestions into decisions.
Do not invent action items or next steps that are not explicit in the chunk notes.
In `# People Mentioned`, include only actual people explicitly named or speaker labels. Do not infer identities and do not include tools or products.
In `# Ambiguous / Unverified Terms`, keep raw terms unless the Domain glossary explicitly defines the meaning.
Use these exact headings in this exact order:
{chr(10).join(REQUIRED_HEADINGS)}

Previous merged summary failed validation for these reasons:
{error_list}

Chunk notes:

{joined_notes}
""".strip()


def summarize_chunk_notes(chunks, backend):
    notes = []

    for index, chunk_text in enumerate(chunks, start=1):
        print(f"[summary] Summarizing chunk {index}/{len(chunks)}...", flush=True)
        notes.append(generate_text(build_chunk_prompt(chunk_text, index, len(chunks)), backend))

    return notes


def generate_chunked_summary(transcript, backend):
    chunks = chunk_transcript_lines(transcript.splitlines())
    chunk_notes = summarize_chunk_notes(chunks, backend)
    merged_summary = generate_text(build_merge_prompt(chunk_notes), backend)
    return merged_summary, chunk_notes


def try_repair_summary(invalid_summary, errors, backend):
    print("[summary] Validation failed. Retrying with repair prompt...", flush=True)
    repaired_summary = generate_text(build_repair_prompt(invalid_summary, errors), backend)
    return repaired_summary, validate_summary(repaired_summary)


def generate_summary_markdown(transcript, backend):
    chunk_notes = None

    if len(transcript) <= DIRECT_SUMMARY_MAX_CHARS:
        summary = generate_text(build_prompt(transcript), backend)
    else:
        print("[summary] Using chunked summarization...", flush=True)
        summary, chunk_notes = generate_chunked_summary(transcript, backend)

    errors = validate_summary(summary)
    if not errors:
        return summary

    repaired_summary, repaired_errors = try_repair_summary(summary, errors, backend)
    if not repaired_errors:
        return repaired_summary

    if chunk_notes is None:
        print("[summary] Falling back to chunked summarization...", flush=True)
        summary, chunk_notes = generate_chunked_summary(transcript, backend)
        errors = validate_summary(summary)
        if not errors:
            return summary

        repaired_summary, repaired_errors = try_repair_summary(summary, errors, backend)
        if not repaired_errors:
            return repaired_summary

    print("[summary] Rebuilding final summary from chunk notes...", flush=True)
    recovered_summary = generate_text(
        build_notes_recovery_prompt(chunk_notes, repaired_errors),
        backend,
    )
    recovery_errors = validate_summary(recovered_summary)

    if recovery_errors:
        joined_errors = "; ".join(recovery_errors)
        raise ValueError(f"Summary validation failed after recovery: {joined_errors}")

    return recovered_summary


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
