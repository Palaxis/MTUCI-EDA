import os
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET", "replace_me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


app = FastAPI(title="Order Service", version="0.1.0")


@app.get("/healthz")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def ready() -> dict:
    return {"status": "ready"}


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


def get_user_from_token(authorization: Optional[str]) -> TokenUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenUser(id=int(payload.get("uid", 0)), email=payload.get("sub", ""), role=payload.get("role", "client"))
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


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
    # TODO: persist status change and publish Kafka event
    return {"order_id": order_id, "new_status": payload.status}


