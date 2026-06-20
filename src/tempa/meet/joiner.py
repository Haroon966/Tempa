import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from tempa.meet.storage import ArtifactStorageAdapter, LocalStorageAdapter

_logger = logging.getLogger(__name__)

_background_uploads: list[asyncio.Task] = []


async def _flush_pending_uploads() -> None:
    if _background_uploads:
        await asyncio.gather(*list(_background_uploads), return_exceptions=True)


def _upload_screenshot_bg(local_path: str, storage: Optional[ArtifactStorageAdapter]) -> None:
    """Synchronous upload helper -- meant to run via asyncio.to_thread."""
    if not storage:
        return
    try:
        storage.upload(local_path, content_type="image/png")
    except Exception:
        _logger.exception("GMEET: background screenshot upload failed for %s", local_path)


async def _take_and_upload_screenshot(
    page,
    local_path: str,
    storage: Optional[ArtifactStorageAdapter],
) -> None:
    """Take a screenshot, save locally, and fire-and-forget upload to remote storage."""
    await page.screenshot(path=local_path)
    if storage:
        task = asyncio.create_task(asyncio.to_thread(_upload_screenshot_bg, local_path, storage))
        _background_uploads.append(task)
        task.add_done_callback(lambda t: _background_uploads.remove(t) if t in _background_uploads else None)


async def _dismiss_consent_popup(
    page,
    screenshot_dir: Optional[str],
    screenshot_storage: Optional[ArtifactStorageAdapter] = None,
) -> bool:
    consent_clicked = False
    consent_selectors = [
        'button:has-text("Continue without")',
        'a:has-text("Continue without")',
        '[role="link"]:has-text("Continue without")',
        'button:has-text("Continue without microphone")',
        'button:has-text("Got it")',
        'button:has-text("Dismiss")',
        "text=/Continue without microphone and camera/i",
        "text=/Continue without/i",
    ]

    scopes = [page.locator('div[role="dialog"]').first, page]
    for scope in scopes:
        for selector in consent_selectors:
            target = scope.locator(selector).first
            if await target.count() > 0 and await target.is_visible():
                await target.click()
                consent_clicked = True
                _logger.info("GMEET: consent popup dismissed")
                if screenshot_dir:
                    await _take_and_upload_screenshot(
                        page,
                        f"{screenshot_dir}/02b_after_consent.png",
                        screenshot_storage,
                    )
                return consent_clicked

    allow_without = page.get_by_role("link", name="Continue without microphone and camera")
    if await allow_without.count() > 0 and await allow_without.is_visible():
        await allow_without.click()
        _logger.info("GMEET: consent popup dismissed via role link")
        return True

    consent_dialog = page.locator('div[role="dialog"]').first
    dropdown_button = consent_dialog.locator(
        'button[aria-label*="More"], button[aria-label*="options"], button[aria-haspopup="menu"]'
    ).first
    if await dropdown_button.count() > 0:
        await dropdown_button.click()
        menu_option = page.locator('div[role="menu"]').locator("text=/Continue without/i").first
        if await menu_option.count() > 0 and await menu_option.is_visible():
            await menu_option.click()
            consent_clicked = True
            _logger.info("GMEET: consent popup dismissed via menu")
            if screenshot_dir:
                await _take_and_upload_screenshot(
                    page,
                    f"{screenshot_dir}/02b_after_consent.png",
                    screenshot_storage,
                )

    if not consent_clicked:
        direct_text = page.locator("text=/Continue without microphone and camera/i").first
        if await direct_text.count() > 0 and await direct_text.is_visible():
            await direct_text.click()
            consent_clicked = True
            _logger.info("GMEET: consent popup dismissed via direct text")
            if screenshot_dir:
                await _take_and_upload_screenshot(
                    page,
                    f"{screenshot_dir}/02b_after_consent.png",
                    screenshot_storage,
                )

    return consent_clicked


