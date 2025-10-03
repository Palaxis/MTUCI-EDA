from fastapi import FastAPI


app = FastAPI(title="Order Service", version="0.1.0")


@app.get("/healthz")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def ready() -> dict:
    return {"status": "ready"}


