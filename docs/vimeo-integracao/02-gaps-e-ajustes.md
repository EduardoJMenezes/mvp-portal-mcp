# 02 — Gaps, arquitetura × API real e ajustes

> Documento 2 do §71. Baseado na [matriz de capacidades](01-matriz-de-capacidades.md);
> os códigos entre parênteses (A7, E4…) apontam para as linhas de lá.

## Veredito

**O objetivo é atingível com a Vimeo REST API.** O núcleo da especificação tem endpoint oficial documentado:

- descobrir o acervo com subpastas;
- importar milhares de vídeos com paginação;
- manter a identidade por `vimeo_video_id`;
- detectar vídeo removido ou inacessível;
- respeitar o rate limit;
- incorporar o vídeo com privacidade por domínio;
- fazer upload e substituir o arquivo.

Cinco pontos mudam o desenho:

1. **Pastas não têm ordem manual na API** (A7). A ordem da importação precisa vir da convenção de nomes, de revisão humana ou de um showcase com até 100 vídeos.
2. **Transcrição tem restrição de data e de plano** (E4, E5). Vídeos enviados antes de 25/05/2022 não ganham legenda automática, e gerar sob demanda só é possível no Enterprise. O acervo começa em 2022.
3. **Analytics do Vimeo é exclusivo do Enterprise** (G2). A métrica pedagógica de vídeo deve nascer do Player SDK.
4. **Webhooks são ambíguos** (G1). A base precisa ser polling com reconciliação; webhook vira otimização se a POC confirmar.
5. **Privacidade de embed depende do plano** (D1, D2). O ideal do §26 ("não listado + embed só nos nossos domínios") exige no mínimo o plano Starter.

## Gaps: o que a API não entrega e o que faremos

