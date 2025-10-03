from typing import Dict, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


app = FastAPI(title="Notification Service", version="0.1.0")


@app.get("/healthz")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def ready() -> dict:
    return {"status": "ready"}


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                self.active_connections.pop(user_id, None)

    async def send_personal_message(self, user_id: str, message: str) -> None:
        for ws in self.active_connections.get(user_id, set()):
            await ws.send_text(message)


manager = ConnectionManager()


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)


@app.post("/notify/{user_id}")
async def notify_user(user_id: str, message: str) -> dict:
    await manager.send_personal_message(user_id, message)
    return {"status": "sent"}


