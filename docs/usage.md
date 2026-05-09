# Usage

## Audio Pipeline

Default behavior:

- transcribe with WhisperX
- write transcript JSON to `transcripts/`
- summarize transcript to markdown in `summaries/`
- index transcript and summary into the shared database

Example:

```bash
python3 noterizer.py audio /path/to/input.mp3
```

Custom output directories:

```bash
python3 noterizer.py audio \
  /path/to/input.mp3 \
  --transcripts-dir /path/to/transcripts \
  --summaries-dir /path/to/summaries
```

Generate all WhisperX output formats instead of JSON only:

```bash
python3 noterizer.py audio /path/to/input.mp3 --transcript-output all
```

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

Restrict query to one content type:

```bash
python3 noterizer.py query --type transcript "Who said this?"
python3 noterizer.py query --type summary "What decisions were made?"
python3 noterizer.py query --type image_note "What was written on the whiteboard?"
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

The main tradeoff is that old standalone scripts such as `ask_memory.py` still use their earlier database assumptions. Use `noterizer.py query` for the new combined flow.

## Output Layout

Typical outputs beside your source files:

```text
project/
├── audio/
│   ├── input.mp3
│   ├── transcripts/
│   │   └── input.json
│   └── summaries/
│       └── input.summary.md
├── images/
│   ├── whiteboard.jpg
│   └── notes/
│       └── whiteboard.note.md
└── noterizer_db/
```

## Older One-Off Scripts

If you want manual control over individual steps:

```bash
python3 run_whisperx.py input.mp3
python3 summarize_transcript.py transcripts/input.json
python3 image_to_note.py note.jpg
python3 index_transcript.py transcripts/input.json
python3 ask_memory.py "What did we discuss?"
```

Those are preserved, but `noterizer.py` is now the preferred workflow.
