from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

_STEALTH_INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]


def _launch_auth_context(
    playwright,
    *,
    profile_dir: Path | None,
    headless: bool,
) -> tuple[BrowserContext, object | None]:
    """Launch Google Chrome (not Playwright Chromium) for Google sign-in."""
    launch_kwargs: dict = {
        "headless": headless,
        "channel": "chrome",
        "ignore_default_args": ["--enable-automation"],
        "args": _LAUNCH_ARGS,
        "viewport": {"width": 1280, "height": 720},
        "locale": "en-US",
    }
    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        context = playwright.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)
        context.add_init_script(_STEALTH_INIT_SCRIPT)
        return context, None

    browser = playwright.chromium.launch(**launch_kwargs)
    context = browser.new_context()
    context.add_init_script(_STEALTH_INIT_SCRIPT)
    return context, browser


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Playwright storage state for Google Meet login.")
    parser.add_argument("--output", default="storage_state.json", help="Output path for storage state JSON")
    parser.add_argument(
        "--start-url",
        default="https://meet.google.com/",
        help="Page to open for sign-in (Meet URL works better than raw accounts.google.com)",
    )
    parser.add_argument(
        "--profile-dir",
        default=None,
        help="Persistent Chrome profile directory (recommended; default: next to output)",
    )
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(args.profile_dir) if args.profile_dir else output.parent / "meet-auth-profile"

    print("Opening Google Chrome for Meet login...")
    print("If Google blocks sign-in, close the window and install/update Google Chrome, then retry.")
    print(f"Profile: {profile_dir}")
    print(f"Output:  {output}")

    with sync_playwright() as p:
        context, browser = _launch_auth_context(p, profile_dir=profile_dir, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(args.start_url, wait_until="domcontentloaded")
            print()
            print("1. Sign in with your Google account in the Chrome window")
            print("2. Open https://meet.google.com and confirm you are logged in")
            print("3. Return here and press Enter to save storage_state.json")
            print()
            input("Press Enter when signed in...")
            context.storage_state(path=str(output))
            print(f"Saved: {output}")
        finally:
            context.close()
            if browser is not None:
                browser.close()


if __name__ == "__main__":
    main()
