import json
import sys
import time
import requests
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:14b"

TEMPERATURE = 0.1
PROGRESS_INTERVAL_SECONDS = 2

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


def ask_ollama(prompt):
    print("[1/4] Sending prompt to Ollama...", flush=True)

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": TEMPERATURE
            }
        },
        stream=True,
        timeout=600
    )

    response.raise_for_status()

    print("[2/4] Generating notes...", flush=True)

    chunks = []
    approx_words = 0
    last_update = time.time()

    for line in response.iter_lines():
        if not line:
            continue

        data = json.loads(line.decode("utf-8"))

        chunk = data.get("response", "")

        if chunk:
            chunks.append(chunk)
            approx_words += len(chunk.split())

        now = time.time()

        if now - last_update >= PROGRESS_INTERVAL_SECONDS:
            print(f"[progress] ~{approx_words} words generated...", flush=True)
            last_update = now

        if data.get("done"):
            print("[3/4] Generation complete.", flush=True)
            break

    return "".join(chunks).strip()


def build_prompt(transcript):
    return f"""
You are generating permanent private reference notes from a transcript.

Your job is information preservation and extraction, NOT executive storytelling.

Write dense, factual, technically precise notes.

Domain glossary:
{DOMAIN_GLOSSARY}

Glossary rules:
- If the transcript uses a term from the glossary, use the glossary meaning.
- If a term is not in the glossary and is not explicitly expanded in the transcript, do not expand it.
- Do not guess acronym meanings.

Entity rules:
- Do NOT identify a person, company, product, team, or organization unless the transcript explicitly identifies it as such.
- Do NOT say "John's company", "Sean's company", or similar unless the transcript explicitly says that.
- Do NOT say an acronym is a company, product, or organization unless explicitly stated.
- If a relationship is unclear, write "relationship unclear" or "not specified".
- Preserve the wording from the transcript rather than assigning entity types.

Critical rules:
- Preserve concrete details from the transcript.
- Prefer exact facts over polished summaries.
- Preserve implementation details, architecture ideas, constraints, commands, parameters, filenames, APIs, tooling, company names, timelines, technical tradeoffs, and reasoning.
- Do NOT generalize specific technical discussions into vague business language.
- Do NOT rewrite the conversation into a polished narrative.
- Do NOT add conversational filler.
- Do NOT add conclusions, encouragement, pleasantries, or assistant-style statements.
- Do NOT include greetings, closings, offers, apologies, or phrases like "let me know", "if you need", "I can", "happy to help", or "feel free".
- Do NOT infer emotions, motivations, agreement, excitement, or business intent unless explicitly stated.
- Do NOT invent details.
- Do NOT add advice unless the transcript itself includes it.
- Do NOT optimize for readability over information retention.
- If information is ambiguous, state the ambiguity.
- If a section has no relevant information, write "Not mentioned."
- Keep speaker labels and timestamps when they help preserve context.
- Use concise Markdown.
- Never convert a technical term into a company or organization.
- Never assign ownership, employer, customer, or role relationships unless explicitly stated.

Acronym and terminology rules:
- Do NOT expand acronyms unless the transcript explicitly expands them or the term is in the Domain glossary.
- Do NOT guess what abbreviations mean.
- Preserve acronyms exactly as spoken or transcribed.
- If an acronym or term may be ambiguous, list it under "# Ambiguous / Unverified Terms".
- Example: if the transcript says "FEM", write "FEM / Front End Module" because FEM is defined in the Domain glossary.
- If the transcript appears to contain a transcription error, mark it as uncertain instead of correcting it silently.

Technical preservation rules:
- Capture specific product/system names.
- Capture workflow details.
- Capture software architecture ideas.
- Capture deployment ideas.
- Capture data privacy/security concerns.
- Capture customer/user segmentation.
- Capture business model details only when tied to the technical plan.
- Capture integration points, data systems, databases, networks, hardware/software interfaces, and multi-tenant/separate-instance discussions.
- Preserve exact terms even if they seem domain-specific or unclear.

Avoid generic phrases such as:
- "the discussion revolves around"
- "both expressed interest"
- "challenging yet rewarding"
- "moving forward"
- "mutual appreciation"
- "current context and background"
- "closing thoughts"
- "ends on a positive note"
- "look forward to future discussions"

Output EXACTLY these sections:

# Executive Summary

Keep this short: 3-5 bullets maximum. No narrative wrap-up.

# Key Facts

Concrete facts only. Use bullets.

# Main Topics Discussed

Use bullets. Avoid generic labels.

# Technical Details

Preserve exact technologies, systems, acronyms, settings, filenames, tools, model names, parameters, errors, constraints, implementation details, system architecture details, troubleshooting notes, numeric values, and tradeoffs when present.

Do not expand acronyms unless explicitly expanded in the transcript or defined in the Domain glossary.

# Architecture / System Ideas

Include platform structure, deployment model, data separation, instances, networking, databases, integrations, and system boundaries if discussed.

# Business / Product Details

Only include business model, customer, pricing, market, or sales details if actually discussed.

# Constraints / Risks / Concerns

Include privacy, security, sales, time, technical feasibility, customer adoption, data separation, or implementation risks if discussed.

# Action Items

Include owner, task, and due date if stated.

# Decisions Made

# Open Questions

# Ambiguous / Unverified Terms

List acronyms, unclear words, possible transcription errors, or terms that should not be guessed.

# People Mentioned

# Chronological Timeline

Use timestamps when useful.

# Important Quotes

Only include quotes that are unusually important, precise, or technically meaningful.

# Next Steps

Only include next steps explicitly stated or clearly implied by the transcript.

Transcript:

{transcript}
""".strip()


def main():
    if len(sys.argv) < 2:
        print("Usage: python summarize_transcript.py transcripts/input.json")
        sys.exit(1)

    transcript_path = Path(sys.argv[1])

    if not transcript_path.exists():
        print(f"Error: file not found: {transcript_path}")
        sys.exit(1)

    print("[0/4] Loading transcript...", flush=True)

    transcript = load_transcript(transcript_path)

    if not transcript.strip():
        print("Error: transcript contains no usable text.")
        sys.exit(1)

    print(f"[0/4] Loaded transcript chars: {len(transcript):,}", flush=True)

    prompt = build_prompt(transcript)

    print(f"[0/4] Prompt chars: {len(prompt):,}", flush=True)

    summary = ask_ollama(prompt)

    out_path = transcript_path.with_suffix(".summary.md")

    print(f"[4/4] Writing notes to {out_path}", flush=True)

    out_path.write_text(summary + "\n")

    print("[done]", flush=True)


if __name__ == "__main__":
    main()
