"""Detect when a Google Meet session has ended by checking DOM signals."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from tempa.meet.bot_participants import count_humans

_logger = logging.getLogger(__name__)

# Hard safety cap: leave even if humans somehow still appear present.
MEET_HARD_MAX_SECONDS = 28800

_END_SELECTORS = [
    'text="You left the meeting"',
    'text="The call has ended"',
    'text="You\'ve been removed from the meeting"',
    'text="The meeting has ended for everyone"',
    'button:has-text("Rejoin")',
    'button:has-text("Return to home screen")',
    'a:has-text("Rejoin")',
    'a:has-text("Return to home screen")',
]

_LEAVE_BUTTON_SELECTOR = 'button[aria-label*="Leave call"], button[aria-label*="Leave meeting"]'

# Returns display names for each participant tile (empty string when unknown).
_PARTICIPANT_NAMES_JS = """
(() => {
    const PIN_RE = /^Pin\\s+(.+?)\\s+to your main screen$/i;
    const MORE_RE = /^More options for\\s+(.+)$/i;
    const UI_TEXT = /^(you|pin|mute|unmute|remove|turn|more|present|share|raise|lower|add|host)$/i;
    const names = [];
    for (const tile of document.querySelectorAll('[data-participant-id]')) {
        let name = '';
        for (const child of tile.querySelectorAll('[aria-label]')) {
            const label = child.getAttribute('aria-label') || '';
            let m = label.match(PIN_RE);
            if (m) { name = m[1].trim(); break; }
            m = label.match(MORE_RE);
            if (m) { name = m[1].trim(); break; }
        }
        if (!name) {
            const walker = document.createTreeWalker(tile, NodeFilter.SHOW_TEXT);
            let node;
            while (node = walker.nextNode()) {
                const t = (node.textContent || '').trim();
                if (t.length < 2 || t.length > 60) continue;
                if (UI_TEXT.test(t) || /^\\(You\\)$/i.test(t)) continue;
                const parent = node.parentElement;
                if (parent && parent.closest('button')) continue;
                name = t;
                break;
            }
        }
        names.push(name);
    }
    if (names.length > 0) return names;

    // Fallback: toolbar people count only (no names) — return that many empty strings.
    const btn = document.querySelector(
        'button[aria-label*="participant"], button[aria-label*="people"]'
    );
    if (btn) {
        const match = (btn.textContent || '').match(/(\\d+)/);
        if (match) {
            const n = parseInt(match[1], 10);
            if (n > 0) return Array(n).fill('');
        }
    }
    return null;
})()
"""


@dataclass
class MeetingEndTracker:
    """Tracks human presence so Tempa does not exit while humans remain (bots ignored)."""

    alone_since: float | None = None
    saw_multiple_participants: bool = False
    alone_grace_seconds: float = 300.0
    last_human_count: int = -1


def calendar_start_timestamp(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


async def get_participant_names(page) -> list[str] | None:
    """Return display names from Meet tiles, or None if DOM scrape failed."""
    try:
        result = await page.evaluate(_PARTICIPANT_NAMES_JS)
        if result is None:
            return None
        if isinstance(result, list):
            return [str(n or "") for n in result]
        return None
    except Exception as err:
        _logger.debug("GMEET: participant names evaluate failed err=%s", err)
        return None


async def get_human_participant_count(page) -> int:
    """Human tile count (known meeting bots excluded). -1 if unknown."""
    names = await get_participant_names(page)
    if names is None:
        return -1
    return count_humans(names)


async def check_meeting_ended(
    page,
    *,
    tracker: MeetingEndTracker | None = None,
    event_start_ts: float | None = None,
) -> bool:
    # ponytail: pre-start lobby wait — don't alone-exit before the calendar start time
    if event_start_ts is not None and time.time() < event_start_ts:
        if tracker is not None:
            tracker.alone_since = None
        return False

    for selector in _END_SELECTORS:
        try:
            count = await page.locator(selector).count()
            if count > 0:
                _logger.info("GMEET: meeting-end signal detected: %s", selector)
                return True
        except Exception as err:
            _logger.debug("GMEET: end selector check failed selector=%s err=%s", selector, err)

    try:
        leave_count = await page.locator(_LEAVE_BUTTON_SELECTOR).count()
        if leave_count == 0:
            url = page.url or ""
            if "meet.google.com" not in url:
                _logger.info("GMEET: navigated away from Meet, treating as ended")
                return True
    except Exception as err:
        _logger.debug("GMEET: leave button check failed err=%s", err)

    human_count = await get_human_participant_count(page)
    if human_count < 0:
        return False

    if tracker is not None:
        tracker.last_human_count = human_count

    if human_count > 0:
        if tracker is not None:
            tracker.alone_since = None
            tracker.saw_multiple_participants = True
        return False

    # No humans left — only Tempa and/or other meeting bots remain.
    if tracker is None:
        _logger.info("GMEET: no humans left in meeting, treating as ended")
        return True

    now = time.monotonic()
    if tracker.alone_since is None:
        tracker.alone_since = now
        _logger.info(
            "GMEET: no humans left (bots ignored), waiting up to %.0fs before leaving",
            tracker.alone_grace_seconds,
        )
        return False

    alone_for = now - tracker.alone_since
    if alone_for >= tracker.alone_grace_seconds:
        _logger.info(
            "GMEET: no humans for %.0fs (grace %.0fs), treating as ended",
            alone_for,
            tracker.alone_grace_seconds,
        )
        return True

    return False
