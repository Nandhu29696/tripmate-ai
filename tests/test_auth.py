"""Accounts: email + password, Google sign-in, sessions, account deletion."""

import re
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import accounts
import backend
import config
import mailer
import oauth_google
import security
from app import app
from tests.conftest import signed_in_client

PASSWORD = "correct horse battery"
EMAIL = "alice@example.com"
PROMPT = "Plan a 7-day Japan trip from Dhaka in October."


def anonymous() -> TestClient:
    return TestClient(app)


def link_in(mail: dict) -> str:
    return re.search(r"https?://\S+", mail["body"]).group(0)


def path_of(link: str) -> str:
    parsed = urlparse(link)
    return parsed.path + ("?" + parsed.query if parsed.query else "")


def register(client, email=EMAIL, password=PASSWORD, name="Alice"):
    return client.post("/api/auth/register", json={"email": email, "password": password, "name": name})


def verified_account(wired, mailbox, email=EMAIL):
    """Register and confirm through the emailed link; returns the signed-in client."""
    client = anonymous()
    assert register(client, email).status_code == 200
    verify = client.get(path_of(link_in(mailbox[-1])), follow_redirects=False)
    assert verify.status_code == 303
    return client


# ---- passwords and tokens (unit) -------------------------------------------------
def test_password_hashing_roundtrip():
    stored = accounts.hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert accounts.verify_password(PASSWORD, stored)
    assert not accounts.verify_password("wrong password!", stored)
    assert accounts.hash_password(PASSWORD) != stored  # random salt
    assert not accounts.verify_password(PASSWORD, None)
    assert not accounts.verify_password(PASSWORD, "garbage")
    assert not accounts.verify_password(PASSWORD, "bcrypt$1$2$3$aa$bb")


@pytest.mark.parametrize(
    "password,ok",
    [("correct horse battery", True), ("short", False), ("x" * 129, False),
     ("password123", False), ("aaaaaaaaaaaa", False), ("alice@example.com", False)],
)
def test_password_policy(password, ok):
    assert (accounts.validate_password(password, "alice@example.com") is None) is ok


def test_email_validation_and_normalisation():
    assert accounts.normalize_email("  Alice@Example.COM ") == "alice@example.com"
    assert accounts.validate_email("alice@example.com") is None
    for bad in ("", "no-at-sign", "a@b", "a b@c.com", "x" * 250 + "@example.com"):
        assert accounts.validate_email(bad)


def test_tokens_are_single_use_expiring_and_purpose_bound():
    store = accounts.InMemoryUserStore()
    user = store.create_user("a@example.com", "A", None, None, True)

    token, hashed = accounts.new_token()
    store.add_token(user["id"], "reset", hashed, 60)
    assert store.consume_token(hashed, "verify") is None  # wrong purpose
    assert store.consume_token(hashed, "reset") == user["id"]
    assert store.consume_token(hashed, "reset") is None  # already used

    _, expired = accounts.new_token()
    store.add_token(user["id"], "reset", expired, 60)
    store.expire_tokens()
    assert store.consume_token(expired, "reset") is None
    assert token not in str(store._tokens)  # only hashes are stored


def test_duplicate_email_is_rejected():
    store = accounts.InMemoryUserStore()
    store.create_user("a@example.com", "A", None, None, False)
    with pytest.raises(accounts.DuplicateEmailError):
        store.create_user("a@example.com", "B", None, None, False)