async def _dismiss_consent_with_retry(
    page,
    screenshot_dir: Optional[str],
    *,
    max_attempts: int = 5,
    interval_s: float = 1.0,
    wait_for_dialog: bool = False,
    screenshot_storage: Optional[ArtifactStorageAdapter] = None,
) -> bool:
    """Try to dismiss the consent popup, retrying up to *max_attempts* times.

    When *wait_for_dialog* is True, first waits up to 5 s for a dialog element
    to appear before entering the retry loop (useful after join click when the
    dialog can lag).
    """
    if wait_for_dialog:
        try:
            await page.wait_for_selector('div[role="dialog"]', timeout=5000)
        except PlaywrightTimeoutError:
            _logger.debug("GMEET: no consent dialog appeared within 5 s, skipping retry loop")
            return False

    for attempt in range(1, max_attempts + 1):
        try:
            if await _dismiss_consent_popup(
                page,
                screenshot_dir,
                screenshot_storage=screenshot_storage,
            ):
                return True
        except Exception:
            _logger.debug("GMEET: consent dismiss attempt %d raised, retrying", attempt)

        if attempt < max_attempts:
            await asyncio.sleep(interval_s)

    _logger.warning("GMEET: consent popup not dismissed after %d attempts", max_attempts)
    return False


@dataclass
class MeetSession:
    playwright: object
    browser: object
    context: object
    page: object

    async def close(self):
        await self.context.close()
        await self.browser.close()
        await self.playwright.stop()


_WAITING_ROOM_TEXTS = [
    "Please wait until a meeting host brings you into the call",
    "Asking to join",
    "Waiting for someone to let you in",
    "Ask to join",
]


async def _in_waiting_room(page) -> bool:
    for text in _WAITING_ROOM_TEXTS:
        try:
            if await page.locator(f'text="{text}"').count() > 0:
                return True
        except Exception as err:
            _logger.debug("GMEET: failed waiting-room text check text=%s err=%s", text, err)
    return False


async def _is_in_active_call(page) -> bool:
    """True when the bot is in the call (not the pre-join or lobby screen)."""
    try:
        return bool(
            await page.evaluate(
                """() => {
                    const waitingTexts = [
                        'Please wait until a meeting host brings you into the call',
                        'Asking to join',
                        'Waiting for someone to let you in',
                    ];
                    const bodyText = document.body?.innerText || '';
                    for (const t of waitingTexts) {
                        if (bodyText.includes(t)) return false;
                    }
                    const leaveBtn = document.querySelector('button[aria-label*="Leave call"]');
                    const tiles = document.querySelectorAll('[data-participant-id]');
                    const peopleBtn = document.querySelector('button[aria-label*="People"]');
                    const micBtn = document.querySelector(
                        'button[aria-label*="microphone" i][data-is-muted], button[data-is-muted]'
                    );
                    if (leaveBtn && tiles.length >= 1) return true;
                    if (leaveBtn && peopleBtn && micBtn) return true;
                    return false;
                }"""
            )
        )
    except Exception as err:
        _logger.debug("GMEET: failed in-call detection err=%s", err)
        return False


async def wait_for_admission(
    page,
    *,
    timeout_s: float = 120.0,
    poll_interval_s: float = 2.0,
) -> bool:
    """Block until the bot is admitted into the meeting.

    Detects the lobby via known waiting-room copy. Once that copy is gone and
    in-call controls are visible, the bot is treated as admitted — including
    when it is the only participant (organizer joining an empty room).
    """
    import time as _time

    deadline = _time.monotonic() + timeout_s
    _logger.info("GMEET: waiting for host admission (timeout=%.0fs)", timeout_s)

    while _time.monotonic() < deadline:
        if await _in_waiting_room(page):
            await asyncio.sleep(poll_interval_s)
            continue

        if await _is_in_active_call(page):
            _logger.info("GMEET: admitted to meeting (in-call UI detected)")
            return True

        await asyncio.sleep(poll_interval_s)

    _logger.warning("GMEET: admission timeout after %.0fs", timeout_s)
    return False


_STEALTH_INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"

_GUEST_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
]

_LAUNCH_ARGS = [
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
]


_JOIN_BUTTON_SELECTOR = (
    'button:has-text("Switch here"), '
    'button:has-text("Join now"), '
    'button:has-text("Join here"), '
    'button:has-text("Ask to join"), '
    'button[jsname="Qx7uuf"]'
)


