# 01 — Matriz de capacidades da Vimeo REST API

> Documento 1 do §71 da especificação de longo prazo.
>
> Pesquisa feita em 10/09/2026 somente em documentação oficial: a referência de
> developer.vimeo.com (OpenAPI da API 3.4.9, que vem embutida nas próprias
> páginas), os guias de developer.vimeo.com e os artigos de help.vimeo.com.
> **Nenhuma chamada foi feita contra a conta real.** Tudo que depende disso está
> marcado para a POC ([05-plano-de-poc.md](05-plano-de-poc.md)).

## Como ler

| Símbolo | Significado |
|---|---|
| ✅ | Suportado e documentado |
| 🟡 | Parcial: dá para fazer, com limitação relevante |
| ❌ | Não suportado pela API |
| 💳 | Depende do plano da conta |
| ❓ | Ambíguo: documentação incompleta, fechada ou conflitante |

- `{uid}` é `me` ou o ID do usuário. Em pasta de time, é o ID do dono do time ([guia de folders][guia-folders]).
- *Folder* e *project* são a mesma coisa; os endpoints usam `projects` ([guia de folders][guia-folders]).
- **Escopo:** qualquer escopo além de `public` exige também `private`, e dado privado exige `private` ([autenticação][guia-auth]). A coluna mostra o escopo específico da operação quando a referência o informa.
- Planos atuais: Free, Starter, Standard, Advanced e Enterprise ([planos][ajuda-planos]). O guia de rate limit cita também o Studio.

## Resumo das linhas pedidas no §63

| Capacidade | Veredito | Linhas |
|---|---|---|
| Listar folders | ✅ | A1–A3 |
| Listar vídeos da folder | ✅ | A6 |
| Subfolders | ✅ | A4, A5 |
| Ordem manual | ❌ em pastas · 🟡 em showcases (até 100 vídeos) | A7, C4 |
| Search videos | ✅ no próprio acervo · 💳❓ busca federada | B3–B5 |
| Metadata | ✅ | B6, B7 |
| Thumbnail | ✅ | B11, B12 |
| Privacy | ✅💳 | D1 |
| Embed restriction | ✅💳 | D2 |
| Transcript | ✅💳 leitura · 💳 geração sob demanda só no Enterprise | E1–E6 |
| Analytics | 💳 só Enterprise | G2 |
| Upload | ✅ (acesso de upload do app ❓) | F1–F7 |
| Replace | ✅ | F8 |
| Delete | ✅, mas a integração não deve usar | F9, A12, A13 |
| Showcase | ✅ | C1–C5 |
| Webhook | ❓ | G1 |
| Tags | ✅ | C6 |
| Comments | ✅ | C8 |

## A. Pastas

| # | Capacidade | Status | Endpoint | Escopo | Plano | Limitações e observações | POC | Fonte |
|---|---|---|---|---|---|---|---|---|
| A1 | Listar pastas | ✅ | `GET /users/{uid}/projects` | `private` | todos | `per_page` ≤ 100 (padrão 25). `sort`: `date`, `default`, `modified_time`, `name`, `pinned_on`. **Não está documentado se lista só o primeiro nível ou todas as pastas** | Sim (R3) | [ref-folders], [guia-formatos] |
| A2 | Obter pasta por ID | ✅ | `GET /users/{uid}/projects/{project_id}` | `private` | todos | 404 com `error_code` 5000 quando não existe | Não | [ref-folders] |
| A3 | Localizar pasta por nome | 🟡 | `GET /users/{uid}/projects?query=…` | `private` | todos | Busca textual; nomes repetidos exigem desambiguação na nossa camada | Sim (R3) | [ref-folders] |
| A4 | Subpastas: criar, ver pai, ver filhos | ✅ | criar: `POST /users/{uid}/projects` com `parent_folder_uri` · filhos: `GET …/projects/{id}/items?filter=folder` · pai: `metadata.connections.parent_folder` e `metadata.connections.ancestor_path` | `create` / `private` | todos | Até **10 níveis**. A pasta traz `has_subfolder`, `metadata.connections.folders.total` e `metadata.interactions.add_subfolder.subfolder_depth_limit_reached` | Sim (R4) | [guia-folders], [schema-project] |
| A5 | Percorrer a árvore | 🟡 | Não há endpoint de árvore: compor `items?filter=folder` nível a nível. Para vídeos, há `GET …/projects/{id}/videos?include_subfolders=true` | `private` | todos | `metadata.connections.videos.deep_total` (vídeos da pasta e de todas as subpastas) confere a contagem. `items` também pode trazer `showcase` e `live_event` | Sim (R4, R6) | [ref-folders], [schema-project], [schema-item] |
| A6 | Listar vídeos da pasta, paginado | ✅ | `GET /users/{uid}/projects/{id}/videos` ou `…/items?filter=video` | `private` | todos | `per_page` ≤ 100; `query` e `query_fields` (padrão `title,description,chapters,tags`); `filter_tag`, `filter_tag_all_of`, `filter_tag_exclude` | Sim (R5) | [ref-folders], [guia-folders] |
| A7 | Ordem manual dos vídeos na pasta | ❌ | `sort` aceita apenas `alphabetical`, `date`, `default`, `duration`, `last_user_action_event_date` | — | — | Não existe `manual` nem campo de posição. **O significado de `default` não é documentado** | Sim (R5) | [ref-folders] |
| A8 | Um vídeo em várias pastas | ❌ | — | — | — | "It's not possible to put one video into multiple folders." | Não | [ajuda-folders-add] |
| A9 | Descobrir a pasta de um vídeo | ✅ | campo `parent_project` do Video | `private` | todos | A referência não detalha o formato do objeto | Sim (R6) | [schema-video] |
| A10 | Criar e renomear pasta | ✅ | `POST /users/{uid}/projects` · `PATCH /users/{uid}/projects/{id}` | `create` / `edit` | todos | Free e Starter: pastas só do dono. Standard e Advanced: colaboração com o time | Sim (W1–W3) | [ref-folders], [guia-folders] |
| A11 | Colocar vídeos numa pasta | ✅ | um: `PUT …/projects/{id}/videos/{video_id}` · lista: `PUT …/projects/{id}/videos` · ou `POST …/projects/{id}/items` com `{"items":[{"uri":"/videos/…"}]}` | `interact` | todos | Mover não altera link nem embed. **Não está documentado se incluir numa pasta move o vídeo que já estava em outra** | Sim (W4, W5) | [ref-folders], [guia-folders], [ajuda-folders-add] |
| A12 | Tirar vídeos da pasta | ✅⚠️ | um: `DELETE …/projects/{id}/videos/{video_id}` ("doesn't delete the video itself") · lista: `DELETE …/projects/{id}/videos` · via items: `DELETE …/items?uris=…&should_delete_items=false` | `delete` (um) / `interact` (lista) | todos | **Risco:** pelo guia, remover via `items` sem `should_delete_items=false` apaga os vídeos | Evitar | [ref-folders], [guia-folders] |
| A13 | Excluir pasta | ✅⚠️ | `DELETE /users/{uid}/projects/{id}` | `delete` | todos | Com `should_delete_clips=true`, apaga também os vídeos | Não usar | [guia-folders] |

