# IPTV — espelho privado

Espelho automatizado do código-fonte SaimoPlayer e dos arquivos de catálogo configurados em `clonar.py`.

## Estrutura

- `SaimoPlayer/` — arquivos do repositório Git de origem, sem o histórico Git interno.
- `canais-saimo/` — arquivos de catálogo de canais.
- `filmes-saimo/` — índice, catálogos por letra, partições de episódios e arquivos auxiliares.
- `redeflix/` — arquivos de links auxiliares, dentro de `filmes-saimo/`.

## Execução

O GitHub Actions roda:
- manualmente em **Actions → Clonar tudo → Run workflow**;
- automaticamente após cada `push` na branch `main`.

O script lê `indice.txt`, identifica as chaves `#` e `A`–`Z`, tenta as variantes `%23`, `0` e `outros` para a chave `#`, e baixa as listas de filmes/séries e as partições numeradas de episódios a partir de `-0`, parando no primeiro arquivo que não retornar HTTP 2xx.

## Execução local

Requisitos: Python 3.10+ e Git.

```bash
python3 clonar.py
```

## Observações operacionais

- Arquivos opcionais que não existirem na origem são registrados como ausentes.
- `indice.txt` e pelo menos um arquivo de canais são obrigatórios para uma execução bem-sucedida.
- O limite de segurança é de 1.000 partições por letra; se for atingido, a execução falha explicitamente.
- O espelhamento preserva os nomes e a estrutura de diretórios definidos no script.
- Mantenha este repositório privado: os catálogos podem conter URLs e credenciais de serviços. A visibilidade privada reduz exposição, mas não substitui controle de acesso, rotação de credenciais e armazenamento seguro de segredos.
