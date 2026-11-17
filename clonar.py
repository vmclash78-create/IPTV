#!/usr/bin/env python3
"""Mirror authorized Saimo source code and text catalogs into this repository.

The catalog layout is preserved:
  PrismaPlayer/
  canais/
  filmes/
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
EXTRA_URL = "https://saimo-tv.pages.dev/"
SOURCE_GIT = "https://github.com/SaimoTV/SaimoPlayer.git"
USER_AGENT = "Mozilla/5.0 (compatible; IPTV-Catalog-Mirror/1.0)"
TIMEOUT = 35
RETRIES = 3
DELAY = 0.30          # aumentado para reduzir risco de rate limit no Cloudflare
MAX_SERIES_PARTS = 1000

CHANNEL_FILES = (
    "catalogo.txt",
    "canais.txt",
    "guia.txt",
    "radios.txt",
    "restritos.txt",
)
EXTRA_FILES = (
    "eventos-extra.json",
    "fontes-desativadas.json",
)
MOVIE_FIXED_FILES = (
    "indice.txt",
    "destaques.txt",
    "busca.txt",
    "generos.txt",
    "marcas.txt",
    "fichas.txt",
    "detalhes.txt",
    # "links-doramas.txt",  # removido: retorna 404 (migrado para redeflix/)
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
    # FIX: rejeita respostas vazias para evitar sobrescrever arquivos bons
    if len(data) == 0:
        print(f"  AVISO: resposta vazia para {relative_path} — ignorado", flush=True)
        return False
    # Otimização: evita re-escrita se o conteúdo já é idêntico
    if destination.exists() and destination.read_bytes() == data:
        print(f"  Sem mudança: {relative_path}", flush=True)
        return True
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print(f"  OK {relative_path} ({len(data):,} bytes)", flush=True)
    time.sleep(DELAY)
    return True


def apply_custom_patches() -> None:
    """Garante que os arquivos Swift apontem sempre para o repositório do vmclash78-create."""
    sources = ROOT / "PrismaPlayer" / "Sources"
    if not sources.exists():
        return

    # 1. Enderecos.swift
    enderecos = sources / "Enderecos.swift"
    if enderecos.exists():
        txt = enderecos.read_text(encoding="utf-8")
        if "padraoCanais" not in txt:
            txt = txt.replace(
                'static func resolver(guardado: String?) -> String {',
                'static let padraoCanais = "https://raw.githubusercontent.com/vmclash78-create/IPTV/main/canais/"\n    static let padraoFilmes = "https://raw.githubusercontent.com/vmclash78-create/IPTV/main/filmes/"\n\n    static func resolver(guardado: String?, padrao: String = "") -> String {\n        let valor = (guardado ?? "").trimmingCharacters(in: .whitespacesAndNewlines)\n        return valor.isEmpty ? padrao : valor\n    }'
            )
            txt = txt.replace(
                'get { resolver(guardado: UserDefaults.standard.string(forKey: chaveCanais)) }',
                'get { resolver(guardado: UserDefaults.standard.string(forKey: chaveCanais), padrao: padraoCanais) }'
            )
            txt = txt.replace(
                'get { resolver(guardado: UserDefaults.standard.string(forKey: chaveFilmes)) }',
                'get { resolver(guardado: UserDefaults.standard.string(forKey: chaveFilmes), padrao: padraoFilmes) }'
            )
            enderecos.write_text(txt, encoding="utf-8")
            print("  Patch aplicado em Enderecos.swift", flush=True)

    # 2. VersaoPublicada.swift
    versao = sources / "VersaoPublicada.swift"
    if versao.exists():
        txt = versao.read_text(encoding="utf-8")
        if "SaimoTV/saimo-downloads" in txt:
            txt = txt.replace(
                "https://github.com/SaimoTV/saimo-downloads/releases/latest/download/versao.json",
                "https://github.com/vmclash78-create/IPTV/releases/latest/download/versao.json"
            )
            versao.write_text(txt, encoding="utf-8")
            print("  Patch aplicado em VersaoPublicada.swift", flush=True)

    # 3. Events.swift
    events = sources / "Events.swift"
    if events.exists():
        txt = events.read_text(encoding="utf-8")
        if "saimo-tv.pages.dev/eventos-extra.json" in txt or "canais-saimo" in txt:
            txt = txt.replace(
                "https://saimo-tv.pages.dev/eventos-extra.json",
                "https://raw.githubusercontent.com/vmclash78-create/IPTV/main/canais/eventos-extra.json"
            )
            txt = txt.replace("canais-saimo", "canais")
            events.write_text(txt, encoding="utf-8")
            print("  Patch aplicado em Events.swift", flush=True)

    # 4. FontesDesativadas.swift
    fontes = sources / "FontesDesativadas.swift"
    if fontes.exists():
        txt = fontes.read_text(encoding="utf-8")
        if "saimo-tv.pages.dev/fontes-desativadas.json" in txt or "canais-saimo" in txt:
            txt = txt.replace(
                "https://saimo-tv.pages.dev/fontes-desativadas.json",
                "https://raw.githubusercontent.com/vmclash78-create/IPTV/main/canais/fontes-desativadas.json"
            )
            txt = txt.replace("canais-saimo", "canais")
            fontes.write_text(txt, encoding="utf-8")
            print("  Patch aplicado em FontesDesativadas.swift", flush=True)

    # 5. Info.plist e Marca Prisma TV
    plist = ROOT / "PrismaPlayer" / "Info.plist"
    if plist.exists():
        txt = plist.read_text(encoding="utf-8")
        if "Saimo TV" in txt or "dev.saimo.player" in txt:
            txt = txt.replace("Saimo TV", "Prisma TV")
            txt = txt.replace("SaimoTV", "PrismaTV")
            txt = txt.replace("dev.saimo.player", "dev.prismatv.player")
            txt = txt.replace("_saimotv._tcp", "_prismatv._tcp")
            plist.write_text(txt, encoding="utf-8")
            print("  Patch de marca aplicado em Info.plist", flush=True)

    # 6. Anti-lag / Otimização de Performance no ProxyServer.swift
    proxy = sources / "ProxyServer.swift"
    if proxy.exists():
        txt = proxy.read_text(encoding="utf-8")
        if "penalidadeDeHost: TimeInterval = 300" in txt:
            txt = txt.replace("penalidadeDeHost: TimeInterval = 300", "penalidadeDeHost: TimeInterval = 60")
        if "recusasParaTrocar = 3" in txt:
            txt = txt.replace("recusasParaTrocar = 3", "recusasParaTrocar = 2")
        if "validadeDaGuardada: TimeInterval = 20" in txt:
            txt = txt.replace("validadeDaGuardada: TimeInterval = 20", "validadeDaGuardada: TimeInterval = 10")
        proxy.write_text(txt, encoding="utf-8")
        print("  Otimização anti-lag aplicada em ProxyServer.swift", flush=True)

    # 7. Redução de atraso na reconexão em PlayerModel.swift
    model = sources / "PlayerModel.swift"
    if model.exists():
        txt = model.read_text(encoding="utf-8")
        if "let delay = min(pow(1.6, Double(reconnectAttempt)), 20)" in txt:
            txt = txt.replace(
                "let delay = min(pow(1.6, Double(reconnectAttempt)), 20)",
                "let delay = min(pow(1.5, Double(reconnectAttempt)), 8)"
            )
            model.write_text(txt, encoding="utf-8")
            print("  Otimização de reconexão rápida aplicada em PlayerModel.swift", flush=True)

    # 8. Renomeações de arquivos Swift de marca
    saimo_app = sources / "SaimoApp.swift"
    prisma_app = sources / "PrismaApp.swift"
    if saimo_app.exists() and not prisma_app.exists():
        saimo_app.rename(prisma_app)
    saimo_connect = sources / "SaimoConnect.swift"
    prisma_connect = sources / "PrismaConnect.swift"
    if saimo_connect.exists() and not prisma_connect.exists():
        saimo_connect.rename(prisma_connect)


def mirror_git_source() -> None:
    target = ROOT / "PrismaPlayer"
    temp = ROOT / ".PrismaPlayer-clone"
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
    print("PrismaPlayer source mirrored.", flush=True)
    apply_custom_patches()


def mirror_channels() -> None:
    print("\n== Canais ==", flush=True)
    target = ROOT / "canais"
    successes = 0
    for name in CHANNEL_FILES:
        if download_file(CHANNELS_URL, name, target / name):
            successes += 1
        else:
            print(f"  Ausente/indisponível: {name}", flush=True)
    for name in EXTRA_FILES:
        download_file(EXTRA_URL, name, target / name)
    if successes == 0:
        raise RuntimeError("Nenhum arquivo de canais foi baixado; confira a origem.")
    injetar_fontes_confiaveis()


def injetar_fontes_confiaveis() -> None:
    """Garante que canais essenciais (Record, SBT, Band, etc.) tenham fontes oficiais e ativas."""
    catalogo_path = ROOT / "canais" / "catalogo.txt"
    manuais_path = ROOT / "canais" / "manuais.txt"
    if not catalogo_path.exists() or not manuais_path.exists():
        return

    manuais: dict[str, dict[str, str]] = {}
    for line in manuais_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) >= 4:
            nome, logo, cat, url = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
            manuais[nome.lower()] = {"nome": nome, "logo": logo, "cat": cat, "url": url}

    texto = catalogo_path.read_text(encoding="utf-8", errors="replace")
    linhas = texto.splitlines()
    novas_linhas: list[str] = []
    injetados = 0

    i = 0
    while i < len(linhas):
        l = linhas[i]
        if l.startswith("canal:"):
            canal_nome = l[6:].strip()
            canal_lower = canal_nome.lower()
            novas_linhas.append(l)
            if canal_lower in manuais:
                m = manuais[canal_lower]
                tem_fonte = False
                j = i + 1
                while j < len(linhas) and not linhas[j].startswith("canal:"):
                    if m["url"] in linhas[j]:
                        tem_fonte = True
                        break
                    j += 1
                if not tem_fonte:
                    k = i + 1
                    while k < len(linhas) and (linhas[k].startswith("categoria:") or linhas[k].startswith("logo:") or not linhas[k].strip()):
                        novas_linhas.append(linhas[k])
                        k += 1
                    novas_linhas.append(f"fonte: {m['url']}")
                    novas_linhas.append("qualidade: FHD · Stream Direto Oficial")
                    injetados += 1
                    i = k
                    continue
        novas_linhas.append(l)
        i += 1

    catalogo_path.write_text("\n".join(novas_linhas), encoding="utf-8")
    print(f"  Injetadas fontes oficiais e ativas em {injetados} canais essenciais.", flush=True)


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
            if dest.exists() and dest.read_bytes() == data:
                print(f"  Sem mudança: {canonical}", flush=True)
                return True
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            print(f"  OK {canonical} via {name} ({len(data):,} bytes)", flush=True)
            time.sleep(DELAY)
            return True
        time.sleep(DELAY)
    print(f"  Ausente: {kind}-{letter}.txt", flush=True)
    return False


def download_series_parts(base_url: str, folder: Path, letter: str) -> int:
    # FIX: codifica '#' como '%23' na URL para evitar arquivos ausentes
    url_letter = "%23" if letter == "#" else letter
    downloaded = 0
    for part in range(MAX_SERIES_PARTS):
        relative_url = f"series-{url_letter}-{part}.txt"
        relative_local = f"series-{letter}-{part}.txt"
        dest = folder / relative_local
        if not download_file(base_url, relative_url, dest):
            # O formato publicado usa numeração contígua base-zero; para na primeira ausência.
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
    target = ROOT / "filmes"
    target.mkdir(parents=True, exist_ok=True)

    if not download_file(MOVIES_URL, "indice.txt", target / "indice.txt"):
        raise RuntimeError("Não foi possível baixar filmes/indice.txt.")

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
    # FIX: etapas isoladas — falha em uma não cancela as demais
    steps = [
        ("PrismaPlayer (código-fonte)", mirror_git_source),
        ("Canais", mirror_channels),
        ("Filmes e Séries", mirror_movies),
    ]
    failed: list[str] = []
    for name, func in steps:
        print(f"\n{'='*60}", flush=True)
        print(f"Iniciando: {name}", flush=True)
        print(f"{'='*60}", flush=True)
        try:
            func()
            print(f"Concluído: {name}", flush=True)
        except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
            print(f"ERRO em '{name}': {exc}", file=sys.stderr, flush=True)
            failed.append(name)

    print(f"\n{'='*60}", flush=True)
    if failed:
        print(
            f"Espelhamento concluído COM ERROS nas etapas: {', '.join(failed)}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print("Espelhamento concluído com sucesso.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
