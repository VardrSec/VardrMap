from routers.api_surface import infer_path_template


def payload(**overrides):
    data = {
        "method": "GET",
        "url": "https://api.example.com/v1/users/123/orders/550e8400-e29b-41d4-a716-446655440000?token=never-store-query",
        "source_tool": "repeater",
        "identity_label": "standard-user",
        "request_headers": "Authorization: Bearer abcdefghijklmnop\nCookie: sid=supersecret",
        "request_body": '{"password":"hunter 2","profile":{"name":"Ada"}}',
        "response_headers": "Content-Type: application/json\nSet-Cookie: sid=returnedsecret",
        "response_body": '{"id":123,"access_token":"secret-token-value"}',
        "response_status": 200,
        "response_length": 44,
        "response_mime": "application/json",
        "response_time_ms": 73,
        "note": "baseline request",
    }
    data.update(overrides)
    return data


def test_path_template_inference():
    assert infer_path_template("/users/123/orders/550e8400-e29b-41d4-a716-446655440000") == "/users/{id}/orders/{uuid}"
    assert infer_path_template("/accounts/acct_abcdefghijklmnop") == "/accounts/{opaque_id}"


def test_create_exchange_requires_auth(client, program_id):
    response = client.post(f"/engagements/{program_id}/api/exchanges", json=payload())
    assert response.status_code == 401


def test_create_exchange_redacts_and_upserts(client, auth_headers, program_id):
    first = client.post(f"/engagements/{program_id}/api/exchanges", json=payload(), headers=auth_headers)
    assert first.status_code == 201
    body = first.json()
    assert body["endpoint"]["path_template"] == "/v1/users/{id}/orders/{uuid}"
    assert body["endpoint"]["observation_count"] == 1
    exchange = body["exchange"]
    retained = " ".join(str(exchange[key]) for key in ("request_headers", "request_body", "response_headers", "response_body"))
    assert "abcdefghijklmnop" not in retained
    assert "supersecret" not in retained
    assert "hunter 2" not in retained
    assert "secret-token-value" not in retained
    assert retained.count("[REDACTED]") >= 4
    assert exchange["parameter_names"] == ["name", "password", "profile"]

    second = client.post(
        f"/engagements/{program_id}/api/exchanges",
        json=payload(response_status=403, identity_label="anonymous"), headers=auth_headers,
    )
    assert second.status_code == 201
    assert second.json()["endpoint"]["id"] == body["endpoint"]["id"]
    assert second.json()["endpoint"]["observation_count"] == 2

    listed = client.get(f"/engagements/{program_id}/api/endpoints", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    endpoint = listed.json()["endpoints"][0]
    assert endpoint["statuses"] == [200, 403]
    assert endpoint["identities"] == ["anonymous", "standard-user"]


def test_query_values_are_never_stored(client, auth_headers, program_id):
    response = client.post(f"/engagements/{program_id}/api/exchanges", json=payload(), headers=auth_headers)
    endpoint = client.get(
        f"/engagements/{program_id}/api/endpoints/{response.json()['endpoint']['id']}", headers=auth_headers
    )
    rendered = str(endpoint.json())
    assert "never-store-query" not in rendered


def test_cross_user_is_404(client, auth_headers, other_headers, program_id):
    created = client.post(f"/engagements/{program_id}/api/exchanges", json=payload(), headers=auth_headers)
    endpoint_id = created.json()["endpoint"]["id"]
    assert client.get(f"/engagements/{program_id}/api/endpoints", headers=other_headers).status_code == 404
    assert client.get(f"/engagements/{program_id}/api/endpoints/{endpoint_id}", headers=other_headers).status_code == 404


def test_rejects_invalid_url_method_and_tool(client, auth_headers, program_id):
    assert client.post(f"/engagements/{program_id}/api/exchanges", json=payload(url="file:///etc/passwd"), headers=auth_headers).status_code == 400
    assert client.post(f"/engagements/{program_id}/api/exchanges", json=payload(method="BREW"), headers=auth_headers).status_code == 400
    assert client.post(f"/engagements/{program_id}/api/exchanges", json=payload(source_tool="mystery"), headers=auth_headers).status_code == 400


def test_delete_exchange(client, auth_headers, program_id):
    created = client.post(f"/engagements/{program_id}/api/exchanges", json=payload(), headers=auth_headers).json()
    exchange_id = created["exchange"]["id"]
    response = client.delete(f"/engagements/{program_id}/api/exchanges/{exchange_id}", headers=auth_headers)
    assert response.status_code == 200
    detail = client.get(f"/engagements/{program_id}/api/endpoints/{created['endpoint']['id']}", headers=auth_headers).json()
    assert detail["observation_count"] == 0
    assert detail["exchanges"] == []
