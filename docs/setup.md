# Setup

## 1. Python Environment

Recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install Python dependencies:

```bash
pip install -U \
  whisperx \
  pyannote.audio \
  huggingface_hub \
  chromadb \
  requests
```

## 2. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Verify:

```bash
ollama --version
```

## 3. Pull Models

Chat / summarization model:

```bash
ollama pull qwen2.5:14b
```

Embedding model:

```bash
ollama pull nomic-embed-text
```

Vision OCR model:

```bash
ollama pull minicpm-v
```

Alternatives:

```bash
ollama pull llama3.1:8b
ollama pull mistral:7b
ollama pull llava
ollama pull llama3.2-vision
```

## 4. Hugging Face Setup for Diarization

WhisperX diarization requires Hugging Face access to pyannote models.

Create a token:

```text
https://huggingface.co/settings/tokens
```

Accept these licenses:

```text
https://huggingface.co/pyannote/speaker-diarization-3.1
https://huggingface.co/pyannote/segmentation-3.0
```

Then either log in locally:

```bash
huggingface-cli login
```

Or export a token:

```bash
export HF_TOKEN=hf_xxxxxxxxx
```

If you use shell startup files, reload them:

```bash
source ~/.bashrc
```

## 5. WhisperX Command Baseline

This repo keeps the baseline WhisperX flags in [`whisper-cmd.txt`](../whisper-cmd.txt).

Current defaults:

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

`run_whisperx.py` and `noterizer.py` both use that file.

## 6. Recommended Hardware

Minimum:

- modern CPU
- 32GB RAM
- 6GB+ VRAM GPU

Recommended:

- NVIDIA GPU with CUDA support
- 8GB+ VRAM
- 64GB RAM

Ideal:

- 12GB-24GB VRAM
- large local SSD
- fast CPU

## 7. Verify Local Services

Ollama should be running before summarization, OCR, indexing, or query:

```bash
ollama serve
```

Sanity checks:

```bash
python3 noterizer.py --help
python3 noterizer.py audio --help
python3 noterizer.py image --help
python3 noterizer.py query --help
```
