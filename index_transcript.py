import json
import sys
import uuid
import requests
import chromadb
from pathlib import Path

DB_PATH = "./voice_db"
COLLECTION = "memory"
EMBED_MODEL = "nomic-embed-text"

client = chromadb.PersistentClient(path=DB_PATH)
collection = client.get_or_create_collection(COLLECTION)

def embed(text):
    r = requests.post(
        "http://localhost:11434/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text}
    )
    r.raise_for_status()
    return r.json()["embedding"]

path = Path(sys.argv[1])
data = json.loads(path.read_text())

count = 0

for seg in data.get("segments", []):
    text = seg.get("text", "").strip()
    if not text:
        continue

    speaker = seg.get("speaker", "UNKNOWN")
    start = float(seg.get("start", 0))
    end = float(seg.get("end", 0))

    doc = f"{speaker} [{start:.1f}-{end:.1f}]: {text}"

    collection.add(
        ids=[str(uuid.uuid4())],
        documents=[doc],
        embeddings=[embed(doc)],
        metadatas=[{
            "source": path.name,
            "speaker": speaker,
            "start": start,
            "end": end
        }]
    )

    count += 1

print(f"Indexed {count} transcript chunks into {DB_PATH}")
