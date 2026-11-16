#!/usr/bin/env python3
"""Testador e Validador de Canais IPTV (Health Check).

Analisa os links de canais (tanto em canais.txt quanto em catalogo.txt),
testa a conectividade e disponibilidade em paralelo e gera relatórios completos.
"""
from __future__ import annotations

import concurrent.futures
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
CANAIS_DIR = ROOT / "canais"
TIMEOUT = 6
MAX_WORKERS = 25
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


@dataclass
class CanalTeste:
    nome: str
    categoria: str
    url: str
    referer: Optional[str] = None
    agente: Optional[str] = None
    status: str = "PENDENTE"
    codigo_http: int = 0
    tempo_ms: int = 0
    erro: str = ""


def extrair_canais_m3u(arquivo: Path) -> list[CanalTeste]:
    canais: list[CanalTeste] = []
    if not arquivo.exists():
        return canais

    linhas = arquivo.read_text(encoding="utf-8", errors="ignore").splitlines()
    canal_atual = ""
    categoria_atual = "Geral"

    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue
        if linha.startswith("#EXTINF:"):
            # Extrai nome após a última vírgula
            partes = linha.split(",", 1)
            canal_atual = partes[1].strip() if len(partes) > 1 else "Sem Nome"
            # Extrai group-title se existir
            match_grupo = re.search(r'group-title="([^"]+)"', linha)
            if match_grupo:
                categoria_atual = match_grupo.group(1).strip()
            else:
                categoria_atual = "Geral"
        elif not linha.startswith("#") and (linha.startswith("http://") or linha.startswith("https://")):
            canais.append(CanalTeste(
                nome=canal_atual,
                categoria=categoria_atual,
                url=linha,
            ))
            canal_atual = ""
    return canais


def extrair_canais_catalogo(arquivo: Path) -> list[CanalTeste]:
    canais: list[CanalTeste] = []
    if not arquivo.exists():
        return canais

    linhas = arquivo.read_text(encoding="utf-8", errors="ignore").splitlines()
    canal_atual = "Desconhecido"
    categoria_atual = "Geral"
    fonte_atual = ""
    referer_atual: Optional[str] = None
    agente_atual: Optional[str] = None

    def salvar_fonte():
        nonlocal fonte_atual, referer_atual, agente_atual
        if fonte_atual:
            canais.append(CanalTeste(
                nome=canal_atual,
                categoria=categoria_atual,
                url=fonte_atual,
                referer=referer_atual,
                agente=agente_atual
            ))
            fonte_atual = ""
            referer_atual = None
            agente_atual = None

    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("canal:"):
            salvar_fonte()
            canal_atual = linha[6:].strip()
            categoria_atual = "Geral"
        elif linha.startswith("categoria:"):
            categoria_atual = linha[10:].strip()
        elif linha.startswith("fonte:"):
            salvar_fonte()
            fonte_atual = linha[6:].strip()
        elif linha.startswith("referer:"):
            referer_atual = linha[8:].strip()
        elif linha.startswith("agente:"):
            agente_atual = linha[7:].strip()

    salvar_fonte()
    return canais


def testar_stream(canal: CanalTeste) -> CanalTeste:
    headers = {
        "User-Agent": canal.agente or DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Connection": "close",
    }
    if canal.referer:
        headers["Referer"] = canal.referer

    req = urllib.request.Request(canal.url, headers=headers)
    inicio = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            duracao = int((time.time() - inicio) * 1000)
            canal.codigo_http = resp.status
            canal.tempo_ms = duracao
            if 200 <= resp.status < 400:
                canal.status = "ONLINE"
            else:
                canal.status = "OFFLINE"
    except urllib.error.HTTPError as exc:
        duracao = int((time.time() - inicio) * 1000)
        canal.codigo_http = exc.code
        canal.tempo_ms = duracao
        if exc.code in (401, 403):
            canal.status = "BLOQUEADO"
            canal.erro = f"HTTP {exc.code} (Autenticação / Token)"
        elif exc.code in (404, 410):
            canal.status = "OFFLINE"
            canal.erro = f"HTTP {exc.code} (Não Encontrado)"
        else:
            canal.status = "OFFLINE"
            canal.erro = f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        duracao = int((time.time() - inicio) * 1000)
        canal.tempo_ms = duracao
        canal.status = "INACESSIVEL"
        motivo = str(exc)
        if "timed out" in motivo.lower():
            canal.erro = "Timeout (Servidor lento / sem resposta)"
        else:
            canal.erro = "Falha de conexão / Host indisponível"
    except Exception as exc:
        canal.status = "ERRO"
        canal.erro = str(exc)

    return canal


