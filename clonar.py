#!/usr/bin/env python3
"""Browser-based mirror for the authorized Saimo sources.

Uses Chromium because the sites are client-rendered and expose navigation
through the "Endereços do Saimo" interface rather than plain static HTML.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parent
TMP = ROOT / ".mirror-tmp"
ENTRY_URL = "https://saimo-tv.pages.dev/home"
SOURCE_REPO = "https://github.com/SaimoTV/SaimoPlayer.git"
ALLOWED_HOSTS = {
    "saimo-tv.pages.dev",
    "canais-saimo.pages.dev",
    "filmes-saimo.pages.dev",
}
FOLDER_BY_HOST = {
    "saimo-tv.pages.dev": "saimo-tv",
    "canais-saimo.pages.dev": "canais-saimo",
    "filmes-saimo.pages.dev": "filmes-saimo",
}
SKIP_EXTENSIONS = {
    ".mp4", ".m3u8", ".ts", ".mp3", ".aac", ".mkv", ".avi", ".mov",
    ".woff", ".woff2", ".ttf", ".otf",
}


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def mirror_git_repo() -> None:
    destination = ROOT / "SaimoPlayer"
    if TMP.exists():
        shutil.rmtree(TMP)
    run(["git", "clone", "--depth", "1", SOURCE_REPO, str(TMP)])
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(TMP, destination, ignore=shutil.ignore_patterns(".git"))
    shutil.rmtree(TMP)


def local_path(url: str) -> Path | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return None
    folder = ROOT / FOLDER_BY_HOST[host]
    path = unquote(parsed.path or "/")
    if path.endswith("/"):
        path += "index.html"
    if not Path(path).suffix:
        path += ".html"
    relative = Path(path.lstrip("/"))
    if ".." in relative.parts:
        return None
    return folder / relative


def mirror_web_sources() -> None:
    for folder in FOLDER_BY_HOST.values():
        target = ROOT / folder
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

    queue = [ENTRY_URL]
    visited: set[str] = set()
    saved: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                        "Mobile/15E148 Safari/604.1"),
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
        )
        page = context.new_page()

        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            if len(visited) > 250:
                print("Safety limit reached: 250 pages.")
                break

            print(f"Opening in Chromium: {url}", flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
            except PlaywrightTimeoutError:
                print(f"Navigation timed out; checking rendered page: {url}")

            # The welcome screen exposes the catalog/source links through this control.
            try:
                button = page.get_by_text("Endereços do Saimo", exact=False).first
                if button.is_visible(timeout=1500):
                    button.click(timeout=5000)
                    page.wait_for_timeout(1800)
            except Exception:
                pass

            # Collect links after client-side rendering and after opening the address panel.
            links = page.locator("a[href]").evaluate_all(
                "(els) => els.map(a => a.href)"
            )
            resource_urls = page.evaluate(
                "() => performance.getEntriesByType('resource').map(e => e.name)"
            )
            current_url = page.url
            candidates = [current_url, *links, *resource_urls]

            # Preserve rendered HTML, including the page state reached after the button click.
            try:
                html = page.content()
                dest = local_path(current_url)
                if dest:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(html, encoding="utf-8")
                    saved.add(current_url)
            except Exception as exc:
                print(f"Could not save rendered HTML for {current_url}: {exc}")

            for candidate in candidates:
                parsed = urlparse(candidate)
                host = (parsed.hostname or "").lower()
                if host not in ALLOWED_HOSTS:
                    continue
                normalized = parsed._replace(fragment="").geturl()
                dest = local_path(normalized)
                if not dest or normalized in saved:
                    continue
                suffix = dest.suffix.lower()
                if suffix in SKIP_EXTENSIONS:
                    continue
                # Queue HTML pages for rendering; download static assets and catalog files.
                if suffix in {"", ".html", ".htm"}:
                    if normalized not in visited and normalized not in queue:
                        queue.append(normalized)
                    continue
                try:
                    response = context.request.get(normalized, timeout=30000)
                    if response.ok:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(response.body())
                        saved.add(normalized)
                        print(f"Saved {normalized} ({len(response.body())} bytes)")
                except Exception as exc:
                    print(f"Skipped {normalized}: {exc}")

        browser.close()

    if not saved:
        raise RuntimeError("No pages or assets were captured. Check the source routes/access.")


def main() -> int:
    try:
        mirror_git_repo()
        mirror_web_sources()
    except Exception as exc:
        print(f"Mirror failed: {exc}", file=sys.stderr)
        return 1
    print("Mirror completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
