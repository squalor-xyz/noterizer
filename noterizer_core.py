#!/usr/bin/env python3
import base64
import copy
import hashlib
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests


DEFAULT_PROFILE = {
    "database": {
        "path": "./noterizer_db",
        "collection": "memory",
    },
    "summary_backend": {
        "kind": "ollama_generate",
        "url": "http://localhost:11434/api/generate",
        "model": "qwen2.5:14b",
        "options": {
            "temperature": 0.1,
        },
    },
    "query_backend": {
        "kind": "ollama_generate",
        "url": "http://localhost:11434/api/generate",
        "model": "qwen2.5:14b",
        "options": {
            "temperature": 0.1,
        },
    },
    "embedding_backend": {
        "kind": "ollama_embeddings",
        "url": "http://localhost:11434/api/embeddings",
        "model": "nomic-embed-text",
    },
    "vision_backend": {
        "kind": "ollama_chat",
        "url": "http://localhost:11434/api/chat",
        "model": "minicpm-v",
        "options": {
            "temperature": 0.0,
        },
    },
    "audio": {
        "transcripts_dirname": "transcripts",
        "summaries_dirname": "summaries",
        "transcript_output": "both",
        "index": "both",
    },
    "image": {
        "notes_dirname": "notes",
        "index": True,
    },
    "query": {
        "type": "any",
        "results": 10,
    },
}

PROFILES_DIR = Path(__file__).with_name("profiles")
LOG_FILE = Path(__file__).with_name("noterizer.log")

IMAGE_PROMPT = """
Perform OCR extraction on this handwritten note.

Rules:
- Extract text as literally as possible.
- Preserve line breaks and structure.
- Do NOT summarize.
- Do NOT interpret.
- Do NOT rewrite.
- Do NOT infer missing words.
- If text is unclear, write [unclear].
- Preserve technical terms exactly.
- Preserve arrows, bullets, indentation, and labels.
- Output Markdown only.
""".strip()


def add_log_level_arg(parser):
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="ERROR",
        help="Minimum level to write to the shared log file.",
    )


def configure_logging(level_name="ERROR"):
    root_logger = logging.getLogger()
    logger_level = getattr(logging, level_name.upper(), logging.ERROR)

    for handler in root_logger.handlers:
        if getattr(handler, "_noterizer_handler", False):
            handler.setLevel(logger_level)
            root_logger.setLevel(min(root_logger.level, logger_level))
            return

    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2)
    handler._noterizer_handler = True
    handler.setLevel(logger_level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )

    root_logger.addHandler(handler)
    root_logger.setLevel(logger_level)


def merge_dicts(base, override):
    merged = copy.deepcopy(base)

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value

    return merged


def expand_env(value):
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    if isinstance(value, str):
        return os.path.expandvars(value)
    return value


def resolve_profile_path(profile_value):
    candidate = Path(profile_value).expanduser()

    if candidate.suffix == ".json" or candidate.exists():
        return candidate.resolve()

    return (PROFILES_DIR / f"{profile_value}.json").resolve()


def load_profile(profile_value):
    profile_path = resolve_profile_path(profile_value)

    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    profile_data = json.loads(profile_path.read_text())
    profile = merge_dicts(DEFAULT_PROFILE, profile_data)
    profile = expand_env(profile)
    profile["_profile_name"] = Path(profile_path).stem
    profile["_profile_path"] = str(profile_path)
    return profile


def available_profiles():
    if not PROFILES_DIR.exists():
        return []

    return sorted(path.stem for path in PROFILES_DIR.glob("*.json"))


def ensure_exists(path, label):
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def default_child_dir(path, child_name):
    return (path.parent / child_name).resolve()


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcript_json_path(audio_path, transcripts_dir):
    return transcripts_dir / f"{audio_path.stem}.json"


def transcript_srt_path(audio_path, transcripts_dir):
    return transcripts_dir / f"{audio_path.stem}.srt"


def summary_markdown_path(audio_path, summaries_dir):
    return summaries_dir / f"{audio_path.stem}.summary.md"


def note_markdown_path(image_path, notes_dir):
    return notes_dir / f"{image_path.stem}.note.md"


def resolve_db_path(profile, override=None):
    if override:
        return Path(override).expanduser().resolve()

    return Path(profile["database"]["path"]).expanduser().resolve()


def auth_headers(backend):
    token = backend.get("api_key")
    api_key_env = backend.get("api_key_env")

    if not token and api_key_env:
        token = os.environ.get(api_key_env)

    if token:
        return {"Authorization": f"Bearer {token}"}

    return {}


def unload_backend_model(backend):
    kind = backend.get("kind")
    model = backend.get("model")
    url = backend.get("url")

    if kind == "ollama_generate":
        requests.post(
            url,
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=60,
            headers=auth_headers(backend),
        ).raise_for_status()
        return

    if kind == "ollama_chat":
        requests.post(
            url,
            json={"model": model, "messages": [], "keep_alive": 0},
            timeout=60,
            headers=auth_headers(backend),
        ).raise_for_status()
        return

    if kind == "ollama_embeddings":
        unload_url = url.replace("/api/embeddings", "/api/generate")
        requests.post(
            unload_url,
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=60,
            headers=auth_headers(backend),
        ).raise_for_status()


def unload_profile_ollama_models(profile):
    seen = set()

    for key in ("summary_backend", "query_backend", "embedding_backend", "vision_backend"):
        backend = profile.get(key)
        if not backend:
            continue

        kind = backend.get("kind")
        if not kind or not kind.startswith("ollama_"):
            continue

        model_key = (backend.get("url"), backend.get("model"), kind)
        if model_key in seen:
            continue
        seen.add(model_key)
        unload_backend_model(backend)


