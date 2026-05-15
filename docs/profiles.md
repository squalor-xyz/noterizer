# Profiles

Profiles are JSON files that define:

- summary backend
- query backend
- embedding backend
- vision backend
- shared database path and collection
- default audio and image behavior

Bundled profiles live in [`../profiles/`](../profiles/).

List them from the CLI:

```bash
python3 noterizer.py profiles
```

## Built-In Profiles

`default`

- local Ollama
- `qwen2.5:14b` for summary and query
- `nomic-embed-text` for embeddings
- `minicpm-v` for OCR

`ollama-light`

- local Ollama
- `qwen2.5:7b` for summary and query
- `llava` for OCR

`openai-compatible-local`

- local server exposing OpenAI-style endpoints
- example URLs use `http://localhost:8000/v1/...`
- update the model names to match your server

`openai-api-template`

- hosted OpenAI-compatible API example
- uses `OPENAI_API_KEY`
- intended as a starting point for a copied local profile

## Supported Backend Kinds

Text:

- `ollama_generate`
- `openai_chat_completions`

Embeddings:

- `ollama_embeddings`
- `openai_embeddings`

Vision:

- `ollama_chat`
- `openai_chat_completions_vision`

## Custom Profile Example

```json
{
  "database": {
    "path": "./noterizer_db"
  },
  "summary_backend": {
    "kind": "openai_chat_completions",
    "url": "http://localhost:8000/v1/chat/completions",
    "model": "my-chat-model",
    "options": {
      "temperature": 0.1
    }
  },
  "query_backend": {
    "kind": "openai_chat_completions",
    "url": "http://localhost:8000/v1/chat/completions",
    "model": "my-chat-model"
  },
  "embedding_backend": {
    "kind": "openai_embeddings",
    "url": "http://localhost:8000/v1/embeddings",
    "model": "my-embedding-model"
  },
  "vision_backend": {
    "kind": "openai_chat_completions_vision",
    "url": "http://localhost:8000/v1/chat/completions",
    "model": "my-vision-model"
  }
}
```

Use it with:

```bash
python3 noterizer.py audio input.mp3 --profile ./profiles/my-stack.local.json
```

## API Keys

Profiles can reference an environment variable:

```json
{
  "summary_backend": {
    "api_key_env": "OPENAI_API_KEY"
  }
}
```

Export it before use:

```bash
export OPENAI_API_KEY=...
```

Do not commit private profile files with secrets. The repo ignores `profiles/*.local.json`.
