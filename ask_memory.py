import sys
import requests
import chromadb

DB_PATH = "./voice_db"
COLLECTION = "memory"
EMBED_MODEL = "nomic-embed-text"
CHAT_MODEL = "qwen2.5:14b"

client = chromadb.PersistentClient(path=DB_PATH)
collection = client.get_or_create_collection(COLLECTION)

def embed(text):
    r = requests.post(
        "http://localhost:11434/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text}
    )
    r.raise_for_status()
    return r.json()["embedding"]

def ask_llm(prompt):
    r = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": CHAT_MODEL, "prompt": prompt, "stream": False}
    )
    r.raise_for_status()
    return r.json()["response"]

question = " ".join(sys.argv[1:])

results = collection.query(
    query_embeddings=[embed(question)],
    n_results=12
)

docs = results["documents"][0]
metas = results["metadatas"][0]

context_lines = []
for doc, meta in zip(docs, metas):
    context_lines.append(
        f"Source: {meta['source']} | Time: {meta['start']:.1f}-{meta['end']:.1f}\n{doc}"
    )

context = "\n\n".join(context_lines)

prompt = f"""
Answer the question using only the transcript excerpts below.

If the answer is not in the excerpts, say:
"I don't see that in the indexed transcripts."

Include source filenames and timestamps when useful.

Question:
{question}

Transcript excerpts:
{context}
"""

print(ask_llm(prompt))