## B. Vídeos e metadados

| # | Capacidade | Status | Endpoint | Escopo | Plano | Limitações e observações | POC | Fonte |
|---|---|---|---|---|---|---|---|---|
| B1 | Obter vídeo por ID | ✅ | `GET /videos/{video_id}` | `private` (não públicos) | todos | 404 "No such video exists" | Não | [ref-videos] |
| B2 | Listar todos os vídeos da conta | ✅ | `GET /users/{uid}/videos` | `private` | todos | `per_page` ≤ 100; `sort` inclui `modified_time`; `filter` inclui `playable`, `embeddable`, `cold_storage`, `cold_privacy`; aceita `If-Modified-Since` | Sim (R16) | [ref-videos], [guia-formatos] |
| B3 | Pesquisar no próprio acervo | ✅ | `GET /users/{uid}/videos?query=…&query_fields=title,description,chapters,tags` · numa pasta: `GET …/projects/{id}/videos?query=…` | `private` | todos | Busca textual do Vimeo, sem ranking configurável | Sim (R15) | [ref-videos], [ref-folders] |
| B4 | Busca federada (vídeos e pastas) | 💳❓ | `GET /search/{uid}/items` | `private` | A página de planos lista "Search API" só no Enterprise; a referência não diz o plano deste endpoint | Filtros por privacidade e data de modificação; `sort=folder_path` | Só se Enterprise | [ref-search], [ajuda-planos] |
| B5 | `GET /videos` e `GET /tags/{word}/videos` | ❌ para o acervo | — | — | — | `/tags/{word}/videos` devolve só vídeos **públicos**. `/videos` é a busca geral do Vimeo (filtros de licença CC, `trending`, categorias) | Não | [ref-videos] |
| B6 | Metadados para importação | ✅ | qualquer GET de vídeo com `fields=` | `private` | todos | Campos úteis: `uri`, `name`, `description`, `duration`, `created_time`, `modified_time`, `release_time`, `link`, `player_embed_url`, `pictures`, `privacy`, `status`, `transcode`, `is_playable`, `transcript`, `parent_project`, `resource_key`, `tags`, `is_cold_storage`, `is_cold_privacy_restricted` | Sim (R8) | [schema-video], [guia-formatos] |
| B7 | Status técnico | ✅ | campos `status`, `transcode.status`, `upload.status`, `is_playable` | `private` | todos | `status`: `available`, `failed`, `processing`, `quota_exceeded`, `total_cap_exceeded`, `transcode_starting`, `transcoding`, `transcoding_error`, `unavailable`, `uploading`, `uploading_error`. `transcode.status`: `complete`, `error`, `in_progress` | Sim (R9) | [schema-video], [ajuda-transcode] |
| B8 | Estabilidade do ID | 🟡 | `uri` = `/videos/{id}` | — | — | Substituir o arquivo mantém ID, URL e embed. Mover de pasta não altera link nem embed. Copiar (`POST /users/{uid}/videos/{video_id}/copy`) e reenviar criam outro vídeo. **Renomear: não há declaração explícita** | Sim (W6) | [produto-replace], [guia-upload], [ajuda-folders-add], [ref-videos] |
| B9 | Detectar vídeo apagado ou inacessível | 🟡 | `GET /videos/{id}` → 404 · `GET /users/{uid}/videos/{video_id}` confere se o usuário é dono | `private` | todos | A resposta 403 no GET não está documentada | Sim (R17) | [ref-videos] |
| B10 | Detectar mudança de privacidade | ✅ por polling | comparar `privacy.view` e `privacy.embed` com o snapshot | `private` | todos | `is_cold_privacy_restricted` e `privacy.original_view` indicam privacidade suprimida porque o plano deixou de suportá-la. O webhook `video-updated` é ambíguo (G1) | Não | [schema-video] |
| B11 | Ler thumbnails | ✅ | `pictures` do vídeo · `GET /videos/{id}/pictures` · parâmetro `sizes=640x,…` | `private` | todos | `sizes[]` com `width`, `height` e `link`; `base_link`. A Central de Ajuda recomenda **não cachear** URLs de thumbnail | Sim (R14) | [schema-picture], [guia-formatos], [ajuda-thumbs] |
| B12 | Criar ou trocar thumbnail | ✅ | `POST /videos/{id}/pictures` · `PATCH /videos/{id}/pictures/{picture_id}` | `upload` / `edit` | todos | — | Não | [ref-videos] |
| B13 | Nome original, tamanho e codec do arquivo | ✅ por versão | `GET /videos/{id}/versions` → `filename`, `filesize`, `duration`, `source_metadata` | `private` | todos | **Nenhum hash (MD5 etc.) documentado.** No vídeo, só `files_size` | Sim (R13) | [schema-version], [schema-video] |
| B14 | Links de arquivo e download | 💳 | campos `play`, `files`, `download` | `video_files` | Standard, Advanced, Enterprise (e legados Pro, Business, Premium) | `play` e `download` expiram em 24 h; `files` não expira. Todos são redirects 302 | Não | [ajuda-download], [guia-auth] |
| B15 | Capítulos do vídeo | ✅ | `GET` e `POST /videos/{id}/chapters` | `upload` para criar | todos | Podem marcar trechos de uma resolução | Não | [ref-videos] |

