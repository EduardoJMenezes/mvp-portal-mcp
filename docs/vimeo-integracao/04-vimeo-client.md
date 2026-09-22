# 04 — Interface do cliente Vimeo

> Documento 4 do §71. Só entram métodos que a
> [matriz](01-matriz-de-capacidades.md) confirmou como suportados. O que depende
> de plano Enterprise ou de POC fica separado no fim, fora das interfaces base.

## Decisões de desenho

- **Três clientes, três tokens.** Leitura (`public private`), escrita (`public private create edit interact`) e upload (`public private upload edit`). Nenhum token tem `delete`.
- **Nenhum método de exclusão**, embora a API permita (gap 14). Tirar um vídeo de uma pasta é mover para outra pasta (POC W5).
- **Nomes em português**, como o resto do repositório. Tabela de correspondência com a especificação:

| Especificação (§71) | Proposto | Endpoint |
|---|---|---|
| `list_folders` | `iterar_pastas` | `GET /users/{uid}/projects` |
| `get_folder` | `obter_pasta` | `GET /users/{uid}/projects/{id}` |
| `iter_folder_videos` | `iterar_videos_da_pasta` | `GET /users/{uid}/projects/{id}/videos` |
| `get_video` | `obter_video` | `GET /videos/{id}` |
| `search_videos` | `iterar_videos_da_conta(busca=…)` | `GET /users/{uid}/videos?query=…` |
| `get_transcript` | `listar_faixas_de_texto` + `obter_transcricao` | `GET /videos/{id}/texttracks` e `GET /videos/{id}/transcripts/{tt}` |
| `get_analytics` | `consultar_analytics` (só Enterprise) | `GET /users/{uid}/analytics` |
| `upload_video` | `iniciar_upload_tus`, `iniciar_upload_pull` | `POST /users/{uid}/videos` |
| `replace_video` | `iniciar_nova_versao_tus`, `iniciar_nova_versao_pull` | `POST /videos/{id}/versions` |

## Tipos

```python
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Direcao = Literal["asc", "desc"]
OrdemPastas = Literal["date", "default", "modified_time", "name", "pinned_on"]
OrdemItens = Literal["alphabetical", "date", "default", "duration", "last_user_action_event_date"]
OrdemVideosDaConta = Literal[
    "alphabetical", "date", "default", "duration",
    "last_user_action_event_date", "likes", "modified_time", "plays",
]
OrdemVideosDoShowcase = Literal[
    "alphabetical", "comments", "date", "default", "duration",
    "likes", "manual", "modified_time", "plays",
]
TipoItem = Literal["folder", "live_event", "video"]
PrivacidadeView = Literal["anybody", "disable", "nobody", "password", "unlisted"]
PrivacidadeEmbed = Literal["private", "public", "whitelist"]


@dataclass(frozen=True)
class LimiteDeRequisicoes:
    limite: int              # X-RateLimit-Limit
    restante: int            # X-RateLimit-Remaining
    reinicia_em: datetime    # X-RateLimit-Reset


@dataclass(frozen=True)
class ContaVimeo:
    uri: str
    nome: str
    plano: str                    # membership (formato confirmado na POC R1)
    tem_acesso_de_upload: bool    # upload_quota presente em GET /me


@dataclass(frozen=True)
class PastaVimeo:
    uri: str                         # /users/{uid}/projects/{id}
    nome: str
    pai_uri: str | None              # metadata.connections.parent_folder.uri
    ancestrais: list[str]            # metadata.connections.ancestor_path[].uri, do pai para cima
    tem_subpasta: bool               # has_subfolder
    total_videos: int                # metadata.connections.videos.total
    total_videos_com_subpastas: int  # metadata.connections.videos.deep_total
    modificada_em: datetime          # modified_time


@dataclass(frozen=True)
class ItemDePasta:
    tipo: Literal["folder", "live_event", "showcase", "video"]
    uri: str
    nome: str


@dataclass(frozen=True)
class VideoVimeo:
    uri: str                         # /videos/{id}: a chave canônica
    nome: str
    descricao: str | None
    duracao_segundos: int
    link: str
    player_embed_url: str            # guardar como veio (unlisted leva o hash `h`)
    thumbnail_base_link: str | None  # pictures.base_link
    status: str                      # available, transcoding, uploading_error, …
    transcode_status: str | None     # complete, error, in_progress
    reproduzivel: bool               # is_playable
    privacidade_view: str
    privacidade_embed: str
    transcricao_status: str | None   # transcript.status
    pasta_uri: str | None            # parent_project
    versao_atual_uri: str | None     # metadata.connections.versions.current_uri
    resource_key: str
    criado_em: datetime
    modificado_em: datetime
    em_cold_storage: bool            # is_cold_storage
    privacidade_suprimida: bool      # is_cold_privacy_restricted


@dataclass(frozen=True)
class VersaoVimeo:
    uri: str
    arquivo_nome: str       # filename
    arquivo_tamanho: int    # filesize
    duracao_segundos: int
    ativa: bool             # active
    enviada_em: datetime    # upload_date
    transcode_status: str | None


@dataclass(frozen=True)
class FaixaDeTexto:
    id: int
    tipo: Literal["captions", "descriptions", "subtitles"]
    idioma: str
    origem: str                         # provenance: autogen_source_audio, user_uploaded, …
    ativa: bool
    link_vtt: str | None                # download_links.vtt
    links_expiram_em: datetime | None   # download_links_expires_time


@dataclass(frozen=True)
class TicketDeUpload:
    video_uri: str
    upload_link: str     # o próprio link autoriza o PATCH; não é o token


@dataclass(frozen=True)
class ProgressoDeUpload:
    offset: int          # Upload-Offset
    tamanho: int         # Upload-Length
```

