#!/usr/bin/env python3
"""Mirror a public/openly licensed VOD M3U feed without replacing the last good copy."""
from __future__ import annotations

import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_URL = "https://biskyt.github.io/legalFreeIPTVplaylist/movies.m3u"
DESTINATION = ROOT / "filmes" / "filmes-publicos.m3u"
USER_AGENT = "PrismaTV-VOD-Mirror/1.0"
TIMEOUT_SECONDS = 45
MAX_BYTES = 20 * 1024 * 1024
MINIMUM_MOVIES = 100


def validate_playlist(data: bytes) -> tuple[str, int]:
    text = data.decode("utf-8-sig")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise ValueError("A resposta não começa com #EXTM3U.")

    count = 0
    waiting_for_url = False
    for line in lines[1:]:
        if line.startswith("#EXTINF:"):
            if 'tvg-type="movie"' not in line:
                raise ValueError("A fonte retornou uma entrada sem tvg-type=\"movie\".")
            waiting_for_url = True
            continue
        if line.startswith("#"):
            continue
        if waiting_for_url:
            if not line.startswith("https://"):
                raise ValueError("A lista contém URL que não usa HTTPS.")
            count += 1
            waiting_for_url = False

    if count < MINIMUM_MOVIES:
        raise ValueError(
            f"A fonte trouxe apenas {count} filmes; mínimo para aceitar é {MINIMUM_MOVIES}."
        )
    return text.rstrip() + "\n", count


def main() -> int:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "audio/x-mpegurl, application/vnd.apple.mpegurl, text/plain, */*",
            "Cache-Control": "no-cache",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if not 200 <= response.status < 300:
                raise urllib.error.HTTPError(
                    SOURCE_URL, response.status, "Non-success status", response.headers, None
                )
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError(f"A lista excedeu o limite de {MAX_BYTES} bytes.")
        text, count = validate_playlist(data)

        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=DESTINATION.parent,
                prefix=".filmes-publicos-",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_name = temp_file.name
                temp_file.write(text)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, DESTINATION)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

        print(f"Lista atualizada: {count} filmes em {DESTINATION.relative_to(ROOT)}.")
    except Exception as exc:
        print(
            f"::warning::Não foi possível atualizar a M3U pública; "
            f"a última cópia válida foi preservada. Motivo: {exc}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
