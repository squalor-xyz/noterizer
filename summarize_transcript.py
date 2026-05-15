#!/usr/bin/env python3
import argparse
import json
import logging
import re
from pathlib import Path
from time import perf_counter

import requests

from noterizer_core import add_log_level_arg, configure_logging, generate_text, load_profile

logger = logging.getLogger(__name__)


DOMAIN_GLOSSARY = """
Known terminology:
- FEM = Front End Module, a hardware/product term. Do not treat FEM as a company unless the transcript explicitly says it is a company.
- PVT may refer to R&S PVT360A equipment or to the test term "Power VS Time". Do not choose between these meanings unless the transcript context makes it clear.
- RVTM = Requirements Verification and Traceability Matrix.
""".strip()

SUMMARY_TEMPLATES = {
    "meeting": {
        "headings": [
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
        ],
        "section_requirements": [
            "- `# Executive Summary`: 3-5 bullets max.",
            "- `# Key Facts`: concrete facts only.",
            "- `# Main Topics Discussed`: specific topics, not generic labels.",
            "- `# Technical Details`: exact implementation and workflow details.",
            "- `# Architecture / System Ideas`: system structure, boundaries, integrations, data flow.",
            "- `# Business / Product Details`: only if actually discussed.",
            "- `# Constraints / Risks / Concerns`: include technical and process risks.",
            "- `# Action Items`: include only explicit tasks, requests, or follow-ups. If no clear task exists, write `- None stated.`",
            "- `# Decisions Made`: explicit decisions only. Do not include proposals, open ideas, or \"should\" statements.",
            "- `# Open Questions`: unresolved questions only.",
            "- `# Ambiguous / Unverified Terms`: unclear terms, possible transcription errors, unexpanded acronyms.",
            "- `# People Mentioned`: names or speaker references only if useful. Do not infer real identities from speaker labels.",
            "- `# Chronological Timeline`: short timeline bullets with timestamps when useful.",
            "- `# Important Quotes`: only unusually precise or important statements.",
            "- `# Next Steps`: explicit next steps only. Do not infer likely next steps from discussion context.",
        ],
        "content_rules": [
            "- Do not upgrade suggestions, proposals, or ideas into decisions or commitments.",
            "- Do not invent action items or next steps that were not explicitly assigned, requested, or agreed.",
        ],
    },
    "presentation": {
        "headings": [
            "# Executive Summary",
            "# Core Themes",
            "# Products / Features Shown",
            "# Technical Details",
            "# Demonstrations / Examples",
            "# Announcements / Claims",
            "# Risks / Caveats",
            "# Open Questions / Ambiguities",
            "# People Mentioned",
            "# Chronological Timeline",
            "# Important Quotes",
        ],
        "section_requirements": [
            "- `# Executive Summary`: 3-5 bullets max.",
            "- `# Core Themes`: main themes or messages from the presentation.",
            "- `# Products / Features Shown`: products, capabilities, or features demonstrated or described.",
            "- `# Technical Details`: exact technical facts, specs, integrations, protocols, models, workflows, and constraints.",
            "- `# Demonstrations / Examples`: concrete demos, walkthroughs, comparisons, or illustrative examples shown.",
            "- `# Announcements / Claims`: roadmap statements, claims, or positioning presented by the speakers. Treat these as presented claims, not verified facts.",
            "- `# Risks / Caveats`: limitations, cautions, tradeoffs, or uncertainty if actually mentioned.",
            "- `# Open Questions / Ambiguities`: unclear terms, possible transcription issues, unresolved questions, or ambiguous claims.",
            "- `# People Mentioned`: names or speaker references only if useful. Do not infer real identities from speaker labels.",
            "- `# Chronological Timeline`: major beats of the presentation with timestamps when useful.",
            "- `# Important Quotes`: unusually precise or important statements only.",
        ],
        "content_rules": [
        "- Do not force meeting-style sections such as action items, decisions, or next steps into presentation summaries.",
            "- Do not invent commitments, follow-ups, or tasks unless the presentation explicitly includes them.",
            "- Prefer products, demos, claims, and technical points over conversational process notes.",
        ],
    },
}

REQUIRED_HEADINGS = SUMMARY_TEMPLATES["meeting"]["headings"]
CHUNK_TARGET_CHARS = 8000
DIRECT_SUMMARY_MAX_CHARS = 12000
LONG_TRANSCRIPT_MIN_LINES = 120
SRT_PREFERENCE_RATIO = 0.8
SUMMARY_FORMAT_CHOICES = ["auto", "meeting", "presentation"]

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
    "yeah",
    "yes",
    "no",
    "oh",
    "you",
}

