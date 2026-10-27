import logging
import os

from app.api import errors
from app.api.router import api_v1
from app.api.routers import health
from fastapi import FastAPI



logging.basicConfig(level=logging.INFO)

app = FastAPI(title="OptiBud API", version="1.0.0")
errors.install(app)

app.include_router(health.router)
app.include_router(api_v1)
