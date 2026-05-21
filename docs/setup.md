# Setup

## 1. Python Environment

This repo assumes you are running commands from the repo root:

```bash
cd /path/to/noterizer
```

If you are brand new to this stack, the shortest path is:

1. Create and activate a Python virtual environment
2. Install Python dependencies
3. Install and start Ollama
4. Pull the Ollama models used by the default profile
5. Log in to Hugging Face for WhisperX diarization
6. Run one small audio file end to end

You do not need to understand every component before the first run.

Recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Equivalent manual install:

```bash
pip install -U \
  whisperx \
  pyannote.audio \
  huggingface_hub \
  chromadb \
  requests
```

System tools you will usually need:

- `ffmpeg` for audio handling
- NVIDIA CUDA drivers if you want GPU WhisperX

If `ffmpeg` is missing, install it with your OS package manager before continuing.

## 2. Choose a Backend Style

This repo can work with:

- local Ollama
- local OpenAI-compatible servers such as vLLM, LocalAI, or LM Studio
- hosted OpenAI-compatible APIs

For `v0.1.0`, the tested path is local Ollama. The bundled OpenAI-compatible profiles are included as examples and starting points, but were not validated end to end in release testing.

See [profiles.md](./profiles.md) for profile details.

If you do not want to make backend decisions yet, use the bundled `default` profile first.

## 3. Install Ollama

If you are using an Ollama-based profile such as `default` or `ollama-light`:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Verify:

```bash
ollama --version
```

Start Ollama if it is not already running:

```bash
ollama serve
```

## 4. Pull Models

If you are using an Ollama-based profile, pull the models referenced by that profile:

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

If you are using an OpenAI-compatible local server or hosted API instead, configure the relevant profile and ensure those models are available on that backend.

No separate OpenAI Python SDK is required for those profiles; the current connector path uses `requests` against OpenAI-compatible HTTP endpoints.

For a first successful audio run, you only need:

- `qwen2.5:14b`
- `nomic-embed-text`

You only need `minicpm-v` if you plan to use the image OCR pipeline.

## 5. Hugging Face Setup for Diarization

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

That is the preferred path. The current scripts rely on your Hugging Face CLI login and do not pass `--hf_token` on the generated WhisperX command line.

If you need a shell environment variable for manual testing, you can still export one:

```bash
export HF_TOKEN=hf_xxxxxxxxx
```

If you use shell startup files, reload them:

```bash
source ~/.bashrc
```

If diarization fails later with a pyannote access or authentication error, this is the first section to revisit.

## 6. WhisperX Command Baseline

This repo keeps the baseline WhisperX flags in [`whisper-cmd.txt`](../whisper-cmd.txt).

Baseline example from `whisper-cmd.txt`:

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

`run_whisperx.py` and `noterizer.py` both use that file, but they override `--output_format` at runtime.
They also omit `--hf_token` from the generated command and rely on your existing Hugging Face login.

Current script behavior:

- `python3 noterizer.py audio ...` defaults to transcript JSON + SRT
- `python3 run_whisperx.py ...` defaults to `--type all`
- `python3 noterizer.py audio ...` defaults to `summary.format: auto`

During summarization, the CLI now prints which transcript source was used:

- JSON transcript
- sibling SRT transcript, when it looks intentionally trimmed/cleaner

It also prints which summary format was chosen:

- `meeting`
- `presentation`
- `auto-detected` when `summary.format` is `auto`

## 7. First Successful Run

Use one small audio file first, not a large batch.

Example:

```bash
python3 noterizer.py audio /path/to/example.mp3
```

What the default audio pipeline does:

- transcribes the audio with WhisperX
- writes `transcripts/example.json`
- writes `transcripts/example.srt`
- generates `summaries/example.summary.md`
- indexes transcript and summary content into `./noterizer_db`

What you should expect to see in the terminal:

- WhisperX command execution
- a line showing which transcript source is being summarized
- a line showing which summary format is being used
- a final summary write message
- indexing messages

Typical success artifacts beside your source file:

```text
audio-dir/
├── example.mp3
├── transcripts/
│   ├── example.json
│   └── example.srt
└── summaries/
    └── example.summary.md
```

If that works, then test retrieval:

```bash
python3 noterizer.py query "What was discussed?"
```

Once you have many indexed files, list sources before narrowing a query:

```bash
python3 noterizer.py query-list --type summary
python3 noterizer.py query-list --type summary --date 2026-05-13
```

Then query one listed source by number using the same filters:

```bash
python3 noterizer.py query --type summary --date 2026-05-13 --source 2 "What were the main topics?"
```

## 8. Minimal Verification Checklist

Use these checks in order if you are unsure what is broken.

Python environment:

```bash
python3 --version
python3 noterizer.py --help
```

Ollama:

```bash
ollama ps
```

WhisperX-only step:

```bash
python3 run_whisperx.py /path/to/example.mp3 --type both
```

Summary-only step:

```bash
python3 summarize_transcript.py /path/to/transcripts/example.json
```

Query path:

```bash
python3 noterizer.py query "What happened?"
python3 noterizer.py query-list --type summary
```

## 9. Recommended Hardware

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

## 10. Verify Local Services

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
python3 noterizer.py profiles
```

## 11. Logging

Pipeline scripts write to one shared rotating log file:

```text
./noterizer.log
```

Default behavior:

- CLI output stays visible in the terminal
- the log file records `ERROR` and above
- old logs rotate to `noterizer.log.1` and `noterizer.log.2`

Increase log detail when debugging:

```bash
python3 noterizer.py --log-level INFO audio input.mp3
python3 summarize_transcript.py --log-level INFO transcripts/input.json
```

At `INFO` level, the shared log also captures timing data for major steps such as transcription, chunk summarization, indexing, OCR, and query.

## 12. Common Failures

### Hugging Face / pyannote access errors

Symptoms:

- WhisperX fails during diarization
- errors mention `pyannote`, authentication, gated models, or missing access

Check:

- you ran `huggingface-cli login`
- you accepted the required pyannote model licenses

### GPU out-of-memory during WhisperX

Symptoms:

- `RuntimeError: CUDA failed with error out of memory`

Common causes:

- Ollama is already using most of the GPU
- the WhisperX model is too large for available VRAM

Check GPU usage:

```bash
nvidia-smi
ollama ps
```

If Ollama is holding VRAM, stop or unload it before transcription.

### Ollama is slow or keeps reloading

Symptoms:

- summarization works but is slow between chunk steps

Likely reason:

- the model is being loaded, unloaded, and reloaded between requests

This is slower but safer for limited VRAM systems.

### Summary generation fails validation

Symptoms:

- errors mention missing required headings or failed recovery

What it usually means:

- the model returned malformed output
- the transcript is noisy, overlong, or badly transcribed

Things to try:

- rerun summary only:

```bash
python3 noterizer.py audio /path/to/example.mp3 --overwrite summary
```

- force a presentation template for keynote/demo material:

```bash
python3 noterizer.py audio /path/to/example.mp3 --summary-format presentation --overwrite summary
```

- trim the source recording or the `.srt` if the tail contains noise

### Domain-specific technical vocabulary comes out wrong

Symptoms:

- unusual engineering terms, acronyms, product names, or RF/test terminology are transcribed incorrectly
- the summary then repeats those bad terms as if they were real facts

Why this happens:

- WhisperX does not know every domain-specific term in your environment
- the summary model may treat a bad transcript token as if it were a legitimate technical term

Where this is most likely:

- conference talks
- RF/test-measurement presentations
- recordings with many uncommon product names, acronyms, or internal jargon

What helps:

- trim noisy tails before summarization
- keep a cleaner edited sibling `.srt` when possible
- use human skim review for important outputs
- treat unusual technical terms in summaries as suspect unless they match known vocabulary

### OpenAI-compatible profile path has not been release-tested

Symptoms:

- local Ollama profiles work, but you are unsure whether `openai-compatible-local` or `openai-api-template` is production-ready for this release

Current status:

- those profile shapes are supported in code
- they were not exercised end to end during `v0.1.0` release validation
- the tested setup for this release is Ollama-based

### Transcript seems noisy after the real content ended

Symptoms:

- summary contains nonsense from background chatter after the meeting or talk ended

What helps:

- trim the audio earlier before transcription, or
- keep a trimmed sibling `.srt`; the summarizer can prefer it when it is meaningfully shorter than the `.json`

### Nothing shows up in the log

Default behavior writes only `ERROR` and above to `./noterizer.log`.

If you want more detail:

```bash
python3 noterizer.py --log-level INFO audio /path/to/example.mp3
```
