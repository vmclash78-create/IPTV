#!/usr/bin/env python3
"""Testador e Validador Completo de Canais IPTV (Health Check Avançado) - Prisma TV.

Realiza auditoria e health check automatizado em paralelo:
- Validação HTTP / HTTPS com tratamento de redirecionamentos
- Verificação de DNS, timeouts e erros de SSL
- Detecção de URLs de erro (/error.txt, links quebrados por scrapers, s25-cloudfront)
- Detecção de respostas HTML em vez de streams de vídeo
- Identificação de duplicatas
- Análise de manifests HLS para identificação de codecs (H.264/AVC vs HEVC/H.265)
- Classificação de compatibilidade Web, iPhone e Safari
- Atualização do registro de fontes desativadas (fontes-desativadas.json)
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
CANAIS_DIR = ROOT / "canais"
CATALOGO_FILE = CANAIS_DIR / "catalogo.txt"
MANUAIS_FILE = CANAIS_DIR / "manuais.txt"
FONTES_DESATIVADAS_FILE = CANAIS_DIR / "fontes-desativadas.json"

DEFAULT_TIMEOUT = 8
DEFAULT_WORKERS = 20
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Contexto SSL permissivo para testes
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


@dataclass
class FonteInfo:
    canal: str
    categoria: str
    url: str
    referer: Optional[str] = None
    agente: Optional[str] = None
    is_https: bool = False
    status: str = "PENDENTE"  # ONLINE, OFFLINE, BLOQUEADO, TIMEOUT, DNS_FAIL, SSL_ERROR, INVALIDO_HTML, ERRO
    codigo_http: int = 0
    tempo_ms: int = 0
    codec_video: str = "desconhecido"  # h264, hevc, desconhecido
    codec_audio: str = "desconhecido"  # aac, mp3, desconhecido
    compativel_safari: bool = False
    motivo_incompatibilidade: str = ""
    detalhes_erro: str = ""


def extrair_fontes_catalogo(caminho: Path) -> list[FonteInfo]:
    fontes: list[FonteInfo] = []
    if not caminho.exists():
        return fontes

    linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines()
    canal_atual = "Desconhecido"
    categoria_atual = "Geral"
    referer_atual: Optional[str] = None
    agente_atual: Optional[str] = None

    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("canal:"):
            canal_atual = linha[6:].strip()
            categoria_atual = "Geral"
            referer_atual = None
            agente_atual = None
        elif linha.startswith("categoria:"):
            categoria_atual = linha[10:].strip()
        elif linha.startswith("referer:"):
            referer_atual = linha[8:].strip()
        elif linha.startswith("agente:"):
            agente_atual = linha[7:].strip()
        elif linha.startswith("fonte:"):
            url = linha[6:].strip()
            if url.startswith("http"):
                fontes.append(
                    FonteInfo(
                        canal=canal_atual,
                        categoria=categoria_atual,
                        url=url,
                        referer=referer_atual,
                        agente=agente_atual,
                        is_https=url.startswith("https://"),
                    )
                )
    return fontes


def extrair_fontes_manuais(caminho: Path) -> list[FonteInfo]:
    fontes: list[FonteInfo] = []
    if not caminho.exists():
        return fontes

    linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines()
    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        partes = linha.split("|")
        if len(partes) >= 4:
            nome, _, cat, url = partes[0].strip(), partes[1].strip(), partes[2].strip(), partes[3].strip()
            if url.startswith("http"):
                fontes.append(
                    FonteInfo(
                        canal=nome,
                        categoria=cat,
                        url=url,
                        is_https=url.startswith("https://"),
                    )
                )
    return fontes


def carregar_dominios_desativados() -> set[str]:
    if FONTES_DESATIVADAS_FILE.exists():
        try:
            dados = json.loads(FONTES_DESATIVADAS_FILE.read_text(encoding="utf-8"))
            return set(dados.get("desativados", []))
        except Exception:
            pass
    return set()


def testar_fonte(info: FonteInfo, timeout: int = DEFAULT_TIMEOUT) -> FonteInfo:
    url = info.url

    # Pré-validação rápida de URLs de erro conhecidas
    if "/error.txt" in url or "/error/" in url:
        info.status = "INVALIDO"
        info.codigo_http = 0
        info.detalhes_erro = "URL de erro (/error.txt)"
        info.motivo_incompatibilidade = "Link gerado por erro de scraper"
        return info

    if "s25-cloudfront-net.lat" in url:
        info.status = "INVALIDO"
        info.detalhes_erro = "Domínio de erro scraper (s25-cloudfront-net.lat)"
        info.motivo_incompatibilidade = "Domínio inválido"
        return info

    headers = {
        "User-Agent": info.agente or DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Connection": "close",
    }
    if info.referer:
        headers["Referer"] = info.referer

    req = urllib.request.Request(url, headers=headers)
    inicio = time.time()

    try:
        handler = urllib.request.HTTPSHandler(context=SSL_CTX)
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=timeout) as resp:
            duracao = int((time.time() - inicio) * 1000)
            info.tempo_ms = duracao
            info.codigo_http = resp.status
            ct = resp.headers.get("Content-Type", "")

            # Resposta HTML (geralmente página de erro de servidor/proxy)
            if "text/html" in ct.lower():
                info.status = "INVALIDO_HTML"
                info.detalhes_erro = f"Resposta HTML ({ct})"
                info.motivo_incompatibilidade = "Página web em vez de fluxo de vídeo"
                return info

            if 200 <= resp.status < 400:
                info.status = "ONLINE"
                # Analisa o conteúdo HLS se for playlist
                try:
                    conteudo = resp.read(8192).decode("utf-8", errors="replace")
                    # Detecta vídeo codec
                    if "avc1" in conteudo or "avc" in conteudo.lower():
                        info.codec_video = "h264"
                    elif "hev1" in conteudo or "hvc1" in conteudo:
                        info.codec_video = "hevc"

                    # Detecta áudio codec
                    if "mp4a.40" in conteudo or "aac" in conteudo.lower():
                        info.codec_audio = "aac"
                    elif "mp3" in conteudo.lower():
                        info.codec_audio = "mp3"

                    # Avaliação de compatibilidade Safari / iPhone
                    # Safari/iOS suporta HLS H.264 nativamente.
                    # HEVC em MPEG-TS (.ts) causa tela preta no iOS/Safari (apenas fMP4 é suportado).
                    if info.codec_video == "hevc":
                        info.compativel_safari = False
                        info.motivo_incompatibilidade = (
                            "HEVC/H.265 em MPEG-TS causa tela preta no Safari/iOS"
                        )
                    elif info.codec_video == "h264":
                        info.compativel_safari = True
                    elif "#EXTM3U" in conteudo:
                        # HLS padrão sem tag explícita de codec
                        info.codec_video = "desconhecido"
                        info.compativel_safari = True  # Maioria dos HLS sem tag é AVC/AAC padrão
                    else:
                        info.codec_video = "desconhecido"
                except Exception:
                    pass
            else:
                info.status = "OFFLINE"
                info.detalhes_erro = f"HTTP {resp.status}"

    except urllib.error.HTTPError as exc:
        duracao = int((time.time() - inicio) * 1000)
        info.tempo_ms = duracao
        info.codigo_http = exc.code
        if exc.code in (401, 403):
            info.status = "BLOQUEADO"
            info.detalhes_erro = f"HTTP {exc.code} (Autenticação/Proibido)"
            info.motivo_incompatibilidade = "Acesso negado ou token expirado"
        elif exc.code in (404, 410):
            info.status = "OFFLINE"
            info.detalhes_erro = f"HTTP {exc.code} (Não encontrado)"
            info.motivo_incompatibilidade = "Stream inexistente ou removido"
        else:
            info.status = "OFFLINE"
            info.detalhes_erro = f"HTTP {exc.code}"

    except Exception as exc:
        duracao = int((time.time() - inicio) * 1000)
        info.tempo_ms = duracao
        msg = str(exc).lower()
        if "timed out" in msg or "timeout" in msg:
            info.status = "TIMEOUT"
            info.detalhes_erro = f"Timeout ({timeout}s)"
        elif "getaddrinfo" in msg or "nodename" in msg or "name or service not known" in msg:
            info.status = "DNS_FAIL"
            info.detalhes_erro = "Falha permanente de DNS (domínio inexistente)"
            info.motivo_incompatibilidade = "Host inalcançável"
        elif "ssl" in msg or "certificate" in msg:
            info.status = "SSL_ERROR"
            info.detalhes_erro = "Erro de certificado SSL"
        else:
            info.status = "ERRO"
            info.detalhes_erro = str(exc)[:80]

    return info


def executar_auditoria_completa(
    timeout: int = DEFAULT_TIMEOUT,
    workers: int = DEFAULT_WORKERS,
    salvar_json: bool = True,
) -> dict:
    print("=" * 65)
    print("Prisma TV — Auditoria e Health Check Completo de Streams")
    print(f"Data/Hora: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    fontes_catalogo = extrair_fontes_catalogo(CATALOGO_FILE)
    fontes_manuais = extrair_fontes_manuais(MANUAIS_FILE)
    dominios_mortos = carregar_dominios_desativados()

    todas_fontes = fontes_catalogo + fontes_manuais
    print(f"Total de fontes encontradas: {len(todas_fontes)}")
    print(f"  - Catálogo: {len(fontes_catalogo)}")
    print(f"  - Manuais: {len(fontes_manuais)}")

    # 1. Identificar duplicatas
    urls_unicas: dict[str, FonteInfo] = {}
    duplicatas: list[str] = []
    for f in todas_fontes:
        if f.url in urls_unicas:
            duplicatas.append(f.url)
        else:
            urls_unicas[f.url] = f

    print(f"URLs duplicadas identificadas: {len(duplicatas)}")

    # 2. Identificar URLs de erro (/error.txt) e domínios desativados
    urls_erro = [f for f in urls_unicas.values() if "/error.txt" in f.url or "s25-cloudfront-net.lat" in f.url]
    print(f"URLs com /error.txt ou s25-cloudfront: {len(urls_erro)}")

    # Filtrar fontes para teste
    testar_lista = list(urls_unicas.values())
    print(f"Executando Health Check em {len(testar_lista)} URLs únicas com {workers} threads...")

    inicio_total = time.time()
    resultados: list[FonteInfo] = []
    concluidos = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futuros = {executor.submit(testar_fonte, f, timeout): f for f in testar_lista}
        for futuro in concurrent.futures.as_completed(futuros):
            res = futuro.result()
            resultados.append(res)
            concluidos += 1
            if concluidos % 50 == 0 or concluidos == len(testar_lista):
                on = sum(1 for r in resultados if r.status == "ONLINE")
                print(f"  [{concluidos}/{len(testar_lista)}] {concluidos/len(testar_lista)*100:.0f}% | Online: {on} | Tempo: {int(time.time()-inicio_total)}s")

    duracao_total = round(time.time() - inicio_total, 1)

    # 3. Consolidação dos resultados
    online = [r for r in resultados if r.status == "ONLINE"]
    online_https = [r for r in online if r.is_https]
    h264_online = [r for r in online if r.codec_video == "h264"]
    hevc_online = [r for r in online if r.codec_video == "hevc"]
    safari_comp = [r for r in online if r.compativel_safari]

    offline = [r for r in resultados if r.status == "OFFLINE"]
    bloqueados = [r for r in resultados if r.status == "BLOQUEADO"]
    timeouts = [r for r in resultados if r.status == "TIMEOUT"]
    dns_fails = [r for r in resultados if r.status == "DNS_FAIL"]
    ssl_errors = [r for r in resultados if r.status == "SSL_ERROR"]
    invalidos = [r for r in resultados if r.status in ("INVALIDO", "INVALIDO_HTML")]
    outros = [r for r in resultados if r.status == "ERRO"]

    # Extrai novos domínios mortos de DNS_FAIL
    novos_dominios_mortos = set()
    for r in dns_fails:
        m = re.search(r"https?://([^/:]+)", r.url)
        if m:
            novos_dominios_mortos.add(m.group(1).lower())
    for r in urls_erro:
        m = re.search(r"https?://([^/:]+)", r.url)
        if m:
            novos_dominios_mortos.add(m.group(1).lower())

    print("\n" + "=" * 65)
    print("SUMÁRIO DA AUDITORIA")
    print("=" * 65)
    print(f"Tempo total de execução: {duracao_total}s")
    print(f"Total de fontes auditadas: {len(resultados)}")
    print(f"  ✅ Online: {len(online)} ({len(online)/len(resultados)*100:.1f}%)")
    print(f"     - HTTPS: {len(online_https)}")
    print(f"     - H.264/AVC confirmado: {len(h264_online)}")
    print(f"     - HEVC/H.265 (incompatível Safari/iOS): {len(hevc_online)}")
    print(f"     - Compatíveis com Safari/iPhone: {len(safari_comp)}")
    print(f"  ❌ Offline (404/410): {len(offline)}")
    print(f"  🔒 Bloqueados / Privados (401/403): {len(bloqueados)}")
    print(f"  ⏱️ Timeouts: {len(timeouts)}")
    print(f"  🌐 Falha permanente de DNS: {len(dns_fails)}")
    print(f"  🔐 Erros de certificado SSL: {len(ssl_errors)}")
    print(f"  📄 Inválidos / Erro de Scraper (/error.txt ou HTML): {len(invalidos)}")
    print(f"  ⚠️ Outros erros: {len(outros)}")
    print(f"  📋 Duplicatas encontradas: {len(duplicatas)}")

    resumo = {
        "data_verificacao": datetime.now(timezone.utc).isoformat(),
        "duracao_segundos": duracao_total,
        "totais": {
            "total_auditado": len(resultados),
            "online": len(online),
            "online_https": len(online_https),
            "h264_confirmado": len(h264_online),
            "hevc_confirmado": len(hevc_online),
            "compativel_safari_iphone": len(safari_comp),
            "offline": len(offline),
            "bloqueado": len(bloqueados),
            "timeout": len(timeouts),
            "dns_fail": len(dns_fails),
            "ssl_error": len(ssl_errors),
            "invalido_erro_txt": len(invalidos),
            "duplicatas": len(duplicatas),
        },
        "novos_dominios_mortos": sorted(list(novos_dominios_mortos)),
        "fontes_online": [asdict(r) for r in online],
        "fontes_inativas": [asdict(r) for r in offline + bloqueados + timeouts + dns_fails + ssl_errors + invalidos],
    }

    if salvar_json:
        # Atualiza fontes-desativadas.json preservando e consolidando
        todos_desativados = dominios_mortos.union(novos_dominios_mortos)
        historico_desativados = []
        for r in offline + bloqueados + dns_fails + invalidos:
            historico_desativados.append(
                {
                    "canal": r.canal,
                    "url": r.url,
                    "motivo": r.detalhes_erro or r.status,
                    "status_http": r.codigo_http,
                    "data_verificacao": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "origem": "catalogo/manuais",
                }
            )

        FONTES_DESATIVADAS_FILE.write_text(
            json.dumps(
                {
                    "ultima_atualizacao": datetime.now(timezone.utc).isoformat(),
                    "total_dominios_desativados": len(todos_desativados),
                    "desativados": sorted(list(todos_desativados)),
                    "historico": historico_desativados[:500],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Registro de fontes desativadas atualizado: {FONTES_DESATIVADAS_FILE}")

        # Salva relatório completo
        relatorio_path = CANAIS_DIR / "relatorio_saude.json"
        relatorio_path.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Relatório de saúde salvo em: {relatorio_path}")

    return resumo


if __name__ == "__main__":
    executar_auditoria_completa()
