#!/usr/bin/env python3
"""Mirror authorized Saimo source code and text catalogs into this repository.

The catalog layout is preserved:
  SaimoPlayer/
  canais-saimo/
  filmes-saimo/
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
CHANNELS_URL = "https://canais-saimo.pages.dev/"
MOVIES_URL = "https://filmes-saimo.pages.dev/"
SOURCE_GIT = "https://github.com/SaimoTV/SaimoPlayer.git"
USER_AGENT = "Mozilla/5.0 (compatible; IPTV-Catalog-Mirror/1.0)"
TIMEOUT = 35
RETRIES = 3
DELAY = 0.12
MAX_SERIES_PARTS = 1000

CHANNEL_FILES = (
    "catalogo.txt",
    "canais.txt",
    "guia.txt",
    "radios.txt",
    "restritos.txt",
)
MOVIE_FIXED_FILES = (
    "indice.txt",
    "destaques.txt",
    "busca.txt",
    "generos.txt",
    "marcas.txt",
    "fichas.txt",
    "detalhes.txt",
    "links-doramas.txt",
    "redeflix/links-animes.txt",
    "redeflix/links-doramas.txt",
)


def request_bytes(url: str) -> Optional[bytes]:
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/plain, text/*;q=0.9, */*;q=0.5",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                if 200 <= response.status < 300:
                    return response.read()
                return None
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                return None
            if exc.code in (401, 403):
                print(f"  HTTP {exc.code}: {url}", flush=True)
                return None
            if attempt == RETRIES:
                print(f"  HTTP {exc.code}: {url}", flush=True)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == RETRIES:
                print(f"  Request failed: {url}: {exc}", flush=True)
        time.sleep(attempt * 0.8)
    return None


def download_file(base_url: str, relative_path: str, destination: Path) -> bool:
    url = base_url.rstrip("/") + "/" + relative_path.lstrip("/")
    data = request_bytes(url)
    if data is None:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print(f"  OK {relative_path} ({len(data):,} bytes)", flush=True)
    time.sleep(DELAY)
    return True


def mirror_git_source() -> None:
    target = ROOT / "SaimoPlayer"
    temp = ROOT / ".SaimoPlayer-clone"
    if temp.exists():
        shutil.rmtree(temp)
    subprocess.run(
        ["git", "clone", "--depth", "1", SOURCE_GIT, str(temp)],
        check=True,
    )
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(temp, target, ignore=shutil.ignore_patterns(".git"))
    shutil.rmtree(temp)
    print("SaimoPlayer source mirrored.", flush=True)


def mirror_channels() -> None:
    print("\n== Canais ==", flush=True)
    target = ROOT / "canais-saimo"
    successes = 0
    for name in CHANNEL_FILES:
        if download_file(CHANNELS_URL, name, target / name):
            successes += 1
        else:
            print(f"  Ausente/indisponível: {name}", flush=True)
    if successes == 0:
        raise RuntimeError("Nenhum arquivo de canais foi baixado; confira a origem.")


def parse_index_letters(index_text: str) -> list[str]:
    letters: list[str] = []
    for raw in index_text.splitlines():
        line = raw.strip("\ufeff \r")
        if not line or line.lower().startswith("base:"):
            continue
        # Index rows are tab-delimited: key, movie count, series count, optional count.
        cols = re.split(r"\t+", line)
        if len(cols) >= 3:
            key = cols[0].strip()
            if key == "#" or re.fullmatch(r"[A-Z]", key):
                if key not in letters:
                    letters.append(key)
    return letters


def download_letter_file(
    base_url: str, folder: Path, kind: str, letter: str
) -> bool:
    # '#' can be published under URL-encoded, numeric, or textual aliases.
    candidates = ["%23", "0", "outros"] if letter == "#" else [letter]
    for candidate in candidates:
        name = f"{kind}-{candidate}.txt"
        data = request_bytes(base_url.rstrip("/") + "/" + name)
        if data is not None:
            canonical = f"{kind}-{letter}.txt"
            dest = folder / canonical
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            print(f"  OK {canonical} via {name} ({len(data):,} bytes)", flush=True)
            time.sleep(DELAY)
            return True
        time.sleep(DELAY)
    print(f"  Ausente: {kind}-{letter}.txt", flush=True)
    return False


def download_series_parts(base_url: str, folder: Path, letter: str) -> int:
    downloaded = 0
    for part in range(MAX_SERIES_PARTS):
        relative = f"series-{letter}-{part}.txt"
        dest = folder / relative
        if not download_file(base_url, relative, dest):
            # The published format uses contiguous zero-based part numbers.
            break
        downloaded += 1
    if downloaded == MAX_SERIES_PARTS:
        raise RuntimeError(
            f"Limite de {MAX_SERIES_PARTS} partes atingido para a letra {letter}; "
            "verifique se a origem tem mais arquivos."
        )
    return downloaded


def mirror_movies() -> None:
    print("\n== Filmes e séries ==", flush=True)
    target = ROOT / "filmes-saimo"
    target.mkdir(parents=True, exist_ok=True)

    if not download_file(MOVIES_URL, "indice.txt", target / "indice.txt"):
        raise RuntimeError("Não foi possível baixar filmes-saimo/indice.txt.")

    index_text = (target / "indice.txt").read_text(encoding="utf-8-sig")
    letters = parse_index_letters(index_text)
    if not letters:
        raise RuntimeError("Nenhuma letra válida encontrada em indice.txt.")

    for name in MOVIE_FIXED_FILES:
        if name == "indice.txt":
            continue
        if not download_file(MOVIES_URL, name, target / name):
            print(f"  Opcional/ausente: {name}", flush=True)

    print(f"\nLetras encontradas no índice: {', '.join(letters)}", flush=True)
    for letter in letters:
        download_letter_file(MOVIES_URL, target, "filmes", letter)
        download_letter_file(MOVIES_URL, target, "series", letter)
        parts = download_series_parts(MOVIES_URL, target, letter)
        print(f"  Partes de episódios para {letter}: {parts}", flush=True)


def main() -> int:
    try:
        mirror_git_source()
        mirror_channels()
        mirror_movies()
    except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr, flush=True)
        return 1
    print("\nEspelhamento concluído.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
