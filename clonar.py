#!/usr/bin/env python3
"""Mirror the authorized SaimoPlayer repository and three Pages sites."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TMP = ROOT / ".mirror-tmp"

SITES = {
    "saimo-tv": "https://saimo-tv.pages.dev/",
    "canais-saimo": "https://canais-saimo.pages.dev/",
    "filmes-saimo": "https://filmes-saimo.pages.dev/",
}
SOURCE_REPO = "https://github.com/SaimoTV/SaimoPlayer.git"


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
    shutil.copytree(
        TMP,
        destination,
        ignore=shutil.ignore_patterns(".git"),
    )
    shutil.rmtree(TMP)


def mirror_site(folder: str, url: str) -> None:
    destination = ROOT / folder
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    # Mirror same-host pages and their referenced assets/catalog files.
    run([
        "wget",
        "--mirror",
        "--page-requisites",
        "--convert-links",
        "--adjust-extension",
        "--no-parent",
        "--domains", url.split("//", 1)[1].split("/", 1)[0],
        "--directory-prefix", str(destination),
        "--execute", "robots=off",
        "--wait", "0.2",
        "--tries", "3",
        "--timeout", "30",
        url,
    ])


def main() -> int:
    try:
        mirror_git_repo()
        for folder, url in SITES.items():
            mirror_site(folder, url)
    except subprocess.CalledProcessError as exc:
        print(f"Mirror failed (exit {exc.returncode}): {exc}", file=sys.stderr)
        return exc.returncode or 1
    print("Mirror completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
