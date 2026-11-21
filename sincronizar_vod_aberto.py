#!/usr/bin/env python3
"""Espelha playlists M3U de VOD aberto, preservando metadados, licenças e última cópia válida.

Os vídeos continuam hospedados nas fontes originais; este script só copia índices M3U.
"""
from __future__ import annotations

import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
USER_AGENT = "PrismaTV-VOD-Mirror/1.1"
TIMEOUT_SECONDS = 60
MAX_BYTES = 25 * 1024 * 1024

FEEDS = (
    {
        "kind": "movie",
        "url": "https://nexonic-technologies.github.io/nexonic-iptv/playlists/vod/movies.m3u",
        "destination": ROOT / "filmes" / "filmes-abertos.m3u",
        "minimum": 100,
    },
    {
        "kind": "series",
        "url": "https://nexonic-technologies.github.io/nexonic-iptv/playlists/vod/series.m3u",
        "destination": ROOT / "filmes" / "series-abertas.m3u",
        "minimum": 25,
    },
)


def normalize_and_validate(data: bytes, kind: str, minimum: int) -> tuple[str, int]:
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    if not lines or not lines[0].strip().startswith("#EXTM3U"):
        raise ValueError("A resposta não começa com #EXTM3U.")

    output: list[str] = []
    entries = 0
    pending_type: str | None = None
    pending_has_license = False
    pending_has_source = False

    for raw in lines:
        line = raw.strip()
        if line.startswith("#EXTINF:"):
            if pending_type is not None:
                raise ValueError("Entrada anterior sem URL de vídeo.")
            match = re.search(r'\bx-type="(movie|series)"', line)
            if not match or match.group(1) != kind:
                raise ValueError(f"Entrada sem x-type=\"{kind}\".")
            pending_type = match.group(1)
            pending_has_license = bool(re.search(r'\bx-licen[cs]e="[^"]+"', line))
            pending_has_source = bool(re.search(r'\bx-source="https://[^"]+"', line))
            if not pending_has_license or not pending_has_source:
                raise ValueError("Entrada sem metadados de licença ou fonte original.")
            if not re.search(r'\btvg-type="', line):
                line += f' tvg-type="{kind}"'
            output.append(line)
            continue

        if pending_type is not None and line and not line.startswith("#"):
            if not line.startswith("https://"):
                raise ValueError("A lista contém URL que não usa HTTPS.")
            output.append(line)
            entries += 1
            pending_type = None
            pending_has_license = False
            pending_has_source = False
            continue

        output.append(raw.rstrip())

    if pending_type is not None:
        raise ValueError("A última entrada não possui URL de vídeo.")
    if entries < minimum:
        raise ValueError(f"A fonte trouxe {entries} entradas; mínimo aceito: {minimum}.")

    return "\n".join(output).rstrip() + "\n", entries


def atomic_write(destination: Path, text: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def sync_feed(feed: dict[str, object]) -> bool:
    source_url = str(feed["url"])
    kind = str(feed["kind"])
    destination = Path(feed["destination"])
    minimum = int(feed["minimum"])
    request = urllib.request.Request(
        source_url,
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
                    source_url, response.status, "Non-success status", response.headers, None
                )
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError(f"A lista excedeu o limite de {MAX_BYTES} bytes.")
        text, count = normalize_and_validate(data, kind, minimum)
        atomic_write(destination, text)
        print(f"Lista atualizada: {count} entradas {kind} em {destination.relative_to(ROOT)}.")
        return True
    except Exception as exc:
        print(
            f"::warning::Falha ao atualizar a lista {kind}; a última cópia válida "
            f"foi preservada. Motivo: {exc}"
        )
        return False


def main() -> int:
    results = [sync_feed(feed) for feed in FEEDS]
    # Uma falha na rede não apaga listas existentes nem impede a sincronização principal.
    return 0 if any(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
