# Fontes de canais — Prisma TV

Atualizado em 17/11/2026.

## Regra de publicação

O Prisma TV separa duas perguntas diferentes:

1. O stream está tecnicamente acessível? O auditor verifica manifesto HLS e o primeiro segmento de mídia, ou a assinatura MPEG-TS.
2. A fonte tem uma política de inclusão oficial suficientemente documentada? Só canais vindos de fontes curadas com critérios explícitos entram em auditada.m3u.

A aprovação técnica, isoladamente, não prova titularidade nem autorização para redistribuição. A playlist usada pelo player recebe apenas streams online das fontes marcadas como official_curated. As fontes de descoberta continuam sendo analisadas, mas aparecem em auditoria.json, no campo review_candidates, e não são exportadas para o player.

## Fontes publicáveis

### 1. Doubo Public Channel Directory

- Repositório: https://github.com/streamline-iptv/iptv-playlists
- Feed Brasil: https://raw.githubusercontent.com/streamline-iptv/iptv-playlists/dist/countries/br.m3u
- Política: https://github.com/streamline-iptv/iptv-playlists/blob/main/POLICY.md
- Licença dos dados: CC BY 4.0; atribuição: “Doubo Public Channel Directory” com link para o repositório.
- Critérios declarados: domínio do próprio broadcaster ou CDN/plataforma gratuita em allowlist; exclusão de canais pagos, adultos, fechados, hosts não confiáveis, blocklist e takedowns; verificação diária até o primeiro segmento.
- Filtro local: somente tvg-country BR; URLs assinadas ou com credenciais são descartadas para não armazenar tokens temporários.

### 2. Nexonic IPTV — tier oficial

- Repositório: https://github.com/Shahrukhalid/nexonic-iptv
- Feed Brasil: https://raw.githubusercontent.com/Shahrukhalid/nexonic-iptv/main/playlists/countries/br.m3u
- Política de origem: https://github.com/Shahrukhalid/nexonic-iptv/blob/main/docs/SOURCE_POLICY.md
- Licença dos dados: CC0.
- Critérios declarados para o tier oficial: evidência de que o broadcaster ou órgão público oferece o stream gratuitamente; rejeição de restreams, agregadores, URLs com tokens, DRM, canais pagos/premium e canais com exigência de headers especiais.
- Filtro local: país BR e somente entradas sem x-tier=community (ou explicitamente x-tier=official). O repositório diferencia oficialmente os tiers; o tier comunitário não é promovido automaticamente.

## Fontes mantidas apenas para descoberta

Estas listas podem ajudar a encontrar nomes e endpoints, mas a disponibilidade pública ou a licença do arquivo M3U não demonstram, por si, que cada transmissão pode ser republicada. Elas são auditadas para diagnóstico, porém seus resultados não entram em auditada.m3u automaticamente.

- iptv-org Brasil — https://github.com/iptv-org/iptv
- CatTV Playlist Brasil — https://github.com/SamuelSantos-R/cattv-playlist
- IPTV-com Brasil — https://github.com/iptv-com/iptv
- FreeCastHub — https://github.com/freecasthub/public-iptv

## Repositórios analisados e não importados como feed automático

- Free-TV/IPTV — https://github.com/Free-TV/IPTV. Tem uma filosofia de qualidade e canais gratuitos, além de uma lista brasileira. Não foi conectado como feed porque não foi identificada uma licença explícita para redistribuir os dados do catálogo; pode ser usado como referência para pesquisar a página oficial de um broadcaster, não como autorização automática para copiar streams.
- biskyt/legalFreeIPTVplaylist — https://github.com/biskyt/legalFreeIPTVplaylist. Tem um modelo de evidência particularmente rigoroso: os canais ao vivo são aceitos somente quando há permissão/termos do titular e a página oficial publica o stream. O feed ao vivo examinado contém VOA Persian, VOA Chinese e District of Columbia Network, sem uma lista brasileira útil; por isso não foi conectado ao catálogo BR.

## Limitações e atribuição

- O repositório Doubo licencia sua seleção/organização de links sob CC BY 4.0; essa licença não transfere direitos sobre os sinais de TV.
- A licença CC0 do catálogo Nexonic também não transfere direitos sobre o conteúdo audiovisual.
- Geo-restrições não são contornadas. URLs com JWT, token, assinatura, expiração ou credenciais não são armazenadas.
- Um primeiro segmento válido não garante estabilidade, decodificação prolongada nem reprodução em todos os dispositivos.
- Qualquer solicitação de remoção ou evidência de falta de autorização deve levar à retirada do canal e à revisão da fonte.
