# Saar Enterprise RAG — Setup & Authentication Guide

## Overview

Saar Enterprise RAG is an enterprise-grade retrieval-augmented generation platform featuring:
- Multitenant knowledge retrieval and access control.
- Bedrock embeddings and text generation (Amazon Titan + Amazon Nova Lite).
- Hybrid storage: PostgreSQL on Render for document metadata, audit logs, approvals, conversation history, and user authentication; Pinecone for vector search.
- Industry-standard email and password authentication with PBKDF2-HMAC-SHA256 password hashing and signed JWT session tokens.

---

## 1. Database Initialization

To initialize or verify all required PostgreSQL tables (including `users`, `documents`, `feedback`, `audit_events`, `approvals`, and `chat_messages`):

```bash
python scripts/init_db.py
```

---

## 2. Authentication System

### Password Security
- Passwords are encrypted using **PBKDF2-HMAC-SHA256** with **600,000 rounds** and a 16-byte cryptographically secure random salt generated per user.
- Password verification is timing-attack resistant using `hmac.compare_digest`.

### Authentication Endpoints
- **Register**: `POST /api/auth/register`
  ```json
  {
    "email": "user@example.com",
    "password": "StrongPassword123!",
    "tenant": "demo-workspace",
    "admin": false
  }
  ```
- **Login**: `POST /api/auth/login`
  ```json
  {
    "email": "user@example.com",
    "password": "StrongPassword123!"
  }
  ```
- **Current User Profile**: `GET /api/auth/me` (Requires `Authorization: Bearer <token>`)
- **Logout**: `POST /api/auth/logout`

### Role-Based Access Control (RBAC)
- **Member**: Authorized to upload documents, search knowledge base, participate in chats, and submit feedback.
- **Admin**: Authorized for all Member actions plus reviewing approvals (`/api/approvals`, `/api/approvals/{id}/decision`) and viewing operational guardrail telemetry (`/api/admin/metrics`, `/api/admin/guardrails`).

---

## 3. Running the Server

Start the development server with Uvicorn:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000` in your browser. Unauthenticated users are presented with a sign-in / registration dialog. Once signed in, access tokens are persisted in browser storage and attached to all API requests.

---

## 4. Running Tests

Run the comprehensive authentication test suite:

```bash
python test/test_auth.py
```