# ---- registration, verification, login ---------------------------------------------
def test_register_verify_login_flow(wired, mailbox):
    client = anonymous()
    response = register(client)
    assert response.status_code == 200 and response.json()["success"]

    assert len(mailbox) == 1 and mailbox[0]["to"] == EMAIL
    assert "/auth/verify?token=" in mailbox[0]["body"]
    user = wired.users.get_by_email(EMAIL)
    assert user["email_verified"] is False and user["has_password"] is True

    # cannot use the app, or log in, until the email is confirmed
    assert client.post("/api/travel", json={"message": PROMPT}).status_code == 401
    unverified = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert unverified.status_code == 403 and unverified.json()["code"] == "email_not_verified"
    assert len(mailbox) == 2  # a fresh confirmation link was sent

    verify = client.get(path_of(link_in(mailbox[-1])), follow_redirects=False)
    assert verify.status_code == 303 and verify.headers["location"] == "/?verified=1"
    assert wired.users.get_by_email(EMAIL)["email_verified"] is True
    session = client.get("/api/session").json()
    assert session["authenticated"] and session["user"]["email"] == EMAIL and session["user"]["name"] == "Alice"
    assert "password_hash" not in str(session)

    fresh = anonymous()
    login = fresh.post("/api/auth/login", json={"email": "  ALICE@example.com", "password": PASSWORD})
    assert login.status_code == 200
    assert fresh.get("/api/session").json()["authenticated"]


def test_session_cookie_flags(wired, mailbox):
    client = anonymous()
    register(client)
    response = client.get(path_of(link_in(mailbox[-1])), follow_redirects=False)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie


def test_verification_link_is_single_use_and_rejects_garbage(wired, mailbox):
    client = anonymous()
    register(client)
    path = path_of(link_in(mailbox[-1]))
    assert client.get(path, follow_redirects=False).headers["location"] == "/?verified=1"
    assert client.get(path, follow_redirects=False).headers["location"] == "/?auth_error=invalid_link"
    assert client.get("/auth/verify?token=nope", follow_redirects=False).headers["location"] == "/?auth_error=invalid_link"
    assert client.get("/auth/verify", follow_redirects=False).headers["location"] == "/?auth_error=invalid_link"


def test_expired_verification_link(wired, mailbox):
    client = anonymous()
    register(client)
    wired.users.expire_tokens()
    response = client.get(path_of(link_in(mailbox[-1])), follow_redirects=False)
    assert response.headers["location"] == "/?auth_error=invalid_link"


def test_register_does_not_reveal_whether_an_email_exists(wired, mailbox):
    verified_account(wired, mailbox)
    mailbox.clear()

    new = register(anonymous(), "brand-new@example.com")
    existing = register(anonymous(), EMAIL)
    assert (new.status_code, new.json()) == (existing.status_code, existing.json())

    notice = next(m for m in mailbox if m["to"] == EMAIL)
    assert "already" in notice["subject"].lower() and "/auth/verify" not in notice["body"]
    assert len(wired.users._users) == 2  # no duplicate was created


def test_registering_an_unverified_email_again_keeps_the_original_password(wired, mailbox):
    register(anonymous(), EMAIL, PASSWORD)
    before = wired.users.get_password_hash(wired.users.get_by_email(EMAIL)["id"])
    register(anonymous(), EMAIL, "attacker chosen password")
    assert wired.users.get_password_hash(wired.users.get_by_email(EMAIL)["id"]) == before


@pytest.mark.parametrize(
    "email,password",
    [("not-an-email", PASSWORD), ("bob@example.com", "short"), ("bob@example.com", "password123")],
)
def test_register_validation(wired, mailbox, email, password):
    response = register(anonymous(), email, password)
    assert response.status_code == 400 and not response.json()["success"]
    assert mailbox == []


def test_register_is_rate_limited_per_ip(wired, mailbox):
    client = anonymous()
    for i in range(5):
        assert register(client, f"user{i}@example.com").status_code == 200
    limited = register(client, "user99@example.com")
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0


def test_login_failures_are_generic_and_throttled(wired, mailbox):
    verified_account(wired, mailbox)
    client = anonymous()

    wrong = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong password!"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"] == unknown.json()["error"] == "Invalid email or password."

    for _ in range(4):
        client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong password!"})
    blocked = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert blocked.status_code == 429 and "retry-after" in blocked.headers


def test_google_only_account_cannot_log_in_with_a_password(wired):
    wired.users.create_user("g@example.com", "G", None, "sub-1", True)
    response = anonymous().post("/api/auth/login", json={"email": "g@example.com", "password": PASSWORD})
    assert response.status_code == 401


