"""Authentication context.
Redirects to app.auth for email and password authentication.
"""
from app.auth import Principal, principal, get_current_user

__all__ = ["Principal", "principal", "get_current_user"]
