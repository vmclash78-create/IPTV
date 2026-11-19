#!/usr/bin/env python3
"""Sincroniza canais de fontes públicas e abertas para o repositório Prisma TV.

Fontes de canais (100% independentes, sem Saimo):
  - iptv-org/iptv: +8.000 canais de 200+ países, organizados por país e categoria
  - Canais manuais em canais/manuais.txt (você adiciona seus próprios links)

Fontes de filmes e séries (mantidas localmente):
  - Preserva os arquivos já existentes em filmes/ sem sobrescrever
  - Listas manuais em filmes/manuais-filmes.txt (você adiciona links diretos)

Layout do repositório:
  canais/
    catalogo.txt       ← gerado automaticamente (canais iptv-org + manuais)
    canais.txt         ← gerado automaticamente (mesmo catálogo, formato alternativo)
    radios.txt         ← gerado automaticamente (rádios do iptv-org)
    manuais.txt        ← seus canais manuais (não sobrescrito pelo robô)
    adultos.txt        ← canais adultos em categoria separada (opt-in)
  filmes/
    (mantidos como estão)
    manuais-filmes.txt ← seus filmes manuais (não sobrescrito pelo robô)
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
USER_AGENT = "Mozilla/5.0 (compatible; PrismaTV-Sync/2.0)"
TIMEOUT = 30
RETRIES = 3
DELAY = 0.20

# ─────────────────────────── Fontes iptv-org ───────────────────────────────
# Usamos o repositório oficial do projeto iptv-org no GitHub (raw).
# Cada URL abaixo é uma playlist M3U pública e gratuita.

IPTV_ORG_BASE = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams"

# Países prioritários (canais brasileiros e de língua portuguesa primeiro)
PRIORITY_COUNTRIES = ["br", "pt", "ao", "mz"]

# Outros países desejados (internacionais populares)
EXTRA_COUNTRIES = [
    "us", "gb", "ar", "mx", "co", "cl", "pe", "es",
    "it", "fr", "de", "jp", "kr", "cn", "in", "ru",
]

# Categorias de canais que queremos (iptv-org usa essas tags em group-title)
WANTED_CATEGORIES = {
    "Entretenimento", "Entertainment",
    "Notícias", "News",
    "Esportes", "Sports",
    "Infantil", "Kids", "Children",
    "Documentários", "Documentary", "Documentaries",
    "Filmes", "Movies",
    "Séries", "Series",
    "Música", "Music",
    "Variedades", "General",
    "TV Aberta", "TV Paga",
    "Religioso", "Religious",
    "Governo", "Government",
    "Negócios", "Business",
    "Ciência", "Science",
    "Natureza", "Nature",
    "Saúde", "Health",
    "Viagem", "Travel",
    "Culinária", "Cooking",
    "Moda", "Fashion",
    "Tecnologia", "Technology",
    "Auto", "Automotive",
    "Clássicos", "Classic",
    "Regional",
    "Cultura", "Culture",
    "Arte", "Art",
    "Humor", "Comedy",
    "Thriller", "Drama",
    "Ação", "Action",
    "Animação", "Animation",
    "Reality", "Show",
    "Talk Show",
    "undefined", "",  # sem categoria — incluímos mesmo assim
}

# Categorias adultas (separadas em adultos.txt)
ADULT_CATEGORIES = {
    "Adults Only", "XXX", "Adult", "Erotic", "18+", "Adultos", "+18",
}

# ─────────────────────────── Mapeamento de categorias (PT-BR) ──────────────
CATEGORY_MAP = {
    "News": "Notícias",
    "Sports": "Esportes",
    "Kids": "Infantil",
    "Children": "Infantil",
    "Documentary": "Documentários",
    "Documentaries": "Documentários",
    "Movies": "Filmes",
    "Series": "Séries",
    "Music": "Música",
    "General": "Variedades",
    "Entertainment": "Entretenimento",
    "Religious": "Religioso",
    "Government": "Governo",
    "Business": "Negócios",
    "Science": "Ciência",
    "Nature": "Natureza",
    "Health": "Saúde",
    "Travel": "Viagem",
    "Cooking": "Culinária",
    "Fashion": "Moda",
    "Technology": "Tecnologia",
    "Automotive": "Auto",
    "Classic": "Clássicos",
    "Culture": "Cultura",
    "Art": "Arte",
    "Comedy": "Humor",
    "Animation": "Animação",
    "undefined": "Variedades",
    "": "Variedades",
}

# ─────────────────────────── Estrutura de canal ────────────────────────────
class Canal:
    __slots__ = ("nome", "logo", "categoria", "pais", "fontes", "adulto")

    def __init__(self, nome: str, logo: str = "", categoria: str = "",
                 pais: str = "", adulto: bool = False):
        self.nome = nome
        self.logo = logo
        self.categoria = categoria
        self.pais = pais
        self.fontes: list[str] = []
        self.adulto = adulto


# ─────────────────────────── HTTP util ────────────────────────────────────
def request_bytes(url: str) -> Optional[bytes]:
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                if 200 <= resp.status < 300:
                    return resp.read()
                return None
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410, 403):
                return None
            if attempt == RETRIES:
                print(f"  HTTP {exc.code}: {url}", flush=True)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == RETRIES:
                print(f"  Falha: {url}: {exc}", flush=True)
        time.sleep(attempt * 0.8)
    return None


def request_text(url: str) -> Optional[str]:
    data = request_bytes(url)
    if data is None:
        return None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ─────────────────────────── Parser M3U ───────────────────────────────────
def parse_m3u(text: str, pais: str = "") -> list[Canal]:
    """Converte texto M3U para lista de Canal."""
    canais: list[Canal] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF:"):
            # Extrai metadados da linha #EXTINF
            nome = ""
            logo = ""
            categoria = ""
            adulto = False

            # Nome: texto após a última vírgula
            if "," in line:
                nome = line.split(",", 1)[-1].strip()

            # Atributos: tvg-logo, group-title etc.
            logo_m = re.search(r'tvg-logo="([^"]*)"', line)
            if logo_m:
                logo = logo_m.group(1).strip()

            group_m = re.search(r'group-title="([^"]*)"', line)
            if group_m:
                raw_cat = group_m.group(1).strip()
                if raw_cat in ADULT_CATEGORIES:
                    adulto = True
                    categoria = "Adultos"
                else:
                    # Mapeia para PT-BR
                    categoria = CATEGORY_MAP.get(raw_cat, raw_cat or "Variedades")

            # Próxima linha é a URL
            if i + 1 < len(lines):
                url_line = lines[i + 1].strip()
                if url_line and not url_line.startswith("#"):
                    dominios_bloqueados = carregar_dominios_desativados()
                    if (
                        nome
                        and url_line.startswith("http")
                        and "/error.txt" not in url_line
                        and "/error/" not in url_line
                        and not any(d in url_line for d in dominios_bloqueados)
                    ):
                        c = Canal(nome=nome, logo=logo, categoria=categoria,
                                  pais=pais, adulto=adulto)
                        c.fontes.append(url_line)
                        canais.append(c)
                    i += 2
                    continue
        i += 1
    return canais


def carregar_dominios_desativados() -> set[str]:
    """Carrega lista de domínios mortos para blindagem do catálogo."""
    dominios = {"s25-cloudfront-net.lat"}
    path = ROOT / "canais" / "fontes-desativadas.json"
    if path.exists():
        try:
            dados = json.loads(path.read_text(encoding="utf-8"))
            dominios.update(dados.get("desativados", []))
        except Exception:
            pass
    return dominios


# ─────────────────────────── Listas manuais ───────────────────────────────
def ler_manuais_canais() -> list[Canal]:
    """Lê canais/manuais.txt (formato simples: nome|logo|categoria|url)."""
    path = ROOT / "canais" / "manuais.txt"
    if not path.exists():
        # Cria arquivo de exemplo se não existir
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Canais Manuais Prisma TV\n"
            "# Formato: nome|logo_url|categoria|stream_url\n"
            "# Exemplo:\n"
            "# TV Brasil|https://tvbrasil.ebc.com.br/logo.png|TV Aberta|https://link.m3u8\n"
            "# Deixe em branco as que não tiver — nome e URL são obrigatórios.\n",
            encoding="utf-8",
        )
        return []
    canais: list[Canal] = []
    dominios_bloqueados = carregar_dominios_desativados()
    for linha in path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        partes = linha.split("|")
        if len(partes) < 2:
            continue
        nome = partes[0].strip()
        logo = partes[1].strip() if len(partes) > 1 else ""
        categoria = partes[2].strip() if len(partes) > 2 else "Manual"
        url = partes[3].strip() if len(partes) > 3 else ""
        if (
            nome
            and url
            and url.startswith("http")
            and "/error.txt" not in url
            and not any(d in url for d in dominios_bloqueados)
        ):
            c = Canal(nome=nome, logo=logo, categoria=categoria, pais="BR")
            c.fontes.append(url)
            canais.append(c)
    return canais


def ler_catalogo_existente() -> list[Canal]:
    """Lê o catalogo.txt atual para preservar canais que ainda funcionam."""
    path = ROOT / "canais" / "catalogo.txt"
    if not path.exists():
        return []
    canais: list[Canal] = []
    current: Optional[Canal] = None
    dominios_bloqueados = carregar_dominios_desativados()
    for linha in path.read_text(encoding="utf-8", errors="replace").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("canal:"):
            if current and current.fontes:
                canais.append(current)
            current = Canal(nome=linha[6:].strip())
        elif current:
            if linha.startswith("logo:"):
                current.logo = linha[5:].strip()
            elif linha.startswith("categoria:"):
                current.categoria = linha[10:].strip()
            elif linha.startswith("fonte:"):
                url = linha[6:].strip()
                if (
                    url
                    and url.startswith("http")
                    and "saimo-tv.pages.dev" not in url
                    and "/error.txt" not in url
                    and "/error/" not in url
                    and not any(d in url for d in dominios_bloqueados)
                ):
                    current.fontes.append(url)
    if current and current.fontes:
        canais.append(current)
    return canais


# ─────────────────────────── Merge de canais ──────────────────────────────
def normalizar_nome(nome: str) -> str:
    """Normaliza nome para comparação (remove acentos, caixa, espaços extras)."""
    s = unicodedata.normalize("NFD", nome.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def mesclar(existentes: list[Canal], novos: list[Canal]) -> list[Canal]:
    """
    Funde canais: novos do iptv-org + existentes locais.
    Canais com mesmo nome normalizado têm suas fontes combinadas (sem duplicatas).
    """
    por_nome: dict[str, Canal] = {}

    # Primeiro: adiciona existentes (prioridade)
    for c in existentes:
        chave = normalizar_nome(c.nome)
        if chave not in por_nome:
            por_nome[chave] = Canal(
                nome=c.nome, logo=c.logo, categoria=c.categoria,
                pais=c.pais, adulto=c.adulto,
            )
        canal = por_nome[chave]
        for f in c.fontes:
            if f not in canal.fontes:
                canal.fontes.append(f)

    # Depois: adiciona novos (complementam fontes se canal já existe)
    for c in novos:
        chave = normalizar_nome(c.nome)
        if chave not in por_nome:
            por_nome[chave] = Canal(
                nome=c.nome, logo=c.logo or "",
                categoria=c.categoria or "Variedades",
                pais=c.pais, adulto=c.adulto,
            )
        canal = por_nome[chave]
        # Atualiza logo se não tinha
        if not canal.logo and c.logo:
            canal.logo = c.logo
        # Atualiza categoria se estava vazia
        if not canal.categoria and c.categoria:
            canal.categoria = c.categoria
        for f in c.fontes:
            if f not in canal.fontes:
                canal.fontes.append(f)

    return list(por_nome.values())


# ─────────────────────────── Geração do catalogo.txt ──────────────────────
def gerar_catalogo(canais: list[Canal], adultos: list[Canal]) -> str:
    total = len(canais)
    hoje = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    linhas: list[str] = [
        "# PRISMA TV — LISTA DE CANAIS",
        f"# {total} canais · {hoje}",
        "#",
        "# Gerado automaticamente por sincronizar.py",
        "# Fontes: iptv-org/iptv + listas manuais em canais/manuais.txt",
        "#",
        "# Formato: uma linha por campo.",
        "#   canal:     começa um canal novo",
        "#   logo:      imagem do canal (opcional)",
        "#   categoria: seção da lista",
        "#   fonte:     URL do stream (pode repetir para múltiplas fontes)",
        "#",
        "# Linhas em branco e linhas começadas por # são ignoradas.",
        "",
    ]

    # Agrupa por categoria
    por_cat: dict[str, list[Canal]] = defaultdict(list)
    for c in sorted(canais, key=lambda x: (x.categoria or "Variedades", normalizar_nome(x.nome))):
        por_cat[c.categoria or "Variedades"].append(c)

    for cat in sorted(por_cat.keys()):
        linhas.append(f"# ── {cat} ──────────────────────────────────────────")
        for c in por_cat[cat]:
            linhas.append(f"canal: {c.nome}")
            if c.logo:
                linhas.append(f"logo: {c.logo}")
            if c.categoria:
                linhas.append(f"categoria: {c.categoria}")
            for f in c.fontes:
                linhas.append(f"fonte: {f}")
            linhas.append("")

    # Adultos em bloco separado no final
    if adultos:
        linhas.append("# ══════════════════════════════════════════════════")
        linhas.append("# ADULTOS (+18) — Categoria separada")
        linhas.append("# ══════════════════════════════════════════════════")
        for c in sorted(adultos, key=lambda x: normalizar_nome(x.nome)):
            linhas.append(f"canal: {c.nome}")
            if c.logo:
                linhas.append(f"logo: {c.logo}")
            linhas.append("categoria: Adultos")
            for f in c.fontes:
                linhas.append(f"fonte: {f}")
            linhas.append("")

    return "\n".join(linhas)


def gerar_adultos_txt(adultos: list[Canal]) -> str:
    hoje = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    linhas = [
        "# PRISMA TV — CANAIS ADULTOS (+18)",
        f"# {len(adultos)} canais · {hoje}",
        "# Arquivo gerado automaticamente por sincronizar.py",
        "",
    ]
    for c in sorted(adultos, key=lambda x: normalizar_nome(x.nome)):
        linhas.append(f"canal: {c.nome}")
        if c.logo:
            linhas.append(f"logo: {c.logo}")
        linhas.append("categoria: Adultos")
        for f in c.fontes:
            linhas.append(f"fonte: {f}")
        linhas.append("")
    return "\n".join(linhas)


def gerar_radios_txt(radios: list[Canal]) -> str:
    hoje = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    linhas = [
        "# PRISMA TV — RÁDIOS",
        f"# {len(radios)} estações · {hoje}",
        "# Gerado automaticamente por sincronizar.py",
        "",
    ]
    for c in sorted(radios, key=lambda x: normalizar_nome(x.nome)):
        linhas.append(f"canal: {c.nome}")
        if c.logo:
            linhas.append(f"logo: {c.logo}")
        linhas.append("categoria: Rádio")
        for f in c.fontes:
            linhas.append(f"fonte: {f}")
        linhas.append("")
    return "\n".join(linhas)


# ─────────────────────────── Download iptv-org ────────────────────────────
def baixar_pais(codigo: str) -> list[Canal]:
    url = f"{IPTV_ORG_BASE}/{codigo}.m3u"
    print(f"  Baixando: {url}", flush=True)
    texto = request_text(url)
    if not texto:
        print(f"  Não disponível: {codigo}", flush=True)
        return []
    canais = parse_m3u(texto, pais=codigo.upper())
    print(f"  {len(canais)} canais de {codigo.upper()}", flush=True)
    time.sleep(DELAY)
    return canais


def baixar_categoria_iptv_org(categoria: str) -> list[Canal]:
    """Baixa uma categoria específica do iptv-org (ex: news, sports)."""
    # iptv-org organiza por categoria em /categories/
    cat_slug = categoria.lower().replace(" ", "_").replace("ç", "c").replace("ã", "a")
    url = f"https://raw.githubusercontent.com/iptv-org/iptv/master/streams/{cat_slug}.m3u"
    texto = request_text(url)
    if not texto:
        return []
    canais = parse_m3u(texto)
    time.sleep(DELAY)
    return canais


def baixar_radios_iptv_org() -> list[Canal]:
    """Baixa a lista de rádios do iptv-org."""
    # iptv-org tem um repositório separado: iptv-org/streams
    url = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/br.m3u"
    texto = request_text(url)
    if not texto:
        return []
    # Filtra apenas canais de rádio (grupo "Radio" ou nome contém "radio/rádio")
    todos = parse_m3u(texto, pais="BR")
    radios = [c for c in todos if "radio" in normalizar_nome(c.nome)
              or "radio" in (c.categoria or "").lower()]
    return radios


# ─────────────────────────── Main ─────────────────────────────────────────
def sincronizar_canais() -> None:
    print("\n== Sincronizando Canais ==", flush=True)
    target = ROOT / "canais"
    target.mkdir(parents=True, exist_ok=True)

    todos_canais: list[Canal] = []

    # 1. Países prioritários (BR, PT, AO, MZ)
    print("\n-- Países prioritários --", flush=True)
    for codigo in PRIORITY_COUNTRIES:
        canais = baixar_pais(codigo)
        todos_canais.extend(canais)

    # 2. Países extras (internacionais)
    print("\n-- Países internacionais --", flush=True)
    for codigo in EXTRA_COUNTRIES:
        canais = baixar_pais(codigo)
        todos_canais.extend(canais)

    # 3. Manuais do usuário
    print("\n-- Canais Manuais --", flush=True)
    manuais = ler_manuais_canais()
    print(f"  {len(manuais)} canais manuais carregados", flush=True)

    # 4. Preserva canais existentes (sem fontes Saimo)
    print("\n-- Canais Existentes (preservando) --", flush=True)
    existentes = ler_catalogo_existente()
    existentes = [c for c in existentes if c.fontes]  # apenas com fontes válidas
    print(f"  {len(existentes)} canais existentes preservados", flush=True)

    # 5. Separa adultos
    adultos = [c for c in todos_canais if c.adulto]
    normais = [c for c in todos_canais if not c.adulto]

    # 6. Funde todos
    print("\n-- Mesclando --", flush=True)
    # Prioridade: manuais > existentes > iptv-org
    mesclados = mesclar(normais, manuais + existentes)
    # Remove canais sem fontes
    mesclados = [c for c in mesclados if c.fontes]
    print(f"  Total após merge: {len(mesclados)} canais normais, {len(adultos)} adultos", flush=True)

    # 7. Validação de segurança e preservação de backup
    print("\n-- Salvando arquivos --", flush=True)
    if len(mesclados) < 50:
        print(f"  ALERTA: Poucos canais válidos ({len(mesclados)}). Operação abortada para segurança.", file=sys.stderr)
        return

    catalogo_path = target / "catalogo.txt"
    if catalogo_path.exists():
        backup_path = catalogo_path.with_suffix(".txt.bak")
        shutil.copy2(catalogo_path, backup_path)
        print(f"  Backup preservado: {backup_path.name}", flush=True)

    # catalogo.txt
    catalogo_txt = gerar_catalogo(mesclados, adultos)
    catalogo_path.write_text(catalogo_txt, encoding="utf-8")
    print(f"  Salvo: canais/catalogo.txt ({len(mesclados)} canais)", flush=True)

    # canais.txt (cópia do catálogo — alguns players preferem esse nome)
    (target / "canais.txt").write_text(catalogo_txt, encoding="utf-8")
    print("  Salvo: canais/canais.txt", flush=True)

    # adultos.txt
    if adultos:
        (target / "adultos.txt").write_text(gerar_adultos_txt(adultos), encoding="utf-8")
        print(f"  Salvo: canais/adultos.txt ({len(adultos)} canais adultos)", flush=True)

    # radios.txt
    radios = baixar_radios_iptv_org()
    if radios:
        (target / "radios.txt").write_text(gerar_radios_txt(radios), encoding="utf-8")
        print(f"  Salvo: canais/radios.txt ({len(radios)} rádios)", flush=True)

    # 8. Sincronização de playlists M3U (lista.m3u, canais.m3u, lista-web.m3u)
    try:
        import agregar_fontes
        print("\n-- Atualizando Playlists M3U e Lista Web --", flush=True)
        agregar_fontes.executar_agregacao()
    except Exception as exc:
        print(f"  Aviso ao sincronizar playlists M3U: {exc}", flush=True)


def criar_manuais_filmes_se_nao_existir() -> None:
    """Cria arquivo de filmes manuais de exemplo se não existir."""
    path = ROOT / "filmes" / "manuais-filmes.txt"
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Filmes e Séries Manuais Prisma TV\n"
        "# Formato: Título TAB dub=url_dublado TAB leg=url_legendado\n"
        "# Exemplo:\n"
        "# Meu Filme\tdub=https://link-dublado.m3u8\tleg=https://link-legendado.m3u8\n"
        "# Apenas dub:\n"
        "# Meu Outro Filme\tdub=https://link.mp4\n",
        encoding="utf-8",
    )
    print("  Criado: filmes/manuais-filmes.txt (adicione seus filmes aqui)", flush=True)


def main() -> int:
    print("=" * 60, flush=True)
    print("Prisma TV — Sincronização Independente v2.0", flush=True)
    print(f"Início: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print("=" * 60, flush=True)

    falhas: list[str] = []

    # Canais
    try:
        sincronizar_canais()
    except Exception as exc:
        print(f"ERRO nos canais: {exc}", file=sys.stderr, flush=True)
        falhas.append("Canais")

    # Filmes (apenas cria arquivo de manuais se não existir; não apaga nada)
    try:
        print("\n== Filmes e Séries ==", flush=True)
        criar_manuais_filmes_se_nao_existir()
        total_filmes = len(list((ROOT / "filmes").glob("filmes-*.txt")))
        total_series = len(list((ROOT / "filmes").glob("series-*.txt")))
        print(f"  {total_filmes} arquivos de filmes, {total_series} partes de séries preservados", flush=True)
    except Exception as exc:
        print(f"ERRO nos filmes: {exc}", file=sys.stderr, flush=True)
        falhas.append("Filmes")

    print("\n" + "=" * 60, flush=True)
    if falhas:
        print(f"Concluído COM ERROS: {', '.join(falhas)}", file=sys.stderr, flush=True)
        return 1
    print("Sincronização concluída com sucesso!", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
