import pytest


@pytest.mark.asyncio
async def test_admin_can_manage_role_mapping_without_dev_principal_fk_violation(
    api_client,
    admin_headers,  # type: ignore[no-untyped-def]
) -> None:
    login = await api_client.post(
        "/api/v1/auth/dev", json={"login": "role-target", "role": "Viewer"}
    )
    assert login.status_code == 200
    user_id = login.json()["user_id"]
    response = await api_client.put(
        f"/api/v1/role-mappings/{user_id}",
        headers={**admin_headers, "Origin": "http://localhost:5173"},
        json={"role": "Operator"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "Operator"
    assert response.json()["granted_by"] is None


@pytest.mark.asyncio
async def test_operator_cannot_manage_role_mapping(
    api_client,
    operator_headers,  # type: ignore[no-untyped-def]
) -> None:
    response = await api_client.put(
        "/api/v1/role-mappings/00000000-0000-0000-0000-000000000001",
        headers=operator_headers,
        json={"role": "Admin"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
