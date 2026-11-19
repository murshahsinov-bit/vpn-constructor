# -*- coding: utf-8 -*-
import pytest

pytest.importorskip("flask")

import netrun_worker.app as worker
from netrun_worker.licensing import issue_license
from netrun_worker.trials import TrialLedger

SECRET = "sales-test-secret"
DEVICE_ID = "android-abcdef0123456789"


@pytest.fixture
def sales(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "LICENSE_SECRET", SECRET)
    monkeypatch.setattr(worker, "TRIAL_LEDGER", TrialLedger(tmp_path / "trials.json"))
    monkeypatch.setattr(worker, "PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setattr(worker, "ALLOW_USER_AUTH", False)
    monkeypatch.setattr(worker, "TRIAL_TOTAL_BYTES", 10 * 1024**3)
    monkeypatch.setattr(
        worker,
        "get_asset",
        lambda name: (b"vless://x@example.test:443?type=tcp#Test", f"test:{name}", False),
    )
    return worker.app.test_client()


def test_plans_are_served_in_rubles(sales):
    response = sales.get("/api/plans")

    assert response.status_code == 200
    body = response.get_json()
    assert body["currency"] == "RUB"
    assert body["trial_days"] == 3
    assert [plan["id"] for plan in body["plans"]] == ["m1", "m3", "m12"]
    assert body["plans"][0]["price_rub"] == 149
    assert body["plans"][0]["price_stars"] >= 1
    assert body["license_enabled"] is True
    assert "android_apk" in body["links"]


def test_license_endpoint_accepts_valid_token(sales):
    token = issue_license(SECRET, sub="abc", plan="m1", device="android", days=30)

    response = sales.get("/api/license", query_string={"token": token})

    assert response.status_code == 200
    body = response.get_json()
    assert body["valid"] is True
    assert body["plan"] == "m1"
    assert body["days_left"] in (29, 30)
    assert body["subscription_url"].startswith("https://example.test/sub/auto_happ.txt?token=SVS1.")
    assert body["ios_url"].startswith("https://example.test/sub/incy.txt?token=SVS1.")


def test_license_endpoint_rejects_expired(sales, monkeypatch):
    token = issue_license(SECRET, sub="abc", plan="trial", days=1, now=1_000)
    monkeypatch.setattr(worker.time, "time", lambda: 1_000 + 2 * 86_400)

    response = sales.get("/api/license", query_string={"token": token})

    assert response.status_code == 403
    assert response.get_json()["valid"] is False


def test_activate_accepts_bot_link_text(sales):
    token = issue_license(SECRET, sub="abc", plan="m3", device="ios", days=90)
    link = f"https://example.test/activate/{token}"

    response = sales.post("/api/activate", json={"link": f"Ссылка: {link}"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["valid"] is True
    assert body["device"] == "ios"
    assert body["plan"] == "m3"


def test_activate_requires_a_license(sales):
    assert sales.post("/api/activate", json={}).status_code == 400
    assert (
        sales.post("/api/activate", json={"link": "https://example.test/activate/nope"}).status_code
        == 400
    )


def test_trial_issues_once_per_device(sales):
    first = sales.post("/api/trial", json={"device": "android", "device_id": DEVICE_ID})

    assert first.status_code == 200
    body = first.get_json()
    assert body["valid"] is True
    assert body["trial"] is True
    assert body["trial_days"] == 3
    assert body["days_left"] == 3
    assert body["token"].startswith("SVS1.")
    assert body["subscription_url"].startswith("https://example.test/sub/auto_happ.txt?token=SVS1.")

    second = sales.post("/api/trial", json={"device": "android", "device_id": DEVICE_ID})
    assert second.status_code == 409
    assert second.get_json()["error"] == "trial_already_used"


def test_trial_rejects_bad_device_id(sales):
    response = sales.post("/api/trial", json={"device": "android", "device_id": "short"})
    assert response.status_code == 400

    response = sales.post("/api/trial", json={"device": "windows", "device_id": DEVICE_ID})
    assert response.status_code == 400


def test_license_token_opens_subscription(sales):
    token = issue_license(SECRET, sub="abc", plan="m1", device="android", days=30)

    response = sales.get("/sub/auto_happ.txt", query_string={"token": token})

    assert response.status_code == 200
    assert b"vless://" in response.data
    # Триал и платный тариф получают разные лимиты трафика.
    assert "total=" in response.headers["subscription-userinfo"]


def test_expired_license_is_forbidden_on_subscription(sales, monkeypatch):
    token = issue_license(SECRET, sub="abc", plan="m1", days=1, now=1_000)
    monkeypatch.setattr(worker.time, "time", lambda: 1_000 + 2 * 86_400)

    response = sales.get("/sub/auto_happ.txt", query_string={"token": token})

    assert response.status_code == 403


def test_user_auth_is_off_by_default(sales):
    response = sales.get("/sub/auto_happ.txt", query_string={"user": "qa@shieldvpn.dev"})
    assert response.status_code == 403


def test_user_auth_can_be_enabled_for_migration(sales, monkeypatch):
    monkeypatch.setattr(worker, "ALLOW_USER_AUTH", True)

    response = sales.get("/sub/auto_happ.txt", query_string={"user": "qa@shieldvpn.dev"})

    assert response.status_code == 200


def test_admin_issue_is_hidden_without_token(sales):
    response = sales.post("/api/admin/issue", json={"plan": "m1"})
    assert response.status_code == 404


def test_admin_issue_returns_license(sales, monkeypatch):
    monkeypatch.setattr(worker, "ADMIN_TOKEN", "admin-secret")

    response = sales.post(
        "/api/admin/issue",
        json={"plan": "m12", "device": "ios"},
        headers={"X-Admin-Token": "admin-secret"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["valid"] is True
    assert body["plan"] == "m12"
    assert body["device"] == "ios"


def test_activation_page_renders_license(sales):
    token = issue_license(SECRET, sub="abc", plan="m1", device="android", days=30)

    response = sales.get(f"/activate/{token}")

    assert response.status_code == 200
    assert "shieldvpn://activate?token=SVS1." in response.get_data(as_text=True)
    assert "Действует до" in response.get_data(as_text=True)