## Erros

| Classe | Quando | Retentável |
|---|---|---|
| `VimeoCredencialInvalida` | 401, `error_code` 8000 | não |
| `VimeoSemPermissao` | 403 | não |
| `VimeoNaoEncontrado` | 404, `error_code` 5000 | não |
| `VimeoParametroInvalido` | 400, `error_code` 2204 | não |
| `VimeoConflitoDeOffset` | 409 no `PATCH` tus | depois de um `HEAD` |
| `VimeoLimiteDeRequisicoes` | 429, `error_code` 9000 | sim, após `X-RateLimit-Reset` |
| `VimeoIndisponivel` | 502, 503, 504, timeout | sim |

Todas herdam de `VimeoErro(codigo, status_http, error_code, retentavel)`. O `developer_message` do Vimeo vai para o log; a mensagem que chega ao professor é nossa.

## Leitura (Fase 1)

```python
class VimeoLeitura(Protocol):
    """Só GET e HEAD. Token: public private."""

    ultimo_limite: LimiteDeRequisicoes | None

    async def verificar_token(self) -> bool:
        """GET /oauth/verify."""

    async def obter_conta(self) -> ContaVimeo:
        """GET /me?fields=uri,name,membership,upload_quota."""

    def iterar_pastas(
        self, *, busca: str | None = None, ordem: OrdemPastas = "default",
        direcao: Direcao | None = None,
    ) -> AsyncIterator[PastaVimeo]:
        """GET /users/{uid}/projects, 100 por página."""

    async def obter_pasta(self, pasta_id: str) -> PastaVimeo:
        """GET /users/{uid}/projects/{id}. 404 vira VimeoNaoEncontrado."""

    def iterar_itens_da_pasta(
        self, pasta_id: str, *, tipo: TipoItem | None = None,
        ordem: OrdemItens = "default", direcao: Direcao | None = None,
    ) -> AsyncIterator[ItemDePasta]:
        """GET /users/{uid}/projects/{id}/items."""

    def percorrer_arvore(
        self, pasta_raiz_id: str, *, profundidade_maxima: int = 10,
    ) -> AsyncIterator[tuple[int, PastaVimeo]]:
        """Composição de iterar_itens_da_pasta(tipo="folder"); devolve (profundidade, pasta)."""

    def iterar_videos_da_pasta(
        self, pasta_id: str, *, incluir_subpastas: bool = False,
        busca: str | None = None, ordem: OrdemItens = "default",
        direcao: Direcao | None = None,
    ) -> AsyncIterator[VideoVimeo]:
        """GET /users/{uid}/projects/{id}/videos (include_subfolders, query, sort)."""

    async def obter_video(self, video_id: str) -> VideoVimeo:
        """GET /videos/{id}. 404 vira VimeoNaoEncontrado."""

    def iterar_videos_da_conta(
        self, *, busca: str | None = None,
        campos_de_busca: Sequence[Literal["chapters", "description", "tags", "title"]] | None = None,
        ordem: OrdemVideosDaConta = "default", direcao: Direcao | None = None,
        modificados_desde: datetime | None = None,
    ) -> AsyncIterator[VideoVimeo]:
        """GET /users/{uid}/videos. `modificados_desde` envia If-Modified-Since."""

    async def listar_versoes(self, video_id: str) -> list[VersaoVimeo]:
        """GET /videos/{id}/versions."""

    async def listar_faixas_de_texto(self, video_id: str) -> list[FaixaDeTexto]:
        """GET /videos/{id}/texttracks. Exige token do dono do vídeo."""

    async def obter_transcricao(self, video_id: str, faixa_id: int) -> dict:
        """GET /videos/{id}/transcripts/{texttrack_id}. Vira DTO depois da POC R12."""

    async def listar_dominios_de_embed(self, video_id: str) -> list[str]:
        """GET /videos/{id}/privacy/domains."""

    def iterar_videos_do_showcase(
        self, showcase_id: str, *, ordem: OrdemVideosDoShowcase = "manual",
    ) -> AsyncIterator[VideoVimeo]:
        """GET /users/{uid}/albums/{album_id}/videos."""
```

