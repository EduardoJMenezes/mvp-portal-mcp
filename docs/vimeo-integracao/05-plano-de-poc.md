# 05 — Plano de POC na conta real

> Documento 5 do §71. Chamadas reais para fechar o que a documentação deixa em
> aberto, na ordem: leitura (R), escrita numa pasta de teste (W), upload (U) e
> webhooks (H). Cada passo aponta a linha da
> [matriz](01-matriz-de-capacidades.md) que resolve.

## Regras

- Começar só com leitura. Escrita apenas numa pasta criada para o teste e em vídeos descartáveis.
- **Nenhuma chamada de exclusão**: nada de `DELETE /videos/…`, `DELETE …/projects/{id}` ou `DELETE …/items`. A limpeza final é feita pela interface do Vimeo.
- Tokens só em variável de ambiente, nunca no repositório, em log ou em fixture.
- Guardar as respostas, sem token e sem dado pessoal, para virarem fixtures dos testes de contrato.

## Preparação

1. Criar um app em developer.vimeo.com/apps, acessível só pelo dono ("No" em *Will people besides you be able to access your app?*).
2. Gerar dois tokens pessoais do tipo *Authenticated*:
   - `VIMEO_POC_TOKEN_LEITURA`: `public private` (e `stats` só se for testar o R19);
   - `VIMEO_POC_TOKEN_ESCRITA`: `public private create edit interact upload`, **sem `delete`**.
3. Separar:
   - uma pasta real grande, de preferência com subpastas e mais de 100 vídeos;
   - um vídeo unlisted;
   - um vídeo com legenda automática;
   - um vídeo enviado antes de 25/05/2022;
   - um arquivo de vídeo descartável e pequeno.
4. Escrever `scripts/poc_vimeo.py` (httpx) que executa os passos, imprime o essencial e salva cada resposta em `.poc_vimeo/<passo>.json`, com a pasta no `.gitignore`.

Todas as chamadas levam estes headers:

```bash
curl -sS -D - "https://api.vimeo.com/me?fields=uri,name,membership,upload_quota" -H "Authorization: bearer $VIMEO_POC_TOKEN_LEITURA" -H "Accept: application/vnd.vimeo.*+json;version=3.4" -H "User-Agent: mvp-portal-aluno-poc/0.1"
```

## Leitura (R): token de leitura

| Passo | Chamada | O que registrar | Resolve |
|---|---|---|---|
| R1 | `GET /oauth/verify` · `GET /me?fields=uri,name,membership,upload_quota` | Plano (`membership`); presença de `upload_quota`, que indica acesso de upload; headers `X-RateLimit-*` | H1, H10, F5, F7 |
| R2 | `GET /me` sem `fields` e com `fields=uri` | `X-RateLimit-Limit` nos dois casos (o guia diz que o header já considera a cota dobrada) | H4 |
| R3 | `GET /me/projects?per_page=100&fields=<CAMPOS_PASTA>` · o mesmo com `query=<nome real>` | Se a lista traz subpastas ou só o primeiro nível; `total`; qualidade da busca por nome | A1, A3 |
| R4 | Na pasta grande: `GET /me/projects/{id}/items?filter=folder&per_page=100&fields=<CAMPOS_ITEM_DE_PASTA>`, recursivamente | Árvore completa × interface; soma de vídeos × `deep_total`; se `fields` aninhado funciona em `items` | A4, A5 |
| R5 | `GET /users/{uid}/projects/{id}/videos?per_page=100&fields=uri,name` com `sort=default`, depois `sort=alphabetical&direction=asc`, depois `sort=date&direction=asc` | Qual ordem bate com a da interface; `paging.next` e `total` numa pasta com mais de 100 vídeos | A6, A7, H3 |
| R6 | `…/videos?include_subfolders=true&fields=uri,name,parent_project` | Contagem × `deep_total`; formato de `parent_project` | A5, A9 |
| R7 | `GET /videos/{id}` sem `fields`, para 3 vídeos | Payload completo para os DTOs | B6 |
| R8 | `GET /videos/{id}?fields=<CAMPOS_VIDEO_IMPORTACAO>` | Cada campo existe e vem preenchido | B6 |
| R9 | `GET /me/videos?per_page=100&fields=uri,created_time,status,transcode.status,is_playable,transcript.status,privacy.view,privacy.embed,is_cold_storage,is_cold_privacy_restricted`, todas as páginas | Distribuição de `status` e `transcript.status`; quantos vídeos anteriores a 25/05/2022 estão sem transcrição | B7, E3, E4 |
| R10 | Vídeo unlisted: `player_embed_url` e reprodução no portal pelo Player SDK usando `url` | Presença do `h`; eventos `play`, `timeupdate` e `ended` chegando | D3, D5 |
| R11 | `GET /videos/{id}/privacy/domains` | Domínios permitidos hoje | D2 |
| R12 | Vídeo com legenda automática: `GET /videos/{id}/texttracks` · `GET /videos/{id}/transcripts/{texttrack_id}` · baixar `download_links.vtt` | `provenance`, idioma, validade dos links, formato dos segmentos | E1, E2 |
| R13 | `GET /videos/{id}/versions?fields=<CAMPOS_VERSAO>` | Nome original e tamanho do arquivo | B13 |
| R14 | `GET /videos/{id}/pictures?sizes=640x`, repetido 48 h depois | Se a URL da thumbnail muda | B11 |
| R15 | `GET /me/videos?query=<termo real>&query_fields=title` · o mesmo dentro de uma pasta | Qualidade e ordem da busca | B3 |
| R16 | `GET /me/videos?per_page=1` com `If-Modified-Since` atual e com uma data antiga | 304 × 200 | B2, H6 |
| R17 | `GET /videos/{id}` com ID inexistente e com vídeo privado de outra conta | 404 × 403 e corpo do erro | B9 |
| R18 | `GET /` autenticado | Salvar a especificação OpenAPI | H8 |
| R19 | Opcional, com `stats`: `GET /me/analytics?dimension=total&from=…&to=…` | 200 ou erro de plano | G2 |

