import pytest


@pytest.mark.asyncio
async def test_every_response_is_noindex(client):
    """The login page was showing up in Google; the header covers any route, 404s included."""
    for path in ("/", "/login", "/nope-does-not-exist"):
        response = await client.get(path)
        assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive", path