def test_disabled_user_loses_access_immediately(wired):
    client = signed_in_client(wired.users)
    assert client.get("/api/travel/threads").status_code == 200
    wired.users._users[client.user["id"]]["is_active"] = False
    assert client.get("/api/travel/threads").status_code == 401
    assert client.get("/api/session").json()["authenticated"] is False


# ---- forgot / reset password -------------------------------------------------------------
def test_forgot_password_is_generic_and_only_mails_real_accounts(wired, mailbox):
    verified_account(wired, mailbox)
    mailbox.clear()

    known = anonymous().post("/api/auth/forgot", json={"email": EMAIL})
    unknown = anonymous().post("/api/auth/forgot", json={"email": "ghost@example.com"})
    garbage = anonymous().post("/api/auth/forgot", json={"email": "not an email"})
    assert known.json() == unknown.json() == garbage.json()
    assert [m["to"] for m in mailbox] == [EMAIL]


def test_reset_flow_revokes_old_sessions_and_token_is_single_use(wired, mailbox):
    old_session = verified_account(wired, mailbox)
    assert old_session.get("/api/travel/threads").status_code == 200
    mailbox.clear()

    anonymous().post("/api/auth/forgot", json={"email": EMAIL})
    link = link_in(mailbox[0])
    token = parse_qs(urlparse(link).query)["reset"][0]
    time.sleep(0.05)

    weak = anonymous().post("/api/auth/reset", json={"token": token, "password": "short"})
    assert weak.status_code == 400

    client = anonymous()
    new_password = "a brand new passphrase"
    done = client.post("/api/auth/reset", json={"token": token, "password": new_password})
    assert done.status_code == 200 and client.get("/api/session").json()["authenticated"]
    assert any("password was changed" in m["subject"] for m in mailbox)

    assert old_session.get("/api/travel/threads").status_code == 401  # revoked
    assert client.get("/api/travel/threads").status_code == 200  # the new session works
    assert anonymous().post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401
    assert anonymous().post("/api/auth/login", json={"email": EMAIL, "password": new_password}).status_code == 200

    again = anonymous().post("/api/auth/reset", json={"token": token, "password": "yet another passphrase"})
    assert again.status_code == 400


def test_reset_with_a_bad_or_expired_token(wired, mailbox):
    verified_account(wired, mailbox)
    mailbox.clear()
    anonymous().post("/api/auth/forgot", json={"email": EMAIL})
    token = parse_qs(urlparse(link_in(mailbox[0])).query)["reset"][0]

    assert anonymous().post("/api/auth/reset", json={"token": "x" * 40, "password": PASSWORD}).status_code == 400
    wired.users.expire_tokens()
    assert anonymous().post("/api/auth/reset", json={"token": token, "password": PASSWORD}).status_code == 400


def test_forgot_password_is_throttled_per_email(wired, mailbox):
    verified_account(wired, mailbox)
    mailbox.clear()
    for _ in range(5):
        assert anonymous().post("/api/auth/forgot", json={"email": EMAIL}).status_code == 200
    assert len(mailbox) == 3  # the per-address limit silently stops further emails


def test_reset_also_lets_a_google_only_user_add_a_password(wired, mailbox):
    wired.users.create_user("g@example.com", "G", None, "sub-1", True)
    anonymous().post("/api/auth/forgot", json={"email": "g@example.com"})
    token = parse_qs(urlparse(link_in(mailbox[0])).query)["reset"][0]
    assert anonymous().post("/api/auth/reset", json={"token": token, "password": PASSWORD}).status_code == 200
    assert anonymous().post("/api/auth/login", json={"email": "g@example.com", "password": PASSWORD}).status_code == 200


