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

# Fontes publicaveis: listas com politica de inclusao oficial documentada.
# Os repositorios de descoberta permanecem apenas como candidatos para revisao;
# disponibilidade tecnica sozinha nunca autoriza publicar um stream.
SOURCES = [
    {
        "name": "Doubo Public Channel Directory — Brasil",
        "url": "https://raw.githubusercontent.com/streamline-iptv/iptv-playlists/dist/countries/br.m3u",
        "role": "official_curated",
        "publish": True,
        "country": "BR",
        "rights_basis": "Politica publica: dominio do broadcaster ou CDN oficial em allowlist; exclui canais pagos, blocklist e takedowns. Dados CC BY 4.0; atribuicao registrada em canais/fontes.md.",
    },
    {
        "name": "Nexonic IPTV — Brasil (somente tier oficial)",
        "url": "https://raw.githubusercontent.com/Shahrukhalid/nexonic-iptv/main/playlists/countries/br.m3u",
        "role": "official_curated",
        "publish": True,
        "country": "BR",
        "tier_policy": "official_only",
        "rights_basis": "SOURCE_POLICY.md exige evidencia do broadcaster ou orgao publico; entradas x-tier=community sao excluidas. Dados CC0.",
    },
    {
        "name": "iptv-org Brasil — descoberta, nao publicar automaticamente",
        "url": "https://iptv-org.github.io/iptv/countries/br.m3u",
        "role": "discovery_only",
        "publish": False,
    },
    {
        "name": "CatTV Playlist Brasil — descoberta, nao publicar automaticamente",
        "url": "https://raw.githubusercontent.com/SamuelSantos-R/cattv-playlist/main/playlist/br.m3u",
        "role": "discovery_only",
        "publish": False,
    },
    {
        "name": "IPTV-com Brasil — descoberta, nao publicar automaticamente",
        "url": "https://github.com/iptv-com/iptv/raw/refs/heads/main/lists/brazil.m3u",
        "role": "discovery_only",
        "publish": False,
    },
    {
        "name": "FreeCastHub — descoberta, requer evidencia individual",
        "url": "https://raw.githubusercontent.com/freecasthub/public-iptv/main/playlist.m3u",
        "role": "discovery_only",
        "publish": False,
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
                "tvg_country": attrs.get("tvg-country", "").upper(),
                "tier": attrs.get("x-tier", "").lower(),
                "source": source,
            }
        elif line and not line.startswith("#") and metadata:
            parsed = urllib.parse.urlparse(line)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                entries.append({**metadata, "url": line})
            metadata = None
    return entries


SENSITIVE_QUERY_KEYS = {
    "jwt", "token", "access_token", "auth", "authorization",
    "signature", "sig", "exp", "expires", "hdnts", "wmsauthsign",
    "session", "sessionid", "password",
}


def has_ephemeral_auth(url: str) -> bool:
    """Nao armazena URLs assinadas, credenciais ou tokens de sessao que expiram."""
    parsed = urllib.parse.urlparse(url)
    if parsed.username or parsed.password:
        return True
    keys = {
        key.lower()
        for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    }
    return bool(keys & SENSITIVE_QUERY_KEYS)


def filter_source_entries(entries: list[dict], source: dict) -> tuple[list[dict], dict]:
    """Aplica pais, tier e politica de publicacao antes da checagem de stream."""
    kept = []
    excluded = {"wrong_country": 0, "non_official_tier": 0, "signed_or_credential_url": 0}
    country = source.get("country", "").upper()
    tier_policy = source.get("tier_policy", "")

    for original in entries:
        entry = dict(original)
        if country and entry.get("tvg_country", "").upper() != country:
            excluded["wrong_country"] += 1
            continue
        if tier_policy == "official_only" and entry.get("tier", "") not in ("", "official"):
            excluded["non_official_tier"] += 1
            continue
        if has_ephemeral_auth(entry["url"]):
            excluded["signed_or_credential_url"] += 1
            continue

        entry["source_role"] = source.get("role", "discovery_only")
        entry["publishable_source"] = bool(source.get("publish", False))
        entry["rights_basis"] = source.get("rights_basis", "")
        kept.append(entry)

    return kept, excluded


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
    # Somente fontes com politica oficial revisada podem alimentar o M3U do player.
    unique = {}
    for item in online:
        if not item.get("publishable_source", False):
            continue
        identity = item.get("tvg_id", "").strip().casefold() or item["url"]
        unique.setdefault(identity, item)
    published = list(unique.values())

    lines = ["#EXTM3U"]
    for item in published:
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
    # Nao apaga a ultima playlist publicada quando uma rodada nao aprova fontes oficiais.
    if published:
        OUT_M3U.write_text("\n".join(lines) + "\n", encoding="utf-8")

    pending = [item for item in results if not item.get("publishable_source", False)]
    for source in source_stats:
        source["published"] = sum(1 for item in published if item["source"] == source["name"])

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "HLS manifest + first media segment, or MPEG-TS signature; source publication policy applied separately",
        "publication_policy": "channels contains only technically online entries from reviewed official-curated sources; review_candidates are not included in the player playlist",
        "summary": {
            "discovered": len(results),
            "unique_urls": len({item["url"] for item in results}),
            "online": len(online),
            "approved": len(published),
            "pending_rights_review": sum(1 for item in pending if item["online"]),
            "failed": len(results) - len(online),
        },
        "sources": source_stats,
        # Contract for the app/dashboard: channels is safe-to-publish only.
        "channels": published,
        # Discovery feeds remain visible for research but are not part of auditada.m3u.
        "review_candidates": pending,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# Auditoria de canais — Prisma TV",
        "",
        f"Gerado em: {payload['generated_at']}",
        "",
        "## Resumo",
        "",
        f"- Candidatos analisados tecnicamente: **{len(results)}**",
        f"- Streams que passaram no teste tecnico: **{len(online)}**",
        f"- Canais publicados de fontes oficiais curadas: **{len(published)}**",
        f"- Streams online retidos para revisao de procedencia: **{payload['summary']['pending_rights_review']}**",
        f"- Falhas tecnicas: **{len(results) - len(online)}**",
        "",
        "> Um stream responder tecnicamente nao prova autorizacao de distribuicao. "
        "Somente fontes com politica de inclusao oficial revisada entram em auditada.m3u.",
        "> A checagem confirma manifesto e um segmento (ou assinatura MPEG-TS), nao reprodução prolongada.",
        "",
        "## Fontes",
        "",
    ]
    for source in source_stats:
        label = "publicavel" if source["publishable"] else "somente descoberta/revisao"
        md.append(
            f"- {source['name']}: {source['count']} encontrados; "
            f"{source['eligible_count']} elegiveis; {source['published']} publicados; "
            f"{label}; {source['status']}"
        )
    md += [
        "",
        "## Falhas tecnicas",
        "",
        "| Canal | Fonte | Motivo |",
        "|---|---|---|",
    ]
    for item in results:
        if not item["online"]:
            md.append(f"| {item['name'].replace('|', '/')} | {item['source']} | {item['status']} |")
    md += [
        "",
        "## Revisao de procedencia",
        "",
        "Candidatos tecnicamente online das fontes de descoberta ficam em auditoria.json/review_candidates. "
        "Eles nao sao exportados para auditada.m3u ate haver evidencia de que a transmissao e oficialmente gratuita e autorizada.",
    ]
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

