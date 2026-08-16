"""Connection keys, and the middleware that turns one into an identity.

The remote MCP endpoint is authenticated by a secret in the URL, which means the
middleware in `api/mcp_auth.py` is the only thing between the internet and the
scoped registry. These tests pin the lifecycle (mint, use, expire, revoke) and
the rejections, because every branch that fails open here is a data leak.
"""

from datetime import datetime, timedelta, timezone

import pytest

from autoviz.api.mcp_auth import _split_key
from autoviz.core.database import get_sessionmaker
from autoviz.mcp.server import PROFILES
from autoviz.storage import repository


@pytest.fixture()
def user_id(api_db):
    session = get_sessionmaker()()
    try:
        return repository.create_user(session, "keys@example.com", "x").id
    finally:
        session.close()


@pytest.fixture()
def db(api_db):
    session = get_sessionmaker()()
    yield session
    session.close()


# --- minting -----------------------------------------------------------------


def test_the_plaintext_key_is_never_stored(db, user_id):
    """A dump of this table must yield no working links."""
    row, plaintext = repository.create_mcp_key(db, user_id, label="Claude")
    assert plaintext
    assert row.token_hash != plaintext
    assert plaintext not in row.token_hash
    # Nothing on the row carries it.
    assert plaintext not in "".join(
        str(getattr(row, c.name)) for c in row.__table__.columns
    )


def test_a_minted_key_resolves_to_its_owner(db, user_id):
    _row, plaintext = repository.create_mcp_key(db, user_id)
    found = repository.get_usable_mcp_key(db, plaintext)
    assert found is not None and found.user_id == user_id


def test_keys_are_unguessable_and_url_safe(db, user_id):
    """It goes in a path segment, so it must survive being one."""
    _row, plaintext = repository.create_mcp_key(db, user_id)
    assert len(plaintext) >= 40
    assert "/" not in plaintext and "?" not in plaintext and "#" not in plaintext


def test_two_keys_are_different(db, user_id):
    _a, one = repository.create_mcp_key(db, user_id)
    _b, two = repository.create_mcp_key(db, user_id)
    assert one != two


# --- rejection ---------------------------------------------------------------


def test_an_unknown_key_resolves_to_nothing(db, user_id):
    assert repository.get_usable_mcp_key(db, "not-a-real-key") is None


def test_a_revoked_key_stops_working(db, user_id):
    row, plaintext = repository.create_mcp_key(db, user_id)
    assert repository.revoke_mcp_key(db, user_id, row.id) is True
    assert repository.get_usable_mcp_key(db, plaintext) is None


def test_revocation_is_scoped_to_the_owner(db, user_id):
    """Someone else's key id must not be revocable."""
    other = repository.create_user(db, "other@example.com", "x")
    row, plaintext = repository.create_mcp_key(db, user_id)
    assert repository.revoke_mcp_key(db, other.id, row.id) is False
    assert repository.get_usable_mcp_key(db, plaintext) is not None


