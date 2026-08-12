#!/usr/bin/env python3
"""Run the pinned RoomFlow browser smoke pages in a local Chromium browser."""

from __future__ import annotations

import argparse
import json
import shutil
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        return


@contextmanager
def local_server(root: Path):
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(root), **kwargs)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def browser_executable() -> str | None:
    candidates = (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path("/usr/bin/microsoft-edge"),
        Path("/usr/bin/chromium"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    )
    return next((str(path) for path in candidates if path.is_file()), shutil.which("chromium"))


TESTS = (
    ("tests/browser-smoke.html", "#smoke-result", "json"),
    ("tests/estimate-builder-smoke.html", "body", "dataset"),
    ("tests/header-responsive-smoke.html", "body", "dataset"),
    ("tests/leads-panel-smoke.html", "#test-result", "json"),
    ("tests/more-responsive-smoke.html", "body", "dataset"),
    ("tests/shared-jobs-smoke.html", "#result", "text"),
    ("tests/shared-jobs-upload-smoke.html", "#result", "text"),
    ("tests/tracker-delete-smoke.html", "#test-result", "json"),
    ("tests/user-guide-smoke.html", "#test-result", "json"),
)


def wait_for_result(page, selector: str, mode: str) -> tuple[bool, str]:
    if mode == "dataset":
        page.wait_for_function("document.body.dataset.passed === 'true' || document.body.dataset.passed === 'false'", timeout=20_000)
        text = page.locator("#result, #test-result").first.text_content() or ""
        return page.locator("body").get_attribute("data-passed") == "true", text
    page.wait_for_function(
        "([selector]) => { const value = document.querySelector(selector)?.textContent?.trim(); return value && value !== 'RUNNING'; }",
        arg=[selector],
        timeout=20_000,
    )
    text = page.locator(selector).text_content() or ""
    if mode == "text":
        return text.strip() == "PASS", text
    try:
        report = json.loads(text)
        return bool(report.get("passed")), text
    except json.JSONDecodeError:
        return page.title().startswith("PASS"), text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--bundle-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    executable = browser_executable()
    if not executable:
        print("ERROR: no local Chromium-family browser found")
        return 1

    failures: list[str] = []
    tests = () if args.bundle_only else TESTS[:1] if args.index_only else TESTS
    with local_server(root) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
        try:
            for relative, selector, mode in tests:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                # The exact pinned source uses a CDN for Lucide. Its icon refresh
                # API is cosmetic, so provide the same no-op surface when this
                # offline audit cannot reach that CDN. Native bundles vendor it.
                page.add_init_script("window.lucide = window.lucide || { createIcons() {} };")
                errors: list[str] = []
                page.on("pageerror", lambda error, target=errors: target.append(str(error)))
                try:
                    page.goto(f"{base_url}/{relative}", wait_until="domcontentloaded", timeout=30_000)
                    passed, detail = wait_for_result(page, selector, mode)
                    if passed:
                        print(f"PASS {relative}")
                    else:
                        failures.append(f"{relative}: {detail[:1_000]}")
                except PlaywrightError as exc:
                    failures.append(f"{relative}: {exc}")
                finally:
                    if errors:
                        failures.append(f"{relative} JavaScript: {' | '.join(errors[:5])}")
                    page.close()
            if args.bundle_only:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                try:
                    page.add_init_script("window.lucide = window.lucide || { createIcons() {} };")
                    page.goto(f"{base_url}/index.html", wait_until="domcontentloaded", timeout=30_000)
                    page.evaluate("""
                      localStorage.setItem('roomflow_jobs', JSON.stringify({
                        'Overlay Audit Job': {
                          currentJobName: 'Overlay Audit Job', customerName: 'Test Customer',
                          customerAddress: '100 Test Street', rooms: [], lastModified: Date.now()
                        }
                      }));
                    """)
                    page.reload(wait_until="domcontentloaded", timeout=30_000)
                    page.locator("#btn-jobs").evaluate("element => element.click()")
                    page.wait_for_function("document.querySelector('#jobs-list-container')?.textContent?.includes('Overlay Audit Job')", timeout=10_000)
                    close_button = page.locator("#btn-close-jobs")
                    close_button.evaluate("element => element.click()")
                    hidden = page.locator("#jobs-modal").evaluate("element => element.classList.contains('hidden')")
                    if hidden and not errors:
                        print("PASS prepared bundle legacy job database render/close")
                    else:
                        failures.append("prepared bundle job database did not close cleanly")
                except PlaywrightError as exc:
                    failures.append(f"prepared bundle job database: {exc}")
                finally:
                    if errors:
                        failures.append(f"prepared bundle JavaScript: {' | '.join(errors[:5])}")
                    page.close()
        finally:
            browser.close()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    if tests:
        print(f"RoomFlow browser smoke tests passed: {len(tests)}/{len(tests)}")
    else:
        print("RoomFlow prepared-bundle browser smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
