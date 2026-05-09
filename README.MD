# Local AI Knowledge Capture Pipeline

## Overview

This repository documents a fully local-first AI pipeline for:

- Long-form audio transcription
- Speaker diarization
- Technical note extraction
- Local LLM summarization
- Image/note OCR extraction
- Semantic indexing
- Conversational querying over historical data

The system is designed for:

- Privacy-sensitive workflows
- Offline/local AI usage
- Technical conversations
- Engineering discussions
- Research and development workflows
- Personal knowledge management
- Long-term searchable memory

The pipeline avoids cloud AI services after initial model downloads.

---

# Architecture

```text
Audio Recorder / Images
        ↓
WhisperX + Diarization
        ↓
Structured Transcript JSON
        ↓
Local LLM Summarization
        ↓
Markdown Notes
        ↓
Embedding Generation
        ↓
Chroma Vector Database
        ↓
Conversational Querying
```

---

# Components

| Component | Purpose |
|---|---|
| WhisperX | Audio transcription + timestamps |
| pyannote.audio | Speaker diarization |
| Ollama | Local LLM inference |
| Qwen / Llama / Mistral | Summarization models |
| MiniCPM-V / LLaVA | Vision/OCR models |
| ChromaDB | Local vector database |
| nomic-embed-text | Embedding model |
| Python scripts | Pipeline orchestration |

---

# Privacy Model

This pipeline is intended to operate locally.

Audio, transcripts, summaries, embeddings, and images remain on the local machine.

Exceptions:
- Hugging Face token/model download during setup
- Optional model downloads from Ollama registry

After models are installed, inference is local.

---

# Recommended Hardware

## Minimum

- Modern CPU
- 32GB RAM
- 6GB+ VRAM GPU

## Recommended

- NVIDIA GPU with CUDA support
- 8GB+ VRAM
- 64GB RAM

## Ideal

- 12GB–24GB VRAM
- Large local SSD
- Fast CPU

---

# Directory Structure

```text
project/
├── transcripts/
│   ├── input.json
│   ├── input.summary.md
│   └── ...
│
├── notes/
│   └── handwritten.note.md
│
├── voice_db/
│   └── chroma database files
│
├── summarize_transcript.py
├── index_transcript.py
├── ask_memory.py
├── image_to_note.py
└── README.md
```

---

# Setup

# 1. Python Environment

Recommended:

```bash
python -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -U \
    whisperx \
    pyannote.audio \
    huggingface_hub \
    chromadb \
    requests
```

---

# 2. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Verify:

```bash
ollama --version
```

---

# 3. Pull Models

## Summarization Models

Recommended:

```bash
ollama pull qwen2.5:7b
```

Alternative:

```bash
ollama pull llama3.1:8b
ollama pull mistral:7b
```

---

## Embedding Model

```bash
ollama pull nomic-embed-text
```

---

## Vision Models

Recommended:

```bash
ollama pull minicpm-v
```

Alternatives:

```bash
ollama pull llava
ollama pull llama3.2-vision
```

---

# 4. Hugging Face Setup

Required for diarization.

Create token:

```text
https://huggingface.co/settings/tokens
```

Accept licenses:

```text
https://huggingface.co/pyannote/speaker-diarization-3.1
https://huggingface.co/pyannote/segmentation-3.0
```

Login:

```bash
huggingface-cli login
```

OR export token:

```bash
export HF_TOKEN=hf_xxxxxxxxx
```

---

# Audio Pipeline

# Purpose

Convert long-form audio into:
- diarized transcripts
- technical notes
- searchable knowledge

---

# Audio → Transcript

Preferred wrapper:

```bash
python run_whisperx.py input.mp3
```

Other useful variants:

```bash
python run_whisperx.py input.mp3 --type json
python run_whisperx.py input.mp3 --type srt
python run_whisperx.py input.mp3 --output-dir ./transcripts
```

The wrapper reads the baseline WhisperX flags from `whisper-cmd.txt` and defaults output to a `transcripts/` directory beside the audio file.

Equivalent raw WhisperX command:

```bash
whisperx input.mp3 \
  --model large-v3 \
  --language en \
  --diarize \
  --batch_size 2 \
  --compute_type int8 \
  --output_format json \
  --output_dir transcripts
```

Alternative with explicit token:

```bash
whisperx input.mp3 \
  --model large-v3 \
  --language en \
  --diarize \
  --hf_token $HF_TOKEN \
  --batch_size 2 \
  --compute_type int8 \
  --output_format json \
  --output_dir transcripts
```

Output:

```text
transcripts/input.json
```

---

# WhisperX Notes

## VRAM Optimization

Recommended for lower-memory GPUs:

```bash
--compute_type int8
--batch_size 2
```

Reduce further if necessary:

```bash
--batch_size 1
```

Alternative model:

```bash
--model medium
```

---

# Diarization Notes

WhisperX loads:
- transcription model
- alignment model
- diarization model

simultaneously.

Diarization significantly increases memory usage.

---

# Transcript JSON Format

Example:

```json
{
  "start": 12.4,
  "end": 16.2,
  "speaker": "SPEAKER_00",
  "text": "We should separate customer instances."
}
```

---

# Summarization Pipeline

# Purpose

Convert transcripts into:
- technical notes
- architectural memory
- action items
- searchable summaries

---

# Run Summarization

