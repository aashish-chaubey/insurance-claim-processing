from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import audit, claims, dashboard, decisions

app = FastAPI(title="Intelligent Insurance Claims Processing")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(claims.router)
app.include_router(decisions.router)
app.include_router(audit.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    return {"status": "ok"}
