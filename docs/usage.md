# Usage

## Audio Pipeline

Default behavior:

- transcribe with WhisperX
- write transcript JSON and SRT to `transcripts/`
- summarize transcript to markdown in `summaries/`
- index transcript and summary into the shared database

Example:

```bash
python3 noterizer.py audio /path/to/input.mp3
```

Use a different backend/model profile:

```bash
python3 noterizer.py audio /path/to/input.mp3 --profile ollama-light
python3 noterizer.py audio /path/to/input.mp3 --profile openai-compatible-local
```

The OpenAI-compatible profiles are available, but `v0.1.0` was validated with Ollama-based profiles rather than an end-to-end OpenAI-compatible run.

Summary format selection defaults to the active profile. The bundled default uses `auto`, which tries to detect whether a transcript is closer to a meeting or a presentation/keynote.

Override it explicitly when needed:

```bash
python3 noterizer.py audio /path/to/input.mp3 --summary-format meeting
python3 noterizer.py audio /path/to/input.mp3 --summary-format presentation
```

During summarization, the CLI prints both:

- which transcript source was used for summarization (`json` or sibling `srt`)
- which summary format was used (`meeting` or `presentation`, including auto-detected cases)

Custom output directories:

```bash
python3 noterizer.py audio \
  /path/to/input.mp3 \
  --transcripts-dir /path/to/transcripts \
  --summaries-dir /path/to/summaries
```

Keep only JSON transcript output from the main audio pipeline:

```bash
python3 noterizer.py audio /path/to/input.mp3 --transcript-output json
```

Generate all WhisperX output formats instead of the default JSON + SRT:

```bash
python3 noterizer.py audio /path/to/input.mp3 --transcript-output all
```

Control overwrite behavior for reruns:

```bash
python3 noterizer.py audio /path/to/input.mp3 --overwrite
python3 noterizer.py audio /path/to/input.mp3 --overwrite summary
python3 noterizer.py audio /path/to/input.mp3 --overwrite none
```

Overwrite modes:

- `--overwrite` or `--overwrite both`: regenerate transcript and summary
- `--overwrite transcript`: regenerate transcript and summary
- `--overwrite summary`: keep the transcript, regenerate the summary
- `--overwrite none`: reuse existing outputs when present

Skip indexing:

```bash
python3 noterizer.py audio /path/to/input.mp3 --index none
```

Index only transcript or only summary:

```bash
python3 noterizer.py audio /path/to/input.mp3 --index transcript
python3 noterizer.py audio /path/to/input.mp3 --index summary
```

## Image OCR Pipeline

Default behavior:

- run OCR with the local vision model
- write markdown to `notes/`
- index the markdown into the shared database

Example:

```bash
python3 noterizer.py image /path/to/note.jpg
```

Custom notes directory:

```bash
python3 noterizer.py image /path/to/note.jpg --notes-dir /path/to/notes
```

Skip indexing:

```bash
python3 noterizer.py image /path/to/note.jpg --no-index
```

## Query Indexed Data

Query across everything:

```bash
python3 noterizer.py query "What follow-up items were mentioned?"
```

List indexed sources before narrowing a query:

```bash
python3 noterizer.py query-list
python3 noterizer.py query-list --type summary
python3 noterizer.py query-list --type summary --date 2026-05-13
```

`--source N` uses the numbering from the current filtered source list. Use the same `--type` and `--date` filters for `query-list` and `query` when selecting one source by number.

Use a non-default profile:

```bash
python3 noterizer.py query \
  --profile openai-compatible-local \
  "What technical risks were discussed?"
```

Restrict query to one content type:

```bash
python3 noterizer.py query --type transcript "Who said this?"
python3 noterizer.py query --type summary "What decisions were made?"
python3 noterizer.py query --type image_note "What was written on the whiteboard?"
```

Restrict query to one indexed source:

```bash
python3 noterizer.py query --type summary --source 2 "What were the main topics?"
python3 noterizer.py query --type summary --source-name 260513_1057_ni-connect_keynote-01.summary.md "What was shown?"
```

Restrict query to sources from one date:

```bash
python3 noterizer.py query --type summary --date 2026-05-13 "What themes came up?"
python3 noterizer.py query --type summary --date 260513 --source 2 "What were the main topics?"
```

Control retrieval depth:

```bash
python3 noterizer.py query \
  --results 15 \
  "What technical risks were discussed?"
```

## Shared Database Behavior

The shared database lives at `./noterizer_db` by default.

This is intentionally one combined database, not one database per recording.

Why:

- simpler operational model
- easier cross-file recall
- one query surface across transcript, summary, and OCR note data
- metadata still allows filtering by content type

Standalone scripts now use the same shared profile and database model, so they no longer diverge from the main CLI.

## Output Layout

Typical outputs beside your source files:

```text
project/
├── audio/
│   ├── input.mp3
│   ├── transcripts/
│   │   ├── input.json
│   │   └── input.srt
│   └── summaries/
│       └── input.summary.md
├── images/
│   ├── whiteboard.jpg
│   └── notes/
│       └── whiteboard.note.md
└── noterizer_db/
```

## Convenience One-Off Scripts

If you want manual control over individual steps:

```bash
python3 run_whisperx.py input.mp3
python3 run_whisperx.py input.mp3 --type srt
python3 run_whisperx.py input.mp3 --type both
python3 summarize_transcript.py transcripts/input.json
python3 summarize_transcript.py transcripts/input.json --summary-format presentation
python3 image_to_note.py note.jpg
python3 index_transcript.py transcripts/input.json
python3 ask_memory.py "What did we discuss?"
```

`run_whisperx.py` supports `json`, `srt`, `both`, and `all`. `noterizer.py` is still the supported end-to-end workflow, with JSON + SRT as the default transcript artifacts.
