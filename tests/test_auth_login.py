"""Hash scrypt con sal, re-hash de hashes viejos, límite de intentos y 503 sin base (sin base real)."""

import hashlib
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.core.ratelimit import AttemptLimiter
from app.core.security import hash_password, needs_rehash, verify_password
from app.main import app
from app.routes import auth

client = TestClient(app)
UID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def test_scrypt_hash_is_salted_and_verifies():
    h1, h2 = hash_password("secreto"), hash_password("secreto")
    assert h1 != h2 and h1.startswith("scrypt$")
    assert verify_password("secreto", h1) and not verify_password("otro", h1)
    assert not needs_rehash(h1)


def test_legacy_sha256_still_verifies_and_needs_rehash():
    legacy = hashlib.sha256(b"secreto").hexdigest()
    assert verify_password("secreto", legacy) and not verify_password("otro", legacy)
    assert needs_rehash(legacy)


def test_limiter_blocks_after_max_and_resets():
    lim = AttemptLimiter(max_attempts=2, window_s=60)
    lim.hit("k"); lim.hit("k")
    with pytest.raises(Exception) as exc:
        lim.check("k")
    assert exc.value.status_code == 429
    lim.reset("k")
    lim.check("k")


class FakeUsers:
    """Una fila de usuario; guarda los UPDATE de password_hash."""

    def __init__(self, stored):
        self.stored = stored
        self.updates = []

    @contextmanager
    def begin(self):
        outer = self

        class Conn:
            def execute(self, statement, params=None):
                sql = str(statement)
                if sql.startswith("UPDATE users"):
                    outer.updates.append(params["pw_hash"])

                class Result:
                    def fetchone(self_inner):
                        return (UID, outer.stored) if sql.startswith("SELECT") else None

                return Result()

        yield Conn()


@pytest.fixture(autouse=True)
def fresh_limiters(monkeypatch):
    monkeypatch.setattr(auth, "login_limiter", AttemptLimiter(5, 900))
    monkeypatch.setattr(auth, "register_limiter", AttemptLimiter(10, 3600))


def test_login_without_database_is_503(monkeypatch):
    monkeypatch.setattr(auth, "db_engine", None)
    assert client.post("/auth/login", json={"username": "u", "password": "p"}).status_code == 503


def test_login_rehashes_legacy_password(monkeypatch):
    users = FakeUsers(hashlib.sha256(b"secreto").hexdigest())
    monkeypatch.setattr(auth, "db_engine", users)
    resp = client.post("/auth/login", json={"username": "ana", "password": "secreto"})
    assert resp.status_code == 200 and resp.json()["user_id"] == UID
    assert len(users.updates) == 1 and users.updates[0].startswith("scrypt$")


def test_login_locks_after_five_failures(monkeypatch):
    users = FakeUsers(hash_password("secreto"))
    monkeypatch.setattr(auth, "db_engine", users)
    bad = {"username": "ana", "password": "mal"}
    assert [client.post("/auth/login", json=bad).status_code for _ in range(5)] == [400] * 5
    assert client.post("/auth/login", json=bad).status_code == 429
    # ni la contraseña correcta entra mientras dura el bloqueo
    assert client.post("/auth/login", json={"username": "ana", "password": "secreto"}).status_code == 429
    assert users.updates == []
