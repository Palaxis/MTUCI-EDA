import os
from enum import Enum
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, condecimal
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, Numeric
from sqlalchemy import select, update, delete
import httpx

SECRET_KEY = os.getenv("JWT_SECRET", "replace_me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


app = FastAPI(title="Order Service", version="0.1.0")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://mtuci:mtuci_pass@localhost:5432/mtuci_eda")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class OrderStatus(str, Enum):
    cart = "cart"
    pending = "pending"
    confirmed = "confirmed"
    preparing = "preparing"
    ready = "ready"
    delivering = "delivering"
    delivered = "delivered"
    cancelled = "cancelled"


class TokenUser(BaseModel):
    id: int
    email: str
    role: str


class CartItemModel(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    dish_id: Mapped[int] = mapped_column(Integer, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)


class OrderModel(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    restaurant_id: Mapped[int] = mapped_column(Integer, index=True)
    courier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_address_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default=OrderStatus.pending.value)
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2))
    delivery_fee: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2))


class OrderItemModel(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    dish_id: Mapped[int] = mapped_column(Integer)
    dish_name: Mapped[str] = mapped_column(String(200))
    dish_price: Mapped[float] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2))


# Read-only tables from restaurant service
class DishModel(Base):
    __tablename__ = "dishes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)


class RestaurantModel(Base):
    __tablename__ = "restaurants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_fee: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    min_order_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


@app.on_event("startup")
async def on_startup() -> None:
    async with engine.begin() as conn:
        # create only order/cart tables if they don't exist
        await conn.run_sync(Base.metadata.create_all, tables=[CartItemModel.__table__, OrderModel.__table__, OrderItemModel.__table__])


@app.get("/healthz")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def ready() -> dict:
    return {"status": "ready"}


def get_user_from_token(authorization: Optional[str]) -> TokenUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenUser(id=int(payload.get("uid", 0)), email=payload.get("sub", ""), role=payload.get("role", "client"))
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


class CartAdd(BaseModel):
    dish_id: int
    quantity: int = 1


class CartItemOut(BaseModel):
    id: int
    dish_id: int
    quantity: int


