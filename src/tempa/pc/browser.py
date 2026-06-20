from __future__ import annotations

from typing import Any

from playwright.sync_api import sync_playwright


def browser_navigate(url: str) -> dict[str, Any]:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            title = page.title()
            text = page.inner_text("body")[:4000]
            browser.close()
        return {"status": "success", "title": title, "content": text}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}


def browser_execute_js(url: str, script: str) -> dict[str, Any]:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            result = page.evaluate(script)
            browser.close()
        return {"status": "success", "result": result}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}