```bash
python summarize_transcript.py transcripts/input.json
```

Output:

```text
transcripts/input.summary.md
```

---

# Summarization Design Goals

The summarizer is optimized for:

- information preservation
- technical accuracy
- low hallucination
- minimal conversational filler
- archival/reference usage

The prompt intentionally avoids:
- executive-summary fluff
- assistant-style phrasing
- inferred emotions/motivations
- speculative business language

---

# Important Prompt Design Rules

The summarizer prompt includes:
- anti-hallucination rules
- acronym preservation
- glossary support
- technical-detail retention
- ambiguity tracking

Example:

```text
Do NOT expand acronyms unless explicitly expanded in the transcript.
```

---

# Domain Glossary

Supported in prompt:

```python
DOMAIN_GLOSSARY = """
Known terminology:
- FEM = Front End Module
"""
```

Glossary entries override model guessing.

---

# Recommended Model Settings

Recommended:

```python
TEMPERATURE = 0.1
```

Low temperature reduces:
- hallucination
- paraphrasing
- speculative synthesis
- narrative behavior

---

# Progress Output

The summarizer streams progress updates:

```text
[0/4] Loading transcript...
[1/4] Sending prompt to Ollama...
[2/4] Generating notes...
[progress] ~500 words generated...
[3/4] Generation complete.
[4/4] Writing notes...
```

---

# Embedding + Vector Database Pipeline

# Purpose

Enable:
- semantic search
- conversational memory
- historical querying
- cross-session recall

---

# Index Transcript

```bash
python index_transcript.py transcripts/input.json
```

Creates:

```text
./voice_db
```

using ChromaDB.

---

# Embedding Model

Recommended:

```text
nomic-embed-text
```

Used for:
- transcript chunk embeddings
- semantic retrieval
- RAG context selection

---

# Conversational Querying

# Query Historical Data

```bash
python ask_memory.py \
  "What action items were discussed about the database?"
```

Examples:

```bash
python ask_memory.py \
  "Who mentioned networking concerns?"

python ask_memory.py \
  "Summarize discussions about customer isolation."

python ask_memory.py \
  "What technical risks were discussed?"
```

---

# Retrieval Design

Current implementation:
- chunk-level embedding search
- semantic retrieval
- local RAG

Future improvements:
- hierarchical chunking
- recursive summarization
- metadata filtering
- time-based retrieval
- speaker-aware retrieval

---

# Image / Handwritten Note Pipeline

# Purpose

Convert images into:
- OCR text
- technical notes
- searchable memory

---

# Run OCR Extraction

```bash
python image_to_note.py notes.jpg
```

Output:

```text
notes.note.md
```

---

# Recommended Vision Models

Best local options:

| Model | Notes |
|---|---|
| MiniCPM-V | Best OCR/document extraction |
| LLaVA | General vision |
| llama3.2-vision | General multimodal reasoning |

Recommended:

```python
MODEL = "minicpm-v"
```

---

# OCR Prompt Design

The OCR prompt is intentionally strict:

```text
- Do NOT summarize
- Do NOT interpret
- Do NOT infer missing words
- Preserve structure
```

This improves:
- technical extraction
- OCR fidelity
- low hallucination behavior

---

# Handwriting Notes

Local handwriting OCR remains imperfect.

Performance depends heavily on:
- image quality
- contrast
- lighting
- handwriting clarity
- camera angle

Best practices:
- photograph straight down
- crop tightly
- use high contrast
- avoid cursive
- use larger writing

---

# Recommended Workflow

For handwritten notes:

```text
photo
  ↓
local OCR extraction
  ↓
human cleanup
  ↓
summary/index
```

---

# AI-Ingestable Design Notes

This repository is intentionally structured for:
- future LLM ingestion
- semantic indexing
- machine-readable workflows
- deterministic pipeline behavior

Design goals:
- explicit structure
- low ambiguity
- preserved technical detail
- minimized hallucination
- stable Markdown outputs

---

# Common Issues

# Ollama VRAM Problems

Symptoms:
- slow generation
- model unloading
- crashes
- CPU fallback

Solutions:
- smaller models
- lower quantization
- fewer concurrent models
- reduce transcript size

---

# WhisperX Out of Memory

Solutions:

```bash
--batch_size 1
--compute_type int8
```

Alternative:

```bash
--model medium
```

---

# Acronym Hallucination

Problem:
- model expands undefined acronyms incorrectly

Solution:
- strict prompt rules
- domain glossary
- ambiguity section

---

# OCR Hallucinations

Vision models may:
- invent words
- normalize handwriting incorrectly
- summarize instead of extract

Mitigations:
- strict OCR prompts
- low temperature
- human review
- improved image quality

---

# Future Improvements

Potential upgrades:

- automated chunking
- recursive summarization
- speaker identity mapping
- local web UI
- timestamp linking
- Obsidian integration
- SQLite metadata store
- hybrid BM25 + vector retrieval
- transcript deduplication
- daily memory synthesis
- automatic topic extraction
- local agent workflows

---

# Summary

This pipeline provides:

- fully local AI workflows
- audio transcription
- diarization
- technical summarization
- semantic memory
- OCR ingestion
- conversational querying
- privacy-focused operation

Primary strengths:
- privacy
- extensibility
- technical note preservation
- offline/local capability
- searchable historical memory
