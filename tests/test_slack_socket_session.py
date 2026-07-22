"""Socket Mode session liveness markers."""

from tempa.channels.slack import session


def test_touch_envelope_updates_status_field():
    session._last_envelope_at = None  # noqa: SLF001
    session.touch_envelope()
    assert session._last_envelope_at  # noqa: SLF001
