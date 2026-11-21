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
- `.github/workflows/` — Workflows do GitHub Actions para sincronização diária via cron.

## 🎬 Lista de filmes em M3U

O arquivo [`filmes/filmes-publicos.m3u`](filmes/filmes-publicos.m3u) é uma lista separada de filmes sob demanda. Ela é atualizada pelo workflow diário e não substitui o catálogo principal.

- **Link para importar em um player compatível:** [abrir a M3U](https://raw.githubusercontent.com/vmclash78-create/IPTV/main/filmes/filmes-publicos.m3u)
- **Fonte e créditos:** [legalFreeIPTVplaylist](https://github.com/biskyt/legalFreeIPTVplaylist) publica os links e os motivos/licenças de cada entrada; os vídeos continuam hospedados pelas fontes originais.
- **Atualização:** diariamente às 04:00 UTC (01:00 em Hidrolândia, CE), junto da sincronização existente.
- **Como usar no PrismaPlayer:** em *Ajustes → Minhas listas*, adicione o link acima. Outros apps/sites só mostrarão os filmes se aceitarem listas M3U externas.

A lista combina obras de domínio público e obras com licenças abertas conforme os créditos da fonte. A própria fonte informa que algumas classificações de domínio público se baseiam na legislação dos Estados Unidos; a situação pode variar no Brasil. Consulte os créditos e as condições de cada obra antes de redistribuí-la. Este repositório não hospeda os vídeos.

## ⚙️ Testador de Saúde dos Canais

Para auditar o status de todos os canais ao vivo em paralelo:

```bash
python testar_canais.py
```

O relatório detalhado com tempo de resposta e canais online/offline é gerado em `relatorio_canais.md`.

## 🔒 Segurança

Mantenha este repositório privado para preservar os endpoints e configurações.