## C. Organização no Vimeo

| # | Capacidade | Status | Endpoint | Escopo | Plano | Limitações e observações | POC | Fonte |
|---|---|---|---|---|---|---|---|---|
| C1 | Showcases: CRUD | ✅ | `GET` e `POST /users/{uid}/albums` · `GET`, `PATCH` e `DELETE /users/{uid}/albums/{album_id}` | `create` / `edit` / `delete` | não informado | — | Sim (W8) | [ref-showcases] |
| C2 | Showcases: incluir e retirar vídeos | ✅ | `PUT` e `DELETE /users/{uid}/albums/{album_id}/videos/{video_id}` · lote: `PATCH /users/{uid}/albums?album_uris=…&album_item_uris=…` · trocar todos: `PUT …/albums/{album_id}/videos` · conteúdo de uma pasta: `PATCH /users/{uid}/albums/from_folder` | `edit` | não informado | — | Sim (W8) | [ref-showcases] |
| C3 | Um vídeo em vários showcases | ✅ | `GET` e `PATCH /videos/{id}/albums` | não informado | — | "you *can* add videos to more than one showcase" | Sim (W9) | [ajuda-showcase-add], [ref-videos] |
| C4 | Ordem manual em showcase | 🟡 | ler: `GET …/albums/{album_id}/videos?sort=manual` · o showcase tem `sort` com o valor `arranged` | `private` | não informado | **Não é possível ordenar manualmente um showcase com mais de 100 vídeos.** Como gravar a posição de cada vídeo pela API não está documentado | Sim (W8) | [ref-showcases], [schema-album], [ajuda-showcase-add] |
| C5 | Tamanho e privacidade do showcase | ✅ | — | — | — | Sem limite de vídeos. `privacy.view`: `anybody`, `embed_only`, `nobody`, `password`, `team`, `unlisted` | Não | [ajuda-showcase-add], [schema-album] |
| C6 | Tags | ✅ | `GET` e `PUT /videos/{id}/tags` · `PUT` e `DELETE /videos/{id}/tags/{word}` · `filter_tag` nas listagens | `edit` | todos | No acervo privado, filtrar pelas listagens do usuário (ver B5) | Sim (W10) | [ref-videos], [ref-folders] |
| C7 | Custom metadata (IDs internos gravados no Vimeo) | 💳❓ | campos: `POST /teams/{uid}/custom_metadata` · valores: `PUT /videos/{id}/custom_metadata` · pendências: `GET /teams/{uid}/custom_metadata/incomplete_videos` | `edit` | recurso de **time**; plano não informado | Até 20 campos por time; `str` com até 50 caracteres; tipos `int`, `date`, `bool`, `select`, `multi-select` | Sim (W11) | [guia-custom-metadata], [ref-teams] |
| C8 | Comentários | ✅ | `GET` e `POST /videos/{id}/comments` · `PATCH` e `DELETE …/comments/{comment_id}` · respostas: `GET` e `POST …/replies` | `interact` / `edit` / `delete` | todos | — | Não | [ref-videos] |

## D. Privacidade, embed e player

