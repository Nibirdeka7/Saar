import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from fastapi import Request, Header, HTTPException, status
from app.config import settings
from app.db import connection, audit

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Principal:
    subject: str = "anonymous"
    tenant: str = "demo-workspace"
    groups: tuple[str, ...] = ("workspace",)
    admin: bool = False
    email: str = ""
    user_id: str = ""


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with 600,000 rounds and random 16-byte salt."""
    salt = secrets.token_bytes(16)
    iterations = 600_000
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against stored PBKDF2-HMAC-SHA256 hash in constant time."""
    try:
        parts = hashed.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def create_access_token(payload: dict, expires_in_seconds: Optional[int] = None) -> str:
    """Generate a standard HMAC-SHA256 signed JWT-style token."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    if expires_in_seconds is None:
        expires_in_seconds = settings().auth_token_expire_hours * 3600
    exp = now + expires_in_seconds

    full_payload = {
        **payload,
        "iat": now,
        "exp": exp,
    }

    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_bytes = json.dumps(full_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    signing_input = f"{_b64url_encode(header_bytes)}.{_b64url_encode(payload_bytes)}"
    secret = settings().auth_secret_key.encode("utf-8")
    signature = hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()

    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict:
    """Decode and verify HMAC-SHA256 signed token. Raises HTTPException on invalid/expired."""
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token structure",
                headers={"WWW-Authenticate": "Bearer"},
            )

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"
        secret = settings().auth_secret_key.encode("utf-8")
        expected_sig = hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        provided_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, provided_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token signature",
                headers={"WWW-Authenticate": "Bearer"},
            )

        payload_raw = _b64url_decode(payload_b64)
        payload = json.loads(payload_raw.decode("utf-8"))

        now = int(time.time())
        if "exp" in payload and payload["exp"] < now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(request: Request, authorization: Optional[str] = Header(None)) -> Principal:
    """FastAPI dependency to extract and authenticate the current user."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif "saar_access_token" in request.cookies:
        token = request.cookies.get("saar_access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = decode_access_token(token)
    email = claims.get("email") or claims.get("sub", "")
    tenant = claims.get("tenant", "demo-workspace")
    groups = tuple(claims.get("groups", ["workspace"]))
    is_admin = bool(claims.get("admin", False))
    user_id = str(claims.get("uid", ""))

    return Principal(
        subject=email,
        tenant=tenant,
        groups=groups,
        admin=is_admin,
        email=email,
        user_id=user_id,
    )


# Alias principal to get_current_user for backwards compatibility across existing routes
principal = get_current_user


def get_user_by_email(conn, email: str) -> Optional[dict]:
    """Retrieve user record from database by email."""
    row = conn.execute(
        "SELECT id, email, password_hash, tenant_id, role, created_at FROM users WHERE lower(email) = lower(%s)",
        (email.strip(),),
    ).fetchone()
    return dict(row) if row else None


def create_user(conn, email: str, password_hash: str, tenant_id: str = "demo-workspace", role: str = "member") -> dict:
    """Insert a new user record into database."""
    row = conn.execute(
        """INSERT INTO users (email, password_hash, tenant_id, role)
           VALUES (lower(%s), %s, %s, %s)
           RETURNING id, email, tenant_id, role, created_at""",
        (email.strip(), password_hash, tenant_id.strip() or "demo-workspace", role),
    ).fetchone()
    return dict(row)