def main() -> int:
    all_entries = []
    source_stats = []
    for source in SOURCES:
        try:
            playlist = fetch_playlist(source["url"])
            raw_entries = parse_playlist(playlist, source["name"])
            entries, excluded = filter_source_entries(raw_entries, source)
            all_entries.extend(entries)
            source_stats.append({
                "name": source["name"],
                "url": source["url"],
                "count": len(raw_entries),
                "eligible_count": len(entries),
                "excluded_by_policy": excluded,
                "role": source.get("role", "discovery_only"),
                "publishable": bool(source.get("publish", False)),
                "status": "baixada",
            })
            print(
                f"[OK] {source['name']}: {len(raw_entries)} entradas, "
                f"{len(entries)} apos politica"
            )
        except Exception as exc:
            source_stats.append({
                "name": source["name"],
                "url": source["url"],
                "count": 0,
                "eligible_count": 0,
                "excluded_by_policy": {},
                "role": source.get("role", "discovery_only"),
                "publishable": bool(source.get("publish", False)),
                "status": f"falha: {type(exc).__name__}: {str(exc)[:180]}",
            })
            print(f"[AVISO] {source['name']}: {exc}")

    # Deduplicacao inicial por URL reduz chamadas repetidas de auditoria.
    by_url = {}
    for item in all_entries:
        by_url.setdefault(item["url"], item)
    candidates = list(by_url.values())
    if not candidates:
        raise RuntimeError("Nenhuma fonte forneceu candidatos; mantendo a ultima lista auditada.")
    print(f"Auditoria tecnica de {len(candidates)} URLs unicas...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(audit_one, candidates))

    write_outputs(results, source_stats)
    published_count = sum(
        1 for item in results
        if item["online"] and item.get("publishable_source", False)
    )
    if published_count == 0:
        raise RuntimeError(
            "Nenhum canal de fonte oficial curada passou na auditoria; "
            "a playlist anterior foi preservada."
        )
    print(f"Concluido: {published_count} canais publicados de {len(results)} candidatos.")
    print(f"Arquivos: {OUT_M3U}, {OUT_JSON}, {OUT_MD}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