# ---- per-user ownership and quota ------------------------------------------------------------
def test_each_user_has_their_own_trips_and_quota(wired, monkeypatch):
    monkeypatch.setattr(security, "plan_limiter", security.SlidingWindowLimiter(1, 3600))
    alice = signed_in_client(wired.users, "alice@example.com")
    bob = signed_in_client(wired.users, "bob@example.com")

    first = alice.post("/api/travel", json={"message": PROMPT})
    assert first.status_code == 200
    assert alice.post("/api/travel", json={"message": PROMPT}).status_code == 429
    assert bob.post("/api/travel", json={"message": PROMPT}).status_code == 200  # independent quota

    tid = first.json()["thread_id"]
    assert bob.get(f"/api/travel/{tid}").status_code == 404
    assert alice.get(f"/api/travel/{tid}").status_code == 200


def test_trips_follow_the_user_across_devices(wired, mailbox):
    laptop = verified_account(wired, mailbox)
    tid = laptop.post("/api/travel", json={"message": PROMPT}).json()["thread_id"]

    phone = anonymous()
    assert phone.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    assert [t["thread_id"] for t in phone.get("/api/travel/threads").json()["trips"]] == [tid]


# ---- Google sign-in -----------------------------------------------------------------------------
@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "client-secret")
    state = {"claims": {}, "exchanged": []}

    def exchange(code, verifier, base_url):
        state["exchanged"].append((code, verifier, base_url))
        return "raw-id-token"

    monkeypatch.setattr(oauth_google, "_exchange_code", exchange)
    monkeypatch.setattr(oauth_google, "_verify_id_token", lambda raw: dict(state["claims"]))
    return state


def begin_google(client):
    response = client.get("/auth/google/login", follow_redirects=False)
    assert response.status_code == 303
    query = parse_qs(urlparse(response.headers["location"]).query)
    return response, query


def finish_google(client, query, claims, google, state=None, code="auth-code"):
    cookie_payload = security.read_signed(client.cookies.get("tm_oauth"))
    google["claims"] = {"nonce": cookie_payload["n"] if cookie_payload else "x", **claims}
    return client.get(
        "/auth/google/callback", params={"code": code, "state": state or query["state"][0]}, follow_redirects=False
    )


GOOD = {"sub": "google-sub-1", "email": "Alice@Example.com", "email_verified": True, "name": "Alice G"}


def test_google_login_redirect_has_every_protection(wired, google):
    response, query = begin_google(anonymous())
    assert response.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert query["client_id"] == ["client-id.apps.googleusercontent.com"]
    assert query["redirect_uri"] == ["http://testserver/auth/google/callback"]
    assert query["response_type"] == ["code"] and query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) >= 40
    assert len(query["state"][0]) >= 20 and len(query["nonce"][0]) >= 20
    cookie = response.headers["set-cookie"].lower()
    assert "tm_oauth=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "client-secret" not in response.headers["location"]


def test_google_login_when_not_configured(wired, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "")
    response = anonymous().get("/auth/google/login", follow_redirects=False)
    assert response.headers["location"] == "/?auth_error=google_not_configured"
    assert anonymous().get("/api/session").json()["providers"] == {"google": False, "password": True}


def test_google_signup_creates_a_verified_user_and_session(wired, google):
    client = anonymous()
    _, query = begin_google(client)
    response = finish_google(client, query, GOOD, google)

    assert response.status_code == 303 and response.headers["location"] == "/"
    user = wired.users.get_by_google_sub("google-sub-1")
    assert user["email"] == "alice@example.com" and user["email_verified"] and not user["has_password"]
    assert client.get("/api/session").json()["user"]["name"] == "Alice G"
    assert client.get("/api/travel/threads").status_code == 200
    # PKCE verifier and redirect URI reached the token exchange
    code, verifier, base_url = google["exchanged"][0]
    assert code == "auth-code" and len(verifier) >= 43 and base_url == "http://testserver"


def test_google_returning_user_is_not_duplicated(wired, google):
    for _ in range(2):
        client = anonymous()
        _, query = begin_google(client)
        assert finish_google(client, query, GOOD, google).headers["location"] == "/"
    assert len(wired.users._users) == 1


