# Local Voice Notes Pipeline

## 1. Record audio

Record on the Sony recorder.

Transfer the audio file to Ubuntu, for example:

    ~/voice/input.mp3

---

## 2. Run WhisperX with diarization

### If already logged in with `huggingface-cli`

    whisperx input.mp3 \
      --model large-v3 \
      --language en \
      --diarize \
      --batch_size 2 \
      --compute_type int8 \
      --output_format json \
      --output_dir transcripts

### If using `HF_TOKEN` from `.bashrc`

    source ~/.bashrc

    whisperx input.mp3 \
      --model large-v3 \
      --language en \
      --diarize \
      --hf_token $HF_TOKEN \
      --batch_size 2 \
      --compute_type int8 \
      --output_format json \
      --output_dir transcripts

Output:

    transcripts/input.json

---

## 3. Generate summary notes

Make sure Ollama is running:

    ollama serve

In another terminal:

    python summarize_transcript.py transcripts/input.json

Output:

    transcripts/input.summary.md

Summary includes:

- executive summary
- key topics
- action items
- decisions
- open questions
- people mentioned
- timeline
- notable quotes

---

## 4. Index transcript into vector DB

Make sure embedding model exists:

    ollama pull nomic-embed-text

Run indexing:

    python index_transcript.py transcripts/input.json

This creates:

    ./voice_db

---

## 5. Query conversationally later

Ask questions against indexed transcripts:

    python ask_memory.py "What did Mike ask me to follow up on?"

Examples:

    python ask_memory.py "What conversations mentioned taxes?"

    python ask_memory.py "Summarize discussions about insurance."

    python ask_memory.py "What action items came out of yesterday?"

    python ask_memory.py "Who mentioned HVAC repairs?"

---

# Initial Setup

## Install WhisperX + diarization

    pip install -U whisperx pyannote.audio huggingface_hub

## Hugging Face setup

Create token:

    https://huggingface.co/settings/tokens

Accept model licenses:

    https://huggingface.co/pyannote/speaker-diarization-3.1
    https://huggingface.co/pyannote/segmentation-3.0

Login locally:

    huggingface-cli login

OR export token in `.bashrc`:

    export HF_TOKEN=hf_xxxxxxxxx

Reload:

    source ~/.bashrc

---

## Install Ollama

    curl -fsSL https://ollama.com/install.sh | sh

## Pull models

Main LLM:

    ollama pull qwen2.5:14b

Embedding model:

    ollama pull nomic-embed-text

## Install Python packages

    pip install chromadb requests

---

# Current Architecture

    Sony recorder
      ↓
    MP3 audio
      ↓
    WhisperX large-v3 int8 batch_size 2
      ↓
    diarized JSON transcript
      ↓
    Ollama local summary
      ↓
    Chroma vector DB
      ↓
    ask_memory.py conversational search

---

# Daily Use

For each new recording:

    whisperx input.mp3 \
      --model large-v3 \
      --language en \
      --diarize \
      --batch_size 2 \
      --compute_type int8 \
      --output_format json \
      --output_dir transcripts

Then:

    python summarize_transcript.py transcripts/input.json

Then:

    python index_transcript.py transcripts/input.json

Then query:

    python ask_memory.py "What should I follow up on?"