def generate_text(prompt, backend):
    kind = backend["kind"]
    url = backend["url"]
    model = backend["model"]
    options = backend.get("options", {})
    headers = auth_headers(backend)

    if kind == "ollama_generate":
        response = requests.post(
            url,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": 0,
                "options": options,
            },
            timeout=600,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()["response"].strip()

    if kind == "openai_chat_completions":
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if "temperature" in options:
            payload["temperature"] = options["temperature"]

        response = requests.post(
            url,
            json=payload,
            timeout=600,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    raise ValueError(f"Unsupported text backend kind: {kind}")


def embed_text(text, backend):
    kind = backend["kind"]
    url = backend["url"]
    model = backend["model"]
    headers = auth_headers(backend)

    if kind == "ollama_embeddings":
        response = requests.post(
            url,
            json={"model": model, "prompt": text},
            timeout=600,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()["embedding"]

    if kind == "openai_embeddings":
        response = requests.post(
            url,
            json={"model": model, "input": text},
            timeout=600,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    raise ValueError(f"Unsupported embedding backend kind: {kind}")


def encode_image(image_path):
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def extract_note(image_path, backend, prompt=IMAGE_PROMPT):
    kind = backend["kind"]
    url = backend["url"]
    model = backend["model"]
    options = backend.get("options", {})
    headers = auth_headers(backend)
    image_b64 = encode_image(image_path)

    if kind == "ollama_chat":
        response = requests.post(
            url,
            json={
                "model": model,
                "stream": False,
                "keep_alive": 0,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_b64],
                    }
                ],
                "options": options,
            },
            timeout=600,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()["message"]["content"].strip()

    if kind == "openai_chat_completions_vision":
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }
            ],
        }
        if "temperature" in options:
            payload["temperature"] = options["temperature"]

        response = requests.post(
            url,
            json=payload,
            timeout=600,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    raise ValueError(f"Unsupported vision backend kind: {kind}")


def get_collection(db_path, collection_name):
    try:
        import chromadb
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "chromadb is not installed. Install it before using indexing or query features."
        ) from exc

    client = chromadb.PersistentClient(path=str(db_path))
    return client.get_or_create_collection(collection_name)


def stable_id(source_path, content_type, key):
    raw = f"{source_path}|{content_type}|{key}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def clear_existing_docs(collection, source_path, content_type):
    try:
        existing = collection.get(
            where={"source_path": source_path, "content_type": content_type},
            include=[],
        )
    except Exception:
        return

    ids = existing.get("ids", [])
    if ids:
        collection.delete(ids=ids)


def chunk_markdown_sections(text):
    sections = []
    current_heading = "Document"
    current_lines = []

    for line in text.splitlines():
        if line.startswith("#"):
            if current_lines:
                body = "\n".join(current_lines).strip()
                if body:
                    sections.append((current_heading, body))
            current_heading = line.lstrip("#").strip() or "Document"
            current_lines = [line]
            continue

        current_lines.append(line)

    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_heading, body))

    return sections


def index_transcript_file(collection, transcript_path, embedding_backend):
    data = json.loads(transcript_path.read_text())
    source_path = str(transcript_path.resolve())
    clear_existing_docs(collection, source_path, "transcript")

    ids = []
    documents = []
    metadatas = []

    for idx, seg in enumerate(data.get("segments", [])):
        text = seg.get("text", "").strip()
        if not text:
            continue

        speaker = seg.get("speaker", "UNKNOWN")
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))
        doc = f"{speaker} [{start:.1f}-{end:.1f}]: {text}"

        ids.append(stable_id(source_path, "transcript", str(idx)))
        documents.append(doc)
        metadatas.append(
            {
                "content_type": "transcript",
                "source_name": transcript_path.name,
                "source_path": source_path,
                "speaker": speaker,
                "start": start,
                "end": end,
            }
        )

    if not documents:
        print(f"[index] No transcript segments found in {transcript_path}", flush=True)
        return 0

    embeddings = [embed_text(doc, embedding_backend) for doc in documents]
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    print(f"[index] Indexed {len(documents)} transcript chunks from {transcript_path.name}", flush=True)
    return len(documents)


def index_markdown_file(collection, markdown_path, content_type, embedding_backend):
    text = markdown_path.read_text().strip()
    source_path = str(markdown_path.resolve())
    clear_existing_docs(collection, source_path, content_type)

    sections = chunk_markdown_sections(text)
    if not sections:
        print(f"[index] No markdown content found in {markdown_path}", flush=True)
        return 0

    ids = []
    documents = []
    metadatas = []

    for idx, (heading, body) in enumerate(sections):
        ids.append(stable_id(source_path, content_type, str(idx)))
        documents.append(body)
        metadatas.append(
            {
                "content_type": content_type,
                "source_name": markdown_path.name,
                "source_path": source_path,
                "section": heading,
            }
        )

    embeddings = [embed_text(doc, embedding_backend) for doc in documents]
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    print(f"[index] Indexed {len(documents)} {content_type} chunks from {markdown_path.name}", flush=True)
    return len(documents)


def format_context_item(doc, meta):
    label = f"Source: {meta['source_name']} | Type: {meta['content_type']}"

    if meta["content_type"] == "transcript":
        label += f" | Time: {meta.get('start', 0):.1f}-{meta.get('end', 0):.1f}"
        speaker = meta.get("speaker")
        if speaker:
            label += f" | Speaker: {speaker}"
    else:
        section = meta.get("section")
        if section:
            label += f" | Section: {section}"

    return f"{label}\n{doc}"
