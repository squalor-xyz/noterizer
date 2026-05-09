# Noterizer

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

Image OCR:

```bash
python3 noterizer.py image /path/to/note.jpg
```

Query everything together:

```bash
python3 noterizer.py query "What action items were discussed?"
```

Filter query to summaries only:

```bash
python3 noterizer.py query \
  --type summary \
  "What decisions were made?"
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
├── whisper-cmd.txt
├── README.MD
└── docs/
    ├── setup.md
    └── usage.md
```

## Existing Scripts

Legacy step-by-step scripts are still kept:

- `run_whisperx.py`
- `summarize_transcript.py`
- `index_transcript.py`
- `ask_memory.py`
- `image_to_note.py`

Use them if you want one step at a time or need to inspect a single stage. For normal use, `noterizer.py` is the supported primary interface.

## Documentation

- Setup: [docs/setup.md](./docs/setup.md)
- Usage: [docs/usage.md](./docs/usage.md)
