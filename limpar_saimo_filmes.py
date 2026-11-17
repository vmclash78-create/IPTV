#!/usr/bin/env python3
"""Remove URLs mortas de saimo-tv.pages.dev dos arquivos de filmes e séries.

Essas URLs eram as fontes de streaming do Saimo original. Desde que migramos
para fontes diretas, elas só causam falhas silenciosas (o filme tenta, não abre,
o usuário vê erro). Este script limpa somente as URLs Saimo, preservando todas
as fontes diretas (CDN, embed players, etc.).

Uso:
    python limpar_saimo_filmes.py          # dry-run (só mostra o que mudaria)
    python limpar_saimo_filmes.py --aplicar  # aplica as mudanças
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILMES_DIR = ROOT / "filmes"

# URLs que devem ser removidas (fontes que dependem do Saimo)
URLS_MORTAS = [
    "saimo-tv.pages.dev/api/stream",
    "saimo-tv.pages.dev/v1",
    "canais-saimo.pages.dev",
    "filmes-saimo.pages.dev",
]

def url_e_morta(url: str) -> bool:
    return any(morta in url for morta in URLS_MORTAS)

def limpar_linha(linha: str) -> str:
    """Remove fontes mortas de uma linha do catálogo de filmes.
    
    Formato: Título TAB dub=url1,url2,url3 TAB leg=url4,url5
    """
    if not linha.strip() or linha.startswith("#"):
        return linha
    
    partes = linha.rstrip("\n").split("\t")
    if len(partes) < 2:
        return linha
    
    novas_partes = [partes[0]]  # título sempre fica
    
    for parte in partes[1:]:
        if parte.startswith("dub=") or parte.startswith("leg="):
            prefixo = "dub=" if parte.startswith("dub=") else "leg="
            urls_originais = parte[len(prefixo):].split(",")
            urls_limpas = [u for u in urls_originais if u.strip() and not url_e_morta(u)]
            if urls_limpas:
                novas_partes.append(prefixo + ",".join(urls_limpas))
            # Se ficou vazio (só tinha URLs Saimo), não adiciona a parte
        else:
            novas_partes.append(parte)
    
    # Se sobrou só o título (sem nenhuma fonte), mantém a linha original
    # para não apagar filmes que a gente pode corrigir depois
    if len(novas_partes) < 2:
        return linha
    
    return "\t".join(novas_partes) + "\n"

def processar_arquivo(caminho: Path, aplicar: bool) -> tuple[int, int]:
    """Retorna (linhas_alteradas, urls_removidas)."""
    try:
        texto = caminho.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"  ERRO ao ler {caminho.name}: {e}")
        return 0, 0
    
    linhas = texto.splitlines(keepends=True)
    linhas_novas = []
    alteradas = 0
    urls_removidas = 0
    
    for linha in linhas:
        nova = limpar_linha(linha)
        if nova != linha:
            # Conta quantas URLs foram removidas nessa linha
            for morta in URLS_MORTAS:
                urls_removidas += linha.count(morta)
            alteradas += 1
        linhas_novas.append(nova)
    
    if alteradas > 0 and aplicar:
        caminho.write_text("".join(linhas_novas), encoding="utf-8")
    
    return alteradas, urls_removidas

def main() -> int:
    aplicar = "--aplicar" in sys.argv or "--apply" in sys.argv
    
    if not aplicar:
        print("🔍 DRY-RUN — use --aplicar para salvar as mudanças\n")
    else:
        print("✏️  APLICANDO mudanças...\n")
    
    if not FILMES_DIR.exists():
        print(f"Pasta filmes/ não encontrada em {ROOT}")
        return 1
    
    arquivos = sorted(FILMES_DIR.glob("*.txt"))
    total_linhas = 0
    total_urls = 0
    arquivos_afetados = 0
    
    for arquivo in arquivos:
        if arquivo.name.startswith("manuais"):
            continue  # pula manuais do usuário
        linhas, urls = processar_arquivo(arquivo, aplicar)
        if linhas > 0:
            arquivos_afetados += 1
            total_linhas += linhas
            total_urls += urls
            status = "✅ Salvo" if aplicar else "📋 Encontrado"
            print(f"  {status}: {arquivo.name} — {linhas} linhas, {urls} URLs Saimo removidas")
    
    print(f"\n{'='*55}")
    print(f"Total: {arquivos_afetados} arquivos, {total_linhas} linhas, {total_urls} URLs Saimo")
    
    if not aplicar and total_urls > 0:
        print(f"\nExecute com --aplicar para remover as {total_urls} URLs do Saimo.")
    elif aplicar:
        print("\n✅ Limpeza concluída! Filmes agora usam apenas fontes diretas.")
    else:
        print("\n✅ Nenhuma URL Saimo encontrada nos filmes.")
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
