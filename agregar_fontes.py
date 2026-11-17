#!/usr/bin/env python3
"""Agregador Multi-Repositório para Prisma TV.

Combina canais de múltiplos repositórios e fontes:
  1. Catálogo base Saimo (canais pagos, esportes, eventos, filmes/séries)
  2. Fontes Oficiais Manuais (canais/manuais.txt - Record, SBT, Band, Globo...)
  3. iptv-org/iptv (Repositório global GitHub - canais BR e PT)
  4. Preserva fontes alternativas para redundância e failover
"""
from __future__ import annotations

import re
import sys
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOGO_FILE = ROOT / "canais" / "catalogo.txt"
MANUAIS_FILE = ROOT / "canais" / "manuais.txt"
USER_AGENT = "Mozilla/5.0 (compatible; PrismaTV-Aggregator/2.0)"

IPTV_ORG_URLS = [
    ("https://raw.githubusercontent.com/iptv-org/iptv/master/streams/br.m3u", "Brasil"),
]

def normalizar(s: str) -> str:
    n = unicodedata.normalize("NFD", s.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = re.sub(r"[^a-z0-9]", "", n)
    return n

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

    print("== Agregando canais de múltiplos repositórios ==", flush=True)

    # 1. Manuais (Streams Oficiais)
    manuais: dict[str, dict[str, str]] = {}
    if MANUAIS_FILE.exists():
        for line in MANUAIS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                nome, logo, cat, url = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
                manuais[normalizar(nome)] = {"nome": nome, "logo": logo, "cat": cat, "url": url}
    print(f"  {len(manuais)} canais oficiais manuais carregados.")

    # 2. iptv-org M3Us (GitHub)
    externos = []
    for url, rotulo in IPTV_ORG_URLS:
        lista = baixar_m3u(url)
        print(f"  {len(lista)} canais baixados de iptv-org ({rotulo}).")
        externos.extend(lista)

    externos_por_nome: dict[str, list[dict[str, str]]] = defaultdict(list)
    for ext in externos:
        externos_por_nome[normalizar(ext["nome"])].append(ext)

    # 3. Processa catalogo.txt existente
    texto = CATALOGO_FILE.read_text(encoding="utf-8", errors="replace")
    texto = texto.replace("# SAIMO TV — LISTA DE CANAIS", "# PRISMA TV — LISTA DE CANAIS")
    # Limpa adições anteriores do iptv-org para re-agregar de forma limpa
    marcador = "# CANAIS REGIONAIS E ADICIONAIS"
    if marcador in texto:
        idx_marcador = texto.find(marcador)
        # retrocede até o delimitador anterior se existir
        limite = texto.rfind("# ───", 0, idx_marcador)
        if limite != -1:
            texto = texto[:limite].rstrip()
        else:
            texto = texto[:idx_marcador].rstrip()
    linhas = texto.splitlines()

    novas_linhas: list[str] = []
    canais_processados = set()
    fontes_adicionadas = 0

    i = 0
    while i < len(linhas):
        l = linhas[i]
        if l.startswith("canal:"):
            canal_nome = l[6:].strip()
            norm = normalizar(canal_nome)
            canais_processados.add(norm)
            novas_linhas.append(l)

            tem_manual = norm in manuais
            tem_externo = norm in externos_por_nome

            k = i + 1
            while k < len(linhas) and (linhas[k].startswith("categoria:") or linhas[k].startswith("logo:") or not linhas[k].strip()):
                novas_linhas.append(linhas[k])
                k += 1

            if tem_manual:
                url_m = manuais[norm]["url"]
                fontes_existentes = set()
                idx_scan = k
                while idx_scan < len(linhas) and not linhas[idx_scan].startswith("canal:"):
                    if linhas[idx_scan].startswith("fonte:"):
                        fontes_existentes.add(linhas[idx_scan][6:].strip())
                    idx_scan += 1

                if url_m not in fontes_existentes:
                    novas_linhas.append(f"fonte: {url_m}")
                    novas_linhas.append("qualidade: FHD · Stream Direto Oficial")
                    fontes_adicionadas += 1

            if tem_externo:
                fontes_existentes = set()
                idx_scan = k
                while idx_scan < len(linhas) and not linhas[idx_scan].startswith("canal:"):
                    if linhas[idx_scan].startswith("fonte:"):
                        fontes_existentes.add(linhas[idx_scan][6:].strip())
                    idx_scan += 1

                adicionados_ext = 0
                for ext in externos_por_nome[norm]:
                    if ext["url"] not in fontes_existentes and adicionados_ext < 2:
                        novas_linhas.append(f"fonte: {ext['url']}")
                        novas_linhas.append("qualidade: Backup (iptv-org)")
                        fontes_existentes.add(ext["url"])
                        adicionados_ext += 1
                        fontes_adicionadas += 1

            i = k
            continue
        novas_linhas.append(l)
        i += 1

    # 4. Adiciona novos canais do iptv-org
    novos_canais_count = 0
    novas_linhas.append("\n# ──────────────────────────────────────────────────────────")
    novas_linhas.append("# CANAIS REGIONAIS E ADICIONAIS (iptv-org GitHub)")
    novas_linhas.append("# ──────────────────────────────────────────────────────────\n")

    canais_ja_adicionados = set()
    for ext in externos:
        norm = normalizar(ext["nome"])
        if norm not in canais_processados and norm not in canais_ja_adicionados:
            canais_ja_adicionados.add(norm)
            novas_linhas.append(f"canal: {ext['nome']}")
            if ext["logo"]:
                novas_linhas.append(f"logo: {ext['logo']}")
            cat = ext["cat"] if ext["cat"] != "Geral" else "Regional / Aberta"
            novas_linhas.append(f"categoria: {cat}")
            novas_linhas.append(f"fonte: {ext['url']}")
            novas_linhas.append("qualidade: HD")
            novas_linhas.append("")
            novos_canais_count += 1

    CATALOGO_FILE.write_text("\n".join(novas_linhas), encoding="utf-8")
    print(f"  OK! {fontes_adicionadas} fontes de backup injetadas em canais existentes.")
    print(f"  OK! {novos_canais_count} novos canais adicionados do repositório iptv-org.")
    gerar_m3u()
    return novos_canais_count

def gerar_m3u():
    """Gera arquivos lista.m3u, canais.m3u e lista-web.m3u (HTTPS-only para navegador)."""
    texto = CATALOGO_FILE.read_text(encoding="utf-8", errors="replace")
    linhas = texto.splitlines()
    
    m3u_linhas = ["#EXTM3U"]
    canal_atual = ""
    logo_atual = ""
    cat_atual = "Geral"
    fontes = []
    
    # Domínios que exigem Referer e não funcionam direto no navegador
    DOMINIOS_BLOQUEADOS_WEB = ["cdn8embed.xyz"]
    
    def salvar_canal():
        nonlocal canal_atual, logo_atual, cat_atual, fontes
        if canal_atual and fontes:
            for idx, f in enumerate(fontes):
                sufixo = f" (Fonte {idx+1})" if len(fontes) > 1 and idx > 0 else ""
                nome_fmt = f"{canal_atual}{sufixo}"
                m3u_linhas.append(f'#EXTINF:-1 tvg-id="{canal_atual}" tvg-name="{nome_fmt}" tvg-logo="{logo_atual}" group-title="{cat_atual}",{nome_fmt}')
                m3u_linhas.append(f)
        canal_atual = ""
        logo_atual = ""
        cat_atual = "Geral"
        fontes = []

    for l in linhas:
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        if l.startswith("canal:"):
            salvar_canal()
            canal_atual = l[6:].strip()
        elif l.startswith("logo:"):
            logo_atual = l[5:].strip()
        elif l.startswith("categoria:"):
            cat_atual = l[10:].strip()
        elif l.startswith("fonte:"):
            fontes.append(l[6:].strip())
            
    salvar_canal()
    
    m3u_text = "\n".join(m3u_linhas)
    (ROOT / "canais" / "lista.m3u").write_text(m3u_text, encoding="utf-8")
    (ROOT / "canais" / "canais.m3u").write_text(m3u_text, encoding="utf-8")
    print(f"  OK! Playlist M3U gerada em canais/lista.m3u ({len(m3u_linhas)//2} canais/fontes).")
    
    # --- Gerar lista-web.m3u (somente HTTPS, sem domínios que exigem Referer) ---
    web_linhas = ["#EXTM3U"]
    for i in range(1, len(m3u_linhas)):
        if m3u_linhas[i].startswith("#EXTINF:") and i + 1 < len(m3u_linhas):
            url = m3u_linhas[i + 1]
            if url.startswith("https://"):
                bloqueado = any(d in url for d in DOMINIOS_BLOQUEADOS_WEB)
                if not bloqueado:
                    web_linhas.append(m3u_linhas[i])
                    web_linhas.append(url)
    
    web_text = "\n".join(web_linhas)
    (ROOT / "canais" / "lista-web.m3u").write_text(web_text, encoding="utf-8")
    web_count = sum(1 for l in web_linhas if l.startswith("#EXTINF:"))
    print(f"  OK! Playlist WEB (HTTPS-only) gerada em canais/lista-web.m3u ({web_count} canais).")

if __name__ == "__main__":
    executar_agregacao()