PRESENTATION_FACTUAL_HEADINGS = {
    "# Core Themes",
    "# Products / Features Shown",
    "# Technical Details",
    "# Demonstrations / Examples",
    "# Announcements / Claims",
}

AMBIGUITY_HEADINGS = {
    "meeting": "# Ambiguous / Unverified Terms",
    "presentation": "# Open Questions / Ambiguities",
}

SPEAKER_MAPPING_RE = re.compile(r"^(\s*-\s*)(.+?)\s+\((SPEAKER_\d+)\)\s*$")
SPEAKER_ROLE_RE = re.compile(r"^(\s*-\s*)(SPEAKER_\d+)\s+\([^)]+\)\s*$")
SUSPECT_MM_WAVE_RE = re.compile(r"\b\d+\s*mm\s+wave\b", re.IGNORECASE)
MIXED_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*\d[A-Za-z0-9_]*\b")
PAREN_TERM_RE = re.compile(r"\b([A-Z0-9][A-Z0-9_-]{1,})\s+\(([^)]+)\)")
SUSPICIOUS_EXPANSION_WORDS = {"somber"}
SOFT_DECISION_RE = re.compile(
    r"\b(suggest(?:ed)?|proposal|propose|possible|maybe|might|could|should|consider|considering|"
    r"explore|exploring|evaluate|evaluating|future work|planned|plan to|idea)\b",
    re.IGNORECASE,
)
HARD_DECISION_RE = re.compile(
    r"\b(decided|decision|agreed|agreement|the plan is|going with)\b",
    re.IGNORECASE,
)
SOFT_ACTION_RE = re.compile(
    r"\b(explore|investigate|evaluate|consider|discuss|review|look into|possible|maybe|might|could)\b",
    re.IGNORECASE,
)
OWNER_ACTION_RE = re.compile(
    r"^\s*-\s*(SPEAKER_\d+|[A-Z][a-z]+(?:,\s*[A-Z][a-z]+)*)(?:\s+will\b|\s+to\b|:)"
)
HARD_ACTION_RE = re.compile(
    r"\b(i(?:'m| am)? going to|i owe you|we need to|we will|let'?s|can you|"
    r"will work on|will review|will walk through|create an issue|formal request)\b",
    re.IGNORECASE,
)


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


def parse_srt_timestamp(value):
    parts = re.split(r"[:,]", value.strip())
    if len(parts) != 4:
        return 0.0
    hours, minutes, seconds, millis = (int(part) for part in parts)
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def load_srt_lines(path):
    text = Path(path).read_text()
    blocks = re.split(r"\n\s*\n", text.strip())
    lines = []

    for block in blocks:
        block_lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(block_lines) < 2:
            continue

        time_line = block_lines[1] if "-->" in block_lines[1] else block_lines[0]
        if "-->" not in time_line:
            continue

        start_text, end_text = [part.strip() for part in time_line.split("-->", 1)]
        start = parse_srt_timestamp(start_text)
        end = parse_srt_timestamp(end_text)
        content_lines = block_lines[2:] if time_line == block_lines[1] else block_lines[1:]
        content = " ".join(content_lines).strip()

        if content and not is_trivial_closing_segment(content):
            lines.append(f"[{start:.1f}-{end:.1f}] {content}")

    return lines


def choose_summary_lines(path):
    json_lines = load_transcript_lines(path)
    srt_path = Path(path).with_suffix(".srt")

    if not srt_path.exists():
        return json_lines, "json"

    srt_lines = load_srt_lines(srt_path)
    if not srt_lines:
        return json_lines, "json"

    if len(srt_lines) < len(json_lines) * SRT_PREFERENCE_RATIO:
        logger.info(
            "Using shorter sibling SRT for summarization: %s instead of %s",
            srt_path,
            path,
        )
        return srt_lines, "srt"

    return json_lines, "json"


def load_transcript(path):
    lines, source_kind = choose_summary_lines(path)
    return "\n".join(lines), source_kind, lines


def get_template(template_name):
    return SUMMARY_TEMPLATES[template_name]


def template_headings(template_name):
    return get_template(template_name)["headings"]


def chunk_note_headings(template_name):
    return template_headings(template_name)[1:]


