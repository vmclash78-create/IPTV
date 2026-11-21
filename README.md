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

## 🎬 Listas M3U de filmes e séries abertas

As listas abaixo ficam espelhadas neste repositório. O Lovable e os players devem carregar os endereços deste repositório, não o endereço do projeto que publica a fonte original.

| Conteúdo | Arquivo no Prisma TV | URL para usar no Lovable |
| --- | --- | --- |
| Filmes clássicos e acervo aberto | [`filmes/filmes-publicos.m3u`](filmes/filmes-publicos.m3u) | https://raw.githubusercontent.com/vmclash78-create/IPTV/main/filmes/filmes-publicos.m3u |
| Filmes de domínio público/licenças abertas | [`filmes/filmes-abertos.m3u`](filmes/filmes-abertos.m3u) | https://raw.githubusercontent.com/vmclash78-create/IPTV/main/filmes/filmes-abertos.m3u |
| Séries de domínio público/licenças abertas | [`filmes/series-abertas.m3u`](filmes/series-abertas.m3u) | https://raw.githubusercontent.com/vmclash78-create/IPTV/main/filmes/series-abertas.m3u |

O workflow baixa os **índices M3U**, não os vídeos, todos os dias às 04:00 UTC (01:00 em Hidrolândia, CE). Ele preserva a última cópia válida quando a fonte fica indisponível ou falha na validação. O Lovable pode, assim, carregar as listas a partir do seu próprio GitHub. A rotina de atualização ainda consulta as fontes para receber conteúdo novo; os endereços de vídeo continuam nos servidores originais indicados em cada entrada.

A lista de filmes/séries abertos preserva `x-source` e `x-licence` e acrescenta `tvg-type` para distinguir filmes de séries em players comuns. Consulte esses campos antes de redistribuir qualquer entrada: licenças como CC BY-NC têm restrições, e classificações de domínio público feitas com base nos Estados Unidos podem não se aplicar da mesma forma no Brasil. Esta lista não é uma licença geral para redistribuir os vídeos.

- **Créditos da lista aberta:** [Nexonic IPTV](https://github.com/nexonic-technologies/nexonic-iptv), cujas playlists identificam a origem e a licença por entrada.
- **Créditos da lista de filmes públicos:** [legalFreeIPTVplaylist](https://github.com/biskyt/legalFreeIPTVplaylist) e as fontes originais indicadas nos créditos.
- **Como usar no PrismaPlayer:** em *Ajustes → Minhas listas*, adicione o link da lista desejada acima. Outros apps/sites só mostrarão o catálogo se aceitarem M3U externas.

## ⚙️ Testador de Saúde dos Canais

Para auditar o status de todos os canais ao vivo em paralelo:

```bash
python testar_canais.py
```

O relatório detalhado com tempo de resposta e canais online/offline é gerado em `relatorio_canais.md`.

## 🔒 Segurança

Mantenha este repositório privado para preservar os endpoints e configurações.
