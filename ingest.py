"""
Component 1 — Vector Database Pipeline
Loads documents from docs/, chunks them, embeds with HuggingFace, stores in Qdrant Cloud.
Uses separate collections per domain for more precise retrieval.

Collections:
  kb_technical  ← Dokumentasi_Teknis_API_Gateway.pdf
  kb_hr         ← Kebijakan_Cuti_dan_Izin_Karyawan.pdf, SOP_Onboarding_Karyawan_Baru.pdf

Run once (or re-run to re-index): python ingest.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

load_dotenv()

DOCS_DIR = Path("docs")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

# paraphrase-multilingual-MiniLM-L12-v2 produces 384-dim vectors
# Override with EMBEDDING_MODEL in .env to swap models
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
VECTOR_SIZE = 384

# Map each filename (without extension) to its target collection
COLLECTION_MAP = {
    "Dokumentasi_Teknis_API_Gateway": os.getenv("QDRANT_COLLECTION_TECHNICAL", "kb_technical"),
    "Kebijakan_Cuti_dan_Izin_Karyawan": os.getenv("QDRANT_COLLECTION_HR", "kb_hr"),
    "SOP_Onboarding_Karyawan_Baru": os.getenv("QDRANT_COLLECTION_HR", "kb_hr"),
}


def load_pdf(file: Path):
    loader = PyPDFLoader(str(file))
    docs = loader.load()
    for doc in docs:
        doc.metadata["source"] = file.name
        doc.metadata["domain"] = get_domain(file.stem)
    return docs


def get_domain(stem: str) -> str:
    collection = COLLECTION_MAP.get(stem, "unknown")
    return "technical" if "technical" in collection else "hr"


def chunk_documents(docs):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        add_start_index=True,
    )
    chunks = splitter.split_documents(docs)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i
    return chunks


def setup_collection(client: QdrantClient, collection_name: str):
    existing = [c.name for c in client.get_collections().collections]
    if collection_name in existing:
        print(f"    Collection '{collection_name}' exists — recreating.")
        client.delete_collection(collection_name)
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    print(f"    Collection '{collection_name}' created.")


def main():
    print("=" * 60)
    print("KnowledgeHub — Document Ingestion Pipeline")
    print("=" * 60)

    embeddings = HuggingFaceEndpointEmbeddings(
        model=EMBEDDING_MODEL,
        huggingfacehub_api_token=os.getenv("HF_TOKEN"),
    )
    client = QdrantClient(
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY"),
    )

    # Group docs by target collection
    collection_docs: dict[str, list] = {}

    print(f"\n[1/3] Loading & chunking documents from docs/...")
    for file in sorted(DOCS_DIR.glob("*.pdf")):
        stem = file.stem
        target_collection = COLLECTION_MAP.get(stem)
        if target_collection is None:
            print(f"  [SKIP] {file.name} — not in COLLECTION_MAP")
            continue

        raw_docs = load_pdf(file)
        chunks = chunk_documents(raw_docs)
        collection_docs.setdefault(target_collection, []).extend(chunks)
        print(f"  Loaded: {file.name} → '{target_collection}' ({len(chunks)} chunks)")

    # Setup collections
    print(f"\n[2/3] Setting up Qdrant collections...")
    unique_collections = set(collection_docs.keys())
    for col in unique_collections:
        setup_collection(client, col)

    # Insert per collection
    print(f"\n[3/3] Inserting vectors...")
    vector_stores: dict[str, QdrantVectorStore] = {}
    for col, chunks in collection_docs.items():
        vs = QdrantVectorStore(
            client=client,
            collection_name=col,
            embedding=embeddings,
        )
        vs.add_documents(chunks)
        vector_stores[col] = vs
        print(f"  Inserted {len(chunks)} chunks into '{col}'")

    # Validation
    print(f"\n[Validation] Similarity search test per collection...")
    test_queries = {
        os.getenv("QDRANT_COLLECTION_TECHNICAL", "kb_technical"): "cara autentikasi API",
        os.getenv("QDRANT_COLLECTION_HR", "kb_hr"): "kebijakan cuti tahunan",
    }
    for col, query in test_queries.items():
        if col not in vector_stores:
            continue
        results = vector_stores[col].similarity_search(query, k=2)
        print(f"\n  [{col}] Query: '{query}'")
        for r in results:
            print(f"    - [{r.metadata.get('source')}] chunk {r.metadata.get('chunk_id')}: {r.page_content[:80]}...")

    print("\n" + "=" * 60)
    print("Ingestion complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
