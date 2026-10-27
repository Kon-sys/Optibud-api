from fastapi import APIRouter

from app.api.routers import auth, categories, households, insights, planning, profile, sync, transactions


api_v1 = APIRouter(prefix="/v1")
for module in (auth, profile, households, categories, transactions, planning, insights, sync):
    api_v1.include_router(module.router)