def test_google_links_to_an_existing_verified_password_account(wired, mailbox, google):
    verified_account(wired, mailbox)
    client = anonymous()
    _, query = begin_google(client)
    finish_google(client, query, GOOD, google)

    assert len(wired.users._users) == 1
    user = wired.users.get_by_email(EMAIL)
    assert user["has_google"] and user["has_password"]
    assert anonymous().post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200


def test_google_signin_wipes_a_password_set_by_someone_who_never_verified(wired, mailbox, google):
    """Pre-hijack defence: an attacker registered the victim's address first."""
    register(anonymous(), EMAIL, "attacker chosen password")
    assert wired.users.get_by_email(EMAIL)["email_verified"] is False

    victim = anonymous()
    _, query = begin_google(victim)
    assert finish_google(victim, query, GOOD, google).headers["location"] == "/"

    user = wired.users.get_by_email(EMAIL)
    assert user["email_verified"] and user["has_google"] and not user["has_password"]
    attack = anonymous().post("/api/auth/login", json={"email": EMAIL, "password": "attacker chosen password"})
    assert attack.status_code == 401


def test_google_refuses_to_merge_into_a_different_google_identity(wired, google):
    wired.users.create_user("alice@example.com", "A", None, "someone-elses-sub", True)
    client = anonymous()
    _, query = begin_google(client)
    response = finish_google(client, query, GOOD, google)
    assert response.headers["location"] == "/?auth_error=google_failed"
    assert client.get("/api/session").json()["authenticated"] is False


@pytest.mark.parametrize(
    "case",
    ["bad_state", "no_cookie", "bad_nonce", "unverified_email", "missing_sub", "expired_cookie"],
)
def test_google_callback_rejects_bad_logins(wired, google, case):
    client = anonymous()
    _, query = begin_google(client)
    claims = dict(GOOD)

    if case == "bad_state":
        response = finish_google(client, query, claims, google, state="forged-state-value")
    elif case == "no_cookie":
        client.cookies.clear()
        response = finish_google(client, query, claims, google)
    elif case == "bad_nonce":
        google["claims"] = {**claims, "nonce": "not-the-nonce"}
        response = client.get("/auth/google/callback", params={"code": "c", "state": query["state"][0]},
                              follow_redirects=False)
    elif case == "unverified_email":
        response = finish_google(client, query, {**claims, "email_verified": False}, google)
    elif case == "missing_sub":
        response = finish_google(client, query, {**claims, "sub": ""}, google)
    else:
        expired = security.issue_signed({"s": query["state"][0], "n": "n", "v": "v"}, -1)
        client.cookies.clear()
        google["claims"] = {**claims, "nonce": "n"}
        response = client.get(
            "/auth/google/callback",
            params={"code": "c", "state": query["state"][0]},
            headers={"cookie": f"tm_oauth={expired}"},
            follow_redirects=False,
        )

    assert response.status_code == 303 and response.headers["location"] == "/?auth_error=google_failed"
    assert client.get("/api/session").json()["authenticated"] is False
    assert wired.users._users == {}


def test_google_denied_or_codeless_callbacks(wired, google):
    client = anonymous()
    for params in ({"error": "access_denied"}, {}, {"state": "x"}):
        response = client.get("/auth/google/callback", params=params, follow_redirects=False)
        assert response.headers["location"] == "/?auth_error=google_denied"


def test_google_token_verification_failure_is_handled(wired, google, monkeypatch):
    def reject(raw):
        raise oauth_google.OAuthError("Invalid ID token: wrong audience")

    monkeypatch.setattr(oauth_google, "_verify_id_token", reject)
    client = anonymous()
    _, query = begin_google(client)
    response = client.get("/auth/google/callback", params={"code": "c", "state": query["state"][0]},
                          follow_redirects=False)
    assert response.headers["location"] == "/?auth_error=google_failed"


