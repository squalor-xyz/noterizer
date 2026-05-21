# Noterizer

Local-first audio transcription, structured summarization, OCR note capture, and semantic recall.

Local-first pipeline for:

- audio transcription with WhisperX
- speaker diarization
- transcript summarization with Ollama
- image OCR to markdown
- semantic indexing with ChromaDB
- querying across transcripts, summaries, and image notes

The main entrypoint is [`noterizer.py`](./noterizer.py).

License: MPL 2.0. See [LICENSE](./LICENSE).

## What It Does

Audio flow:

```text
audio file
  -> transcripts/<name>.json
  -> transcripts/<name>.srt
  -> summaries/<name>.summary.md
  -> shared Chroma database
```

Image flow:

```text
image file
  -> notes/<name>.note.md
  -> shared Chroma database
```

Query flow:

```text
question
  -> retrieve relevant chunks from transcript/summary/image-note data
  -> answer with local LLM
```

## Quick Start

Install dependencies:

```bash
pip install -r requirements.txt
```

Audio:

```bash
python3 noterizer.py audio /path/to/input.mp3
```

By default, the main audio pipeline keeps both transcript JSON and SRT outputs.
It also defaults to `summary.format: auto`, which tries to pick a meeting-style or presentation-style summary template based on the transcript.
During summarization, the CLI prints which transcript source and summary format were used.

Image OCR:

```bash
python3 noterizer.py image /path/to/note.jpg
```

Query everything together:

```bash
python3 noterizer.py query "What action items were discussed?"
```

List indexed summaries before narrowing a query:

```bash
python3 noterizer.py query-list
python3 noterizer.py query-list --type summary --date 2026-05-13
python3 noterizer.py query --type summary --source 2 "What were the main topics?"
```

`--source N` uses the numbering from the current filtered source list. In practice, run `query-list` with the same `--type` and `--date` filters first, then use that numbered result with `query`.

Filter query to summaries only:

```bash
python3 noterizer.py query \
  --type summary \
  "What decisions were made?"
```

List bundled profiles:

```bash
python3 noterizer.py profiles
```

## Profiles

Profiles live in [`profiles/`](./profiles/) and let you swap models, endpoints, and database defaults without editing code.

Bundled profiles include:

- `default`: local Ollama-based setup
- `ollama-light`: lighter Ollama model choices
- `openai-compatible-local`: local server exposing OpenAI-style `/v1/*` endpoints
- `openai-api-template`: template for hosted OpenAI-compatible APIs using `OPENAI_API_KEY`

The bundled OpenAI-compatible profile examples are included as configuration starting points, but they were not exercised end to end for `v0.1.0`. This release was tested with Ollama-based profiles.

Use a profile by name:

```bash
python3 noterizer.py audio input.mp3 --profile ollama-light
python3 noterizer.py query "What changed?" --profile openai-compatible-local
```

Use a custom local profile file:

```bash
python3 noterizer.py audio input.mp3 --profile ./profiles/my-stack.local.json
```

Override the summary template explicitly:

```bash
python3 noterizer.py audio input.mp3 --summary-format meeting
python3 noterizer.py audio input.mp3 --summary-format presentation
```

Control rerun behavior explicitly:

```bash
python3 noterizer.py audio input.mp3 --overwrite
python3 noterizer.py audio input.mp3 --overwrite summary
python3 noterizer.py audio input.mp3 --overwrite none
```

## Database Model

This repo now uses one shared database for all indexed content in `./noterizer_db`.

That is the sane default. It does not need to be 1:1 per audio file.

The database stores chunk metadata such as:

- `content_type`: `transcript`, `summary`, or `image_note`
- `source_name`
- `source_path`
- transcript timestamps and speakers when available
- markdown section names for summaries and OCR notes

That lets you query everything together while still filtering by content type when needed.

## Repo Layout

```text
noterizer/
├── noterizer.py
├── run_whisperx.py
├── summarize_transcript.py
├── index_transcript.py
├── ask_memory.py
├── image_to_note.py
├── noterizer_core.py
├── profiles/
│   ├── default.json
│   ├── ollama-light.json
│   └── ...
├── whisper-cmd.txt
├── README.MD
└── docs/
    ├── releases/
    ├── profiles.md
    ├── roadmap.md
    ├── setup.md
    └── usage.md
```

## Existing Scripts

Convenience step-by-step scripts are still kept:

- `run_whisperx.py`
- `summarize_transcript.py`
- `index_transcript.py`
- `ask_memory.py`
- `image_to_note.py`

They share the same profile model and database defaults as `noterizer.py`. Use them if you want one step at a time. For normal use, `noterizer.py` is the supported primary interface.

`run_whisperx.py` supports transcript-only output selection with `--type json`, `--type srt`, `--type both`, or `--type all`.

## Documentation

- Setup: [docs/setup.md](./docs/setup.md)
- Usage: [docs/usage.md](./docs/usage.md)
- Profiles: [docs/profiles.md](./docs/profiles.md)
- Roadmap: [docs/roadmap.md](./docs/roadmap.md)

## Logging

Pipeline scripts write errors to a shared rotating log at `./noterizer.log`.
Use `--log-level INFO` when you want more detail in that file, including per-step timing data for transcription, summarization, indexing, OCR, and query.

## Current Limitations

- Human skim review is still recommended for important summaries.
- Long or noisy recordings can degrade summary quality, especially when the recording continues after the real meeting or talk has ended.
- Domain-specific technical vocabulary can still be mis-transcribed by WhisperX and then misinterpreted by the summary model.
- Conference/keynote-style recordings with uncommon RF or engineering terminology are currently the highest-risk case.
- The OpenAI-compatible profile paths are bundled but were not validated end to end for this release; Ollama is the tested backend path for `v0.1.0`.
