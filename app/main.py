from fastapi import FastAPI
from app.routers import analysis

app = FastAPI(title="HyperAgent", version="0.1.0")

app.include_router(analysis.router)

@app.get("/")
async def root():
    return {"message": "HyperAgent Microservice is running"}