@app.get("/cart", response_model=List[CartItemOut])
async def get_cart(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> List[CartItemOut]:
    user = get_user_from_token(authorization)
    async with SessionLocal() as session:
        res = await session.execute(select(CartItemModel).where(CartItemModel.user_id == user.id))
        items = [CartItemOut(id=row.CartItemModel.id, dish_id=row.CartItemModel.dish_id, quantity=row.CartItemModel.quantity) for row in res]
        return items


@app.post("/cart/add", response_model=CartItemOut, status_code=201)
async def add_to_cart(payload: CartAdd, authorization: Optional[str] = Header(default=None, alias="Authorization")) -> CartItemOut:
    user = get_user_from_token(authorization)
    async with SessionLocal() as session:
        # upsert-like: if exists, increment
        res = await session.execute(select(CartItemModel).where(CartItemModel.user_id == user.id, CartItemModel.dish_id == payload.dish_id))
        existing = res.scalar_one_or_none()
        if existing:
            existing.quantity = existing.quantity + payload.quantity
            await session.commit()
            await session.refresh(existing)
            return CartItemOut(id=existing.id, dish_id=existing.dish_id, quantity=existing.quantity)
        obj = CartItemModel(user_id=user.id, dish_id=payload.dish_id, quantity=payload.quantity)
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        return CartItemOut(id=obj.id, dish_id=obj.dish_id, quantity=obj.quantity)


class CartUpdate(BaseModel):
    quantity: int


@app.patch("/cart/item/{item_id}", response_model=CartItemOut)
async def update_cart_item(item_id: int, payload: CartUpdate, authorization: Optional[str] = Header(default=None, alias="Authorization")) -> CartItemOut:
    user = get_user_from_token(authorization)
    async with SessionLocal() as session:
        res = await session.execute(select(CartItemModel).where(CartItemModel.id == item_id, CartItemModel.user_id == user.id))
        obj = res.scalar_one_or_none()
        if not obj:
            raise HTTPException(status_code=404, detail="Cart item not found")
        if payload.quantity <= 0:
            await session.delete(obj)
            await session.commit()
            raise HTTPException(status_code=204, detail="Deleted")
        obj.quantity = payload.quantity
        await session.commit()
        await session.refresh(obj)
        return CartItemOut(id=obj.id, dish_id=obj.dish_id, quantity=obj.quantity)


@app.delete("/cart/item/{item_id}")
async def delete_cart_item(item_id: int, authorization: Optional[str] = Header(default=None, alias="Authorization")) -> dict:
    user = get_user_from_token(authorization)
    async with SessionLocal() as session:
        res = await session.execute(select(CartItemModel).where(CartItemModel.id == item_id, CartItemModel.user_id == user.id))
        obj = res.scalar_one_or_none()
        if not obj:
            raise HTTPException(status_code=404, detail="Cart item not found")
        await session.delete(obj)
        await session.commit()
        return {"status": "deleted"}


class CheckoutIn(BaseModel):
    restaurant_id: int
    delivery_address_id: Optional[int] = None


class OrderOut(BaseModel):
    id: int
    status: OrderStatus
    subtotal: float
    delivery_fee: float
    total_amount: float


NOTIFICATION_URL = os.getenv("NOTIFICATION_URL", "http://localhost:8005")

async def notify_user(user_id: int, message: str) -> None:
    url = f"{NOTIFICATION_URL}/notify/{user_id}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(url, params={"message": message})
    except Exception:
        # Best-effort for MVP
        pass


@app.post("/checkout", response_model=OrderOut, status_code=201)
async def checkout(payload: CheckoutIn, authorization: Optional[str] = Header(default=None, alias="Authorization")) -> OrderOut:
    user = get_user_from_token(authorization)
    async with SessionLocal() as session:
        # load cart
        res = await session.execute(select(CartItemModel).where(CartItemModel.user_id == user.id))
        cart_items = [row.CartItemModel for row in res]
        if not cart_items:
            raise HTTPException(status_code=400, detail="Cart is empty")
        # load restaurant
        rres = await session.execute(select(RestaurantModel).where(RestaurantModel.id == payload.restaurant_id))
        restaurant = rres.scalar_one_or_none()
        if not restaurant or not restaurant.is_active:
            raise HTTPException(status_code=400, detail="Restaurant unavailable")
        delivery_fee = float(restaurant.delivery_fee or 0)

        # load dishes and compute subtotal
        dish_ids = [ci.dish_id for ci in cart_items]
        dres = await session.execute(select(DishModel).where(DishModel.id.in_(dish_ids), DishModel.restaurant_id == payload.restaurant_id, DishModel.is_available == True))
        dishes_by_id = {row.DishModel.id: row.DishModel for row in dres}
        if len(dishes_by_id) != len(dish_ids):
            raise HTTPException(status_code=400, detail="Some dishes are not available")
        subtotal = 0.0
        for ci in cart_items:
            price = float(dishes_by_id[ci.dish_id].price)
            subtotal += price * ci.quantity
        if subtotal < float(restaurant.min_order_amount or 0):
            raise HTTPException(status_code=400, detail="Below minimum order amount")
        total = subtotal + delivery_fee

        # create order
        order = OrderModel(
            customer_id=user.id,
            restaurant_id=payload.restaurant_id,
            courier_id=None,
            delivery_address_id=payload.delivery_address_id,
            status=OrderStatus.pending.value,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            total_amount=total,
        )
        session.add(order)
        await session.flush()
        # create order items snapshot
        for ci in cart_items:
            dish = dishes_by_id[ci.dish_id]
            oi = OrderItemModel(
                order_id=order.id,
                dish_id=dish.id,
                dish_name=dish.name,
                dish_price=float(dish.price),
                quantity=ci.quantity,
                subtotal=float(dish.price) * ci.quantity,
            )
            session.add(oi)
        # clear cart
        await session.execute(delete(CartItemModel).where(CartItemModel.user_id == user.id))
        await session.commit()
        await session.refresh(order)
        await notify_user(user.id, f"Order #{order.id} created with total {total}")
        return OrderOut(id=order.id, status=OrderStatus(order.status), subtotal=float(order.subtotal), delivery_fee=float(order.delivery_fee), total_amount=float(order.total_amount))


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


def can_update_status(role: str, new_status: OrderStatus) -> bool:
    restaurant_allowed = {OrderStatus.confirmed, OrderStatus.preparing, OrderStatus.ready, OrderStatus.cancelled}
    courier_allowed = {OrderStatus.ready, OrderStatus.delivering, OrderStatus.delivered, OrderStatus.cancelled}
    if role in ("restaurant_admin", "restaurant_staff"):
        return new_status in restaurant_allowed
    if role == "courier":
        return new_status in courier_allowed
    return False


@app.post("/orders/{order_id}/status")
async def update_order_status(order_id: int, payload: OrderStatusUpdate, authorization: Optional[str] = Header(default=None, alias="Authorization")):
    user = get_user_from_token(authorization)
    if not can_update_status(user.role, payload.status):
        raise HTTPException(status_code=403, detail="Operation not allowed for role")
    async with SessionLocal() as session:
        res = await session.execute(select(OrderModel).where(OrderModel.id == order_id))
        order = res.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        order.status = payload.status.value
        await session.commit()
        await notify_user(order.customer_id, f"Order #{order.id} status: {order.status}")
        return {"order_id": order_id, "new_status": payload.status}


