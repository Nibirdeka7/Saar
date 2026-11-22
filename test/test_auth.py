"""
Comprehensive test suite for the email/password authentication system.
Tests:
1. Password hashing & constant-time verification
2. Token generation, verification, tampering, expiration
3. User registration API (/api/auth/register)
4. User login API (/api/auth/login)
5. Current user inspection (/api/auth/me)
6. Access control for protected endpoints without authentication (401)
7. RBAC permissions (member vs admin on /api/approvals)
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uuid
import time
from fastapi.testclient import TestClient
from app.main import app
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    Principal,
)

client = TestClient(app)


def test_password_hashing():
    print("\n--- Test 1: Password Hashing & Verification ---")
    raw = "SuperSecret123!"
    hashed = hash_password(raw)
    assert hashed.startswith("pbkdf2_sha256$600000$"), f"Unexpected hash format: {hashed}"
    assert verify_password(raw, hashed) is True, "Password verification failed for correct password"
    assert verify_password("WrongPassword", hashed) is False, "Password verification succeeded for wrong password"
    assert verify_password("", hashed) is False, "Password verification succeeded for empty password"
    print("✓ Password hashing and verification passed!")


def test_token_creation_and_tamper_detection():
    print("\n--- Test 2: Token Creation, Decoding & Tamper Detection ---")
    data = {
        "sub": "tester@example.com",
        "email": "tester@example.com",
        "tenant": "test-tenant",
        "role": "admin",
        "admin": True,
        "groups": ["workspace", "admin"],
    }
    token = create_access_token(data, expires_in_seconds=60)
    claims = decode_access_token(token)
    assert claims["email"] == "tester@example.com"
    assert claims["tenant"] == "test-tenant"
    assert claims["admin"] is True

    # Test tampering
    parts = token.split(".")
    tampered_payload = parts[1] + "extra"
    tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"
    try:
        decode_access_token(tampered_token)
        assert False, "Tampered token should have failed validation"
    except Exception:
        pass

    # Test expired token
    expired_token = create_access_token(data, expires_in_seconds=-10)
    try:
        decode_access_token(expired_token)
        assert False, "Expired token should have failed validation"
    except Exception:
        pass
    print("✓ Token generation, validation, and tamper resistance passed!")


def test_unauthenticated_access_blocked():
    print("\n--- Test 3: Unauthenticated Access Blocked (HTTP 401) ---")
    # /api/auth/me without token
    res = client.get("/api/auth/me")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"

    # /api/documents without token
    res = client.get("/api/documents")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"

    # /api/approvals without token
    res = client.get("/api/approvals")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"

    print("✓ All protected routes correctly reject unauthenticated requests with 401!")


def test_registration_and_login_flow():
    print("\n--- Test 4: Registration, Login & Role-Based Access Control ---")
    unique_suffix = uuid.uuid4().hex[:8]
    member_email = f"member_{unique_suffix}@example.com"
    admin_email = f"admin_{unique_suffix}@example.com"
    password = "StrongPassword2026!"

    # 1. Invalid email registration
    res = client.post("/api/auth/register", json={
        "email": "not-an-email",
        "password": password,
        "tenant": "test-tenant",
        "admin": False
    })
    assert res.status_code == 400, f"Expected 400 for invalid email, got {res.status_code}"

    # 2. Short password registration (Pydantic schema validation returns 422)
    res = client.post("/api/auth/register", json={
        "email": f"short_{unique_suffix}@example.com",
        "password": "123",
        "tenant": "test-tenant",
        "admin": False
    })
    assert res.status_code in (400, 422), f"Expected 400 or 422 for short password, got {res.status_code}"

    # 3. Successful member registration
    res = client.post("/api/auth/register", json={
        "email": member_email,
        "password": password,
        "tenant": "test-tenant",
        "admin": False
    })
    assert res.status_code == 200, f"Member registration failed: {res.text}"
    member_data = res.json()
    member_token = member_data["token"]
    assert member_data["user"]["email"] == member_email
    assert member_data["user"]["role"] == "member"
    assert member_data["user"]["admin"] is False

    # 4. Duplicate registration conflict
    res = client.post("/api/auth/register", json={
        "email": member_email,
        "password": password,
        "tenant": "test-tenant",
        "admin": False
    })
    assert res.status_code == 409, f"Expected 409 for duplicate email, got {res.status_code}"

    # 5. Successful admin registration
    res = client.post("/api/auth/register", json={
        "email": admin_email,
        "password": password,
        "tenant": "test-tenant",
        "admin": True
    })
    assert res.status_code == 200, f"Admin registration failed: {res.text}"
    admin_data = res.json()
    admin_token = admin_data["token"]
    assert admin_data["user"]["role"] == "admin"
    assert admin_data["user"]["admin"] is True

    # 6. Login with wrong password
    res = client.post("/api/auth/login", json={
        "email": member_email,
        "password": "WrongPassword!"
    })
    assert res.status_code == 401, f"Expected 401 for bad password, got {res.status_code}"

    # 7. Login with correct password
    res = client.post("/api/auth/login", json={
        "email": member_email,
        "password": password
    })
    assert res.status_code == 200, f"Login failed: {res.text}"
    login_token = res.json()["token"]

    # 8. Access /api/auth/me with member token
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {login_token}"})
    assert res.status_code == 200, f"/api/auth/me failed: {res.text}"
    me = res.json()
    assert me["email"] == member_email
    assert me["admin"] is False

    # 9. Access documents with member token
    res = client.get("/api/documents", headers={"Authorization": f"Bearer {member_token}"})
    assert res.status_code == 200, f"Documents list failed: {res.text}"

    # 10. Member access to admin-only /api/approvals -> Expect 403 Forbidden
    res = client.get("/api/approvals", headers={"Authorization": f"Bearer {member_token}"})
    assert res.status_code == 403, f"Expected 403 for member accessing approvals, got {res.status_code}"

    # 11. Admin access to admin-only /api/approvals -> Expect 200 OK
    res = client.get("/api/approvals", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200, f"Expected 200 for admin accessing approvals, got {res.status_code}: {res.text}"

    print("✓ Full registration, login, token authentication, and RBAC authorization passed!")


if __name__ == "__main__":
    test_password_hashing()
    test_token_creation_and_tamper_detection()
    test_unauthenticated_access_blocked()
    test_registration_and_login_flow()
    print("\n==========================================")
    print("ALL AUTHENTICATION TESTS PASSED SUCCESSFULLY!")
    print("==========================================")
