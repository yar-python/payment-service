import os
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio

os.environ.setdefault("POSTGRES_USER", "payments")
os.environ.setdefault("POSTGRES_PASSWORD", "payments")
os.environ.setdefault("POSTGRES_DB", "payments")
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("RABBITMQ_USER", "guest")
os.environ.setdefault("RABBITMQ_PASSWORD", "guest")
os.environ.setdefault("RABBITMQ_HOST", "127.0.0.1")
os.environ.setdefault("RABBITMQ_PORT", "5672")
os.environ.setdefault("API_KEY", "test-api-key")


@pytest_asyncio.fixture
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            try:
                yield client
            finally:
                app.dependency_overrides.clear()