async def _wait_for_prejoin_ready(page, *, timeout_ms: int = 120000) -> None:
    """Wait until Meet finishes loading and shows the join controls."""
    import time as _time

    deadline = _time.monotonic() + timeout_ms / 1000
    while _time.monotonic() < deadline:
        unavailable = page.locator(
            "text=/meeting has ended|You can't join|You cannot join|Check your meeting code|Invalid video call/i"
        )
        if await unavailable.count() > 0:
            text = await unavailable.first.inner_text()
            raise RuntimeError(f"Meeting unavailable: {text[:120]}")

        await _dismiss_consent_popup(page, None)

        join_btn = page.locator(_JOIN_BUTTON_SELECTOR).first
        if await join_btn.count() > 0:
            try:
                if await join_btn.is_visible():
                    _logger.info("GMEET: pre-join UI ready")
                    return
            except Exception:
                pass

        getting_ready = page.locator("text=/Getting ready/i")
        if await getting_ready.count() > 0:
            _logger.debug("GMEET: still getting ready…")
        await asyncio.sleep(2)

    raise PlaywrightTimeoutError("Pre-join UI did not appear in time")


async def _click_join_button(page, join_button, *, screenshot_dir, screenshot_storage) -> None:
    if screenshot_dir:
        await _take_and_upload_screenshot(
            page,
            f"{screenshot_dir}/02_before_join.png",
            screenshot_storage,
        )
    _logger.info("GMEET: clicking join")
    try:
        await join_button.click(timeout=10000)
    except Exception:
        await join_button.click(force=True)
    _logger.info("GMEET: join clicked")
    if screenshot_dir:
        await asyncio.sleep(2)
        await _take_and_upload_screenshot(
            page,
            f"{screenshot_dir}/03_after_join.png",
            screenshot_storage,
        )


async def _fill_guest_name(
    page,
    bot_name: str,
    screenshot_dir: Optional[str],
    screenshot_storage: Optional[ArtifactStorageAdapter] = None,
) -> None:
    name_selectors = [
        'input[aria-label="Your name"]',
        'input[type="text"][aria-label*="name" i]',
        'input[type="text"]',
    ]
    for selector in name_selectors:
        input_el = page.locator(selector).first
        try:
            await input_el.wait_for(state="visible", timeout=10000)
        except PlaywrightTimeoutError:
            continue
        await input_el.fill(bot_name)
        _logger.info("GMEET: guest name set to %r via %s", bot_name, selector)
        if screenshot_dir:
            await _take_and_upload_screenshot(
                page,
                f"{screenshot_dir}/01b_after_name.png",
                screenshot_storage,
            )
        return

    _logger.warning("GMEET: could not find guest name input")


