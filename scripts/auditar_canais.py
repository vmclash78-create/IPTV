#!/usr/bin/env python3
"""Agrega playlists publicas e valida HLS antes de publicar a lista auditada.

A validacao confirma manifesto e pelo menos um segmento acessivel. Isso nao
substitui um teste prolongado de decodificacao no app/player.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_M3U = ROOT / "canais" / "auditada.m3u"
OUT_JSON = ROOT / "canais" / "auditoria.json"
OUT_MD = ROOT / "relatorio_auditoria.md"
TIMEOUT = 14
MAX_WORKERS = 12
USER_AGENT = "PrismaTV-PublicPlaylistAuditor/1.0"

# Fontes de canais publicos/gratuitos. Nao importar listas privadas ou
# fontes de canais pagos sem autorizacao do titular dos direitos.
SOURCES = [
    {
        "name": "iptv-org Brasil",
        "url": "https://iptv-org.github.io/iptv/countries/br.m3u",
    },
    {
        "name": "CatTV Playlist Brasil",
        "url": "https://raw.githubusercontent.com/SamuelSantos-R/cattv-playlist/main/playlist/br.m3u",
    },
    {
        "name": "IPTV-com Brasil",
        "url": "https://github.com/iptv-com/iptv/raw/refs/heads/main/lists/brazil.m3u",
    },
]


def request_bytes(url: str, limit: int = 512_000) -> tuple[bytes, str, int]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Range": f"bytes=0-{limit - 1}",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        data = response.read(limit)
        return data, response.geturl(), response.status


def fetch_playlist(url: str) -> str:
    data, _, status = request_bytes(url, 8_000_000)
    if status < 200 or status >= 300:
        raise RuntimeError(f"HTTP {status}")
    text = data.decode("utf-8-sig", errors="replace")
    if "#EXTM3U" not in text[:500]:
        raise RuntimeError("resposta nao parece ser uma playlist M3U")
    return text


def parse_playlist(text: str, source: str) -> list[dict]:
    entries = []
    metadata = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF:"):
            name = line.rsplit(",", 1)[-1].strip() or "Canal sem nome"
            attrs = {
                key.lower(): value
                for key, value in re.findall(r'([\w-]+)="([^"]*)"', line)
            }
            metadata = {
                "name": name,
                "tvg_id": attrs.get("tvg-id", ""),
                "logo": attrs.get("tvg-logo", ""),
                "group": attrs.get("group-title", "TV Aberta"),
                "source": source,
            }
        elif line and not line.startswith("#") and metadata:
            parsed = urllib.parse.urlparse(line)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                entries.append({**metadata, "url": line})
            metadata = None
    return entries


def resolve_url(base: str, child: str) -> str:
    return urllib.parse.urljoin(base, child.strip())


def validate_hls(url: str, depth: int = 0) -> tuple[bool, str, str]:
    if depth > 2:
        return False, "hls_nesting_limit", url
    data, final_url, status = request_bytes(url)
    if status < 200 or status >= 300:
        return False, f"http_{status}", final_url
    text = data.decode("utf-8-sig", errors="replace")
    if not text.lstrip().startswith("#EXTM3U"):
        # Stream TS direto: exigir assinatura MPEG-TS, nao apenas HTTP 200.
        if len(data) >= 376 and data[0] == 0x47 and data[188] == 0x47:
            return True, "mpegts_signature_ok", final_url
        return False, "http_ok_but_not_hls_or_ts", final_url

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    variant = None
    for index, line in enumerate(lines[:-1]):
        if line.startswith("#EXT-X-STREAM-INF:"):
            candidate = lines[index + 1]
            if not candidate.startswith("#"):
                variant = candidate
                break
    if variant:
        return validate_hls(resolve_url(final_url, variant), depth + 1)

    segment = next(
        (
            line for line in lines
            if not line.startswith("#") and not line.lower().startswith("data:")
        ),
        None,
    )
    if not segment:
        return False, "hls_without_media_segment", final_url

    segment_url = resolve_url(final_url, segment)
    try:
        segment_data, segment_final, segment_status = request_bytes(segment_url, 256_000)
    except Exception as exc:
        return False, f"segment_error:{type(exc).__name__}", segment_url
    if segment_status < 200 or segment_status >= 300:
        return False, f"segment_http_{segment_status}", segment_final
    # TS segment: pacote MPEG-TS tem sync byte a cada 188 bytes.
    # fMP4: fragmentos ISO-BMFF normalmente começam com tamanho + 'styp'/'moof'.
    ts_ok = len(segment_data) >= 376 and segment_data[0] == 0x47 and segment_data[188] == 0x47
    mp4_ok = len(segment_data) >= 8 and segment_data[4:8] in (b"styp", b"moof", b"ftyp")
    if not (ts_ok or mp4_ok):
        return False, "segment_format_unrecognized", segment_final
    return True, "hls_manifest_and_segment_ok", segment_final


def audit_one(entry: dict) -> dict:
    started = time.monotonic()
    try:
        ok, status, checked_url = validate_hls(entry["url"])
        error = ""
    except urllib.error.HTTPError as exc:
        ok, status, checked_url, error = False, f"http_{exc.code}", entry["url"], str(exc)
    except Exception as exc:
        ok, status, checked_url, error = False, "request_error", entry["url"], str(exc)[:240]
    return {
        **entry,
        "online": ok,
        "status": status,
        "checked_url": checked_url,
        "error": error,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def write_outputs(results: list[dict], source_stats: list[dict]) -> None:
    online = [item for item in results if item["online"]]
    # Evita duplicar a mesma URL mesmo quando aparece em mais de uma fonte.
    unique = {}
    for item in online:
        unique.setdefault(item["url"], item)
    approved = list(unique.values())

    lines = ["#EXTM3U"]
    for item in approved:
        attrs = [
            f'tvg-name="{item["name"].replace(chr(34), "")}"',
            f'group-title="{item["group"].replace(chr(34), "")}"',
        ]
        if item["tvg_id"]:
            attrs.append(f'tvg-id="{item["tvg_id"].replace(chr(34), "")}"')
        if item["logo"]:
            attrs.append(f'tvg-logo="{item["logo"].replace(chr(34), "")}"')
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{item["name"]}')
        lines.append(item["url"])
    OUT_M3U.write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "HLS manifest + first media segment, or MPEG-TS signature",
        "summary": {
            "discovered": len(results),
            "unique_urls": len({item["url"] for item in results}),
            "approved": len(approved),
            "failed": len(results) - len(online),
        },
        "sources": source_stats,
        "channels": results,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# Auditoria de canais — Prisma TV",
        "",
        f"Gerado em: {payload['generated_at']}",
        "",
        "## Resumo",
        "",
        f"- Entradas encontradas: **{len(results)}**",
        f"- URLs unicas aprovadas: **{len(approved)}**",
        f"- Entradas reprovadas/nao verificadas: **{len(results) - len(online)}**",
        "",
        "> A aprovacao confirma acesso ao manifesto e a um segmento (ou assinatura MPEG-TS). "
        "Nao garante disponibilidade continua nem decodificacao em todos os dispositivos.",
        "",
        "## Fontes",
        "",
    ]
    for source in source_stats:
        md.append(f"- {source['name']}: {source['count']} canais; {source['status']}")
    md += ["", "## Falhas e motivos", "", "| Canal | Fonte | Motivo |", "|---|---|---|"]
    for item in results:
        if not item["online"]:
            md.append(f"| {item['name'].replace('|', '/')} | {item['source']} | {item['status']} |")
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> int:
    all_entries = []
    source_stats = []
    for source in SOURCES:
        try:
            playlist = fetch_playlist(source["url"])
            entries = parse_playlist(playlist, source["name"])
            all_entries.extend(entries)
            source_stats.append({
                "name": source["name"],
                "url": source["url"],
                "count": len(entries),
                "status": "baixada",
            })
            print(f"[OK] {source['name']}: {len(entries)} entradas")
        except Exception as exc:
            source_stats.append({
                "name": source["name"],
                "url": source["url"],
                "count": 0,
                "status": f"falha: {type(exc).__name__}: {str(exc)[:180]}",
            })
            print(f"[AVISO] {source['name']}: {exc}")

    # Deduplicacao inicial por URL reduz chamadas repetidas de auditoria.
    by_url = {}
    for item in all_entries:
        by_url.setdefault(item["url"], item)
    candidates = list(by_url.values())
    if not candidates:
        raise RuntimeError("Nenhuma playlist forneceu canais; mantendo a ultima lista auditada.")
    print(f"Auditoria de {len(candidates)} URLs unicas...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(audit_one, candidates))

    approved = sum(1 for item in results if item["online"])
    if approved == 0:
        raise RuntimeError("Nenhuma transmissao passou na auditoria; lista anterior preservada.")
    write_outputs(results, source_stats)
    print(f"Concluido: {approved}/{len(results)} aprovadas.")
    print(f"Arquivos: {OUT_M3U}, {OUT_JSON}, {OUT_MD}")
    # Nao falhar o workflow quando uma fonte externa estiver temporariamente fora.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