| # | A API não expõe ou limita | Impacto | O que faremos | Fase | Fonte |
|---|---|---|---|---|---|
| 1 | Ordem manual dos vídeos em pastas (A7) | **Alto** (§36, `preserve_order` do §52) | Ordem inferida por `VimeoNamingStrategy` (número no título), com confiança exibida no preview e revisão humana antes de aprovar. A POC (R5) verifica se `sort=default` reproduz a ordem da interface. Opcional: ler a ordem de um showcase `arranged` quando o capítulo tiver até 100 vídeos | 1–2 | [ref-folders], [ajuda-showcase-add] |
| 2 | Um vídeo em várias pastas (A8) | Confirma o §5 | A organização anual fica só no PostgreSQL, como a especificação já prevê | — | [ajuda-folders-add] |
| 3 | Legenda automática para vídeos enviados antes de 25/05/2022 (E4) | **Alto** para §28–29 | Medir na POC (R9) quantos vídeos não têm `transcript.status=completed`. Caminhos: (a) AI API, se Enterprise; (b) testar se uma nova versão do mesmo arquivo (`POST /videos/{id}/versions`) gera a legenda, preservando o ID; (c) transcrição própria a partir do arquivo (`video_files`, Standard ou superior). **Nunca reenviar como vídeo novo**: isso troca o ID | 6 | [ajuda-legendas-auto], [ajuda-ai-api], [ajuda-download] |
| 4 | Analytics só no Enterprise (G2) | Médio (§30, §59) | Eventos do Player SDK gravados no nosso banco como fonte principal; analytics do Vimeo só como complemento se o plano permitir | 7 | [ajuda-analytics-api] |
| 5 | Webhooks ambíguos (G1) | Médio (§32–33) | Polling incremental e job de reconciliação como base. Inbox de eventos só depois da POC H1–H4 | 3 / 8 | [ref-api-apps], [ajuda-transcode] |
| 6 | Nenhum hash de arquivo (B13) | Baixo (§39) | Candidatos a duplicata por `filename` + `filesize` + `duration` da versão ativa, sempre com confirmação humana | 6 | [schema-version] |
| 7 | Sem ETag; `If-Modified-Since` só em `/users/{uid}/videos` (H6) | Médio (§18–19) | Sync incremental por `GET /users/{uid}/videos?sort=modified_time&direction=desc`, parando no último `modified_time` conhecido; sync completo periódico; o snapshot no PostgreSQL é o cache principal | 3 | [guia-formatos], [ref-videos] |
| 8 | `Retry-After` não documentado (H4) | Baixo | Esperar até `X-RateLimit-Reset`, com jitter e teto de tentativas | 1 | [guia-rate-limit] |
| 9 | Sem refresh token; token inativo é apagado (H1, H2) | Médio | Verificação diária com `GET /oauth/verify`, status da conexão visível no admin e procedimento de troca de token | 1 | [guia-auth] |
| 10 | URL de thumbnail não deve ser cacheada (B11) | Baixo | Guardar `base_link` e renovar no sync | 3 | [ajuda-thumbs] |
| 11 | Acesso de upload pode exigir pedido (F5) | Médio (§22) | Pedir cedo; confirmar na POC (R1, U1) pela presença de `upload_quota`. Plano B: upload manual no Vimeo seguido de importação | 5 | [guia-upload], [schema-user] |
| 12 | Busca federada provavelmente restrita ao Enterprise (B4) | Baixo (§40) | Busca própria no PostgreSQL sobre o snapshot; o `query` do Vimeo fica para consultas pontuais | 1 | [ajuda-planos] |
| 13 | `/tags/{word}/videos` só retorna vídeos públicos (B5) | Baixo (§41) | Usar `filter_tag` nas listagens do usuário e das pastas | 4 | [ref-videos] |
| 14 | Endpoints destrutivos com efeito colateral (A12, A13) | **Alto** (segurança) | Nenhum cliente nosso implementa exclusão; allowlist de método + caminho no transporte; token de escrita sem o escopo `delete`. Tirar um vídeo de uma pasta será "mover para outra pasta" (POC W5) | 4 | [guia-folders] |
| 15 | Não está documentado se incluir numa pasta move o vídeo (A11) | Médio | POC W5 | 4 | [ref-folders] |
| 16 | Privacidade e domínios dependem do plano, com documentação conflitante (D1, D2) | **Alto** para §26 | Confirmar o plano (`membership`) e testar em vídeo descartável com o domínio do Railway e `localhost` (POC W7) | 1 | [guia-interact], [ajuda-planos], [ajuda-dominio] |
| 17 | CORS do `upload_link` não documentado (F2) | Médio (upload do navegador) | POC U4. Plano B: tus pelo backend ou pull a partir de storage próprio com URL assinada válida por pelo menos 6 h | 5 | [guia-upload] |
| 18 | Proteção contra compartilhamento limitada às opções de privacidade (D4) | Médio | Aceitar o limite: `disable` impede ver no vimeo.com e `whitelist` impede embutir fora dos nossos domínios. Um link com hash pode vazar, mas só toca onde o embed é permitido (validar em W7) | 1 | [ajuda-privacidade-api] |
| 19 | Estabilidade do ID ao renomear não declarada (B8) | Baixo | POC W6 | 1 | [ref-videos] |
| 20 | Não há curva de retenção por segundo (G3) | Baixo | Player SDK (`timeupdate`, `seeked`, `ended`) | 7 | [schema-analytics] |

## Arquitetura proposta × limites reais

