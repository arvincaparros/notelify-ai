import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncClient:
    """In-process ASGI client -- no separate server process needed.

    This test still exercises the real app, including the real database
    dependency (app/db/session.py reads DATABASE_URL from the environment),
    consistent with docs/09-TESTING-STRATEGY.md's "never a mock" rule. It
    assumes a reachable Postgres -- run via `docker compose up -d postgres`
    (or the full stack) before `pytest`.

    A full ephemeral-per-session database + migration fixture, as designed
    in 09, isn't built yet: there are no migrations to run against in Phase
    0. This minimal fixture is sufficient for the health check and will be
    extended once Phase 1 introduces real tables.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
