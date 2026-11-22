import io
import logging
import re
from pathlib import Path
from docx import Document
from pypdf import PdfReader
from app.aws import client, embed
from app.vector import upsert
from app.config import settings
from app.db import connection, audit

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('prodRag.worker')


def parse(blob: bytes, suffix: str):
    if suffix == '.pdf':
        reader = PdfReader(io.BytesIO(blob))
        return [(i + 1, page.extract_text() or '') for i, page in enumerate(reader.pages)]
    if suffix == '.docx':
        doc = Document(io.BytesIO(blob))
        return [(1, '\n'.join(p.text for p in doc.paragraphs))]
    return [(1, blob.decode('utf-8', errors='replace'))]


def clean_text(text: str) -> str:
    """Clean extracted text: fix hyphenated line-breaks, normalize whitespace, preserve paragraph boundaries."""
    # Fix hyphenated words broken across lines
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Split by double newline to preserve paragraph structure
    paragraphs = re.split(r'\n\s*\n', text)
    cleaned_paras = []
    for p in paragraphs:
        # Collapse multiple horizontal whitespaces into single space
        cleaned_p = re.sub(r'[ \t]+', ' ', p).strip()
        if cleaned_p:
            cleaned_paras.append(cleaned_p)
    return '\n\n'.join(cleaned_paras)


def guess_section(text: str) -> str:
    """Detect section heading or policy ID from chunk text."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            return line.lstrip('#').strip()[:80]
        m = re.match(r'^(?:##?\s*|\d+\.|\bSection\b|\bPolicy\s*ID:?\b)\s*([^:\n]+)', line, re.IGNORECASE)
        if m:
            return line[:80]
    return ''


def make_chunks(text: str, size: int, overlap: int):
    """Generate text chunks with specified size and overlap."""
    if not text:
        return
    pos = 0
    text_len = len(text)
    while pos < text_len:
        chunk = text[pos:pos + size]
        yield chunk
        if pos + size >= text_len:
            break
        pos += size - overlap


def process_s3_key(key: str):
    s = settings()
    with connection() as conn:
        doc = conn.execute('SELECT * FROM documents WHERE s3_key=%s FOR UPDATE', (key,)).fetchone()
        if not doc or doc['status'] == 'ready':
            return
        if doc['status'] not in ('pending', 'failed'):
            return
        conn.execute("UPDATE documents SET status='processing' WHERE id=%s", (doc['id'],))

    try:
        obj = client('s3').get_object(Bucket=s.s3_bucket, Key=key)
        if obj['ContentLength'] > s.max_upload_bytes:
            raise ValueError('Upload too large')
        blob = obj['Body'].read(s.max_upload_bytes + 1)
        if len(blob) > s.max_upload_bytes:
            raise ValueError('Upload too large')
        if Path(key).suffix.lower() == '.pdf' and not blob.startswith(b'%PDF'):
            raise ValueError('Invalid PDF')

        pages = parse(blob, Path(key).suffix.lower())

        parent_records = []
        vectors = []
        parent_idx = 0
        child_idx = 0

        for page_num, raw_text in pages:
            cleaned = clean_text(raw_text)
            if not cleaned:
                continue

            for parent_text in make_chunks(cleaned, s.parent_chunk_size, s.parent_chunk_overlap):
                parent_idx += 1
                pid = f"{doc['id']}:p{parent_idx}"
                section = guess_section(parent_text)

                parent_records.append({
                    'parent_id': pid,
                    'document_id': str(doc['id']),
                    'tenant_id': doc['tenant_id'],
                    'title': doc['title'],
                    'page_number': page_num,
                    'section': section,
                    'content': parent_text,
                })

                for child_text in make_chunks(parent_text, s.child_chunk_size, s.child_chunk_overlap):
                    child_idx += 1
                    cid = f"{doc['id']}:{doc['current_version']}:{child_idx}"
                    vectors.append({
                        'id': cid,
                        'values': embed(child_text),
                        'metadata': {
                            'parent_id': pid,
                            'document_id': str(doc['id']),
                            'tenant': doc['tenant_id'],
                            'groups': doc['allowed_groups'],
                            'title': doc['title'],
                            'page': page_num,
                            'section': section,
                            'text': child_text,
                            'owner_sub': doc['owner_sub'],
                            'allowed_groups': doc['allowed_groups'],
                        }
                    })

        if not parent_records or not vectors:
            raise ValueError('No extractable text found in document')

        # Persist parent chunks in PostgreSQL (clean up stale versions first)
        with connection() as conn:
            conn.execute("DELETE FROM parent_chunks WHERE document_id = %s", (str(doc['id']),))
            for p in parent_records:
                conn.execute(
                    """INSERT INTO parent_chunks
                       (parent_id, document_id, tenant_id, title, page_number, section, content)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (parent_id) DO UPDATE SET
                           content = EXCLUDED.content,
                           title = EXCLUDED.title,
                           page_number = EXCLUDED.page_number,
                           section = EXCLUDED.section""",
                    (p['parent_id'], p['document_id'], p['tenant_id'], p['title'],
                     p['page_number'], p['section'], p['content'])
                )

        # Upsert child vectors to Pinecone in batches
        for i in range(0, len(vectors), 50):
            upsert(doc['tenant_id'], vectors[i:i + 50])

        with connection() as conn:
            conn.execute(
                "UPDATE documents SET status='ready' WHERE id=%s",
                (doc['id'],)
            )
            audit(conn, doc['owner_sub'], doc['tenant_id'], 'ingest_ready', {
                'document_id': str(doc['id']),
                'parent_chunks': len(parent_records),
                'child_vectors': len(vectors),
            })
        log.info('Ingested document %s: parents=%d children=%d', doc['id'], len(parent_records), len(vectors))

    except Exception:
        log.exception('Ingestion failed for key %s', key)
        with connection() as conn:
            conn.execute("UPDATE documents SET status='failed' WHERE id=%s", (doc['id'],))
        raise
