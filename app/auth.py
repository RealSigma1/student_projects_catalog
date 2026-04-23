import base64
import bcrypt
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Response
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import ACCESS_TOKEN_TTL_HOURS, COOKIE_SECURE, SECRET_KEY
from .database import get_db
from .models import UserModel

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_access_token(user: UserModel) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_TTL_HOURS)).timestamp()),
    }
    encoded_header = b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = hmac.new(SECRET_KEY.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return f"{signing_input}.{b64url_encode(signature)}"


def decode_access_token(token: str) -> dict:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid authentication token.") from exc

    signing_input = f"{encoded_header}.{encoded_payload}"
    expected_signature = hmac.new(SECRET_KEY.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    received_signature = b64url_decode(encoded_signature)
    if not hmac.compare_digest(expected_signature, received_signature):
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    payload = json.loads(b64url_decode(encoded_payload).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=401, detail="Authentication token has expired.")
    return payload


def set_auth_cookie(response: Response, user: UserModel) -> None:
    token = create_access_token(user)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_TTL_HOURS * 3600,
        secure=COOKIE_SECURE,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie("access_token")


def get_current_user(
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    access_token: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Optional[UserModel]:
    for token in (bearer_token, access_token):
        if not token:
            continue
        try:
            payload = decode_access_token(token)
        except HTTPException:
            continue
        return db.query(UserModel).filter(UserModel.id == int(payload["sub"])).first()
    return None


def require_current_user(current_user: Optional[UserModel] = Depends(get_current_user)) -> UserModel:
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return current_user