## Escrita (Fase 4)

```python
class VimeoEscrita(Protocol):
    """Token: public private create edit interact. Sem delete."""

    async def criar_pasta(self, nome: str, *, pai_uri: str | None = None) -> PastaVimeo:
        """POST /users/{uid}/projects (parent_folder_uri para subpasta)."""

    async def renomear_pasta(self, pasta_id: str, nome: str) -> PastaVimeo:
        """PATCH /users/{uid}/projects/{id}."""

    async def mover_video_para_pasta(self, video_id: str, pasta_destino_id: str) -> None:
        """PUT /users/{uid}/projects/{destino}/videos/{video_id}.
        Que isso move (e não duplica nem falha) é confirmado na POC W5."""

    async def atualizar_metadados(
        self, video_id: str, *, nome: str | None = None, descricao: str | None = None,
    ) -> VideoVimeo:
        """PATCH /videos/{id}."""

    async def definir_privacidade(
        self, video_id: str, *, view: PrivacidadeView, embed: PrivacidadeEmbed,
    ) -> VideoVimeo:
        """PATCH /videos/{id}. `disable` e `unlisted` exigem plano Starter ou superior."""

    async def permitir_dominio(self, video_id: str, dominio: str) -> None:
        """PUT /videos/{id}/privacy/domains/{domain}, sem http://."""

    async def remover_dominio(self, video_id: str, dominio: str) -> None:
        """DELETE /videos/{id}/privacy/domains/{domain}. Escopo edit; não apaga conteúdo."""

    async def definir_tags(self, video_id: str, tags: Sequence[str]) -> None:
        """PUT /videos/{id}/tags."""

    async def criar_showcase(self, nome: str) -> str:
        """POST /users/{uid}/albums. Devolve a URI."""

    async def incluir_video_no_showcase(self, showcase_id: str, video_id: str) -> None:
        """PUT /users/{uid}/albums/{album_id}/videos/{video_id}."""

    async def retirar_video_do_showcase(self, showcase_id: str, video_id: str) -> None:
        """DELETE /users/{uid}/albums/{album_id}/videos/{video_id}. Escopo edit; o vídeo continua na conta."""

    async def substituir_videos_do_showcase(self, showcase_id: str, video_ids: Sequence[str]) -> None:
        """PUT /users/{uid}/albums/{album_id}/videos.
        Se a ordem da lista vira a ordem manual é confirmado na POC W8."""
```

## Upload (Fase 5)