def extract_line_text(line):
    return line.split(": ", 1)[1] if ": " in line else line


def extract_line_speaker(line):
    left = line.split(": ", 1)[0]
    return left.split("] ", 1)[1] if "] " in left else "UNKNOWN"


def informative_word_count(text):
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+./_-]*", text)
    return sum(1 for word in words if len(word) >= 3)


def is_low_information_line(line):
    text = extract_line_text(line).strip()
    normalized = normalize_text(text)

    if is_trivial_closing_segment(text):
        return True

    if informative_word_count(text) == 0:
        return True

    if len(normalized.split()) <= 2 and normalize_text(text) in CLOSING_PHRASES:
        return True

    return False


def parse_summary_sections(summary):
    sections = []
    current_heading = None
    current_lines = []

    for line in summary.strip().splitlines():
        if line.startswith("# "):
            if current_heading is not None:
                sections.append((current_heading, current_lines))
            current_heading = line.strip()
            current_lines = []
            continue
        if current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        sections.append((current_heading, current_lines))

    return sections


def render_summary_sections(sections):
    rendered = []

    for heading, lines in sections:
        rendered.append(heading)
        rendered.extend(lines if lines else ["- None stated."])
        rendered.append("")

    return "\n".join(rendered).strip()


def transcript_token_set(transcript_lines):
    transcript_text = "\n".join(transcript_lines)
    return {token.lower() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+./_-]*", transcript_text)}


def strip_chunk_artifacts(line):
    if re.search(r"\bchunk(?:s)?\b", line, re.IGNORECASE):
        return None
    return line


def sanitize_people_line(line):
    match = SPEAKER_MAPPING_RE.match(line)
    if match:
        prefix, name, _speaker = match.groups()
        return f"{prefix}{name}"

    match = SPEAKER_ROLE_RE.match(line)
    if match:
        prefix, speaker = match.groups()
        return f"{prefix}{speaker}"

    return line


def strip_unsupported_parenthetical_expansions(line, transcript_text_lower):
    def replace(match):
        term, expansion = match.groups()
        expansion_words = {
            word.lower()
            for word in re.findall(r"[A-Za-z][A-Za-z-]*", expansion)
        }
        if expansion_words & SUSPICIOUS_EXPANSION_WORDS:
            return term
        if expansion.lower() in transcript_text_lower:
            return match.group(0)
        return term

    return PAREN_TERM_RE.sub(replace, line)


def extract_ambiguous_notes(line, transcript_tokens):
    notes = []

    mm_wave = SUSPECT_MM_WAVE_RE.search(line)
    if mm_wave:
        notes.append(f"- {mm_wave.group(0)} (possible transcription issue)")

    for token in MIXED_TOKEN_RE.findall(line):
        if token.isdigit():
            continue
        if token.lower() not in transcript_tokens:
            notes.append(f"- {token} (term not clearly grounded in transcript text)")

    return notes


def dedupe_preserve_order(lines):
    seen = set()
    result = []

    for line in lines:
        key = line.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(line)

    return result


def sanitize_summary_output(summary, template_name, transcript_lines):
    sections = parse_summary_sections(summary)
    if not sections:
        return summary

    ambiguity_heading = AMBIGUITY_HEADINGS[template_name]
    transcript_text_lower = "\n".join(transcript_lines).lower()
    transcript_tokens = transcript_token_set(transcript_lines)
    ambiguity_notes = []
    sanitized_sections = []

    for heading, lines in sections:
        cleaned_lines = []

        for raw_line in lines:
            line = strip_chunk_artifacts(raw_line)
            if line is None:
                continue

            if heading == "# People Mentioned":
                line = sanitize_people_line(line)

            if template_name == "presentation" and heading in PRESENTATION_FACTUAL_HEADINGS:
                line = strip_unsupported_parenthetical_expansions(line, transcript_text_lower)
                ambiguous = extract_ambiguous_notes(line, transcript_tokens)
                if ambiguous:
                    ambiguity_notes.extend(ambiguous)
                    continue

            cleaned_lines.append(line)

        cleaned_lines = [line for line in cleaned_lines if line.strip()]
        if not cleaned_lines:
            cleaned_lines = ["- None stated."]

        sanitized_sections.append((heading, cleaned_lines))

    if ambiguity_notes:
        ambiguity_notes = dedupe_preserve_order(ambiguity_notes)
        for index, (heading, lines) in enumerate(sanitized_sections):
            if heading != ambiguity_heading:
                continue
            retained_lines = [line for line in lines if line.strip() != "- None stated."]
            sanitized_sections[index] = (heading, dedupe_preserve_order(retained_lines + ambiguity_notes))
            break

    return render_summary_sections(sanitized_sections)