| # | Capacidade | Status | Endpoint | Escopo | Plano | Limitações e observações | POC | Fonte |
|---|---|---|---|---|---|---|---|---|
| D1 | Privacidade de visualização | ✅💳 | `PATCH /videos/{id}` com `privacy.view` | `edit` | `unlisted` e `disable` (fora do Vimeo, só embed) exigem Starter, Standard ou Advanced | Guia: `anybody`, `disable`, `nobody`, `password`, `unlisted`. O schema lista também `contacts`, `users`, `team`, entre outros | Sim (W7) | [guia-interact], [schema-video] |
| D2 | Embed só nos nossos domínios | ✅💳 | `privacy.embed=whitelist` + `PUT` e `DELETE /videos/{id}/privacy/domains/{domain}` · listar: `GET /videos/{id}/privacy/domains` | `edit` | Tabela de planos: Starter ou superior. Artigo de domínios: "all Vimeo plans" (**conflito**) | Até 50 domínios; domínio sem `http://`; em desenvolvimento, `localhost` precisa estar na lista | Sim (W7) | [guia-interact], [ajuda-dominio], [ajuda-planos] |
| D3 | URL de embed | ✅ | `player_embed_url` | `private` | — | Vídeo unlisted só toca com o hash `h`; oEmbed sem o hash devolve 404 | Não (a POC atual já trata) | [schema-video], [ajuda-oembed-privado] |
| D4 | Impedir compartilhamento direto | 🟡 | — | — | — | "The API can toggle a video's privacy settings, but cannot be used to allow video playback outside of the privacy settings we provide." A proteção disponível é combinar `disable` com `whitelist` | Sim (W7) | [ajuda-privacidade-api] |
| D5 | Player SDK: eventos | ✅ | biblioteca JavaScript [player.js][player-sdk] | — | — | `play`, `playing`, `pause`, `ended`, `timeupdate`, `progress`, `seeking`, `seeked` (com `duration`, `percent`, `seconds`), `playbackratechange`, `bufferstart`, `bufferend`, `error`, `loaded`, entre outros. Vídeo unlisted exige `url` com `h`. Não vale para lives | Sim (no portal) | [player-sdk], [ajuda-player-sdk] |
| D6 | oEmbed de vídeo privado | 🟡 | oEmbed | — | — | Privado por domínio: informar o domínio no header. Com senha: resposta truncada | Não | [ajuda-oembed-privado] |

## E. Transcrições e IA

| # | Capacidade | Status | Endpoint | Escopo | Plano | Limitações e observações | POC | Fonte |
|---|---|---|---|---|---|---|---|---|
| E1 | Listar e baixar legendas e transcrições | ✅💳 | `GET /videos/{id}/texttracks` | token pessoal **gerado pelo dono** do vídeo | legenda automática só em planos pagos | Cada faixa traz `type` (`captions`, `subtitles`, `descriptions`), `language`, `provenance` (`autogen_source_audio`, `user_uploaded`, …), `download_links` em `vtt`, `srt` e `ttml` com `download_links_expires_time`, e `link` com `link_expires_time` | Sim (R12) | [ref-videos], [schema-text-track], [ajuda-transcricoes-api] |
| E2 | Segmentos da transcrição | ✅ | `GET /videos/{id}/transcripts/{texttrack_id}` | `private` | pago | O formato dos segmentos (tempos) só aparece no payload real | Sim (R12) | [ref-videos] |
| E3 | Status da transcrição | ✅ | `transcript.status` e `transcript.language` no Video | `private` | — | `blocked`, `completed`, `exceeds_maximum_duration`, `failed`, `in_progress`, `language_not_supported`, `no_speech`, `not_started`, `unknown` | Sim (R9) | [schema-video] |
| E4 | Legenda automática no upload | 💳 | automático | — | FAQ: Standard, Advanced, Enterprise e legados. Tabela de planos: Starter ou superior (**conflito**) | Só para vídeos enviados **depois de 25/05/2022**; até 8 h; mais de 100 idiomas, incluindo português. Para vídeos anteriores, o FAQ manda reenviar | Sim (R9) | [ajuda-legendas-auto], [ajuda-planos] |
| E5 | Gerar transcrição sob demanda | 💳 | `POST /videos/{id}/ai/transcribe` (assíncrono; `GET` no mesmo caminho acompanha) | `ai` | **Enterprise** | 10 requisições/min por endpoint; consome créditos de IA; falha se o vídeo já tiver transcrição; detecta o idioma se não for informado | Só se Enterprise | [ref-videos], [ajuda-ai-api] |
| E6 | Enviar legenda própria | ✅ | `POST /videos/{id}/texttracks` | `upload` | — | — | Não | [ref-videos] |

## F. Upload, substituição e exclusão