```python
class VimeoUpload(Protocol):
    """Token: public private upload edit."""

    async def iniciar_upload_tus(
        self, tamanho_bytes: int, *, nome: str, pasta_uri: str | None = None,
        view: PrivacidadeView = "nobody",
    ) -> TicketDeUpload:
        """POST /users/{uid}/videos com upload.approach=tus. Já cria o vídeo."""

    async def iniciar_upload_pull(
        self, url_do_arquivo: str, tamanho_bytes: int, *, nome: str | None = None,
        pasta_uri: str | None = None, view: PrivacidadeView = "nobody",
    ) -> VideoVimeo:
        """POST /users/{uid}/videos com upload.approach=pull (URL assinada válida por 6 h ou mais)."""

    async def iniciar_nova_versao_tus(
        self, video_id: str, tamanho_bytes: int, nome_do_arquivo: str,
    ) -> TicketDeUpload:
        """POST /videos/{id}/versions com upload.approach=tus. Mantém ID e URL."""

    async def iniciar_nova_versao_pull(
        self, video_id: str, url_do_arquivo: str, tamanho_bytes: int, nome_do_arquivo: str,
    ) -> VersaoVimeo:
        """POST /videos/{id}/versions com upload.approach=pull."""

    async def consultar_progresso(self, upload_link: str) -> ProgressoDeUpload:
        """HEAD {upload_link} com Tus-Resumable: 1.0.0."""

    async def enviar_bloco(self, upload_link: str, offset: int, dados: bytes) -> int:
        """PATCH {upload_link}; devolve o novo Upload-Offset. 409 vira VimeoConflitoDeOffset."""
```

## Condicionais: fora das interfaces base

Só são implementados se a POC ou o plano da conta liberarem.

| Método | Endpoint | Condição |
|---|---|---|
| `consultar_analytics(dimensao, de, ate, intervalo, conteudo_uris)` | `GET /users/{uid}/analytics` (escopo `stats`) | Enterprise, com liberação do suporte |
| `iniciar_transcricao_ia(video_id, idioma=None)` e `status_transcricao_ia(video_id)` | `POST` e `GET /videos/{id}/ai/transcribe` (escopo `ai`) | Enterprise e créditos de IA |
| `busca_federada(busca, ...)` | `GET /search/{uid}/items` | Plano confirmado |
| `listar_webhooks`, `criar_webhook`, `desativar_webhook` | `/apps/{app_id}/webhooks` | POC H1–H4 |
| `definir_metadado_customizado(video_id, campos)` | `PUT /videos/{id}/custom_metadata` | POC W11 (recurso de time) |

## Conjuntos de `fields`

Lista inicial, validada na POC (R4, R8). Todo GET usa um desses conjuntos: isso dobra a cota de rate limit.

```python
CAMPOS_CONTA = "uri,name,membership,upload_quota"

CAMPOS_PASTA = (
    "uri,name,modified_time,has_subfolder,"
    "metadata.connections.parent_folder,metadata.connections.ancestor_path,"
    "metadata.connections.videos.total,metadata.connections.videos.deep_total,"
    "metadata.connections.folders.total"
)

# A sintaxe aninhada em /items é confirmada na POC R4.
CAMPOS_ITEM_DE_PASTA = "type,folder.uri,folder.name,video.uri,video.name"

CAMPOS_VIDEO_IMPORTACAO = (
    "uri,name,description,duration,link,player_embed_url,pictures.base_link,"
    "status,transcode.status,is_playable,privacy.view,privacy.embed,"
    "transcript.status,transcript.language,parent_project,resource_key,"
    "created_time,modified_time,is_cold_storage,is_cold_privacy_restricted,"
    "metadata.connections.versions.current_uri"
)

CAMPOS_VIDEO_SYNC = (
    "uri,name,duration,pictures.base_link,status,transcode.status,is_playable,"
    "privacy.view,privacy.embed,transcript.status,modified_time,"
    "is_cold_storage,is_cold_privacy_restricted,metadata.connections.versions.current_uri"
)

CAMPOS_VERSAO = "uri,filename,filesize,duration,active,upload_date,transcode.status"

CAMPOS_FAIXA_DE_TEXTO = "id,type,language,provenance,active,download_links,download_links_expires_time"
```
