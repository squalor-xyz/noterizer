# Changelog

## v0.1.0

First public release.

### Added

- Unified `noterizer.py` CLI for audio, image OCR, query, and profile listing
- Profile-driven backend configuration
- Bundled example profiles
- Shared rotating error log at `./noterizer.log`
- Structured summary formats for `meeting` and `presentation`
- Auto-detected summary format with CLI override support

### Changed

- Main audio pipeline now keeps transcript JSON and SRT by default
- Transcript summarization now prefers a trimmed sibling `.srt` when it is meaningfully shorter than the `.json`
- Long/noisy transcripts use chunked summarization and stronger validation/recovery
- Transcript, summary, and OCR note indexing now use one shared ChromaDB store

### Notes

- Best results currently come from local-first setups with Ollama and WhisperX
- Summary quality is improved, but important outputs should still be skim-reviewed
- Long/noisy recordings and domain-specific technical vocabulary remain the main summary-quality limitations
