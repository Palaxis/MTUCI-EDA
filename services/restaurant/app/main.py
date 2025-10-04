import os
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, condecimal
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, Numeric


app = FastAPI(title="Restaurant Service", version="0.1.0")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://mtuci:mtuci_pass@localhost:5432/mtuci_eda")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class RestaurantModel(Base):
    __tablename__ = "restaurants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), default=0)
    min_order_amount: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), default=0)
    delivery_fee: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), default=0)
    delivery_time_min: Mapped[int] = mapped_column(Integer, default=30)
    delivery_time_max: Mapped[int] = mapped_column(Integer, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CategoryModel(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[int] = mapped_column(Integer, ForeignKey("restaurants.id"))
    name: Mapped[str] = mapped_column(String(100))
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class DishModel(Base):
    __tablename__ = "dishes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[int] = mapped_column(Integer, ForeignKey("restaurants.id"))
    category_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("categories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False)


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


class RestaurantCreate(BaseModel):
    name: str
    description: Optional[str] = None
    min_order_amount: condecimal(max_digits=10, decimal_places=2) = 0
    delivery_fee: condecimal(max_digits=10, decimal_places=2) = 0
    delivery_time_min: int = 30
    delivery_time_max: int = 60
    is_active: bool = True


class RestaurantOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    min_order_amount: float
    delivery_fee: float
    delivery_time_min: int
    delivery_time_max: int
    is_active: bool


@app.post("/restaurants", response_model=RestaurantOut, status_code=201)
async def create_restaurant(payload: RestaurantCreate) -> RestaurantOut:
    async with SessionLocal() as session:
        obj = RestaurantModel(
            name=payload.name,
            description=payload.description,
            min_order_amount=payload.min_order_amount,
            delivery_fee=payload.delivery_fee,
            delivery_time_min=payload.delivery_time_min,
            delivery_time_max=payload.delivery_time_max,
            is_active=payload.is_active,
        )
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        return RestaurantOut(
            id=obj.id,
            name=obj.name,
            description=obj.description,
            min_order_amount=float(obj.min_order_amount or 0),
            delivery_fee=float(obj.delivery_fee or 0),
            delivery_time_min=obj.delivery_time_min,
            delivery_time_max=obj.delivery_time_max,
            is_active=obj.is_active,
        )


@app.get("/restaurants", response_model=List[RestaurantOut])
async def list_restaurants() -> List[RestaurantOut]:
    async with SessionLocal() as session:
        res = await session.execute(RestaurantModel.__table__.select())
        items = []
        for row in res.fetchall():
            obj = row
            items.append(
                RestaurantOut(
                    id=obj.id,
                    name=obj.name,
                    description=obj.description,
                    min_order_amount=float(obj.min_order_amount or 0),
                    delivery_fee=float(obj.delivery_fee or 0),
                    delivery_time_min=obj.delivery_time_min,
                    delivery_time_max=obj.delivery_time_max,
                    is_active=obj.is_active,
                )
            )
        return items


class CategoryCreate(BaseModel):
    restaurant_id: int
    name: str
    display_order: int = 0


class CategoryOut(BaseModel):
    id: int
    restaurant_id: int
    name: str
    display_order: int


@app.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(payload: CategoryCreate) -> CategoryOut:
    async with SessionLocal() as session:
        obj = CategoryModel(
            restaurant_id=payload.restaurant_id,
            name=payload.name,
            display_order=payload.display_order,
        )
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        return CategoryOut(id=obj.id, restaurant_id=obj.restaurant_id, name=obj.name, display_order=obj.display_order)


@app.get("/restaurants/{restaurant_id}/categories", response_model=List[CategoryOut])
async def list_categories(restaurant_id: int) -> List[CategoryOut]:
    async with SessionLocal() as session:
        res = await session.execute(CategoryModel.__table__.select().where(CategoryModel.restaurant_id == restaurant_id))
        return [CategoryOut(id=row.id, restaurant_id=row.restaurant_id, name=row.name, display_order=row.display_order) for row in res.fetchall()]


class DishCreate(BaseModel):
    restaurant_id: int
    category_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    price: condecimal(max_digits=10, decimal_places=2)
    image_url: Optional[str] = None
    is_available: bool = True
    is_recommended: bool = False


class DishOut(BaseModel):
    id: int
    restaurant_id: int
    category_id: Optional[int]
    name: str
    description: Optional[str]
    price: float
    image_url: Optional[str]
    is_available: bool
    is_recommended: bool


@app.post("/dishes", response_model=DishOut, status_code=201)
async def create_dish(payload: DishCreate) -> DishOut:
    async with SessionLocal() as session:
        obj = DishModel(
            restaurant_id=payload.restaurant_id,
            category_id=payload.category_id,
            name=payload.name,
            description=payload.description,
            price=payload.price,
            image_url=payload.image_url,
            is_available=payload.is_available,
            is_recommended=payload.is_recommended,
        )
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        return DishOut(
            id=obj.id,
            restaurant_id=obj.restaurant_id,
            category_id=obj.category_id,
            name=obj.name,
            description=obj.description,
            price=float(obj.price),
            image_url=obj.image_url,
            is_available=obj.is_available,
            is_recommended=obj.is_recommended,
        )


@app.get("/restaurants/{restaurant_id}/dishes", response_model=List[DishOut])
async def list_dishes(restaurant_id: int) -> List[DishOut]:
    async with SessionLocal() as session:
        res = await session.execute(DishModel.__table__.select().where(DishModel.restaurant_id == restaurant_id))
        return [
            DishOut(
                id=row.id,
                restaurant_id=row.restaurant_id,
                category_id=row.category_id,
                name=row.name,
                description=row.description,
                price=float(row.price),
                image_url=row.image_url,
                is_available=row.is_available,
                is_recommended=row.is_recommended,
            ) for row in res.fetchall()
        ]


