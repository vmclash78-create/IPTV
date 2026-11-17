# Auditoria automatizada de canais publicos

O script \`scripts/auditar_canais.py\` agrega playlists publicas de canais gratuitos
e gera uma lista separada para o Prisma TV.

## Fontes configuradas

- iptv-org — playlist Brasil
- CatTV Playlist — playlist Brasil
- IPTV-com — lista Brasil

A lista original do catálogo não é sobrescrita. Fontes privadas, links de
assinantes e transmissões pagas sem autorização não são importados por este
processo.

## Arquivos gerados

- \`canais/auditada.m3u\`: somente URLs aprovadas na checagem técnica.
- \`canais/auditoria.json\`: resultado por URL, latência, fonte e motivo.
- \`relatorio_auditoria.md\`: resumo legível e lista de falhas.

## Critério de aprovação

Para HLS, o verificador baixa o manifesto e tenta obter o primeiro segmento.
Para MPEG-TS direto, procura a assinatura TS em mais de um pacote. Um HTTP 200
isolado não é suficiente.

Isso é um health check de disponibilidade, não uma garantia de reprodução
contínua: DRM, geobloqueio, cabeçalhos específicos, expiração de token,
instabilidade posterior e incompatibilidade de codec podem impedir a reprodução.

## Execução manual

\`\`\`bash
python3 scripts/auditar_canais.py
\`\`\`

O workflow \`Auditoria publica de canais\` também executa diariamente às 04:30 UTC
e pode ser iniciado manualmente na aba Actions do GitHub.
