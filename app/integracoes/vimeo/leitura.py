"""Cliente de leitura do Vimeo (Fase 1).

Só GET e HEAD, com token de escopos `public private`. Cada método aponta o
endpoint que usa e a linha da matriz de capacidades
(`docs/vimeo-integracao/01-matriz-de-capacidades.md`) que o sustenta.

O que **não** existe aqui, de propósito: nada que crie, altere ou apague coisa
no Vimeo. Escrita e upload entram em módulos próprios, depois da POC.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.utils import format_datetime

from app.integracoes.vimeo.campos import (
    CAMPOS_CONTA,
    CAMPOS_FAIXA_DE_TEXTO,
    CAMPOS_ITEM_DE_PASTA,
    CAMPOS_PASTA,
    CAMPOS_THUMBNAIL,
    CAMPOS_VERSAO,
    CAMPOS_VIDEO_IMPORTACAO,
    CAMPOS_VIDEO_SYNC,
)
from app.integracoes.vimeo.erros import VimeoCredencialInvalida, VimeoNaoEncontrado
from app.integracoes.vimeo.modelos import (
    ContaVimeo,
    FaixaDeTexto,
    ItemDePasta,
    LimiteDeRequisicoes,
    PastaVimeo,
    ThumbnailVimeo,
    VersaoVimeo,
    VideoVimeo,
    id_do_uri,
)
from app.integracoes.vimeo.transporte import TransporteVimeo

# O Vimeo permite subpasta até 10 níveis (guia oficial de folders).
PROFUNDIDADE_MAXIMA = 10


@dataclass(frozen=True)
class NoDaArvore:
    """Uma pasta e a que distância ela está da raiz que pedimos."""

    profundidade: int
    pasta: PastaVimeo


class ClienteVimeoLeitura:
    """Leitura do acervo. `usuario` é `me` ou o id do dono do time."""

    def __init__(self, transporte: TransporteVimeo, *, usuario: str = "me") -> None:
        self._t = transporte
        self._prefixo = "/me" if usuario in ("me", "", None) else f"/users/{usuario}"

    @property
    def limite(self) -> LimiteDeRequisicoes | None:
        return self._t.ultimo_limite

    # --- conta ----------------------------------------------------------------

    async def verificar_token(self) -> bool:
        """`GET /oauth/verify` (H1). Usado pelo job diário: token inativo é apagado pelo Vimeo."""
        try:
            await self._t.get("/oauth/verify", permitir_sem_campos=True)
        except VimeoCredencialInvalida:
            return False
        return True

    async def obter_conta(self) -> ContaVimeo:
        """`GET /me` (H10). `upload_quota` só aparece quando há acesso de upload."""
        corpo = await self._t.get(self._prefixo, campos=CAMPOS_CONTA)
        return ContaVimeo.de_payload(corpo or {})

    # --- pastas ---------------------------------------------------------------

    async def iterar_pastas(
        self,
        *,
        busca: str | None = None,
        ordem: str = "default",
        direcao: str | None = None,
        campos: str = CAMPOS_PASTA,
        maximo_paginas: int = 100,
    ) -> AsyncIterator[PastaVimeo]:
        """`GET {prefixo}/projects` (A1, A3). Escopo `private`."""
        async for bruto in self._t.paginar(
            f"{self._prefixo}/projects",
            campos=campos,
            maximo_paginas=maximo_paginas,
            query=busca,
            sort=ordem,
            direction=direcao,
        ):
            yield PastaVimeo.de_payload(bruto)

    async def listar_pastas(self, **kwargs) -> list[PastaVimeo]:
        return [pasta async for pasta in self.iterar_pastas(**kwargs)]

    async def obter_pasta(self, pasta_id: str, *, campos: str = CAMPOS_PASTA) -> PastaVimeo:
        """`GET {prefixo}/projects/{id}` (A2). 404 com `error_code` 5000 quando não existe."""
        corpo = await self._t.get(f"{self._prefixo}/projects/{pasta_id}", campos=campos)
        if not corpo:
            raise VimeoNaoEncontrado("A pasta não existe mais no Vimeo.", status=404)
        return PastaVimeo.de_payload(corpo)

    async def iterar_itens_da_pasta(
        self,
        pasta_id: str,
        *,
        tipo: str | None = None,
        ordem: str = "default",
        direcao: str | None = None,
        campos: str = CAMPOS_ITEM_DE_PASTA,
        maximo_paginas: int = 100,
    ) -> AsyncIterator[ItemDePasta]:
        """`GET {prefixo}/projects/{id}/items` (A5). `tipo` aceita folder, video e live_event."""
        async for bruto in self._t.paginar(
            f"{self._prefixo}/projects/{pasta_id}/items",
            campos=campos,
            maximo_paginas=maximo_paginas,
            filter=tipo,
            sort=ordem,
            direction=direcao,
        ):
            yield ItemDePasta.de_payload(bruto)

    async def percorrer_arvore(
        self, pasta_raiz_id: str, *, profundidade_maxima: int = PROFUNDIDADE_MAXIMA
    ) -> list[NoDaArvore]:
        """Monta a árvore de subpastas compondo `items?filter=folder` (A4, A5).

        A API não expõe árvore pronta. A raiz não entra no resultado; o retorno
        vem em largura, então a ordem já serve para montar capítulos.
        """
        encontradas: list[NoDaArvore] = []
        vistas: set[str] = set()
        fila: list[tuple[int, str]] = [(1, str(pasta_raiz_id))]
        while fila:
            profundidade, pasta_id = fila.pop(0)
            if profundidade > max(1, min(profundidade_maxima, PROFUNDIDADE_MAXIMA)):
                continue
            async for item in self.iterar_itens_da_pasta(pasta_id, tipo="folder"):
                pasta = item.pasta
                if pasta is None or not pasta.uri or pasta.uri in vistas:
                    continue
                vistas.add(pasta.uri)
                encontradas.append(NoDaArvore(profundidade=profundidade, pasta=pasta))
                filho = pasta.id or id_do_uri(pasta.uri)
                if filho and pasta.tem_subpasta:
                    fila.append((profundidade + 1, filho))
        return encontradas

    # --- vídeos ---------------------------------------------------------------

    async def iterar_videos_da_pasta(
        self,
        pasta_id: str,
        *,
        incluir_subpastas: bool = False,
        busca: str | None = None,
        campos_de_busca: Sequence[str] | None = None,
        ordem: str = "default",
        direcao: str | None = None,
        campos: str = CAMPOS_VIDEO_IMPORTACAO,
        maximo_paginas: int = 100,
    ) -> AsyncIterator[VideoVimeo]:
        """`GET {prefixo}/projects/{id}/videos` (A6).

        `ordem` não tem valor manual: a API só oferece alphabetical, date,
        default, duration e last_user_action_event_date (A7). A ordem
        pedagógica vem do título, pela VimeoNamingStrategy.
        """
        async for bruto in self._t.paginar(
            f"{self._prefixo}/projects/{pasta_id}/videos",
            campos=campos,
            maximo_paginas=maximo_paginas,
            include_subfolders=True if incluir_subpastas else None,
            query=busca,
            query_fields=",".join(campos_de_busca) if campos_de_busca else None,
            sort=ordem,
            direction=direcao,
        ):
            yield VideoVimeo.de_payload(bruto)

    async def listar_videos_da_pasta(self, pasta_id: str, **kwargs) -> list[VideoVimeo]:
        return [video async for video in self.iterar_videos_da_pasta(pasta_id, **kwargs)]

    async def obter_video(self, video_id: str, *, campos: str = CAMPOS_VIDEO_SYNC) -> VideoVimeo:
        """`GET /videos/{id}` (B1). 404 quando o vídeo foi apagado no Vimeo (B9)."""
        corpo = await self._t.get(f"/videos/{video_id}", campos=campos)
        if not corpo:
            raise VimeoNaoEncontrado("O vídeo não existe mais no Vimeo.", status=404)
        return VideoVimeo.de_payload(corpo)

    async def iterar_videos_da_conta(
        self,
        *,
        busca: str | None = None,
        campos_de_busca: Sequence[str] | None = None,
        ordem: str = "default",
        direcao: str | None = None,
        filtro: str | None = None,
        modificados_desde: datetime | None = None,
        campos: str = CAMPOS_VIDEO_SYNC,
        maximo_paginas: int = 100,
    ) -> AsyncIterator[VideoVimeo]:
        """`GET {prefixo}/videos` (B2, B3).

        `modificados_desde` manda `If-Modified-Since`, o único cabeçalho
        condicional que esta listagem aceita (H6); em 304 não vem item nenhum.
        Para o sync incremental, use `ordem="modified_time"` com
        `direcao="desc"` e pare no último horário conhecido.
        """
        cabecalhos = None
        if modificados_desde is not None:
            cabecalhos = {"If-Modified-Since": format_datetime(modificados_desde, usegmt=True)}
        async for bruto in self._t.paginar(
            f"{self._prefixo}/videos",
            campos=campos,
            maximo_paginas=maximo_paginas,
            cabecalhos=cabecalhos,
            query=busca,
            query_fields=",".join(campos_de_busca) if campos_de_busca else None,
            sort=ordem,
            direction=direcao,
            filter=filtro,
        ):
            yield VideoVimeo.de_payload(bruto)

    async def listar_videos_da_conta(self, **kwargs) -> list[VideoVimeo]:
        return [video async for video in self.iterar_videos_da_conta(**kwargs)]

    # --- detalhes de um vídeo -------------------------------------------------

    async def listar_versoes(self, video_id: str) -> list[VersaoVimeo]:
        """`GET /videos/{id}/versions` (B13): nome original, tamanho e versão ativa."""
        corpo = await self._t.get(f"/videos/{video_id}/versions", campos=CAMPOS_VERSAO)
        return [VersaoVimeo.de_payload(item) for item in self._dados(corpo)]

    async def listar_thumbnails(self, video_id: str, *, tamanhos: str | None = None) -> list[ThumbnailVimeo]:
        """`GET /videos/{id}/pictures` (B11). A Central de Ajuda pede para não cachear a URL."""
        corpo = await self._t.get(
            f"/videos/{video_id}/pictures", campos=CAMPOS_THUMBNAIL, sizes=tamanhos
        )
        return [ThumbnailVimeo.de_payload(item) for item in self._dados(corpo)]

    async def listar_faixas_de_texto(self, video_id: str) -> list[FaixaDeTexto]:
        """`GET /videos/{id}/texttracks` (E1). Exige token gerado pelo dono do vídeo."""
        corpo = await self._t.get(f"/videos/{video_id}/texttracks", campos=CAMPOS_FAIXA_DE_TEXTO)
        return [FaixaDeTexto.de_payload(item) for item in self._dados(corpo)]

    async def obter_transcricao(self, video_id: str, faixa_id: int | str) -> dict | None:
        """`GET /videos/{id}/transcripts/{texttrack_id}` (E2).

        Devolve o payload cru: o formato dos segmentos é confirmado na POC R12,
        e só depois vale criar um DTO.
        """
        corpo = await self._t.get(
            f"/videos/{video_id}/transcripts/{faixa_id}", permitir_sem_campos=True
        )
        return corpo if isinstance(corpo, dict) else None

    async def listar_dominios_de_embed(self, video_id: str) -> list[str]:
        """`GET /videos/{id}/privacy/domains` (D2): domínios onde o player pode aparecer."""
        corpo = await self._t.get(f"/videos/{video_id}/privacy/domains", campos="domain")
        return [item["domain"] for item in self._dados(corpo) if item.get("domain")]

    @staticmethod
    def _dados(corpo: object) -> list[dict]:
        if not isinstance(corpo, dict):
            return []
        return [item for item in (corpo.get("data") or []) if isinstance(item, dict)]