| Seção | Situação real | Decisão |
|---|---|---|
| §2 — MCP de negócio sobre `VimeoClient` | Compatível | Manter |
| §3 — PostgreSQL como fonte de verdade | Reforçado por A7 e A8 | Manter |
| §5, §34, §35 — pastas e subpastas | Subpastas suportadas: `items`, `ancestor_path`, `deep_total`, `include_subfolders` | Manter `subfolders_as_chapters`, validando a contagem com `deep_total` |
| §13 — identidade por `vimeo_video_id` e `uri` | Estável ao substituir e ao mover | Manter; guardar também `resource_key` |
| §14 — importação idempotente | Viável | Manter; UPSERT por `vimeo_id` (já é único em `videos`) |
| §15 — paginação | `per_page` ≤ 100 e `paging.next` | Manter o iterador assíncrono |
| §16 — rate limit | Por usuário e minuto; 429 com erro 9000; headers `X-RateLimit-*` | Ajustar: esperar pelo `X-RateLimit-Reset` (não existe `Retry-After`) |
| §17 — `fields` | Dobra a cota efetiva | Tornar obrigatório por teste automatizado |
| §18 — cache | Condicional só numa listagem; sem ETag | Ajustar: o snapshot no PostgreSQL é o cache |
| §19 — sync | Viável | Ajustar: incremental por `modified_time` |
| §20 — reconciliação | Viável, com mais estados que os previstos | Ajustar: ver o mapeamento abaixo |
| §21 — jobs | Necessários para sync, reconciliação e transcrições | Manter. A varredura de 3.000 vídeos custa cerca de 30 requisições e pode rodar inline; chamadas por vídeo (versões, faixas de texto) vão para job |
| §22–23 — upload e replace | Suportados | Ajustar: condicionados ao acesso de upload e ao CORS |
| §24 — transcode | `status`, `transcode.status`, `is_playable` | Bloquear publicação se `is_playable=false` ou `status≠available` |
| §25 — thumbnails | Suportado; não cachear URL | Renovar no sync |
| §26 — embed e privacidade | `disable` + `whitelist` + domínios | 💳 Confirmar o plano antes |
| §27 — Player SDK | Suportado; unlisted exige `url` com `h` | Manter |
| §28–29 — transcrições e busca semântica | Leitura suportada; geração limitada | Fase condicionada à POC (R9, R12, U5) |
| §30 — analytics do Vimeo | Só Enterprise | Player SDK primeiro |
| §32–33 — webhooks | Ambíguo | Opcional, depois da POC |
| §10–11 — autenticação | Token pessoal ou OAuth, sem refresh token | Credenciais separadas por finalidade (leitura, escrita, upload), cada uma com o escopo mínimo; verificação periódica |
| §47–49 — erros, retry, timeout | Compatível | Acrescentar os códigos 2204, 5000, 8000, 9000 e o 409 do tus |
| §56 — multi-tenancy | OAuth com um token por conta | Manter `VimeoConnection` por organização |

## Mapeamento de estados para a reconciliação (§20)

| Estado | Regra | Fonte |
|---|---|---|
| `OK` | `GET /videos/{id}` com 200, `status=available`, `is_playable=true` e privacidade igual à aprovada | [schema-video] |
| `MISSING` | 404 | [ref-videos] |
| `NO_ACCESS` | 401 ou 403 (a POC confirma qual aparece) | R17 |
| `TRANSCODING` | `status` em `uploading`, `transcode_starting`, `transcoding` ou `processing`, ou `transcode.status=in_progress` | [schema-video] |
| `ERROR` | `status` em `uploading_error`, `transcoding_error`, `failed` ou `unavailable`, ou `transcode.status=error` | [schema-video] |
| `QUOTA_EXCEEDED` | `status` em `quota_exceeded` ou `total_cap_exceeded` | [schema-video] |
| `PRIVACY_CHANGED` | `privacy.view` ou `privacy.embed` diferente do aprovado, ou nosso domínio fora de `privacy/domains` | [schema-video], [ref-videos] |
| `PRIVACY_SUPPRESSED` | `is_cold_privacy_restricted=true` | [schema-video] |
| `COLD_STORAGE` | `is_cold_storage=true` | [schema-video] |
| `REPLACED` | `metadata.connections.versions.current_uri` diferente do snapshot | [schema-video] |

Nenhum estado apaga dado pedagógico. Todos marcam o vídeo e pedem ação humana.

## Dependências de plano

| Recurso | Free | Starter | Standard | Advanced | Enterprise | Fonte |
|---|---|---|---|---|---|---|
| Requisições/min, sem `fields` | 25 | 125 | 250 | 750 | 2.500 | [guia-rate-limit] |
| `unlisted` e `disable` (só embed) | ❌ | ✅ | ✅ | ✅ | não citado | [guia-interact] |
| Embed restrito a domínios | ❌ | ✅ | ✅ | ✅ | ✅ | [ajuda-planos] (conflita com [ajuda-dominio]) |
| Legenda automática e transcrições | ❌ | ⚠️ conflito | ✅ | ✅ | ✅ | [ajuda-planos], [ajuda-legendas-auto] |
| Links de arquivo (`video_files`) | ❌ | ❌ | ✅ | ✅ | ✅ | [ajuda-download] |
| Colaboração em pastas | ❌ | ❌ | ✅ | ✅ | não citado | [guia-folders] |
| Analytics API | ❌ | ❌ | ❌ | ❌ | ✅, com liberação | [ajuda-analytics-api] |
| AI API (transcrição sob demanda) | ❌ | ❌ | ❌ | ❌ | ✅ | [ajuda-ai-api] |
| Search API | ❌ | ❌ | ❌ | ❌ | ✅ | [ajuda-planos] |