async def join_meet(
    meet_url: str,
    *,
    storage_state_path: Optional[str] = None,
    bot_name: Optional[str] = None,
    disable_mic: bool = True,
    disable_camera: bool = True,
    join_timeout_ms: int = 90000,
    headless: bool = True,
    slow_mo_ms: Optional[int] = None,
    screenshot_dir: Optional[str] = "./screenshots",
    storage_adapter: Optional[ArtifactStorageAdapter] = None,
) -> MeetSession:
    screenshot_storage = storage_adapter or LocalStorageAdapter()
    guest_mode = bool(bot_name) and not storage_state_path

    if guest_mode and headless:
        display = os.environ.get("DISPLAY")
        if display:
            _logger.info("GMEET: virtual display detected (DISPLAY=%s), using headed mode for guest join", display)
            headless = False
        else:
            _logger.warning(
                "GMEET: headless guest mode may fail due to Google's bot detection. "
                "For reliable guest join, use a virtual display (Xvfb) with DISPLAY env var."
            )

    p = await async_playwright().start()
    browser = None
    context = None
    page = None
    try:
        launch_kwargs = {"headless": headless, "slow_mo": slow_mo_ms}
        launch_args = list(_GUEST_LAUNCH_ARGS if guest_mode else _LAUNCH_ARGS)
        launch_kwargs["args"] = launch_args
        browser = await p.chromium.launch(**launch_kwargs)
        context_kwargs = {}
        if storage_state_path:
            context_kwargs["storage_state"] = storage_state_path
        if guest_mode:
            context_kwargs["viewport"] = {"width": 1280, "height": 720}
            context_kwargs["locale"] = "en-US"
            context_kwargs["permissions"] = ["microphone"]
        context = await browser.new_context(**context_kwargs)
        if guest_mode:
            await context.add_init_script(_STEALTH_INIT_SCRIPT)
        page = await context.new_page()
        _logger.info("GMEET: goto %s (guest_mode=%s)", meet_url, guest_mode)
        await page.goto(meet_url, wait_until="domcontentloaded")
        if screenshot_dir:
            Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
            await _take_and_upload_screenshot(
                page,
                f"{screenshot_dir}/01_after_goto.png",
                screenshot_storage,
            )

        if guest_mode:
            await _fill_guest_name(page, bot_name, screenshot_dir, screenshot_storage)

        await _wait_for_prejoin_ready(page, timeout_ms=join_timeout_ms)

        if disable_mic:
            mic_button = page.locator(
                'button[aria-label*="microphone" i], button[aria-label*="mic" i], button[data-is-muted]'
            ).first
            try:
                await mic_button.wait_for(state="visible", timeout=5000)
                await mic_button.click()
                _logger.info("GMEET: mic toggled")
            except PlaywrightTimeoutError:
                _logger.debug("GMEET: mic button not found, skipping")

        if disable_camera:
            cam_button = page.locator('button[aria-label*="camera" i], button[aria-label*="video" i]').first
            try:
                await cam_button.wait_for(state="visible", timeout=5000)
                await cam_button.click()
                _logger.info("GMEET: camera toggled")
            except PlaywrightTimeoutError:
                _logger.debug("GMEET: camera button not found, skipping")

        await _dismiss_consent_with_retry(
            page,
            screenshot_dir,
            screenshot_storage=screenshot_storage,
        )

        join_now = page.locator(
            'button:has-text("Switch here"), button:has-text("Join now"), button:has-text("Join here")'
        ).first
        ask_to_join = page.locator('button:has-text("Ask to join")').first
        join_button = join_now if await join_now.count() > 0 else ask_to_join
        joined = False
        try:
            await join_button.wait_for(state="visible", timeout=15000)
            await _click_join_button(
                page,
                join_button,
                screenshot_dir=screenshot_dir,
                screenshot_storage=screenshot_storage,
            )
            await _dismiss_consent_with_retry(
                page,
                screenshot_dir,
                wait_for_dialog=True,
                screenshot_storage=screenshot_storage,
            )
            joined = True
        except Exception:
            bbox = await join_button.bounding_box()
            top_el = None
            overlay_count = await page.locator('div[role="dialog"]').count()
            material_overlay_count = await page.locator("div.uW2Fw-Sx9Kwc").count()
            if bbox:
                top_el = await page.evaluate(
                    """(p) => {
                        const el = document.elementFromPoint(p.x, p.y);
                        if (!el) return null;
                        return {
                            tag: el.tagName,
                            id: el.id || null,
                            className: (typeof el.className === 'string' ? el.className : String(el.className)) || null,
                            role: el.getAttribute('role'),
                            ariaLabel: el.getAttribute('aria-label')
                        };
                    }""",
                    {
                        "x": bbox["x"] + bbox["width"] / 2,
                        "y": bbox["y"] + bbox["height"] / 2,
                    },
                )
            try:
                top_class = (top_el or {}).get("className") if isinstance(top_el, dict) else None
                if overlay_count > 0 or material_overlay_count > 0 or top_class == "uW2Fw-IE5DDf":
                    await join_button.click(force=True)
                    await _dismiss_consent_with_retry(
                        page,
                        screenshot_dir,
                        wait_for_dialog=True,
                        screenshot_storage=screenshot_storage,
                    )
                    joined = True
            except Exception as err:
                _logger.warning("GMEET: join force-click fallback failed err=%s", err)
            if not joined:
                raise

        return MeetSession(
            playwright=p,
            browser=browser,
            context=context,
            page=page,
        )
    except Exception:
        if page and screenshot_dir:
            try:
                Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
                await _take_and_upload_screenshot(page, f"{screenshot_dir}/error.png", screenshot_storage)
            except Exception:
                _logger.debug("GMEET: failed to take error screenshot")
        if context:
            with contextlib.suppress(Exception):
                await context.close()
        if browser:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            await p.stop()
        raise
    finally:
        await _flush_pending_uploads()
