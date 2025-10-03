import os
import hashlib
import secrets
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from sqlalchemy import text
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

SECRET_KEY = os.getenv("JWT_SECRET", "replace_me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

def _get_int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    val = val.strip()
    if val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default

ACCESS_TOKEN_EXPIRE_MINUTES = _get_int_env("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
REFRESH_TOKEN_EXPIRE_DAYS = _get_int_env("REFRESH_TOKEN_EXPIRE_DAYS", 30)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


app = FastAPI(title="Auth Service", version="0.1.0")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://mtuci:mtuci_pass@localhost:5432/mtuci_eda")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

from pydantic import BaseModel as _BM


class _UserRow(_BM):
    id: int
    email: str
    password_hash: str
    role: str


@app.get("/healthz")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def ready() -> dict:
    return {"status": "ready"}


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None


class TokenData(BaseModel):
    sub: Optional[str] = None
    role: Optional[str] = None


class User(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool = True


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_refresh_token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("utf-8").rstrip("=")


@app.on_event("startup")
async def ensure_refresh_table() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id BIGSERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                token_hash VARCHAR(128) UNIQUE NOT NULL,
                issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ NOT NULL,
                revoked_at TIMESTAMPTZ NULL,
                family VARCHAR(64) NULL,
                user_agent TEXT NULL,
                ip_address VARCHAR(64) NULL
            )
            """
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash ON refresh_tokens(token_hash)"
        ))


async def issue_refresh_token(session: AsyncSession, user_id: int, family: Optional[str] = None, user_agent: Optional[str] = None, ip_address: Optional[str] = None) -> str:
    raw = _generate_refresh_token()
    token_hash = _hash_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    if family is None:
        family = secrets.token_hex(16)
    await session.execute(
        text(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at, family, user_agent, ip_address)
            VALUES (:user_id, :token_hash, :expires_at, :family, :user_agent, :ip_address)
            """
        ),
        {
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "family": family,
            "user_agent": user_agent,
            "ip_address": ip_address,
        },
    )
    await session.commit()
    return raw


def get_user_from_token(token: str) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject: str = payload.get("sub")
        role: str = payload.get("role")
        uid: int = int(payload.get("uid", 0))
        if subject is None or uid == 0:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return User(id=uid, email=subject, role=role or "client", is_active=True)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    return get_user_from_token(token)


@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Verify against DB users table
    async with SessionLocal() as session:
        result = await session.execute(
            # Using raw query to avoid ORM dependency duplication
            text("SELECT id, email, password_hash, role FROM users WHERE email = :email"),
            {"email": form_data.username},
        )
        row = result.first()
        if not row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        user_id, user_email, password_hash, user_role = row
        if not verify_password(form_data.password, password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        access_token = create_access_token({"sub": user_email, "uid": user_id, "role": user_role})
        refresh_token = await issue_refresh_token(session, user_id=user_id)
        return {"access_token": access_token, "token_type": "bearer", "refresh_token": refresh_token}


@app.get("/me", response_model=User)
async def read_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str


@app.post("/refresh", response_model=TokenPair)
async def refresh_tokens(payload: RefreshIn):
    raw = payload.refresh_token
    token_hash = _hash_token(raw)
    async with SessionLocal() as session:
        # Load token
        res = await session.execute(
            text(
                """
                SELECT id, user_id, issued_at, expires_at, revoked_at, family
                FROM refresh_tokens
                WHERE token_hash = :token_hash
                """
            ),
            {"token_hash": token_hash},
        )
        row = res.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        token_id, user_id, issued_at, expires_at, revoked_at, family = row
        now = datetime.now(timezone.utc)
        if revoked_at is not None or now >= expires_at:
            raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

        # Rotate: revoke current, issue new refresh, issue new access
        await session.execute(
            text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE id = :id"),
            {"id": token_id},
        )

        # Load user for role/email
        ures = await session.execute(
            text("SELECT email, role FROM users WHERE id = :id"),
            {"id": user_id},
        )
        urow = ures.fetchone()
        if not urow:
            raise HTTPException(status_code=401, detail="User not found")
        email, role = urow

        access = create_access_token({"sub": email, "uid": user_id, "role": role})
        new_refresh = await issue_refresh_token(session, user_id=user_id, family=family)
        return TokenPair(access_token=access, refresh_token=new_refresh)


@app.post("/logout")
async def logout(payload: RefreshIn):
    token_hash = _hash_token(payload.refresh_token)
    async with SessionLocal() as session:
        await session.execute(
            text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE token_hash = :token_hash"),
            {"token_hash": token_hash},
        )
        await session.commit()
    return {"status": "ok"}


@app.post("/logout_all")
async def logout_all(current_user: User = Depends(get_current_user)):
    async with SessionLocal() as session:
        await session.execute(
            text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = :uid AND revoked_at IS NULL"),
            {"uid": current_user.id},
        )
        await session.commit()
    return {"status": "ok"}


