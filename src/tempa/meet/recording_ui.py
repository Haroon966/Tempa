from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_RECORDING_BANNER_JS = """
() => {
  const id = 'tempa-recording-notice';
  if (document.getElementById(id)) return;
  const el = document.createElement('div');
  el.id = id;
  el.setAttribute('role', 'status');
  el.setAttribute('aria-live', 'polite');
  el.textContent = '⏺ Tempa is recording this meeting for your records.';
  Object.assign(el.style, {
    position: 'fixed',
    top: '12px',
    right: '12px',
    zIndex: '2147483647',
    background: '#b91c1c',
    color: '#ffffff',
    padding: '10px 14px',
    borderRadius: '8px',
    fontSize: '13px',
    fontFamily: 'system-ui, sans-serif',
    boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
  });
  document.body.appendChild(el);
}
"""


async def show_recording_notice(page) -> None:
    """FR-MEET-14 / SEC-04: visible recording indicator when capture starts."""
    try:
        await page.evaluate(_RECORDING_BANNER_JS)
        logger.info("GMEET: recording notice displayed")
    except Exception:
        logger.exception("GMEET: failed to show recording notice")
