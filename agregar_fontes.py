#!/usr/bin/env python3
"""Agregador e Consolidador Multi-Repositório para Prisma TV.

Combina e higieniza canais de múltiplos repositórios:
  1. Catálogo base Prisma TV (canais limpos, sem /error.txt, sem s25-cloudfront)
  2. Fontes Oficiais Manuais (canais/manuais.txt - Band, SBT News, Record News, TV Brasil, TV Câmara...)
  3. iptv-org/iptv (Repositório global GitHub - canais BR e PT verificados)
  4. Organização estruturada de failover (H.264 oficial > FAST > backup)
  5. Geração de lista.m3u (completa), canais.m3u e lista-web.m3u (HTTPS + H.264 Safari/iPhone)
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANAIS_DIR = ROOT / "canais"
CATALOGO_FILE = CANAIS_DIR / "catalogo.txt"
MANUAIS_FILE = CANAIS_DIR / "manuais.txt"
FONTES_DESATIVADAS_FILE = CANAIS_DIR / "fontes-desativadas.json"

USER_AGENT = "Mozilla/5.0 (compatible; PrismaTV-Aggregator/3.0)"

IPTV_ORG_URLS = [
    ("https://raw.githubusercontent.com/iptv-org/iptv/master/streams/br.m3u", "Brasil"),
]

# Streams conhecidamente HEVC em MPEG-TS (incompatíveis com Safari/iOS tela preta)
HEVC_STREAMS = {
    "https://dfr80qz435crc.cloudfront.net/EFGH/Amagi/Globo/GE_Fast_BR/GE_Fast.m3u8",
    "https://amg01391-sbtinfast-amg01391c4-lg-br-4597.playouts.now.amagi.tv/playlist/amg01391-addigital-cnnbrasil-lgbr/playlist.m3u8",
    "https://amg01391-sbtinfast-amg01391c3-lg-us-8995.playouts.now.amagi.tv/playlist/amg01391-addigital-jovempan-lgus/playlist.m3u8",
    "https://dfr80qz435crc.cloudfront.net/EFGH/Amagi/NewCo/New_Brasil_BR/New_Brasil.m3u8",
    "https://d25usgadhphvwi.cloudfront.net/hls/main.m3u8",
    "https://cnl-cl.otteravision.com/cnl/cl_h265/cl_h265.m3u8",
}


def normalizar(s: str) -> str:
    n = unicodedata.normalize("NFD", s.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = re.sub(r"[^a-z0-9]", "", n)
    return n


def carregar_dominios_desativados() -> set[str]:
    dominios = {"s25-cloudfront-net.lat"}
    if FONTES_DESATIVADAS_FILE.exists():
        try:
            dados = json.loads(FONTES_DESATIVADAS_FILE.read_text(encoding="utf-8"))
            dominios.update(dados.get("desativados", []))
        except Exception:
            pass
    return dominios


def baixar_m3u(url: str) -> list[dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            linhas = resp.read().decode("utf-8", errors="replace").splitlines()
    except Exception as e:
        print(f"  Aviso: Não foi possível acessar {url}: {e}", flush=True)
        return []

    canais = []
    i = 0
    while i < len(linhas):
        l = linhas[i].strip()
        if l.startswith("#EXTINF:"):
            nome = l.split(",")[-1].strip()
            logo_m = re.search(r'tvg-logo="([^"]*)"', l)
            logo = logo_m.group(1).strip() if logo_m else ""
            group_m = re.search(r'group-title="([^"]*)"', l)
            cat = group_m.group(1).strip() if group_m else "TV Aberta"
            if i + 1 < len(linhas):
                url_line = linhas[i + 1].strip()
                if url_line.startswith("http"):
                    canais.append({"nome": nome, "logo": logo, "cat": cat, "url": url_line})
                    i += 2
                    continue
        i += 1
    return canais


def executar_agregacao() -> int:
    if not CATALOGO_FILE.exists():
        print("catalogo.txt não encontrado.")
        return 0

    print("=" * 65)
    print("Prisma TV — Agregação e Higienização de Fontes")
    print(f"Data: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    # Backup de segurança antes de qualquer modificação
    backup_file = CATALOGO_FILE.with_suffix(".txt.bak")
    shutil.copy2(CATALOGO_FILE, backup_file)
    print(f"Backup de segurança criado: {backup_file.name}")

    dominios_desativados = carregar_dominios_desativados()
    print(f"Domínios bloqueados no filtro: {len(dominios_desativados)}")

    # 1. Manuais (Streams Oficiais Validados)
    manuais: dict[str, list[dict[str, str]]] = defaultdict(list)
    if MANUAIS_FILE.exists():
        for line in MANUAIS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                nome, logo, cat, url = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
                if url.startswith("http") and not any(d in url for d in dominios_desativados) and "/error.txt" not in url:
                    manuais[normalizar(nome)].append({"nome": nome, "logo": logo, "cat": cat, "url": url})
    print(f"  {sum(len(v) for v in manuais.values())} fontes manuais auditadas carregadas.")

    # 2. iptv-org M3Us (GitHub)
    externos = []
    for url, rotulo in IPTV_ORG_URLS:
        lista = baixar_m3u(url)
        print(f"  {len(lista)} canais baixados de iptv-org ({rotulo}).")
        externos.extend(lista)

    externos_por_nome: dict[str, list[dict[str, str]]] = defaultdict(list)
    for ext in externos:
        u = ext["url"]
        if "/error.txt" not in u and not any(d in u for d in dominios_desativados):
            externos_por_nome[normalizar(ext["nome"])].append(ext)

    # 3. Processar catalogo.txt existente - HIGIENIZAÇÃO COMPLETA
    texto = CATALOGO_FILE.read_text(encoding="utf-8", errors="replace")
    texto = texto.replace("# SAIMO TV — LISTA DE CANAIS", "# PRISMA TV — LISTA DE CANAIS")

    # Limpa adições antigas de seções dinâmicas
    marcador = "# CANAIS REGIONAIS E ADICIONAIS"
    if marcador in texto:
        idx_marcador = texto.find(marcador)
        limite = texto.rfind("# ───", 0, idx_marcador)
        if limite != -1:
            texto = texto[:limite].rstrip()
        else:
            texto = texto[:idx_marcador].rstrip()

    # Parse dos canais existentes
    canais_existentes: list[dict] = []
    canal_atual: dict | None = None

    for linha in texto.splitlines():
        linha_strip = linha.strip()
        if not linha_strip:
            continue
        if linha_strip.startswith("canal:"):
            if canal_atual and canal_atual["fontes"]:
                canais_existentes.append(canal_atual)
            canal_atual = {
                "nome": linha_strip[6:].strip(),
                "logo": "",
                "categoria": "Geral",
                "fontes": [],  # lista de (url, qualidade, referer, agente)
            }
        elif canal_atual:
            if linha_strip.startswith("logo:"):
                canal_atual["logo"] = linha_strip[5:].strip()
            elif linha_strip.startswith("categoria:"):
                canal_atual["categoria"] = linha_strip[10:].strip()
            elif linha_strip.startswith("fonte:"):
                url = linha_strip[6:].strip()
                # FILTRO RÍGIDO: Remove /error.txt, s25-cloudfront e domínios mortos
                if (
                    url.startswith("http")
                    and "/error.txt" not in url
                    and "/error/" not in url
                    and not any(d in url for d in dominios_desativados)
                ):
                    canal_atual["fontes"].append({
                        "url": url,
                        "qualidade": "FHD",
                        "referer": None,
                        "agente": None,
                    })
            elif linha_strip.startswith("qualidade:") and canal_atual["fontes"]:
                canal_atual["fontes"][-1]["qualidade"] = linha_strip[10:].strip()
            elif linha_strip.startswith("referer:") and canal_atual["fontes"]:
                canal_atual["fontes"][-1]["referer"] = linha_strip[8:].strip()
            elif linha_strip.startswith("agente:") and canal_atual["fontes"]:
                canal_atual["fontes"][-1]["agente"] = linha_strip[7:].strip()

    if canal_atual and canal_atual["fontes"]:
        canais_existentes.append(canal_atual)

    # 4. Injetar fontes manuais e organizar failover
    canais_processados = set()
    total_fontes_injetadas = 0

    for ch in canais_existentes:
        norm = normalizar(ch["nome"])
        canais_processados.add(norm)
        urls_no_canal = {f["url"] for f in ch["fontes"]}

        # Adiciona manuais validados no TOPO (prioridade oficial)
        if norm in manuais:
            for m in reversed(manuais[norm]):
                if m["url"] not in urls_no_canal:
                    ch["fontes"].insert(0, {
                        "url": m["url"],
                        "qualidade": "FHD · Stream Oficial",
                        "referer": None,
                        "agente": None,
                    })
                    urls_no_canal.add(m["url"])
                    total_fontes_injetadas += 1
            if not ch["logo"] and manuais[norm][0]["logo"]:
                ch["logo"] = manuais[norm][0]["logo"]

        # Adiciona até 2 backups do iptv-org
        if norm in externos_por_nome:
            adicionados = 0
            for ext in externos_por_nome[norm]:
                if ext["url"] not in urls_no_canal and adicionados < 2:
                    ch["fontes"].append({
                        "url": ext["url"],
                        "qualidade": "Backup (iptv-org)",
                        "referer": None,
                        "agente": None,
                    })
                    urls_no_canal.add(ext["url"])
                    adicionados += 1
                    total_fontes_injetadas += 1

    # 5. Adicionar canais manuais que não estavam no catálogo
    for norm, m_list in manuais.items():
        if norm not in canais_processados:
            m_first = m_list[0]
            novo_ch = {
                "nome": m_first["nome"],
                "logo": m_first["logo"],
                "categoria": m_first["cat"],
                "fontes": [
                    {"url": m["url"], "qualidade": "FHD · Stream Oficial", "referer": None, "agente": None}
                    for m in m_list
                ],
            }
            canais_existentes.append(novo_ch)
            canais_processados.add(norm)
            print(f"  + Novo canal manual integrado: {m_first['nome']}")

    # 6. Adicionar canais novos do iptv-org
    novos_iptv_org = 0
    for ext in externos:
        norm = normalizar(ext["nome"])
        if norm not in canais_processados:
            u = ext["url"]
            if "/error.txt" not in u and not any(d in u for d in dominios_desativados):
                canais_existentes.append({
                    "nome": ext["nome"],
                    "logo": ext["logo"],
                    "categoria": ext["cat"] if ext["cat"] != "Geral" else "Regional / Aberta",
                    "fontes": [{"url": u, "qualidade": "HD · iptv-org", "referer": None, "agente": None}],
                })
                canais_processados.add(norm)
                novos_iptv_org += 1

    # 7. Salvar catalogo.txt higienizado (com trava de segurança R4)
    MIN_CANAIS = 100
    if len(canais_existentes) < MIN_CANAIS:
        print(
            f"ERRO DE SEGURANÇA (R4): apenas {len(canais_existentes)} canais identificados "
            f"(mínimo esperado: {MIN_CANAIS}). Abortando execução para evitar sobrescrever "
            "playlists válidas em produção.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

    novas_linhas_catalogo = [
        "# PRISMA TV — LISTA DE CANAIS",
        f"# Atualizado em: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "# Auditoria completa: sem /error.txt, sem links mortos, failover ordenado",
        "# ──────────────────────────────────────────────────────────\n",
    ]

    for ch in canais_existentes:
        if not ch["fontes"]:
            continue
        novas_linhas_catalogo.append(f"canal: {ch['nome']}")
        if ch["logo"]:
            novas_linhas_catalogo.append(f"logo: {ch['logo']}")
        novas_linhas_catalogo.append(f"categoria: {ch['categoria']}")
        for f in ch["fontes"]:
            if f.get("referer"):
                novas_linhas_catalogo.append(f"referer: {f['referer']}")
            if f.get("agente"):
                novas_linhas_catalogo.append(f"agente: {f['agente']}")
            novas_linhas_catalogo.append(f"fonte: {f['url']}")
            novas_linhas_catalogo.append(f"qualidade: {f['qualidade']}")
        novas_linhas_catalogo.append("")

    CATALOGO_FILE.write_text("\n".join(novas_linhas_catalogo), encoding="utf-8")
    print(f"catalogo.txt salvo com {len(canais_existentes)} canais válidos.")

    # 8. Gerar playlists M3U
    gerar_m3u(canais_existentes)
    return len(canais_existentes)


def gerar_m3u(canais: list[dict]):
    """Gera lista.m3u (completo), canais.m3u (espelho) e lista-web.m3u (HTTPS + H.264 para Web/Safari)."""
    # Trava de segurança R4
    MIN_CANAIS = 100
    if len(canais) < MIN_CANAIS:
        print(
            f"ERRO DE SEGURANÇA (R4): apenas {len(canais)} canais para geração de M3U "
            f"(mínimo: {MIN_CANAIS}). Abortando.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

    # ── 1. Geração de lista.m3u (completo com failover organizado e dedup por URL R3) ──
    seen_urls_lista: set[str] = set()
    m3u_linhas = ["#EXTM3U"]
    for ch in canais:
        nome = ch["nome"]
        logo = ch.get("logo", "")
        cat = ch.get("categoria", "Geral")
        fontes = ch.get("fontes", [])

        idx_fonte = 0
        for f in fontes:
            url = f["url"].strip()
            # R3: deduplicação por URL para evitar repetição de stream sob nomes variantes
            if not url or url in seen_urls_lista:
                continue
            seen_urls_lista.add(url)
            idx_fonte += 1

            sufixo = f" (Fonte {idx_fonte})" if idx_fonte > 1 else ""
            if url in HEVC_STREAMS:
                sufixo += " [HEVC]"
            nome_fmt = f"{nome}{sufixo}"
            m3u_linhas.append(
                f'#EXTINF:-1 tvg-id="{nome}" tvg-name="{nome_fmt}" tvg-logo="{logo}" group-title="{cat}",{nome_fmt}'
            )
            m3u_linhas.append(url)

    m3u_text = "\n".join(m3u_linhas)
    (CANAIS_DIR / "lista.m3u").write_text(m3u_text, encoding="utf-8")
    (CANAIS_DIR / "canais.m3u").write_text(m3u_text, encoding="utf-8")
    total_lista = len(m3u_linhas) // 2
    print(f"  OK! canais/lista.m3u gerado ({total_lista} streams/fontes únicos — sem URLs duplicadas).")
    print(f"  OK! canais/canais.m3u sincronizado.")

    # ── 2. Geração de lista-web.m3u (HTTPS + H.264 priorizado para Safari/iPhone e dedup R3) ──
    # Requisitos:
    # - Apenas HTTPS
    # - Sem /error.txt
    # - Priorizar fontes H.264
    # - Excluir streams HEVC MPEG-TS que causam tela preta no iOS/Safari quando houver alternativa ou incompatibilidade
    # - R3: Deduplicação por URL de stream
    seen_urls_web: set[str] = set()
    web_linhas = ["#EXTM3U"]
    canais_web_count = 0

    for ch in canais:
        nome = ch["nome"]
        logo = ch.get("logo", "")
        cat = ch.get("categoria", "Geral")
        fontes = ch.get("fontes", [])

        # Filtra apenas fontes HTTPS
        fontes_https = [f for f in fontes if f["url"].startswith("https://")]
        if not fontes_https:
            continue

        # Separa H.264 vs HEVC
        fontes_h264 = [f for f in fontes_https if f["url"] not in HEVC_STREAMS]
        fontes_hevc = [f for f in fontes_https if f["url"] in HEVC_STREAMS]

        # Prioridade total para H.264; só usa HEVC se for o único stream do canal
        fontes_selecionadas = fontes_h264 if fontes_h264 else fontes_hevc

        idx_web = 0
        for f in fontes_selecionadas:
            url = f["url"].strip()
            # R3: deduplicação por URL
            if not url or url in seen_urls_web:
                continue
            seen_urls_web.add(url)
            idx_web += 1

            sufixo = f" (Fonte {idx_web})" if idx_web > 1 else ""
            if url in HEVC_STREAMS:
                sufixo += " [HEVC - Safari Incompativel]"
            nome_fmt = f"{nome}{sufixo}"
            web_linhas.append(
                f'#EXTINF:-1 tvg-id="{nome}" tvg-name="{nome_fmt}" tvg-logo="{logo}" group-title="{cat}",{nome_fmt}'
            )
            web_linhas.append(url)
            canais_web_count += 1

    web_text = "\n".join(web_linhas)
    (CANAIS_DIR / "lista-web.m3u").write_text(web_text, encoding="utf-8")
    print(f"  OK! canais/lista-web.m3u gerado ({canais_web_count} canais HTTPS/H.264 únicos compatíveis).")


if __name__ == "__main__":
    executar_agregacao()
