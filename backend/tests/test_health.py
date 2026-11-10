from httpx import AsyncClient


async def test_health_check_reports_connected_database(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "database": "connected"}
