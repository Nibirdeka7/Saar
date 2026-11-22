import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.aws import client
from app.config import settings
from app.db import connection, audit
from worker.ingest import process_s3_key


def upload_benchmark_doc():
    doc_path = ROOT / "docs" / "novacore_handbook_benchmark.md"
    if not doc_path.exists():
        raise FileNotFoundError(f"Missing {doc_path}")
    content = doc_path.read_bytes()
    filename = "novacore_handbook_benchmark.md"
    tenant = "demo-workspace"
    owner_sub = "benchmark@novacore.internal"
    groups = ["workspace"]

    doc_id = str(uuid.uuid4())
    key = f"tenants/{tenant}/incoming/{doc_id}/v1.md"

    # 1. Upload to S3
    s3 = client("s3")
    s3.put_object(
        Bucket=settings().s3_bucket,
        Key=key,
        Body=content,
        ContentType="text/markdown",
    )
    print(f"Uploaded {filename} to S3: s3://{settings().s3_bucket}/{key}")

    # 2. Insert document record in PostgreSQL
    with connection() as conn:
        conn.execute(
            """INSERT INTO documents(id, tenant_id, title, owner_sub, allowed_groups, s3_key, status, current_version)
               VALUES (%s, %s, %s, %s, %s, %s, 'pending', 1)""",
            (doc_id, tenant, filename, owner_sub, groups, key),
        )
        audit(conn, owner_sub, tenant, "upload_requested", {"document_id": doc_id})
    print(f"Inserted document record: id={doc_id}")

    # 3. Trigger ingestion
    process_s3_key(key)
    print("SUCCESS: Ingested parent_chunks into PostgreSQL and child vectors into Pinecone!")


if __name__ == "__main__":
    upload_benchmark_doc()
