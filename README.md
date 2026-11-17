# 📺 Prisma TV

Plataforma nativa e independente de streaming IPTV e VOD sob demanda para macOS e iOS, com proxy local de alta velocidade, remuxagem em tempo real, aceleração de hardware e catálogos descentralizados.

## 🌟 Recursos Principais

- **Reprodução Nativa (AVFoundation / SwiftUI)**: Aceleração total via Metal e GPU Apple Silicon/Intel.
- **Proxy Local Inteligente (`ProxyServer.swift`)**: Intercepta e injeta cabeçalhos (Referer, User-Agent, Tokens) automaticamente sem bloqueios.
- **Remuxer em Tempo Real**: Converte contêineres `.mkv`, `.ts` e codecs de áudio em tempo real para reprodução nativa sem recodificar o vídeo.
- **Catálogo Descentralizado**: Filmes, séries e canais ao vivo organizados e carregados instantaneamente direto deste repositório.
- **Suporte Multi-Fonte**: Se um link de canal cair, o player pula automaticamente para a fonte reserva sem tela preta.
- **Multi-Tela**: Assista múltiplos canais simultaneamente em grade.
- **Torrents & Debrid**: Suporte integrado a Real-Debrid, Torbox, AllDebrid, Premiumize e motor torrent embutido (Rust).
- **Guia de Programação (EPG)**: Programação de TV ao vivo integrada diretamente no player.

## 📁 Estrutura do Repositório

- `PrismaPlayer/` — Código-fonte da aplicação nativa **Prisma TV** (Swift / SwiftUI).
- `canais/` — Catálogo e metadados de canais ao vivo, guia EPG e rádios.
- `filmes/` — Catálogos particionados de filmes, séries, episódios, sinopses e capas.
- `clonar.py` — Automação de espelhamento e atualização dos catálogos.
- `testar_canais.py` — Testador e auditor de saúde dos canais (Health Check em tempo real).
- `.github/workflows/` — Workflows do GitHub Actions para sincronização diária agendada via cron.

## ⚙️ Testador de Saúde dos Canais

Para auditar o status de todos os canais ao vivo em paralelo:

```bash
python testar_canais.py
```

O relatório detalhado com tempo de resposta e canais online/offline é gerado em `relatorio_canais.md`.

## Fontes e auditoria de canais

O catalogo automatico separa disponibilidade tecnica de procedencia/autorizacao. Somente listas com politica oficial de inclusao revisada alimentam o arquivo canais/auditada.m3u; listas comunitarias ou sem evidencia individual ficam em canais/auditoria.json como candidatos para revisao.

Consulte canais/fontes.md para criterios, fontes aprovadas, fontes em observacao e atribuicoes. A auditoria e executada a cada seis horas pelo GitHub Actions.

## 🔒 Segurança

Mantenha este repositório privado para preservar os endpoints e configurações.