## Decisões pendentes

1. **Qual é o plano da conta Vimeo do professor, e ela é conta de time?** Isso decide D1, D2, E4, B14 e o rate limit.
2. **Como o acervo está organizado hoje?** Pastas por turma e capítulo, subpastas e a convenção de títulos (por exemplo "Q01 - …").
3. **A ordem inferida pelo título, com revisão humana, é aceitável como padrão da importação?**
4. **Transcrições:** qual caminho seguir para os vídeos anteriores a 25/05/2022, depois de medir quantos são (POC R9)?
5. **Nomes no código:** a especificação usa inglês (`VideoAsset`, `QuestionVideo`), mas o `CLAUDE.md` pede o domínio em português. Proposta: português no domínio e inglês só onde o código espelha a API do Vimeo.
6. **Migrações:** introduzir Alembic antes da Fase 2. O banco do Railway já tem dados, o `create_all` não altera tabelas existentes e `--reset` apaga tudo.

[ref-folders]: https://developer.vimeo.com/api/reference/folders
[ref-videos]: https://developer.vimeo.com/api/reference/videos
[ref-api-apps]: https://developer.vimeo.com/api/reference/api-apps
[schema-video]: https://developer.vimeo.com/api/reference/response/video
[schema-version]: https://developer.vimeo.com/api/reference/response/video-version
[schema-analytics]: https://developer.vimeo.com/api/reference/response/analytics
[schema-user]: https://developer.vimeo.com/api/reference/response/user
[guia-folders]: https://developer.vimeo.com/api/guides/folders
[guia-upload]: https://developer.vimeo.com/api/upload/videos
[guia-formatos]: https://developer.vimeo.com/api/common-formats
[guia-rate-limit]: https://developer.vimeo.com/guidelines/rate-limiting
[guia-interact]: https://developer.vimeo.com/api/guides/videos/interact
[guia-auth]: https://developer.vimeo.com/api/authentication
[ajuda-transcode]: https://help.vimeo.com/hc/en-us/articles/12427776744593-Get-video-transcode-status-from-the-API
[ajuda-download]: https://help.vimeo.com/hc/en-us/articles/12427806914577-About-video-file-download-links-from-the-API
[ajuda-analytics-api]: https://help.vimeo.com/hc/en-us/articles/21426264125969-How-to-access-the-Analytics-API
[ajuda-ai-api]: https://help.vimeo.com/hc/en-us/articles/45762682270097-How-to-use-the-Vimeo-AI-API
[ajuda-legendas-auto]: https://help.vimeo.com/hc/en-us/articles/21958502961937-FAQ-Automatic-closed-captions
[ajuda-folders-add]: https://help.vimeo.com/hc/en-us/articles/17144988474001-How-to-create-and-add-videos-to-folders
[ajuda-showcase-add]: https://help.vimeo.com/hc/en-us/articles/15004749856529-How-to-add-videos-to-a-showcase
[ajuda-dominio]: https://help.vimeo.com/hc/en-us/articles/30030693052305-How-do-I-set-up-domain-level-privacy
[ajuda-privacidade-api]: https://help.vimeo.com/hc/en-us/articles/12427776819089-How-to-use-the-API-to-customize-video-privacy-settings
[ajuda-planos]: https://help.vimeo.com/hc/en-us/articles/12425432033937-About-Vimeo-plans
[ajuda-thumbs]: https://help.vimeo.com/hc/en-us/articles/12427892029585-Fix-Video-Thumbnails-in-Custom-Applications