| # | Capacidade | Status | Endpoint | Escopo | Plano | Limitações e observações | POC | Fonte |
|---|---|---|---|---|---|---|---|---|
| F1 | Upload pelo servidor (tus) | ✅ | `POST /users/{uid}/videos` com `upload.approach=tus` e `upload.size` → `PATCH {upload.upload_link}` com `Tus-Resumable: 1.0.0` e `Upload-Offset` | `upload` e `edit` | todos (no Free, o app precisa ser aprovado) | Arquivo até 300 GB e 24 h. O POST já cria o vídeo (placeholder). Blocos de 128–512 MB recomendados. Offset errado → 409 | Sim (U1) | [guia-upload] |
| F2 | Upload pelo navegador | 🟡 | formulário (`upload.approach=post`, `upload.form`, `redirect_url`, sem retomada) ou tus com `upload_link` criado pelo backend | `upload` | — | O `PATCH` tus não leva `Authorization`: o próprio link autoriza. **CORS do `upload_link` não documentado** | Sim (U4) | [guia-upload], [ajuda-upload-navegador] |
| F3 | Upload por URL (pull) | ✅ | `upload.approach=pull` + `upload.link` | `upload` | — | O link deve apontar direto para o arquivo; URL assinada precisa valer pelo menos 6 h; até 16.384 caracteres; arquivo inválido ainda devolve 201 e o erro aparece em `status` | Sim (U2) | [guia-upload] |
| F4 | Upload direto numa pasta | ✅ | parâmetro `folder_uri` no upload | `upload` | — | — | Sim (U1) | [ajuda-upload-api] |
| F5 | Acesso de upload do app | ❓ | — | — | — | O guia lista "Upload access for the API application. You need to request this"; no Free, exige ticket. `upload_quota` só aparece em `GET /me` quando o usuário tem acesso de upload | **Sim** (R1, U1) | [guia-upload], [schema-user] |
| F6 | Progresso e fim do processamento | ✅ | `HEAD {upload_link}` (`Upload-Offset` × `Upload-Length`); depois, polling de `status`, `transcode.status` e `is_playable` | — | — | — | Sim (U1) | [guia-upload], [ajuda-progresso], [ajuda-transcode] |
| F7 | Cota de armazenamento | 💳 | `GET /me` → `upload_quota` (`lifetime`, `periodic`, `space`) | — | planos atuais: armazenamento total vitalício; legados: cota semanal | `status` do vídeo indica `quota_exceeded` e `total_cap_exceeded` | Sim (R1) | [ajuda-armazenamento], [schema-user], [schema-video] |
| F8 | Substituir o arquivo (replace) | ✅ | `POST /videos/{id}/versions` com `file_name` e `upload` (`tus`, `post` ou `pull`) | não listado na referência | gestão de versões: todos | "the updated video retains all its settings, including its URL and thumbnail image". ID constante; analytics, legendas e capítulos permanecem; versões anteriores podem ser restauradas | Sim (U3) | [guia-upload], [produto-replace], [ajuda-versoes], [ref-videos] |
| F9 | Excluir vídeo | ✅ | `DELETE /videos/{id}` | `delete` | — | 204; 403 quando o usuário não pode | Não (fora da integração) | [ref-videos] |

## G. Eventos e analytics

| # | Capacidade | Status | Endpoint | Escopo | Plano | Limitações e observações | POC | Fonte |
|---|---|---|---|---|---|---|---|---|
| G1 | Webhooks de vídeo | ❓ | `GET` e `POST /apps/{app_id}/webhooks` · `GET`, `PATCH` e `DELETE /apps/{app_id}/webhooks/{webhook_id}` | não informado | não informado | `webhook_type`: `video-created`, `video-updated`, `video-deleted`, `video-upload-failed`, `video-transcode-playable`, `video-transcode-fully-playable`, `video-transcode-complete`, `transcript-status-updated`, `transcript-status-complete`, `automatic-thumbnail-available`, `content-scan-completed`, além de eventos de live e de inscrição. Campos: `webhook_url`, `secret`, `is_enabled` (padrão `false`). O webhook é desativado sozinho quando a taxa de falha sobe. **Conflitos:** a Central de Ajuda afirma que não há webhook de fim de transcode; o guia "Working with App Webhooks" exige login; o formato do payload e o uso do `secret` não são públicos | **Sim, obrigatória** (H1–H4) | [ref-api-apps], [schema-webhook], [ajuda-transcode], [guia-app-webhooks] |
| G2 | Analytics do Vimeo | 💳 | `GET /users/{uid}/analytics` | `stats` | **Enterprise**, com pedido de liberação ao suporte | `dimension` (`video`, `country`, `device_type`, `embed_domain`, `total`, …); `time_interval` (`day`, `week`, `month`, `year`); `from` e `to` em ISO 8601; `filter_content` com URIs de vídeo, pasta ou evento; `per_page` ≤ 1000. Métricas: `views`, `impressions`, `finishes`, `completions` (mais de 95% assistido), `unique_viewers`, `total_seconds_watched`, `mean_percent_watched`, entre outras | Só se Enterprise (R19) | [ref-users], [schema-analytics], [ajuda-analytics-api] |
| G3 | Curva de retenção por segundo | ❌ | — | — | — | Não localizada na referência. O mais próximo: `mean_percent_watched`, `completions` e `finishes` | Não | [schema-analytics] |

## H. Base da integração

