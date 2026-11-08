import base64
from datetime import date, timedelta

import pytest

pytest.importorskip("flask")

import netrun_worker.app as worker


def make_client(days: int = 30) -> dict:
    return {
        "name": "Тест",
        "token": "a" * 32,
        "expires_at": (date.today() + timedelta(days=days)).isoformat(),
    }


def test_core_subscription_headers(monkeypatch):
    monkeypatch.delenv("PROFILE_TITLE", raising=False)
    monkeypatch.delenv("SUPPORT_URL", raising=False)
    monkeypatch.delenv("PROFILE_WEB_PAGE_URL", raising=False)
    client = make_client(days=30)

    headers = worker.build_subscription_headers(client)

    assert headers["profile-title"] == "VPN Constructor"
    assert len(headers["profile-title"]) <= 25
    assert headers["profile-update-interval"] == "1"
    assert headers["hide-url"] == "1"
    assert headers["subscription-always-hwid-enable"] == "1"
    assert headers["no-limit-xhttp-enabled"] == "1"

    userinfo = headers["subscription-userinfo"]
    assert "upload=0" in userinfo
    assert "download=0" in userinfo
    assert "total=107374182400" in userinfo
    assert f"expire={worker._expire_unix(client['expires_at'])}" in userinfo

    # До истечения больше 3 дней — баннер не включаем.
    assert "sub-expire" not in headers
    assert "announce" not in headers

    # HTTP-заголовки обязаны быть latin-1: кириллица допускается только в base64.
    for value in headers.values():
        value.encode("latin-1")


def test_expire_banner_and_button(monkeypatch):
    monkeypatch.setenv("SUB_EXPIRE_BUTTON_LINK", "https://t.me/your_bot")
    client = make_client(days=2)

    headers = worker.build_subscription_headers(client)

    assert headers["sub-expire"] == "1"
    assert headers["sub-expire-button-link"] == "https://t.me/your_bot"

    encoded = headers["announce"].removeprefix("base64:")
    message = base64.b64decode(encoded).decode("utf-8")
    assert "Подписка истекает" in message
    assert client["expires_at"] in message


def test_optional_headers_only_when_set(monkeypatch):
    monkeypatch.setenv("SUPPORT_URL", "https://t.me/support")
    monkeypatch.setenv("PROFILE_WEB_PAGE_URL", "https://example.com/tariff")
    monkeypatch.setenv("PROFILE_TITLE", "Мой VPN")

    headers = worker.build_subscription_headers(make_client())

    assert headers["support-url"] == "https://t.me/support"
    assert headers["profile-web-page-url"] == "https://example.com/tariff"

    # Кириллица в HTTP-заголовке недопустима: Happ/INCY понимают base64.
    assert headers["profile-title"].startswith("base64:")
    decoded = base64.b64decode(
        headers["profile-title"].removeprefix("base64:")
    ).decode("utf-8")
    assert decoded == "Мой VPN"


def test_auto_json_route_returns_headers(monkeypatch):
    client = make_client(days=30)
    monkeypatch.setattr(worker, "authorize_token", lambda _token: client)
    monkeypatch.setattr(
        worker,
        "get_asset",
        lambda name: (b'{"outbounds": []}', f"test:{name}", False),
    )

    response = worker.app.test_client().get("/sub/auto.json?token=" + "a" * 32)

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["profile-title"] == "VPN Constructor"
    assert "subscription-userinfo" in response.headers
    assert response.headers["hide-url"] == "1"


def test_txt_routes_return_plain_text(monkeypatch):
    client = make_client(days=30)
    monkeypatch.setattr(worker, "authorize_token", lambda _token: client)
    monkeypatch.setattr(
        worker,
        "get_asset",
        lambda name: (b"vless://uuid@example.com:443?type=tcp#Test", f"test:{name}", False),
    )

    for path in (
        "/sub/auto.txt",
        "/sub/auto_happ.txt",
        "/sub/whitelist.txt",
        "/sub/whitelist_happ.txt",
    ):
        response = worker.app.test_client().get(path + "?token=" + "a" * 32)
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/plain")
        assert response.headers["profile-title"] == "VPN Constructor"
        assert b"vless://" in response.data


def test_webrtc_route_contains_socks_address(monkeypatch):
    client = make_client(days=30)
    monkeypatch.setattr(worker, "authorize_token", lambda _token: client)
    monkeypatch.setenv("WEBRTC_SOCKS5", "socks5://user:pass@203.0.113.5:1080")

    response = worker.app.test_client().get(
        "/sub/webrtc.txt?token=" + "a" * 32
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/plain")
    assert b"socks5://user:pass@203.0.113.5:1080" in response.data


def test_invalid_token_is_forbidden(monkeypatch):
    monkeypatch.setattr(worker, "authorize_token", lambda _token: None)

    response = worker.app.test_client().get(
        "/sub/auto.json?token=" + "a" * 32
    )

    assert response.status_code == 403
