import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, constr
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Boolean, Integer, Text
from passlib.context import CryptContext


app = FastAPI(title="User Service", version="0.1.0")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://mtuci:mtuci_pass@localhost:5432/mtuci_eda")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="client")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AddressModel(Base):
    __tablename__ = "addresses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    street_address: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(100))
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


@app.on_event("startup")
async def on_startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/healthz")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def ready() -> dict:
    return {"status": "ready"}


class UserCreate(BaseModel):
    email: EmailStr
    password: constr(min_length=8, max_length=64)
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserOut(BaseModel):
    id: int
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str = "client"
    is_active: bool = True


@app.post("/users", response_model=UserOut, status_code=201)
async def register_user(payload: UserCreate) -> UserOut:
    async with SessionLocal() as session:
        # check unique email
        existing = await session.execute(
            UserModel.__table__.select().where(UserModel.email == payload.email)
        )
        if existing.first():
            raise HTTPException(status_code=400, detail="Email already registered")

        user = UserModel(
            email=payload.email,
            password_hash=pwd_context.hash(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            role="client",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return UserOut(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=user.role,
            is_active=user.is_active,
        )


