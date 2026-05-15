# Roadmap

This document tracks the planned next stages for Noterizer.

Keep this file current as priorities change so the roadmap stays aligned with the rest of the docs.

## Near Term

### 1. Web UI foundation

Goal:

- add a local-first web UI without duplicating CLI/domain logic

Scope for the first usable version:

- select one or more audio files for processing
- select an image for OCR
- choose a profile
- choose overwrite behavior for audio outputs
- monitor job progress and final output paths
- view generated transcript JSON, summary markdown, and OCR note markdown
- run cross-document queries against the shared database
- list bundled profiles and basic profile details

Out of scope for the first version:

- user accounts
- remote multi-user hosting
- auth
- permissions model
- background distributed workers
- browser-side audio transcription
- in-browser transcript editing

Recommended stack:

- `FastAPI`
- server-rendered `Jinja2` templates
- small amount of vanilla JS or HTMX-style enhancement

Key prerequisite:

- extract reusable service-style functions from `noterizer.py` so the UI calls Python APIs, not CLI/stdout behavior

Planned backend structure:

- `webapp.py`
- `web_jobs.py`
- `web_models.py`
- `templates/`
- `static/`

Recommended first slice:

- `GET /` dashboard
- `POST /audio-jobs`
- `GET /audio-jobs/{id}`
- `POST /query`
- `POST /image-jobs`

Implementation phases:

1. Backend readiness
2. Minimal local UI
3. Output inspection
4. Better operability
5. Nice-to-have improvements

### 2. Query validation and polish

Goal:

- exercise and harden the shared query workflow against real indexed data

Focus areas:

- smoke-test query across transcript, summary, and image-note content
- verify type-filtered retrieval quality
- verify answer grounding and source usefulness
- confirm query behavior under different profiles

### 3. Logging coverage audit

Goal:

- ensure important pipeline failures are consistently written to `./noterizer.log`

Focus areas:

- batch per-file failures
- WhisperX command failures
- summary validation/recovery failures
- query-path backend failures

## Medium Term

### Summary quality hardening

Focus areas:

- continue reducing hallucinated technical terms
- improve presentation-summary accuracy for noisy conference recordings
- tighten factual confidence around `People Mentioned`, technical details, and claims
- evaluate whether additional transcript-cleaning heuristics are needed before summarization

### Operational improvements

Focus areas:

- better GPU/VRAM coordination between WhisperX and Ollama
- faster summarization for chunked long transcripts
- clearer progress reporting across long-running operations

## Longer Term

### Better local workflows

Ideas:

- rerun selected pipeline steps only
- persistent job history
- local profile editor for `.local.json` files
- richer output browsing and inspection tools

### Broader deployment options

Ideas:

- optional non-local hosting model
- stronger security model if UI moves beyond localhost
- more robust background job execution model

## Open Questions

- Should the web UI support browser uploads, local file paths, or both?
- Should job history persist across restarts?
- Should transcript and summary content be editable later?
- Should query results show raw retrieved chunks by default?
- Should the UI expose all CLI flags or only the common path?
