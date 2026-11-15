# IPTV — espelho automatizado

Este repositório contém um processo de espelhamento das fontes autorizadas configuradas em `clonar.py`.

## Estrutura gerada

- `SaimoPlayer/` — clone do repositório Git de origem.
- `saimo-tv/` — espelho do site saimo-tv.pages.dev.
- `canais-saimo/` — espelho do site canais-saimo.pages.dev.
- `filmes-saimo/` — espelho do site filmes-saimo.pages.dev.

## Como executar

O GitHub Actions executa automaticamente:
- após um `push` na branch `main`;
- manualmente, em **Actions → Clonar tudo → Run workflow**.

O workflow baixa as fontes, atualiza as pastas e cria um commit somente quando há alterações.

## Execução local

Requisitos: Python 3, Git e GNU Wget.

```bash
python3 clonar.py
```

## Observações

O espelhamento depende de os endereços de origem permanecerem públicos e acessíveis. O Wget segue páginas e recursos encontrados no mesmo domínio; caminhos protegidos, conteúdo carregado exclusivamente por APIs ou bloqueios do servidor podem exigir regras específicas adicionais. Verifique os direitos de redistribuição e os termos aplicáveis a cada fonte antes de publicar o conteúdo espelhado.