def test_google_network_failure_does_not_leak(wired, google, monkeypatch):
    def boom(code, verifier, base_url):
        raise ConnectionError("db.internal:5432 password=hunter2")

    monkeypatch.setattr(oauth_google, "_exchange_code", boom)
    client = anonymous()
    _, query = begin_google(client)
    response = client.get("/auth/google/callback", params={"code": "c", "state": query["state"][0]},
                          follow_redirects=False)
    assert response.headers["location"] == "/?auth_error=google_failed"
    assert "hunter2" not in response.text


def test_public_base_url_is_used_for_the_redirect_uri(wired, google, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://tripmate-ai.jagoindia.in")
    _, query = begin_google(anonymous())
    assert query["redirect_uri"] == ["https://tripmate-ai.jagoindia.in/auth/google/callback"]


# ---- session and account deletion ------------------------------------------------------------------
def test_logout_clears_the_cookie(wired):
    client = signed_in_client(wired.users)
    response = client.delete("/api/session")
    assert response.status_code == 200 and "tm_session=" in response.headers["set-cookie"]
    client.cookies.clear()
    assert client.get("/api/session").json()["authenticated"] is False


def test_account_deletion_removes_trips_and_user(wired):
    client = signed_in_client(wired.users)
    for _ in range(2):
        assert client.post("/api/travel", json={"message": PROMPT}).status_code == 200
    other = signed_in_client(wired.users, "other@example.com")
    keep = other.post("/api/travel", json={"message": PROMPT}).json()["thread_id"]

    assert client.post("/api/account/delete", json={"confirm": False}).status_code == 400
    deleted = client.post("/api/account/delete", json={"confirm": True})
    assert deleted.status_code == 200 and deleted.json()["trips_deleted"] == 2

    assert wired.users.get(client.user["id"]) is None
    assert wired.registry.list_for_owner(client.user["id"]) == []
    assert client.get("/api/travel/threads").status_code == 401
    assert other.get(f"/api/travel/{keep}").status_code == 200  # other users untouched
    assert anonymous().post("/api/account/delete", json={"confirm": True}).status_code == 401


# ---- mail delivery -------------------------------------------------------------------------------------
def test_smtp_delivery_uses_starttls_login_and_never_raises(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context=None):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user))

        def send_message(self, message):
            calls.append(("send", message["To"], message["Subject"], message["From"]))

    monkeypatch.setattr(mailer, "_sink", None)
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    for name, value in {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": 587, "SMTP_USER": "u",
                        "SMTP_PASSWORD": "p", "SMTP_FROM": "TripMate <no-reply@example.com>",
                        "SMTP_STARTTLS": True}.items():
        monkeypatch.setattr(config, name, value)

    mailer._deliver("to@example.com", "Hello", "Body")
    assert calls == [("connect", "smtp.example.com", 587), ("starttls",), ("login", "u"),
                     ("send", "to@example.com", "Hello", "TripMate <no-reply@example.com>")]

    monkeypatch.setattr(mailer.smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    mailer._deliver("to@example.com", "Hello", "Body")  # logged, not raised


def test_mail_without_smtp_is_logged_for_development(monkeypatch):
    import logging

    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture(level=logging.WARNING)
    logger = logging.getLogger("mailer")
    logger.addHandler(handler)
    try:
        monkeypatch.setattr(mailer, "_sink", None)
        monkeypatch.setattr(config, "SMTP_HOST", "")
        mailer._deliver("dev@example.com", "Subject", "http://localhost/link")
    finally:
        logger.removeHandler(handler)
    assert any("DEV MAIL" in r and "http://localhost/link" in r for r in records)


def test_backend_helpers_exist():
    assert callable(backend.delete_account) and callable(backend.get_user_store)


def test_rejected_registrations_do_not_use_up_the_throttle(wired, mailbox):
    client = anonymous()
    for _ in range(8):
        assert register(client, "bad-address", PASSWORD).status_code == 400
        assert register(client, "ok@example.com", "short").status_code == 400
    assert register(client, "ok@example.com", PASSWORD).status_code == 200