def is_explicit_decision_line(line):
    text = line.strip()
    if text == "- None stated.":
        return True
    if SOFT_DECISION_RE.search(text) and not HARD_DECISION_RE.search(text):
        return False
    return bool(HARD_DECISION_RE.search(text))


def is_explicit_action_line(line):
    text = line.strip()
    if text == "- None stated.":
        return True
    if OWNER_ACTION_RE.search(text):
        return True
    if HARD_ACTION_RE.search(text):
        return True
    return False


def sanitize_commitment_sections(summary, template_name):
    sections = parse_summary_sections(summary)
    if not sections:
        return summary

    sanitized_sections = []

    for heading, lines in sections:
        cleaned_lines = list(lines)

        if heading == "# Decisions Made":
            kept = [
                line for line in cleaned_lines
                if line.strip().startswith("-") and is_explicit_decision_line(line)
            ]
            cleaned_lines = kept or ["- None stated."]

        if heading == "# Action Items":
            kept = [
                line for line in cleaned_lines
                if line.strip().startswith("-") and is_explicit_action_line(line)
            ]
            cleaned_lines = kept or ["- None stated."]

        sanitized_sections.append((heading, cleaned_lines))

    return render_summary_sections(sanitized_sections)


def detect_summary_format(transcript_lines, transcript_path=None):
    path_text = ""
    if transcript_path is not None:
        path_text = str(Path(transcript_path).stem).lower()

    hint_terms = ("keynote", "presentation", "demo", "session", "webinar", "conference", "ni-connect")
    if any(term in path_text for term in hint_terms):
        return "presentation"

    speakers = [extract_line_speaker(line) for line in transcript_lines if extract_line_speaker(line) != "UNKNOWN"]
    unique_speakers = set(speakers)
    speaker_switches = sum(1 for left, right in zip(speakers, speakers[1:]) if left != right)

    transcript_text = " ".join(extract_line_text(line).lower() for line in transcript_lines[:120])
    presentation_markers = sum(
        marker in transcript_text
        for marker in (
            "today",
            "demo",
            "let me show",
            "on stage",
            "thank you all",
            "joining us",
            "welcome",
            "session",
            "keynote",
        )
    )
    meeting_markers = sum(
        marker in transcript_text
        for marker in (
            "next meeting",
            "follow up",
            "let me ask",
            "we need to",
            "what do you think",
            "action item",
            "issue",
            "requirements",
        )
    )

    if len(unique_speakers) <= 2 and speaker_switches <= max(4, len(speakers) // 10):
        return "presentation"

    if presentation_markers >= 2 and meeting_markers == 0:
        return "presentation"

    return "meeting"


def filter_long_transcript_lines(lines):
    if len(lines) < LONG_TRANSCRIPT_MIN_LINES:
        return lines

    filtered_lines = [line for line in lines if not is_low_information_line(line)]
    if filtered_lines:
        logger.info(
            "Filtered %s low-information lines from long transcript",
            len(lines) - len(filtered_lines),
        )
        return filtered_lines

    return lines


def chunk_transcript_line_groups(lines, target_chars=CHUNK_TARGET_CHARS):
    if not lines:
        return []

    chunks = []
    current_lines = []
    current_chars = 0

    for line in lines:
        line_chars = len(line) + 1
        if current_lines and current_chars + line_chars > target_chars:
            chunks.append(current_lines)
            current_lines = [line]
            current_chars = line_chars
            continue

        current_lines.append(line)
        current_chars += line_chars

    if current_lines:
        chunks.append(current_lines)

    return chunks


def chunk_transcript_lines(lines, target_chars=CHUNK_TARGET_CHARS):
    return ["\n".join(group) for group in chunk_transcript_line_groups(lines, target_chars)]


def is_low_information_chunk_lines(chunk_lines):
    if not chunk_lines:
        return True

    total_lines = len(chunk_lines)
    low_info_lines = sum(1 for line in chunk_lines if is_low_information_line(line))
    unknown_lines = sum(1 for line in chunk_lines if extract_line_speaker(line) == "UNKNOWN")
    informative_words = sum(informative_word_count(extract_line_text(line)) for line in chunk_lines)

    if informative_words < 25:
        return True

    if low_info_lines / total_lines > 0.6:
        return True

    if unknown_lines / total_lines > 0.85 and informative_words < 80:
        return True

    return False


def is_noisy_tail_chunk_lines(chunk_lines):
    if not chunk_lines:
        return True

    total_lines = len(chunk_lines)
    unknown_lines = sum(1 for line in chunk_lines if extract_line_speaker(line) == "UNKNOWN")
    informative_words = sum(informative_word_count(extract_line_text(line)) for line in chunk_lines)

    return unknown_lines / total_lines > 0.12 and informative_words < 550


def trim_low_information_tail_chunks(chunk_groups):
    trimmed = list(chunk_groups)

    while len(trimmed) > 1 and (
        is_low_information_chunk_lines(trimmed[-1]) or is_noisy_tail_chunk_lines(trimmed[-1])
    ):
        logger.info("Dropping low-information tail chunk with %s lines", len(trimmed[-1]))
        trimmed.pop()

    return trimmed


def build_prompt(transcript, template_name):
    template = get_template(template_name)
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
{chr(10).join(template["content_rules"])}
- Never mention chunk numbers, chunk boundaries, or intermediate processing in the final output.
- In `# People Mentioned`, include only actual people explicitly named or speaker labels. Do not include tool names, product names, or inferred identities.
- Do not pair a person's name with a speaker label unless the transcript explicitly identifies that mapping.
- If a technical term looks unclear, malformed, or possibly mis-transcribed, keep it out of factual sections and place it in the ambiguity section instead.

Domain glossary:
{DOMAIN_GLOSSARY}

Terminology rules:
- If the transcript uses a term from the glossary, use the glossary meaning.
- Otherwise, do not expand acronyms unless the transcript explicitly expands them.
- If a term may be mis-transcribed or unclear, list it under `# Ambiguous / Unverified Terms`.

Section requirements:
{chr(10).join(template["section_requirements"])}

Required headings:
{chr(10).join(template["headings"])}

Transcript:

{transcript}
""".strip()


def build_chunk_prompt(chunk_text, chunk_index, total_chunks, template_name):
    template = get_template(template_name)
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
- For `# People Mentioned`, include only actual people explicitly named or speaker labels from this chunk.
- Do not mention chunk numbers or chunk boundaries inside the section content.
- Do not pair a person's name with a speaker label unless the chunk explicitly identifies that mapping.
- If a technical term looks unclear, malformed, or possibly mis-transcribed, keep it out of factual sections and place it in the ambiguity section instead.
{chr(10).join(template["content_rules"])}

Domain glossary:
{DOMAIN_GLOSSARY}

Required headings:
{chr(10).join(chunk_note_headings(template_name))}

Transcript chunk {chunk_index}/{total_chunks}:

{chunk_text}
""".strip()


def build_merge_prompt(chunk_notes, template_name):
    template = get_template(template_name)
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
{chr(10).join(template["content_rules"])}
- For `# People Mentioned`, include only actual people explicitly named or speaker labels. Do not infer identities from speaker labels and do not include tools or products.
- For `# Ambiguous / Unverified Terms`, prefer raw transcript terms over guessed expansions unless the Domain glossary explicitly defines them.
- When uncertain whether something is a decision or action item, omit it or place it under `# Open Questions` or `# Main Topics Discussed`.
- Do not pair a person's name with a speaker label unless the transcript explicitly identifies that mapping.
- If a technical term looks unclear, malformed, or possibly mis-transcribed, keep it out of factual sections and place it in the ambiguity section instead.

Domain glossary:
{DOMAIN_GLOSSARY}

Required headings:
{chr(10).join(template["headings"])}

Chunk notes:

{joined_notes}
""".strip()


def validate_summary(summary, template_name=None):
    candidate_templates = [template_name] if template_name else list(SUMMARY_TEMPLATES)
    best_errors = None

    for candidate in candidate_templates:
        errors = validate_summary_against_template(summary, candidate)
        if not errors:
            return []
        if best_errors is None or len(errors) < len(best_errors):
            best_errors = errors

    return best_errors or []


def validate_summary_against_template(summary, template_name):
    required_headings = template_headings(template_name)
    errors = []
    stripped = summary.strip()

    if not stripped.startswith(required_headings[0]):
        errors.append(f"summary does not start with '{required_headings[0]}'")

    positions = []
    for heading in required_headings:
        index = stripped.find(heading)
        if index == -1:
            errors.append(f"missing required heading: {heading}")
        else:
            positions.append(index)

    if positions and positions != sorted(positions):
        errors.append("required headings are out of order")

    heading_count = sum(1 for line in stripped.splitlines() if line.startswith("# "))
    if heading_count < len(required_headings):
        errors.append("summary contains too few section headings")

    first_nonempty = next((line.strip() for line in stripped.splitlines() if line.strip()), "")
    if first_nonempty and first_nonempty != required_headings[0]:
        errors.append("summary begins with prose instead of the required heading")

    return errors


def build_repair_prompt(invalid_summary, errors, template_name):
    error_list = "\n".join(f"- {error}" for error in errors)
    headings = "\n".join(template_headings(template_name))
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
Do not pair a person's name with a speaker label unless the transcript explicitly identifies that mapping.
If a technical term looks unclear, malformed, or possibly mis-transcribed, keep it out of factual sections and place it in the ambiguity section instead.
Use these exact headings in this exact order:
{headings}

Validation errors in the invalid summary:
{error_list}

Invalid summary:
{invalid_summary}
""".strip()


def build_notes_recovery_prompt(chunk_notes, errors, template_name):
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
Do not pair a person's name with a speaker label unless the transcript explicitly identifies that mapping.
If a technical term looks unclear, malformed, or possibly mis-transcribed, keep it out of factual sections and place it in the ambiguity section instead.
Use these exact headings in this exact order:
{chr(10).join(template_headings(template_name))}

Previous merged summary failed validation for these reasons:
{error_list}

Chunk notes:

{joined_notes}
""".strip()


def summarize_chunk_notes(chunks, backend, template_name):
    notes = []

    retained_chunks = [chunk for chunk in chunks if not is_low_information_chunk_lines(chunk)]

    if not retained_chunks:
        retained_chunks = chunks

    for index, chunk_lines in enumerate(retained_chunks, start=1):
        chunk_text = "\n".join(chunk_lines)
        print(f"[summary] Summarizing chunk {index}/{len(retained_chunks)}...", flush=True)
        started = perf_counter()
        notes.append(generate_text(build_chunk_prompt(chunk_text, index, len(retained_chunks), template_name), backend))
        logger.info(
            "Summarized chunk %s/%s in %.2fs",
            index,
            len(retained_chunks),
            perf_counter() - started,
        )

    return notes


def generate_chunked_summary(transcript, backend, template_name):
    started = perf_counter()
    lines = filter_long_transcript_lines(transcript.splitlines())
    chunk_groups = chunk_transcript_line_groups(lines)
    chunk_groups = trim_low_information_tail_chunks(chunk_groups)
    chunk_notes = summarize_chunk_notes(chunk_groups, backend, template_name)
    merge_started = perf_counter()
    merged_summary = generate_text(build_merge_prompt(chunk_notes, template_name), backend)
    logger.info(
        "Merged %s chunk notes in %.2fs (chunked summary total %.2fs)",
        len(chunk_notes),
        perf_counter() - merge_started,
        perf_counter() - started,
    )
    return merged_summary, chunk_notes


def try_repair_summary(invalid_summary, errors, backend, template_name):
    print("[summary] Validation failed. Retrying with repair prompt...", flush=True)
    started = perf_counter()
    repaired_summary = generate_text(build_repair_prompt(invalid_summary, errors, template_name), backend)
    logger.info("Generated repair summary in %.2fs", perf_counter() - started)
    return repaired_summary, validate_summary(repaired_summary, template_name)


def resolve_summary_format(requested_format, transcript_lines, transcript_path=None):
    if requested_format == "auto":
        return detect_summary_format(transcript_lines, transcript_path), True
    return requested_format, False


def generate_summary_markdown(transcript, backend, summary_format, transcript_lines, transcript_path=None):
    started = perf_counter()
    template_name, detected = resolve_summary_format(summary_format, transcript_lines, transcript_path)
    logger.info(
        "Using summary format %s (%s)",
        template_name,
        "auto-detected" if detected else "explicit/profile default",
    )
    chunk_notes = None

    if len(transcript) <= DIRECT_SUMMARY_MAX_CHARS:
        direct_started = perf_counter()
        summary = generate_text(build_prompt(transcript, template_name), backend)
        logger.info("Generated direct summary in %.2fs", perf_counter() - direct_started)
    else:
        print("[summary] Using chunked summarization...", flush=True)
        summary, chunk_notes = generate_chunked_summary(transcript, backend, template_name)

    errors = validate_summary(summary, template_name)
    if not errors:
        logger.info("Completed summary generation in %.2fs", perf_counter() - started)
        final_summary = sanitize_summary_output(summary, template_name, transcript_lines)
        final_summary = sanitize_commitment_sections(final_summary, template_name)
        return final_summary, template_name, detected

    repaired_summary, repaired_errors = try_repair_summary(summary, errors, backend, template_name)
    if not repaired_errors:
        logger.info("Completed summary generation in %.2fs after repair", perf_counter() - started)
        final_summary = sanitize_summary_output(repaired_summary, template_name, transcript_lines)
        final_summary = sanitize_commitment_sections(final_summary, template_name)
        return final_summary, template_name, detected

    if chunk_notes is None:
        print("[summary] Falling back to chunked summarization...", flush=True)
        summary, chunk_notes = generate_chunked_summary(transcript, backend, template_name)
        errors = validate_summary(summary, template_name)
        if not errors:
            logger.info("Completed summary generation in %.2fs after chunk fallback", perf_counter() - started)
            final_summary = sanitize_summary_output(summary, template_name, transcript_lines)
            final_summary = sanitize_commitment_sections(final_summary, template_name)
            return final_summary, template_name, detected

        repaired_summary, repaired_errors = try_repair_summary(summary, errors, backend, template_name)
        if not repaired_errors:
            logger.info(
                "Completed summary generation in %.2fs after chunk fallback repair",
                perf_counter() - started,
            )
            final_summary = sanitize_summary_output(repaired_summary, template_name, transcript_lines)
            final_summary = sanitize_commitment_sections(final_summary, template_name)
            return final_summary, template_name, detected

    print("[summary] Rebuilding final summary from chunk notes...", flush=True)
    recovery_started = perf_counter()
    recovered_summary = generate_text(
        build_notes_recovery_prompt(chunk_notes, repaired_errors, template_name),
        backend,
    )
    logger.info("Generated recovery summary in %.2fs", perf_counter() - recovery_started)
    recovery_errors = validate_summary(recovered_summary, template_name)

    if recovery_errors:
        joined_errors = "; ".join(recovery_errors)
        raise ValueError(f"Summary validation failed after recovery: {joined_errors}")

    logger.info("Completed summary generation in %.2fs after recovery", perf_counter() - started)
    final_summary = sanitize_summary_output(recovered_summary, template_name, transcript_lines)
    final_summary = sanitize_commitment_sections(final_summary, template_name)
    return final_summary, template_name, detected


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize a WhisperX transcript JSON file.")
    add_log_level_arg(parser)
    parser.add_argument("transcript_json", help="Path to the transcript JSON file.")
    parser.add_argument("--profile", default="default", help="Profile name or path to JSON.")
    parser.add_argument("--output", help="Output markdown path. Defaults beside the transcript JSON.")
    parser.add_argument(
        "--summary-format",
        choices=SUMMARY_FORMAT_CHOICES,
        default=None,
        help="Summary template to use. Defaults to the active profile, with auto-detection supported.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    configure_logging(args.log_level)
    transcript_path = Path(args.transcript_json).expanduser().resolve()

    if not transcript_path.exists():
        logger.error("Transcript file not found: %s", transcript_path)
        print(f"Error: file not found: {transcript_path}")
        return 1

    profile = load_profile(args.profile)

    print("[0/4] Loading transcript...", flush=True)
    transcript, transcript_source, transcript_lines = load_transcript(transcript_path)

    if not transcript.strip():
        logger.error("Transcript contains no usable text: %s", transcript_path)
        print("Error: transcript contains no usable text.")
        return 1

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

    print(f"[0/4] Loaded transcript chars: {len(transcript):,}", flush=True)
    requested_format = args.summary_format or profile["summary"]["format"]
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
    print(f"[0/4] Prompt chars: {len(prompt):,}", flush=True)
    print("[1/4] Generating summary...", flush=True)

    try:
        summary, _, _ = generate_summary_markdown(
            transcript,
            profile["summary_backend"],
            requested_format,
            transcript_lines,
            transcript_path,
        )
    except (ValueError, requests.RequestException) as exc:
        logger.exception("Summary generation failed for %s", transcript_path)
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
