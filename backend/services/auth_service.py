"""
TalentHub JWT Authentication Service.
Reuses TalentHub's JWT infrastructure as specified in Lab 3 / Lab 4 detailed design.
Enforces router-layer validation and service-layer role & ownership checks.
"""

import jwt
import datetime
from typing import Optional, Dict, Any, List
from functools import wraps
from flask import request, jsonify

# JWT Configuration (simulating TalentHub auth provider)
JWT_SECRET_KEY = "talenthub-finpay-secure-shared-secret-key-2026"
JWT_ALGORITHM = "HS256"


def create_talenthub_token(user_id: str, role: str = "student", expires_in_hours: int = 24) -> str:
    """
    Generates a signed TalentHub JWT for a given student or finance officer.
    Payload includes standard claims: sub (user_id), role, iat, exp.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "student_id": user_id,
        "role": role,
        "iss": "talenthub-auth",
        "iat": now,
        "exp": now + datetime.timedelta(hours=expires_in_hours)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_talenthub_token(token: str) -> Dict[str, Any]:
    """
    Verifies JWT token signature and expiration.
    Raises jwt.PyJWTError on failure.
    """
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], issuer="talenthub-auth")


def extract_token_from_header() -> Optional[str]:
    """Extracts Bearer token from HTTP Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return None


def require_auth(allowed_roles: Optional[List[str]] = None):
    """
    Decorator for Flask routes:
    1. Validates TalentHub JWT (signature, expiry, issuer) -> 401 if invalid.
    2. Checks role against allowed_roles -> 403 if unauthorized.
    3. Attaches decoded token to request.user.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = extract_token_from_header()
            if not token:
                return jsonify({
                    "error": "AuthenticationRequired",
                    "message": "Missing Bearer token in Authorization header."
                }), 401

            try:
                payload = verify_talenthub_token(token)
            except jwt.ExpiredSignatureError:
                return jsonify({
                    "error": "TokenExpired",
                    "message": "TalentHub token has expired."
                }), 401
            except jwt.InvalidTokenError as e:
                return jsonify({
                    "error": "InvalidToken",
                    "message": f"Invalid TalentHub JWT: {str(e)}"
                }), 401

            user_role = payload.get("role", "student")
            if allowed_roles and user_role not in allowed_roles:
                return jsonify({
                    "error": "ForbiddenRole",
                    "message": f"Role '{user_role}' is not authorized for this resource."
                }), 403

            request.user = payload
            return fn(*args, **kwargs)
        return wrapper
    return decorator

