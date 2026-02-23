"""JWT create/verify and require_admin dependency for protected routes."""
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.config import JWT_EXPIRE_MINUTES, JWT_SECRET

ALGORITHM = "HS256"
ROLE_CLAIM = "role"
ADMIN_ROLE = "admin"

security = HTTPBearer(auto_error=False)


def create_admin_token(admin_id: str) -> str:
    """Create a JWT for an admin user."""
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": admin_id, ROLE_CLAIM: ADMIN_ROLE, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def verify_admin_token(token: str) -> Optional[str]:
    """Verify JWT and return admin id (sub) if role is admin, else None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get(ROLE_CLAIM) != ADMIN_ROLE:
            return None
        return payload.get("sub")
    except Exception:
        return None


def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Dependency: require valid admin JWT; return admin id or raise 401."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    admin_id = verify_admin_token(credentials.credentials)
    if not admin_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return admin_id
