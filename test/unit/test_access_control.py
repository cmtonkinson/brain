from access_control import is_sender_allowed
from config import settings


def test_sender_allowed_by_channel(monkeypatch) -> None:
    monkeypatch.setattr(
        settings.signal,
        "allowed_senders_by_channel",
        {"signal": ["+15551234567"]},
        raising=False,
    )
    monkeypatch.setattr(settings.signal, "allowed_senders", [], raising=False)

    assert is_sender_allowed("signal", "+15551234567") is True
    assert is_sender_allowed("signal", "+15559876543") is False
    assert is_sender_allowed("email", "+15551234567") is False


def test_sender_allowed_legacy_list(monkeypatch) -> None:
    monkeypatch.setattr(settings.signal, "allowed_senders_by_channel", {}, raising=False)
    monkeypatch.setattr(settings.signal, "allowed_senders", ["+15550001111"], raising=False)

    assert is_sender_allowed("signal", "+15550001111") is True
    assert is_sender_allowed("signal", "+15550002222") is False
