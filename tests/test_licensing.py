# -*- coding: utf-8 -*-
import json

import pytest

from netrun_worker import licensing, plans
from netrun_worker.trials import TrialLedger

SECRET = "test-secret-0123456789"


def test_license_roundtrip():
    token = licensing.issue_license(
        SECRET, sub="abc123", plan="m1", device="android", days=30, now=1_700_000_000
    )

    payload = licensing.verify_license(SECRET, token, now=1_700_000_001)

    assert payload["plan"] == "m1"
    assert payload["dev"] == "android"
    assert payload["sub"] == "abc123"
    assert payload["exp"] == 1_700_000_000 + 30 * 86_400


def test_license_rejects_tampering():
    token = licensing.issue_license(SECRET, sub="abc", plan="trial", days=3)
    prefix, body, signature = token.split(".")
    tampered = f"{prefix}.{body[:-1]}A.{signature}"

    with pytest.raises(licensing.LicenseError):
        licensing.verify_license(SECRET, tampered)


def test_license_rejects_expired_and_foreign_secret():
    token = licensing.issue_license(SECRET, sub="abc", plan="trial", days=3, now=1_000)

    with pytest.raises(licensing.LicenseError):
        licensing.verify_license(SECRET, token, now=1_000 + 4 * 86_400)

    with pytest.raises(licensing.LicenseError):
        licensing.verify_license("another-secret", token, now=1_001)


def test_license_rejects_garbage():
    for value in ("", "SVS1", "SVS1.a", "SVS1.a.b.c", "x" * 2000):
        with pytest.raises(licensing.LicenseError):
            licensing.verify_license(SECRET, value)


def test_lookalike_matches_only_license_shape():
    token = licensing.issue_license(SECRET, sub="abc", plan="m1", days=30)

    assert licensing.lookalike(token)
    assert not licensing.lookalike("a" * 32)
    assert not licensing.lookalike(token + ".extra")


def test_plans_are_cheap_and_convert_to_stars(monkeypatch):
    monkeypatch.setenv("STAR_RUB_RATE", "1.5")
    payload = plans.plans_payload()

    assert payload["currency"] == "RUB"
    assert payload["trial_days"] == 3
    prices = [plan["price_rub"] for plan in payload["plans"]]
    assert prices == [149, 349, 990]
    assert payload["plans"][0]["price_stars"] == 100  # ceil(149 / 1.5)
    assert all(plan["days"] > 0 for plan in payload["plans"])


def test_trial_ledger_blocks_second_claim_and_persists(tmp_path):
    path = tmp_path / "trials.json"
    ledger = TrialLedger(path)

    assert ledger.claim("device-aaaa", "ip-1", ttl_days=3)
    assert not ledger.claim("device-aaaa", "ip-2", ttl_days=3)

    reloaded = TrialLedger(path)
    assert not reloaded.claim("device-aaaa", "ip-3", ttl_days=3)
    # Другое устройство с другого IP получает триал.
    assert reloaded.claim("device-bbbb", "ip-4", ttl_days=3)


def test_trial_ledger_limits_ip_per_day(tmp_path):
    ledger = TrialLedger(tmp_path / "trials.json")

    assert ledger.claim("device-1", "same-ip", ttl_days=3, ip_daily_limit=2)
    assert ledger.claim("device-2", "same-ip", ttl_days=3, ip_daily_limit=2)
    assert not ledger.claim("device-3", "same-ip", ttl_days=3, ip_daily_limit=2)


def test_trial_ledger_survives_broken_file(tmp_path):
    path = tmp_path / "trials.json"
    path.write_text("{not-json", encoding="utf-8")

    ledger = TrialLedger(path)

    assert ledger.claim("device-x", "", ttl_days=3)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "device-x" in data["devices"]