def executar_auditoria(limite: Optional[int] = None) -> None:
    arquivo_catalogo = CANAIS_DIR / "catalogo.txt"
    arquivo_m3u = CANAIS_DIR / "canais.txt"

    print("=" * 60)
    print("AUDITORIA DE SAÚDE DOS CANAIS IPTV (HEALTH CHECK)")
    print("=" * 60)

    canais = []
    if arquivo_catalogo.exists():
        print(f"Lendo canais de: {arquivo_catalogo.name}...")
        canais = extrair_canais_catalogo(arquivo_catalogo)
    elif arquivo_m3u.exists():
        print(f"Lendo canais de: {arquivo_m3u.name}...")
        canais = extrair_canais_m3u(arquivo_m3u)

    if not canais:
        print("Nenhum canal encontrado para testar!", file=sys.stderr)
        return

    total = len(canais)
    if limite and limite < total:
        print(f"Testando amostra de {limite} fontes (de um total de {total})...")
        canais = canais[:limite]
        total = limite
    else:
        print(f"Total de fontes a testar: {total}")

    print(f"Disparando testes em paralelo com {MAX_WORKERS} workers (timeout: {TIMEOUT}s)...\n")

    online = 0
    offline = 0
    bloqueados = 0
    inacessiveis = 0

    inicio_geral = time.time()
    resultados: list[CanalTeste] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = {executor.submit(testar_stream, c): c for c in canais}
        concluidos = 0
        for futuro in concurrent.futures.as_completed(futuros):
            res = futuro.result()
            resultados.append(res)
            concluidos += 1
            if res.status == "ONLINE":
                online += 1
                simbolo = "✅"
            elif res.status == "BLOQUEADO":
                bloqueados += 1
                simbolo = "🔒"
            elif res.status == "OFFLINE":
                offline += 1
                simbolo = "❌"
            else:
                inacessiveis += 1
                simbolo = "⚠️"

            if concluidos % 10 == 0 or concluidos == total:
                pct = (concluidos / total) * 100
                print(f"[{concluidos}/{total}] {pct:.1f}% | Online: {online} | Off: {offline} | Bloq: {bloqueados} | Inac: {inacessiveis}", flush=True)

    tempo_total = time.time() - inicio_geral
    print(f"\nTestes concluídos em {tempo_total:.2f} segundos!")
    print(f"  ✅ Online: {online} ({online/total*100:.1f}%)")
    print(f"  ❌ Offline: {offline} ({offline/total*100:.1f}%)")
    print(f"  🔒 Bloqueados: {bloqueados} ({bloqueados/total*100:.1f}%)")
    print(f"  ⚠️ Inacessíveis/Timeout: {inacessiveis} ({inacessiveis/total*100:.1f}%)")

    # Gerar relatório Markdown detalhado
    relatorio_md = ROOT / "relatorio_canais.md"
    gerar_relatorio(relatorio_md, resultados, total, online, offline, bloqueados, inacessiveis, tempo_total)
    print(f"\nRelatório completo gerado em: {relatorio_md}")


def gerar_relatorio(destino: Path, resultados: list[CanalTeste], total: int, online: int, offline: int, bloqueados: int, inacessiveis: int, tempo_total: float):
    linhas = [
        "# 📡 Relatório de Saúde dos Canais IPTV\n",
        f"**Data da verificação**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"**Total de streams testados**: {total}\n",
        f"**Tempo total de execução**: {tempo_total:.2f}s\n\n",
        "## Resumo Geral\n",
        "| Status | Quantidade | Percentual |",
        "|---|---|---|",
        f"| ✅ **Online** | {online} | {online/total*100:.1f}% |",
        f"| ❌ **Offline** | {offline} | {offline/total*100:.1f}% |",
        f"| 🔒 **Bloqueado (401/403)** | {bloqueados} | {bloqueados/total*100:.1f}% |",
        f"| ⚠️ **Inacessível / Timeout** | {inacessiveis} | {inacessiveis/total*100:.1f}% |\n",
        "## Canais Online (Respondendo OK)\n",
        "| Canal | Categoria | Tempo (ms) | Código HTTP |",
        "|---|---|---|---|",
    ]

    for c in sorted([r for r in resultados if r.status == "ONLINE"], key=lambda x: x.tempo_ms):
        linhas.append(f"| {c.nome} | {c.categoria} | {c.tempo_ms}ms | {c.codigo_http} |")

    linhas.extend([
        "\n## Canais com Falha / Fora do Ar (Necessitam Substituição)\n",
        "| Canal | Categoria | Status | Motivo |",
        "|---|---|---|---|",
    ])

    for c in [r for r in resultados if r.status != "ONLINE"]:
        linhas.append(f"| {c.nome} | {c.categoria} | {c.status} | {c.erro} |")

    destino.write_text("\n".join(linhas), encoding="utf-8")


if __name__ == "__main__":
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else None
    executar_auditoria(limite)
