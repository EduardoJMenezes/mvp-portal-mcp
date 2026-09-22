# 03 — Plano de implementação

> Documento 3 do §71. É proposta, não código. Nada daqui começa antes da
> [POC de leitura](05-plano-de-poc.md) e das
> [decisões pendentes](02-gaps-e-ajustes.md#decisões-pendentes).

## 1. O que não muda

- REST e MCP chamam os mesmos services. O MCP não fala com o Vimeo nem com o banco diretamente.
- O PostgreSQL é a fonte de verdade pedagógica; o Vimeo é biblioteca de vídeos.
- Tudo que a IA propõe nasce como rascunho, e publicar exige aprovação humana gravada em `drafts.aprovado_por_id`. A integração com o Vimeo não abre exceção.
- A credencial do Vimeo fica só no backend e nunca é o token do MCP.

## 2. Pré-requisitos (Fase 0)

1. POC de leitura (R1–R18) na conta real.
2. Plano da conta confirmado (`membership` em `GET /me`).
3. **Alembic antes de alterar tabelas.** Hoje o schema vem de `create_all`, que cria tabelas novas mas não altera as existentes; o banco do Railway já tem dados, e `--reset` apaga tudo.
4. Estratégia de ordem da importação decidida ([gap 1](02-gaps-e-ajustes.md#gaps-o-que-a-api-não-entrega-e-o-que-faremos)).
5. Pedido de acesso de upload do app, se a POC mostrar que falta.

## 3. Estrutura de arquivos

```text
backend/app/
  integracoes/
    vimeo/
      transporte.py        # httpx: headers, timeout, retry, rate limit, allowlist de rotas
      erros.py             # VimeoErro e o mapeamento de HTTP/error_code
      campos.py            # conjuntos de `fields` por caso de uso
      paginacao.py         # iterador assíncrono sobre paging.next
      modelos.py           # DTOs das representações usadas
      leitura.py           # VimeoLeitura (Fase 1)
      escrita.py           # VimeoEscrita (Fase 4), sem exclusão
      upload.py            # VimeoUpload (Fase 5): tus e pull
      enterprise.py        # analytics, IA e busca federada, só se o plano permitir
      webhooks.py          # só depois da POC H1–H4
      demo.py              # evolução do VimeoDemo atual, para testes e demo offline
  services/
    vimeo_acervo.py        # varredura da árvore, snapshot e sync
    vimeo_importacao.py    # simulação e criação de rascunho
    vimeo_reconciliacao.py # estados do §20 e pendências
    nomes_vimeo.py         # VimeoNamingStrategy (§38)
    jobs.py                # fila simples em PostgreSQL (Fase 3)
  api/
    vimeo_routes.py        # admin: conexão, preview, jobs, pendências
  mcp_server/tools.py      # tools novas (seção 7)
scripts/
  poc_vimeo.py             # POC (Documento 5)
backend/tests/
  fixtures/vimeo/          # respostas reais da POC, sem token nem dado pessoal
```

`backend/app/vimeo/client.py` vira um adaptador fino sobre `integracoes/vimeo` e depois sai. `get_cliente_vimeo()` continua escolhendo entre real e demo pelo `.env`.

## 4. Modelo de dados

Nomes em português, seguindo o `CLAUDE.md`; o nome da especificação aparece entre parênteses.

### 4.1 `videos` (VideoAsset): evolução da tabela atual

Hoje: `id`, `vimeo_id` (único), `titulo`, `url`, `embed_url`, `thumbnail_url`, `duracao_segundos`, `pasta_vimeo`, `criado_em`.

| Coluna nova | Origem no Vimeo |
|---|---|
| `uri`, `resource_key` | `uri`, `resource_key` |
| `descricao` | `description` |
| `thumbnail_base_link` | `pictures.base_link` |
| `status_vimeo`, `transcode_status`, `reproduzivel` | `status`, `transcode.status`, `is_playable` |
| `privacidade_view`, `privacidade_embed` | `privacy.view`, `privacy.embed` |
| `transcricao_status`, `transcricao_idioma` | `transcript.status`, `transcript.language` |
| `pasta_vimeo_uri` | `parent_project` (formato confirmado na POC R6) |
| `versao_atual_uri` | `metadata.connections.versions.current_uri` |
| `arquivo_nome`, `arquivo_tamanho` | `filename`, `filesize` da versão ativa |
| `em_cold_storage`, `privacidade_suprimida` | `is_cold_storage`, `is_cold_privacy_restricted` |
| `criado_no_vimeo_em`, `modificado_no_vimeo_em` | `created_time`, `modified_time` |
| `estado_reconciliacao`, `sincronizado_em` | calculados por nós |
| `metadados` (JSONB) | última resposta, já filtrada por `fields` |

### 4.2 Tabelas novas

| Tabela | Colunas principais | Observação |
|---|---|---|
| `vimeo_conexoes` (VimeoConnection) | `organizacao_id` (nulo por ora), `vimeo_usuario_uri`, `nome_conta`, `plano`, `status`, `verificado_em`, `sincronizado_em` | `status`: `ATIVA`, `TOKEN_INVALIDO`, `SEM_ACESSO` |
| `vimeo_credenciais` | `conexao_id`, `finalidade` (`LEITURA`, `ESCRITA`, `UPLOAD`), `token_cifrado`, `escopos`, `revogada_em` | Cifrada com chave em variável de ambiente; nunca vai para log nem para o MCP |
| `vimeo_pastas` (VimeoFolder) | `vimeo_uri` (único), `nome`, `pai_uri`, `caminho` (JSONB de `ancestor_path`), `profundidade`, `total_videos`, `total_videos_com_subpastas`, `modificada_no_vimeo_em`, `sincronizada_em` | Snapshot |
| `questao_videos` (QuestionVideo) | `questao_id`, `video_id`, `tipo` (`RESOLUCAO`), `principal` | Único por (`questao_id`, `video_id`); substitui `questions.video_id` |
| `jobs` | como no §21 | Fase 3 |
| `vimeo_eventos` | como no §33 | Só se a POC aprovar webhooks |
| `audit_log` | como no §45 | — |

Ajustes em tabelas existentes:

- `drafts` ganha `versao` (inteiro) para a trava otimista do §54: aprovar grava a versão aprovada, aplicar exige a mesma versão.
- `class_questions` ganha `unique(turma_id, capitulo_id, numero)`, para que duas questões não ocupem a mesma posição. O `uq_turma_questao` atual continua.

## 5. Transporte HTTP (`transporte.py`)

- `httpx.AsyncClient(base_url="https://api.vimeo.com", timeout=httpx.Timeout(15.0, connect=5.0))`.
- Headers fixos: `Authorization: bearer …`, `Accept: application/vnd.vimeo.*+json;version=3.4`, `User-Agent: mvp-portal-aluno/<versão>`.
- `fields` obrigatório em todo GET, garantido por teste.
- Rate limit: guardar o último `X-RateLimit-*`, limitar a concorrência e, quando `Remaining` ficar baixo, esperar o `Reset`.
- Retry com backoff exponencial e jitter só para 429 (esperando o `X-RateLimit-Reset`), 502, 503, 504 e timeout. Nunca para 400, 401, 403, 404 e 409.
- **Allowlist por cliente.** Leitura: só GET e HEAD. Escrita: só as rotas do `VimeoEscrita`. Upload: só `POST /users/{uid}/videos`, `POST /videos/{id}/versions` e `PATCH`/`HEAD` no `upload_link`. `DELETE /videos/{id}`, `DELETE /users/{uid}/projects/{id}` e `DELETE …/items` ficam fora de qualquer cliente.
- Logs estruturados (§46) com operação, recurso, status, duração e `X-RateLimit-Remaining`; o token nunca aparece.

Mapeamento de erros (as bordas traduzem para `ToolError` no MCP e status HTTP no REST, como hoje):

| Vimeo | Código interno | Retentável |
|---|---|---|
| 401 / `error_code` 8000 | `VIMEO_AUTH_INVALID` | não |
| 403 | `VIMEO_PERMISSION_DENIED` | não |
| 404 / 5000 | `VIMEO_RESOURCE_NOT_FOUND` | não |
| 400 / 2204 | `VIMEO_INVALID_PARAMETER` | não |
| 409 (tus) | `VIMEO_UPLOAD_OFFSET_CONFLICT` | após `HEAD` |
| 429 / 9000 | `VIMEO_RATE_LIMITED` | sim |
| 502, 503, 504, timeout | `VIMEO_TEMPORARY_ERROR` | sim |

## 6. Fluxos

### 6.1 Varredura (Fase 1)

1. Percorrer a árvore em largura com `items?filter=folder`, até 10 níveis, gravando `vimeo_pastas`.
2. Conferir a soma de vídeos por pasta contra o `deep_total` da raiz; divergência vira aviso no preview.
3. Listar os vídeos de cada pasta com os campos de importação, 100 por página.
4. Custo para 3.000 vídeos: cerca de 30 páginas de vídeos mais algumas páginas de pastas. É bem menos que um minuto de cota em qualquer plano pago.

### 6.2 Simulação e importação (Fases 1 e 2)

- `simular_importacao_vimeo(pasta_raiz, turma, estrategia="subpastas_como_capitulos")` não grava nada e responde o §53:
  - capítulos (subpastas);
  - vídeos com número inferido e confiança;
  - vídeos que já existem (por `vimeo_id`);
  - conflitos: número repetido, vídeo sem número, questão já vinculada ao capítulo;
  - avisos: `is_playable=false`, privacidade incompatível com o embed, transcrição ausente.
- `importar_pasta_vimeo_como_rascunho(...)` faz a mesma análise e grava um rascunho com `versao`: UPSERT em `videos` por `vimeo_id` e `TurmaQuestao` em `RASCUNHO`. Chave de idempotência: hash da pasta, turma, estratégia e `modified_time` das pastas.
- A publicação continua em `publicar_rascunho`, com aprovação humana e checagem de versão.

### 6.3 Ordem (gap 1)

Prioridade:

1. Número extraído do título pela `VimeoNamingStrategy`, com padrões configuráveis (`001 - …`, `Q01 - …`, `Questão 01`).
2. `sort=default`, se a POC provar que reproduz a ordem da interface.
3. Posição num showcase `arranged`, quando houver e tiver até 100 vídeos.
4. Revisão humana no preview.

O preview sempre mostra título, número inferido, posição e confiança (§38).

### 6.4 Sync e reconciliação (Fase 3)

- **Incremental:** `GET /users/{uid}/videos?sort=modified_time&direction=desc`, parando no último `modified_time` conhecido. Atualiza só metadados (§19).
- **Completo:** semanal, em job.
- **Reconciliação:** estados do [mapeamento](02-gaps-e-ajustes.md#mapeamento-de-estados-para-a-reconciliação-20). Nunca remove dado pedagógico; gera pendência no admin.
- **Credencial:** `GET /oauth/verify` diário, porque token inativo é apagado pelo Vimeo.

### 6.5 Upload e replace (Fase 5)

- **Servidor:** tus em blocos de 128–512 MB, retomando pelo `HEAD`.
- **Navegador:** o backend cria o vídeo com `upload.approach=tus` e entrega só o `upload_link` ao frontend. Se o CORS falhar (POC U4), usar tus pelo backend ou pull a partir de storage próprio.
- **Replace:** `POST /videos/{id}/versions`. A questão continua apontando para o mesmo `vimeo_id`, e a publicação fica bloqueada enquanto `is_playable=false`.

### 6.6 Transcrições (Fase 6)

- Vídeos com `transcript.status=completed`: listar as faixas de texto, baixar o VTT, normalizar e quebrar em trechos com tempo (§29).
- Vídeos sem transcrição: o caminho é decidido depois da POC (R9, U5).

### 6.7 Eventos do player (Fase 7)

Player SDK na tela do aluno → `POST /api/eventos-player` em lote → tabela `eventos_player` com aluno, questão, vídeo, evento, segundos, percentual e momento.

## 7. Tools MCP por fase

| Tool | Fase | Efeito | Idempotente |
|---|---|---|---|
| `listar_pastas_vimeo` | 1 | leitura: árvore com contagens | sim |
| `listar_conteudo_pasta_vimeo` | 1 | leitura | sim |
| `buscar_videos_vimeo` | 1 | leitura | sim |
| `consultar_status_video` | 1 | leitura: status, transcode, privacidade, transcrição | sim |
| `simular_importacao_vimeo` | 1 | leitura: preview, não grava | sim |
| `importar_pasta_vimeo_como_rascunho` | 2 | cria rascunho | sim, por chave de idempotência |
| `vincular_video_a_questao_rascunho` | 2 | cria rascunho | sim |
| `substituir_video_da_questao_rascunho` | 2 | cria rascunho | sim |
| `sincronizar_metadata_vimeo` | 3 | cria job | sim (um por conexão por vez) |
| `reconciliar_acervo_vimeo` | 3 | cria job que só marca estados | sim |
| `consultar_job`, `cancelar_job` | 3 | leitura e cancelamento | sim |

As tools atuais `listar_videos_vimeo` e `importar_questoes_vimeo` viram casos particulares dessas.

## 8. Roadmap com portões

| Fase | Entrega | Portão para começar |
|---|---|---|
| 0 | POC de leitura, plano da conta, Alembic, estratégia de ordem | — |
| 1 | Leitura: árvore, vídeos, metadados, paginação, snapshot, preview | POC R1–R18 |
| 2 | Importação em rascunho, deduplicação por `vimeo_id`, aprovação com versão | Fase 1 e decisão de ordem |
| 3 | Sync incremental, reconciliação, jobs, verificação de credencial | Fase 2 |
| 4 | Escrita no Vimeo: pastas, showcases, privacidade, tags, sem exclusão | POC W1–W11 |
| 5 | Upload e replace | POC U1–U4 e acesso de upload |
| 6 | Transcrições e busca semântica | POC R9, R12, U5 |
| 7 | Eventos do Player SDK; analytics do Vimeo só se Enterprise | Fase 2 |
| 8 | Workers, Redis, OAuth multi-conta e webhooks | POC H1–H4, para webhooks |

## 9. Testes

- **Contrato:** respostas reais da POC salvas sem token em `backend/tests/fixtures/vimeo/`.
- **Transporte:** espera pelo `X-RateLimit-Reset` no 429; nenhum retry em 4xx; allowlist bloqueia DELETE; todo GET tem `fields`.
- **Paginação:** segue `paging.next` até `null`.
- **Nomes:** `VimeoNamingStrategy` contra títulos reais coletados na POC.
- **Importação idempotente:** rodar duas vezes não duplica `videos` nem `TurmaQuestao`.
- **Regra de publicação:** `test_publicacao.py` continua valendo para rascunhos vindos do Vimeo.