## Escrita numa pasta de teste (W): token de escrita

| Passo | Chamada | O que registrar | Resolve |
|---|---|---|---|
| W1 | `POST /me/projects` com `{"name": "POC API (apagar)"}` | 201 e `uri` | A10 |
| W2 | `POST /me/projects` com `{"name": "Sub", "parent_folder_uri": "<uri de W1>"}` | `parent_folder` e `ancestor_path` da subpasta | A4 |
| W3 | `PATCH /me/projects/{sub}` com `{"name": "Sub renomeada"}` | 200 | A10 |
| W4 | `PUT /me/projects/{sub}/videos/{video_descartavel}` | `parent_project` do vídeo; `link` e `player_embed_url` inalterados | A11 |
| W5 | `PUT /me/projects/{W1}/videos/{video_descartavel}` | Se o vídeo **mudou** de pasta, em vez de duplicar ou falhar | A11, gap 15 |
| W6 | `PATCH /videos/{id}` com `{"name": "Renomeado POC"}` | `uri` inalterada | B8 |
| W7 | `PATCH /videos/{id}` com `{"privacy": {"view": "disable", "embed": "whitelist"}}` · `PUT /videos/{id}/privacy/domains/<domínio do Railway>` · o mesmo para `localhost` | Toca no portal (Railway e local); é recusado em outro site; `vimeo.com/{id}` fica inacessível | D1, D2, D4 |
| W8 | `POST /me/albums` e incluir 3 vídeos de teste · `GET /me/albums/{id}/videos?sort=manual` · `PUT /me/albums/{id}/videos` com a ordem invertida, no formato de corpo da referência | Se a ordem da lista vira a ordem manual | C1, C2, C4 |
| W9 | Incluir o mesmo vídeo num segundo showcase | Aceito | C3 |
| W10 | `PUT /videos/{id}/tags` com uma tag de teste · `GET /me/videos?filter_tag=<tag>` | Busca por tag funciona no acervo privado | C6 |
| W11 | `GET /teams/{uid}/custom_metadata` | 200 (recurso disponível) ou erro de plano | C7 |
| W12 | Limpeza pela interface do Vimeo | — | — |

## Upload e replace (U): token de escrita, vídeo descartável

| Passo | Chamada | O que registrar | Resolve |
|---|---|---|---|
| U1 | `POST /me/videos` com `{"upload": {"approach": "tus", "size": N}, "name": "POC upload", "privacy": {"view": "nobody"}}` e `folder_uri` da pasta W1 · `PATCH` no `upload_link` · `HEAD` para progresso · polling de `status` a cada 30 s | Se o app tem acesso de upload; tempo até `is_playable=true`; `transcript.status` final | F1, F4, F5, F6, E4 |
| U2 | Opcional: `upload.approach=pull` a partir de uma URL assinada | 201 e processamento | F3 |
| U3 | `POST /videos/{id}/versions` com `{"file_name": "v2.mp4", "upload": {"status": "in_progress", "size": N, "approach": "tus"}}` e upload | `uri`, `player_embed_url`, thumbnail e faixas de texto inalterados; se a versão anterior continua tocando durante o processamento | F8, B8 |
| U4 | Página HTML local que faz o `PATCH` tus num `upload_link` criado pelo backend | CORS aceito ou bloqueado | F2 |
| U5 | No vídeo de U1 e U3, conferir `transcript.status` depois da nova versão | Se uma nova versão gera legenda automática | E4, gap 3 |

## Webhooks (H): precisa de uma URL pública de teste

| Passo | Chamada | O que registrar | Resolve |
|---|---|---|---|
| H1 | `GET /apps/{app_id}/webhooks` | 200 (disponível) ou erro de plano ou permissão | G1 |
| H2 | `POST /apps/{app_id}/webhooks` com `webhook_type=video-transcode-complete`, `webhook_url` de teste, `secret` aleatório e `is_enabled=true` | Se foi criado | G1 |
| H3 | Disparar com U1 ou U3 | Se chegou; headers; corpo; onde vem o `secret`; tempo de entrega; tentativas | G1 |
| H4 | `PATCH /apps/{app_id}/webhooks/{webhook_id}` com `is_enabled=false` | Desativado | G1 |

## Critério de saída

A POC termina quando esta tabela estiver preenchida e as
[decisões pendentes](02-gaps-e-ajustes.md#decisões-pendentes) tiverem resposta.

| Pergunta | Resultado | Decisão |
|---|---|---|
| Plano da conta e acesso de upload (R1) | | |
| `/me/projects` traz subpastas? (R3) | | |
| `sort=default` reproduz a ordem da interface? (R5) | | |
| Formato de `parent_project` (R6) | | |
| Vídeos sem transcrição, antes e depois de 25/05/2022 (R9) | | |
| Incluir em outra pasta move o vídeo? (W5) | | |
| `disable` + `whitelist` funcionam no Railway e em `localhost`? (W7) | | |
| A ordem manual do showcase é gravável pela API? (W8) | | |
| O replace preserva ID, embed, thumbnail e legendas? (U3) | | |
| CORS do `upload_link` (U4) | | |
| Webhooks disponíveis e formato do `secret` (H1–H3) | | |