| # | Capacidade | Status | Endpoint | Escopo | Plano | Limitações e observações | POC | Fonte |
|---|---|---|---|---|---|---|---|---|
| H1 | Token pessoal (conta única) | ✅ | gerado em developer.vimeo.com/apps, tipo *Authenticated* · verificar: `GET /oauth/verify` · revogar: `DELETE /tokens` | escolhidos na geração | todos | Tokens seguem válidos enquanto usados; **tokens inativos são apagados automaticamente**; token vazado pode ser revogado pelo Vimeo sem aviso | Sim (R1) | [guia-auth], [guia-start], [ref-auth-extras], [ajuda-token] |
| H2 | OAuth para várias contas | ✅ | `https://api.vimeo.com/oauth/authorize?response_type=code…` → `POST /oauth/access_token` | o usuário aprova escopo a escopo | todos | Um token por conta; a resposta **não traz refresh token**; *implicit* expira em 1 h; *client credentials* só lê dado público | Não (futuro) | [guia-auth] |
| H3 | Paginação | ✅ | `page` e `per_page` (≤ 100, padrão 25); resposta com `total` e `paging.next`, `previous`, `first`, `last` | — | — | Página inexistente → 404 | Sim (R5) | [guia-formatos] |
| H4 | Rate limit | ✅💳 | headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` | — | por usuário e por minuto (tabela abaixo) | Ao estourar: 429 com `error_code` 9000 até o fim da janela de 60 s. `fields` dobra a cota efetiva. `Retry-After` não é documentado. Abuso recorrente pode bloquear o app | Sim (R2) | [guia-rate-limit], [ajuda-rate-limits] |
| H5 | Filtro de campos | ✅ | `?fields=uri,name,metadata.connections.x` | — | — | Vale em todos os métodos, exceto DELETE | Não | [guia-formatos] |
| H6 | Requisição condicional | 🟡 | `If-Modified-Since` → 304 | — | — | Só em `/users/{uid}/videos` (e canais, grupos e watch later). ETag e `If-None-Match` não são documentados | Sim (R16) | [guia-formatos] |
| H7 | Versão e identificação do app | ✅ | `Accept: application/vnd.vimeo.*+json;version=3.4` e `User-Agent` próprio | — | — | User-Agent genérico pode levar a bloqueio | Não | [guia-formatos] |
| H8 | Especificação OpenAPI | ✅ | `GET /` autenticado | — | — | Serve para gerar e validar os DTOs | Sim (R18) | [ref-api-info] |
| H9 | Formato de erro | ✅ | JSON com `error_code`, `developer_message`, `invalid_parameters` | — | — | 2204 parâmetro inválido; 5000 pasta inexistente; 8000 credencial inválida; 9000 rate limit; 409 offset do tus | Não | [guia-upload], [ref-folders], [guia-rate-limit] |
| H10 | Plano e cota da conta | ✅ | `GET /me` → `membership`, `upload_quota` | `private` | todos | `upload_quota` só aparece quando o usuário tem acesso de upload e consulta o próprio registro | Sim (R1) | [schema-user] |

### Rate limit por plano

| Plano | Requisições/min sem `fields` | Com `fields` |
|---|---|---|
| Free | 25 | 50 |
| Starter | 125 | 250 |
| Standard | 250 | 500 |
| Advanced | 750 | 1.500 |
| Studio | 1.500 | 3.000 |
| Enterprise | 2.500 | 5.000 |

Planos legados, sem `fields`: Basic 25, Plus 125, PRO 250, Business 500, Premium 750. Fonte: [guia-rate-limit].

## Respostas às perguntas do §64

**Folders**

1. *Como listar todas as folders?* `GET /users/{uid}/projects`, paginado. Se a lista traz subpastas ou só o primeiro nível é verificado na POC (A1).
2. *Parent/child?* Pai em `metadata.connections.parent_folder` e `ancestor_path`; filhos em `items?filter=folder` (A4).
3. *Subfolders oficialmente?* Sim, até 10 níveis (A4).
4. *Percurso recursivo?* Compondo `items?filter=folder`; vídeos com `include_subfolders=true` (A5).
5. *Como a ordem é representada?* Só pelo `sort` da listagem; não há posição (A7).
6. *Posição manual?* Não em pastas. Showcases têm `sort=manual`, limitado a 100 vídeos (A7, C4).
7. *Um vídeo em mais de uma folder?* Não (A8).
8. *Limites?* 10 níveis de subpasta; `per_page` ≤ 100. Não há limite de quantidade de pastas documentado (A4, H3).

**Videos**

9. *Campos para import?* Ver B6. A lista final é validada na POC (R8).
10. *Video ID é estável?* Sim ao mover e ao substituir o arquivo. Renomear não tem declaração explícita (B8).
11. *Replace mantém o ID?* Sim (F8).
12. *Como detectar deleted?* 404 em `GET /videos/{id}`; webhook `video-deleted` pendente de POC (B9, G1).
13. *Como detectar privacy change?* Polling de `privacy.*`, `is_cold_privacy_restricted` e domínios (B10).
14. *Embed URL?* `player_embed_url` (D3).
15. *Thumbnail?* `pictures.sizes` e `base_link` (B11).
16. *Original filename?* `filename` em `GET /videos/{id}/versions` (B13).

**Upload**

17. *Estratégias?* tus, formulário (post) e pull (F1–F3).
18. *TUS?* Sim, `Tus-Resumable: 1.0.0` (F1).
19. *Browser direct?* Formulário documentado; tus com `upload_link` criado no backend depende do CORS (F2).
20. *Server upload?* tus ou pull (F1, F3).
21. *Pull URL?* Sim, com os requisitos de F3.
22. *Progresso?* `HEAD` no `upload_link` (F6).
23. *Transcode complete?* Polling de `status`, `transcode.status` e `is_playable`. O webhook `video-transcode-complete` depende da POC (F6, G1).
24. *Upload access precisa ser solicitado?* O guia diz que sim; a POC confirma pela presença de `upload_quota` (F5).

**Privacy**

25. *Valores?* `privacy.view`: `anybody`, `disable`, `nobody`, `password`, `unlisted` (e outros no schema). `privacy.embed`: `private`, `public`, `whitelist` (D1, D2).
26. *Embed-only?* `privacy.view=disable` (D1).
27. *Restrição por domínio?* `privacy.embed=whitelist` + domínios (D2).
28. *Endpoint?* `PATCH /videos/{id}` e `PUT`/`DELETE /videos/{id}/privacy/domains/{domain}` (D1, D2).
29. *Plano?* `unlisted` e `disable`: Starter, Standard ou Advanced. Domínios: Starter ou superior, com conflito na documentação (D1, D2).

**Transcript**

30. *Como baixar?* `GET /videos/{id}/texttracks` → `download_links`; segmentos em `GET /videos/{id}/transcripts/{texttrack_id}` (E1, E2).
31. *Geração via API?* Só pela AI API, no Enterprise. Nos planos pagos, a legenda é gerada automaticamente no upload (E4, E5).
32. *Idiomas?* Legenda automática: mais de 100, incluindo português. A API expõe `/languages?filter=texttrack` e `GET /videos/ai/languages` (E4, E5, schema de text track).
33. *Formatos?* VTT, SRT e TTML (E1).
34. *Limites?* Legenda automática: vídeos até 8 h, enviados depois de 25/05/2022. AI API: 10 requisições/min e créditos (E4, E5).
35. *AI API é necessária?* Só para gerar sob demanda, por exemplo em vídeos antigos (E5).

**Analytics**

36. *Métricas?* `views`, `impressions`, `finishes`, `completions`, `downloads`, `unique_viewers`, `unique_impressions`, `mean_percent_watched`, `total_seconds_watched`, entre outras (G2).
37. *Nível de vídeo?* Sim, `dimension=video` e `filter_content` (G2).
38. *Período?* `from` e `to` (G2).
39. *Granularidade diária?* `time_interval=day`, em combinação com dimensões específicas (G2).
40. *Retenção?* Não há curva por segundo (G3).
41. *Unique viewers?* Sim (G2).
42. *Limite de chamadas?* Não há limite específico documentado; vale o rate limit geral (G2, H4).
43. *Plano?* Enterprise, com liberação pelo suporte (G2).

**Events**

44. *Existem webhooks?* A referência documenta webhooks de app; o guia é fechado e a Central de Ajuda contradiz (G1).
45. *Quais eventos?* Lista de `webhook_type` em G1.
46. *Assinatura?* Não documentada publicamente; existe um `secret` "passed on webhook payloads" (G1).
47. *Transcode complete?* `video-transcode-complete`, `video-transcode-playable` e `video-transcode-fully-playable` (G1).
48. *Deletion?* `video-deleted` (G1).
49. *Upload?* `video-created` e `video-upload-failed` (G1).
50. *Transcript ready?* `transcript-status-complete` (G1).

**Showcase**

51. *CRUD?* Sim (C1).
52. *Vários showcases por vídeo?* Sim (C3).
53. *Custom order?* `sort=manual` e `arranged`, até 100 vídeos (C4).
54. *Máximo de itens?* Sem limite (C5).
55. *Privacidade e embed?* `privacy.view` do showcase: `anybody`, `embed_only`, `nobody`, `password`, `team`, `unlisted` (C5).

## Fontes

Referência (developer.vimeo.com):

[ref-folders]: https://developer.vimeo.com/api/reference/folders
[ref-showcases]: https://developer.vimeo.com/api/reference/showcases
[ref-videos]: https://developer.vimeo.com/api/reference/videos
[ref-users]: https://developer.vimeo.com/api/reference/users
[ref-search]: https://developer.vimeo.com/api/reference/search
[ref-teams]: https://developer.vimeo.com/api/reference/teams
[ref-auth-extras]: https://developer.vimeo.com/api/reference/authentication-extras
[ref-api-apps]: https://developer.vimeo.com/api/reference/api-apps
[ref-api-info]: https://developer.vimeo.com/api/reference/api-information
[schema-video]: https://developer.vimeo.com/api/reference/response/video
[schema-project]: https://developer.vimeo.com/api/reference/response/project
[schema-item]: https://developer.vimeo.com/api/reference/response/project-item
[schema-album]: https://developer.vimeo.com/api/reference/response/album
[schema-text-track]: https://developer.vimeo.com/api/reference/response/text-track
[schema-picture]: https://developer.vimeo.com/api/reference/response/picture
[schema-version]: https://developer.vimeo.com/api/reference/response/video-version
[schema-analytics]: https://developer.vimeo.com/api/reference/response/analytics
[schema-webhook]: https://developer.vimeo.com/api/reference/response/api-app-webhook
[schema-user]: https://developer.vimeo.com/api/reference/response/user

- [ref-folders] · [ref-showcases] · [ref-videos] · [ref-users] · [ref-search] · [ref-teams] · [ref-auth-extras] · [ref-api-apps] · [ref-api-info]
- [schema-video] · [schema-project] · [schema-item] · [schema-album] · [schema-text-track] · [schema-picture] · [schema-version] · [schema-analytics] · [schema-webhook] · [schema-user]

Guias (developer.vimeo.com):

[guia-folders]: https://developer.vimeo.com/api/guides/folders
[guia-upload]: https://developer.vimeo.com/api/upload/videos
[guia-formatos]: https://developer.vimeo.com/api/common-formats
[guia-rate-limit]: https://developer.vimeo.com/guidelines/rate-limiting
[guia-interact]: https://developer.vimeo.com/api/guides/videos/interact
[guia-auth]: https://developer.vimeo.com/api/authentication
[guia-start]: https://developer.vimeo.com/api/guides/start
[guia-custom-metadata]: https://developer.vimeo.com/api/guides/custom-metadata
[guia-app-webhooks]: https://developer.vimeo.com/api/app-webhooks
[player-sdk]: https://github.com/vimeo/player.js

- [guia-folders] · [guia-upload] · [guia-formatos] · [guia-rate-limit] · [guia-interact] · [guia-auth] · [guia-start] · [guia-custom-metadata] · [guia-app-webhooks] (exige login) · [player-sdk]

Central de Ajuda (help.vimeo.com) e vimeo.com:

[ajuda-rate-limits]: https://help.vimeo.com/hc/en-us/articles/12427783954065-Rate-limits
[ajuda-transcode]: https://help.vimeo.com/hc/en-us/articles/12427776744593-Get-video-transcode-status-from-the-API
[ajuda-download]: https://help.vimeo.com/hc/en-us/articles/12427806914577-About-video-file-download-links-from-the-API
[ajuda-transcricoes-api]: https://help.vimeo.com/hc/en-us/articles/17480150130833-How-to-access-and-download-video-transcripts-via-API
[ajuda-analytics-api]: https://help.vimeo.com/hc/en-us/articles/21426264125969-How-to-access-the-Analytics-API
[ajuda-ai-api]: https://help.vimeo.com/hc/en-us/articles/45762682270097-How-to-use-the-Vimeo-AI-API
[ajuda-legendas-auto]: https://help.vimeo.com/hc/en-us/articles/21958502961937-FAQ-Automatic-closed-captions
[ajuda-folders-add]: https://help.vimeo.com/hc/en-us/articles/17144988474001-How-to-create-and-add-videos-to-folders
[ajuda-showcase-add]: https://help.vimeo.com/hc/en-us/articles/15004749856529-How-to-add-videos-to-a-showcase
[ajuda-versoes]: https://help.vimeo.com/hc/en-us/articles/12426058338961-How-to-manage-video-versions-and-access-history
[produto-replace]: https://vimeo.com/product/replace-video-files
[ajuda-dominio]: https://help.vimeo.com/hc/en-us/articles/30030693052305-How-do-I-set-up-domain-level-privacy
[ajuda-privacidade-api]: https://help.vimeo.com/hc/en-us/articles/12427776819089-How-to-use-the-API-to-customize-video-privacy-settings
[ajuda-planos]: https://help.vimeo.com/hc/en-us/articles/12425432033937-About-Vimeo-plans
[ajuda-oembed-privado]: https://help.vimeo.com/hc/en-us/articles/12427906892689-Use-oEmbed-with-private-videos
[ajuda-thumbs]: https://help.vimeo.com/hc/en-us/articles/12427892029585-Fix-Video-Thumbnails-in-Custom-Applications
[ajuda-token]: https://help.vimeo.com/hc/en-us/articles/12427891978641-Authentication-token-safety
[ajuda-armazenamento]: https://help.vimeo.com/hc/en-us/articles/26238558836881-What-is-the-difference-between-upload-quota-video-usage-and-total-storage
[ajuda-progresso]: https://help.vimeo.com/hc/en-us/articles/12427791654033-Generate-an-upload-progress-bar
[ajuda-upload-navegador]: https://help.vimeo.com/hc/en-us/articles/12427751730449-Upload-videos-from-a-client-or-web-browser
[ajuda-upload-api]: https://help.vimeo.com/hc/en-us/articles/22366164249105-How-to-upload-videos-by-using-the-Vimeo-API
[ajuda-player-sdk]: https://help.vimeo.com/hc/en-us/articles/12427952387601-Overview-Player-SDK

- [ajuda-rate-limits] · [ajuda-transcode] · [ajuda-download] · [ajuda-transcricoes-api] · [ajuda-analytics-api] · [ajuda-ai-api] · [ajuda-legendas-auto] · [ajuda-folders-add] · [ajuda-showcase-add] · [ajuda-versoes] · [produto-replace] · [ajuda-dominio] · [ajuda-privacidade-api] · [ajuda-planos] · [ajuda-oembed-privado] · [ajuda-thumbs] · [ajuda-token] · [ajuda-armazenamento] · [ajuda-progresso] · [ajuda-upload-navegador] · [ajuda-upload-api] · [ajuda-player-sdk]
