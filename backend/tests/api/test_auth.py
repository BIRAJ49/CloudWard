import pytest


@pytest.mark.asyncio
async def test_development_login_sets_signed_session_and_me_works(api_client) -> None:  # type: ignore[no-untyped-def]
    response = await api_client.post(
        "/api/v1/auth/dev", json={"login": "local-operator", "role": "Operator"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "Operator"
    assert "cloudward_session" in response.cookies
    me = await api_client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["login"] == "local-operator"


@pytest.mark.asyncio
async def test_github_login_fails_cleanly_without_credentials(api_client) -> None:  # type: ignore[no-untyped-def]
    response = await api_client.get("/api/v1/auth/github/login", follow_redirects=False)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "OAUTH_NOT_CONFIGURED"
