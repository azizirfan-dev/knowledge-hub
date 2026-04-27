"""
Verify that Qdrant chunks contain `start_index` and `source` in their payload.
Required for eval dataset composite key (source, start_index).

Run: python -m eval.verify_payload
"""

import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient

load_dotenv()

COLLECTIONS = [
    os.getenv("QDRANT_COLLECTION_HR", "kb_hr"),
    os.getenv("QDRANT_COLLECTION_TECHNICAL", "kb_technical"),
]

REQUIRED_META = ["source", "start_index"]


def main():
    client = QdrantClient(
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY"),
    )

    for col in COLLECTIONS:
        print(f"\n=== Collection: {col} ===")
        try:
            points, _ = client.scroll(collection_name=col, limit=3, with_payload=True)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        if not points:
            print("  (empty)")
            continue

        for p in points:
            payload = p.payload or {}
            meta = payload.get("metadata", payload)
            keys_found = {k: meta.get(k) for k in REQUIRED_META}
            print(f"  point id={p.id}")
            print(f"    payload keys: {list(payload.keys())}")
            if "metadata" in payload:
                print(f"    metadata keys: {list(meta.keys())}")
            for k in REQUIRED_META:
                val = keys_found[k]
                status = "OK" if val is not None else "MISSING"
                print(f"    {k}: {status} (value={val!r})")


if __name__ == "__main__":
    main()