def test_an_expired_key_stops_working(db, user_id):
    _row, plaintext = repository.create_mcp_key(
        db, user_id, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    assert repository.get_usable_mcp_key(db, plaintext) is None


def test_a_future_expiry_still_works(db, user_id):
    _row, plaintext = repository.create_mcp_key(
        db, user_id, expires_at=datetime.now(timezone.utc) + timedelta(days=30)
    )
    assert repository.get_usable_mcp_key(db, plaintext) is not None


def test_revoked_keys_stay_listed(db, user_id):
    """A revoked key that vanished would give no way to confirm the revocation."""
    row, _ = repository.create_mcp_key(db, user_id, label="old")
    repository.revoke_mcp_key(db, user_id, row.id)
    assert row.id in {k.id for k in repository.list_mcp_keys(db, user_id)}


def test_listing_is_scoped_to_the_owner(db, user_id):
    other = repository.create_user(db, "other2@example.com", "x")
    mine, _ = repository.create_mcp_key(db, user_id)
    theirs, _ = repository.create_mcp_key(db, other.id)
    ids = {k.id for k in repository.list_mcp_keys(db, user_id)}
    assert mine.id in ids and theirs.id not in ids


# --- last_used ---------------------------------------------------------------


def test_first_use_records_a_timestamp(db, user_id):
    row, _ = repository.create_mcp_key(db, user_id)
    assert row.last_used_at is None
    repository.touch_mcp_key(db, row)
    assert row.last_used_at is not None


def test_touch_is_throttled(db, user_id):
    """One UPDATE per tool call would turn a read-only analysis into write traffic."""
    row, _ = repository.create_mcp_key(db, user_id)
    repository.touch_mcp_key(db, row)
    first = row.last_used_at
    repository.touch_mcp_key(db, row)
    assert row.last_used_at == first


# --- path handling -----------------------------------------------------------


@pytest.mark.parametrize("path,expected", [
    ("/abc123/mcp", ("abc123", "/mcp")),
    ("/abc123/", ("abc123", "/")),
    ("/abc123", ("abc123", "/")),
    ("/", (None, "/")),
    ("", (None, "/")),
])
def test_the_key_is_split_off_the_path(path, expected):
    """The mounted app must see `/mcp`, never the credential."""
    assert _split_key(path) == expected


@pytest.mark.parametrize("path,expected", [
    ("/c/abc123/mcp", ("abc123", "/mcp")),
    ("/c/abc123", ("abc123", "/")),
    ("/c", (None, "/")),
])
def test_the_mount_prefix_is_stripped_before_the_key(path, expected):
    """Starlette hands a mounted ASGI app the full path, prefix included.

    Assuming otherwise read the mount prefix itself as the key, and every
    request 401'd — caught only by exercising the real HTTP path.
    """
    assert _split_key(path, "/c") == expected


# --- the tool surface a key exposes ------------------------------------------


def test_the_host_profile_excludes_our_own_agent():
    """A foreign host's model should plan; ours would be a costly passthrough."""
    names = {fn.__name__ for fn, _ in PROFILES["host"]}
    assert "analyze" not in names
    assert "answer_clarification" not in names


def test_the_host_profile_keeps_the_deterministic_core():
    names = {fn.__name__ for fn, _ in PROFILES["host"]}
    for required in (
        "register_dataset",
        "get_dataset_schema",
        "validate_analysis_plan",
        "execute_analysis",
        "generate_chart",
    ):
        assert required in names, required


def test_new_keys_default_to_the_host_profile(db, user_id):
    row, _ = repository.create_mcp_key(db, user_id)
    assert row.profile == "host"


# --- end to end, over real HTTP ----------------------------------------------
#
# The unit tests above prove the pieces. This proves the chain: an HTTP request
# carrying a key in the URL reaches the MCP transport as an authenticated,
# scoped caller — and one carrying a bad key does not reach it at all.


@pytest.fixture()
def remote_app(api_db, monkeypatch):
    monkeypatch.setenv("AUTOVIZ_REMOTE_MCP", "1")
    from autoviz.api.main import create_app

    return create_app()


def _initialize(client, key: str):
    """An MCP `initialize` — the first thing any host sends."""
    return client.post(
        f"/c/{key}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )


def test_a_valid_key_reaches_the_mcp_transport(remote_app, db, user_id):
    from fastapi.testclient import TestClient

    _row, plaintext = repository.create_mcp_key(db, user_id)
    with TestClient(remote_app) as client:
        r = _initialize(client, plaintext)
    assert r.status_code == 200, r.text
    assert "autoviz" in r.text.lower()


def test_an_invalid_key_is_rejected_before_the_transport(remote_app, db, user_id):
    from fastapi.testclient import TestClient

    with TestClient(remote_app) as client:
        r = _initialize(client, "definitely-not-a-key")
    assert r.status_code == 401
    assert "invalid or expired" in r.text


def test_a_revoked_key_is_rejected_over_http(remote_app, db, user_id):
    from fastapi.testclient import TestClient

    row, plaintext = repository.create_mcp_key(db, user_id)
    repository.revoke_mcp_key(db, user_id, row.id)
    with TestClient(remote_app) as client:
        r = _initialize(client, plaintext)
    assert r.status_code == 401


def test_the_endpoint_is_absent_unless_explicitly_enabled(api_db, monkeypatch):
    """Publicly reachable and capability-authenticated: opt-in, never default."""
    from fastapi.testclient import TestClient

    monkeypatch.delenv("AUTOVIZ_REMOTE_MCP", raising=False)
    from autoviz.api.main import create_app

    with TestClient(create_app()) as client:
        r = client.post("/c/anything/mcp", json={})
    assert r.status_code == 404


# --- the management API the settings UI will call ----------------------------


@pytest.fixture()
def client(api_db):
    from fastapi.testclient import TestClient
    from autoviz.api.main import create_app

    creds = {"email": "keys2@example.com", "password": "pw12345678", "username": "keys2"}
    c = TestClient(create_app())
    c.post("/auth/register", json=creds)
    token = c.post("/auth/login", json=creds).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_creating_a_key_returns_it_exactly_once(client):
    created = client.post("/auth/mcp-keys", json={"label": "Claude"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["key"] and body["url"].endswith("/mcp")
    assert body["key"] in body["url"]

    # Never again, in any later response.
    listed = client.get("/auth/mcp-keys").json()
    assert all("key" not in k for k in listed)


def test_the_connection_url_puts_the_key_in_the_middle(client):
    """Hosts expect a URL ending `/mcp`; a key at the end would be normalised off."""
    url = client.post("/auth/mcp-keys", json={}).json()["url"]
    assert "/c/" in url and url.endswith("/mcp")


def test_keys_default_to_the_host_profile_and_an_expiry(client):
    body = client.post("/auth/mcp-keys", json={}).json()
    assert body["profile"] == "host"
    assert body["expires_at"] is not None


def test_listing_and_revoking(client):
    key_id = client.post("/auth/mcp-keys", json={"label": "phone"}).json()["id"]
    assert key_id in {k["id"] for k in client.get("/auth/mcp-keys").json()}

    assert client.delete(f"/auth/mcp-keys/{key_id}").status_code == 204
    revoked = next(k for k in client.get("/auth/mcp-keys").json() if k["id"] == key_id)
    assert revoked["revoked"] is True


def test_revoking_someone_elses_key_is_a_404(client, api_db):
    from fastapi.testclient import TestClient
    from autoviz.api.main import create_app

    creds = {"email": "third@example.com", "password": "pw12345678", "username": "third"}
    other = TestClient(create_app())
    other.post("/auth/register", json=creds)
    other.headers["Authorization"] = (
        f"Bearer {other.post('/auth/login', json=creds).json()['access_token']}"
    )
    victim_id = client.post("/auth/mcp-keys", json={}).json()["id"]

    assert other.delete(f"/auth/mcp-keys/{victim_id}").status_code == 404


def test_managing_keys_requires_auth(api_db):
    from fastapi.testclient import TestClient
    from autoviz.api.main import create_app

    anon = TestClient(create_app())
    assert anon.get("/auth/mcp-keys").status_code == 401
    assert anon.post("/auth/mcp-keys", json={}).status_code == 401
