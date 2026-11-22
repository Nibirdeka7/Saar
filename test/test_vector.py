
from app.vector import index, upsert, search, delete_document
from app.config import settings


def main():
    print("\n--- Pinecone Connection Test ---")

    config = settings()
    dummy_id = "test-vector-001"
    tenant = "test-tenant"

    # 1. Initialize Pinecone index
    print("\n1. Initializing Pinecone index...")

    idx = index()

    print("SUCCESS: Connected to Pinecone!")
    print(f"Index: {config.pinecone_index_name}")
    print(f"Embedding dimension: {config.embed_dim}")

    # 2. Insert a dummy vector
    print("\n2. Testing upsert...")

    dummy_vector = {
        "id": dummy_id,
        "values": [0.1] * config.embed_dim,
        "metadata": {
            "text": "This is a Pinecone test record.",
            "allowed_groups": ["developers"],
            "owner_sub": "test-user",
            "document_id": "test-document"
        }
    }

    upsert(tenant, [dummy_vector])

    print("SUCCESS: Vector upsert request completed!")

    # 3. Search for the inserted vector
    print("\n3. Testing search...")

    results = search(
        tenant=tenant,
        vector=dummy_vector["values"],
        groups=["developers"],
        owner="test-user",
        limit=5
    )

    print(f"Number of results: {len(results)}")

    for result in results:
        print(f"ID: {result['id']}")
        print(f"Score: {result['score']}")
        print(f"Metadata: {result['metadata']}")

    found = any(result["id"] == dummy_id for result in results)

    if found:
        print("\nSUCCESS: Dummy vector found in Pinecone!")
    else:
        print("\nWARNING: Vector not found yet. Pinecone may need time to index it.")

    # 4. Delete the dummy vector
    print("\n4. Testing delete...")

    delete_document(tenant, [dummy_id])

    print("SUCCESS: Delete request completed!")

    print("\n--- Pinecone Test Completed ---")


if __name__ == "__main__":
    main()
