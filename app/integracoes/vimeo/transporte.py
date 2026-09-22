"""Camada HTTP única da integração com o Vimeo.

Concentra o que a documentação oficial exige e o que a pesquisa mandou tratar:

* header de versão (`Accept: application/vnd.vimeo.*+json;version=3.4`) e
  `User-Agent` próprio — o guia avisa que agente genérico pode ser bloqueado;
* `fields` em todo GET, porque além de encolher o payload ele dobra a cota;
* cota lida dos headers `X-RateLimit-*`, com espera até o `X-RateLimit-Reset`
  quando vem 429 (a API não manda `Retry-After`);
* retry só em erro transitório, nunca em 400, 401, 403 ou 404;
* **allowlist de rotas**: endpoint destrutivo não é alcançável nem por engano
  (gap 14 de `docs/vimeo-integracao/02-gaps-e-ajustes.md`).
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from app.integracoes.vimeo.erros import (
    VimeoErro,
    VimeoIndisponivel,
    VimeoRotaBloqueada,
    erro_de_resposta,
)
from app.integracoes.vimeo.modelos import LimiteDeRequisicoes, mergulhar

BASE_VIMEO = "https://api.vimeo.com"
VERSAO_API = "3.4"
ACEITA = f"application/vnd.vimeo.*+json;version={VERSAO_API}"

MAXIMO_POR_PAGINA = 100  # limite da API, documentado no guia de formatos comuns

# Rotas que a integração nunca chama, mesmo que o token permitisse. Remover
# itens de uma pasta, pelo guia oficial, apaga os vídeos quando
# `should_delete_items=false` não é passado.
ROTAS_PROIBIDAS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DELETE", re.compile(r"^/videos/[^/]+$")),
    ("DELETE", re.compile(r"^/users/[^/]+/videos$")),
    ("DELETE", re.compile(r"^(?:/me|/users/[^/]+)/(?:projects|folders)/[^/]+$")),
    ("DELETE", re.compile(r"^(?:/me|/users/[^/]+)/(?:projects|folders)/[^/]+/items")),
)

STATUS_RETENTAVEIS = frozenset({429, 500, 502, 503, 504})
ESPERA_PADRAO_DA_JANELA = 61.0  # a janela de rate limit do Vimeo é de 60 segundos


class TransporteVimeo:
    """Faz as requisições. Não sabe nada de pasta, vídeo ou questão."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = BASE_VIMEO,
        agente: str = "mvp-portal-aluno/0.1",
        metodos_permitidos: Sequence[str] = ("GET", "HEAD"),
        tentativas: int = 3,
        piso_da_cota: int = 5,
        espera_maxima: float = 90.0,
        timeout: httpx.Timeout | None = None,
        transporte_http: httpx.AsyncBaseTransport | None = None,
        dormir: Callable[[float], Any] = asyncio.sleep,
        aleatorio: Callable[[], float] = random.random,
        agora: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._base_url = base_url
        self._metodos = tuple(m.upper() for m in metodos_permitidos)
        self._tentativas = max(1, tentativas)
        self._piso_da_cota = piso_da_cota
        self._espera_maxima = espera_maxima
        self._dormir = dormir
        self._aleatorio = aleatorio
        self._agora = agora
        self._limite: LimiteDeRequisicoes | None = None
        self._cliente = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout or httpx.Timeout(15.0, connect=5.0),
            transport=transporte_http,
            headers={
                "Authorization": f"bearer {token}",
                "Accept": ACEITA,
                "User-Agent": agente,
            },
        )

    # --- ciclo de vida --------------------------------------------------------

    async def __aenter__(self) -> TransporteVimeo:
        return self

    async def __aexit__(self, *_) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._cliente.aclose()

    @property
    def ultimo_limite(self) -> LimiteDeRequisicoes | None:
        """Cota vista na última resposta, para log e para o painel do admin."""
        return self._limite

    # --- chamadas -------------------------------------------------------------

    async def get(
        self,
        caminho: str,
        *,
        campos: str | None = None,
        cabecalhos: dict[str, str] | None = None,
        permitir_sem_campos: bool = False,
        **params: Any,
    ) -> Any | None:
        """GET com `fields` obrigatório. Devolve o JSON, ou None em 304 e 204."""
        if campos is None and not permitir_sem_campos:
            raise VimeoErro(
                "Requisição interna sem `fields`.",
                developer_message=f"GET {caminho} sem campos: `fields` é obrigatório na integração",
            )
        consulta = {chave: valor for chave, valor in params.items() if valor is not None}
        if campos:
            consulta["fields"] = campos
        resposta = await self.requisitar("GET", caminho, params=consulta or None, cabecalhos=cabecalhos)
        return self._corpo_ou_none(resposta)

    async def get_uri(self, uri: str, *, cabecalhos: dict[str, str] | None = None) -> Any | None:
        """GET numa URI devolvida pela própria API (`paging.next`), que já traz a query."""
        resposta = await self.requisitar("GET", uri, cabecalhos=cabecalhos)
        return self._corpo_ou_none(resposta)

    async def head(self, url: str, *, cabecalhos: dict[str, str] | None = None) -> httpx.Headers:
        """HEAD: usado pelo upload tus para ler `Upload-Offset`."""
        resposta = await self.requisitar("HEAD", url, cabecalhos=cabecalhos)
        return resposta.headers

    async def paginar(
        self,
        caminho: str,
        *,
        campos: str,
        por_pagina: int = MAXIMO_POR_PAGINA,
        maximo_paginas: int = 100,
        cabecalhos: dict[str, str] | None = None,
        **params: Any,
    ) -> AsyncIterator[dict]:
        """Percorre `paging.next` até o fim, item por item."""
        pagina = 0
        corpo = await self.get(
            caminho,
            campos=campos,
            cabecalhos=cabecalhos,
            per_page=min(por_pagina, MAXIMO_POR_PAGINA),
            **params,
        )
        while isinstance(corpo, dict):
            pagina += 1
            for item in corpo.get("data") or []:
                if isinstance(item, dict):
                    yield item
            proxima = mergulhar(corpo, "paging.next")
            if not proxima or pagina >= maximo_paginas:
                return
            corpo = await self.get_uri(proxima)

    # --- interno --------------------------------------------------------------

    async def requisitar(
        self,
        metodo: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        cabecalhos: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Entrada de baixo nível: valida a rota, respeita a cota e trata o retry.

        Os clientes de escrita e de upload (fases 4 e 5) vão usar este método
        direto, porque precisam de POST, PUT, PATCH e do DELETE de domínio.
        """
        self._validar_rota(metodo, url)
        await self._esperar_a_cota_virar()

        ultimo_erro: VimeoErro | None = None
        for tentativa in range(1, self._tentativas + 1):
            try:
                resposta = await self._cliente.request(metodo, url, params=params, headers=cabecalhos)
            except (httpx.TimeoutException, httpx.TransportError) as erro:
                ultimo_erro = VimeoIndisponivel(
                    f"Não foi possível falar com {self._base_url}.",
                    developer_message=f"{type(erro).__name__}: {erro}",
                )
                if tentativa == self._tentativas:
                    raise ultimo_erro from erro
                await self._recuar(tentativa, None)
                continue

            limite = LimiteDeRequisicoes.de_cabecalhos(resposta.headers)
            if limite is not None:
                self._limite = limite

            if resposta.status_code < 400:
                return resposta

            espera = self._espera_ate_a_janela_virar(resposta)
            erro = erro_de_resposta(resposta.status_code, self._corpo(resposta), espera_segundos=espera)
            if resposta.status_code not in STATUS_RETENTAVEIS or tentativa == self._tentativas:
                raise erro
            ultimo_erro = erro
            await self._recuar(tentativa, espera)

        raise ultimo_erro or VimeoIndisponivel("Falha ao falar com o Vimeo.")

    def _validar_rota(self, metodo: str, url: str) -> None:
        metodo = metodo.upper()
        if metodo not in self._metodos:
            raise VimeoRotaBloqueada(
                "Operação não permitida para esta credencial do Vimeo.",
                developer_message=f"{metodo} {url} — métodos permitidos: {', '.join(self._metodos)}",
            )
        caminho = url.split("?", 1)[0]
        if caminho.startswith(self._base_url):
            caminho = caminho[len(self._base_url) :]
        for proibido, padrao in ROTAS_PROIBIDAS:
            if metodo == proibido and padrao.match(caminho):
                raise VimeoRotaBloqueada(
                    "Operação destrutiva no Vimeo não é permitida pela integração.",
                    developer_message=f"{metodo} {caminho} está na lista de rotas proibidas",
                )

    async def _esperar_a_cota_virar(self) -> None:
        """Se a cota está no fim, espera a janela virar em vez de tomar 429."""
        limite = self._limite
        if limite is None or limite.restante is None or limite.restante > self._piso_da_cota:
            return
        espera = ESPERA_PADRAO_DA_JANELA
        if limite.reinicia_em is not None:
            espera = (limite.reinicia_em - self._agora()).total_seconds() + 1
        if espera > 0:
            await self._dormir(min(espera, self._espera_maxima))

    def _espera_ate_a_janela_virar(self, resposta: httpx.Response) -> float | None:
        if resposta.status_code != 429:
            return None
        limite = LimiteDeRequisicoes.de_cabecalhos(resposta.headers)
        if limite is not None and limite.reinicia_em is not None:
            return max(1.0, (limite.reinicia_em - self._agora()).total_seconds() + 1)
        return ESPERA_PADRAO_DA_JANELA

    async def _recuar(self, tentativa: int, espera: float | None) -> None:
        if espera is None:
            espera = (2 ** (tentativa - 1)) + self._aleatorio()
        await self._dormir(min(espera, self._espera_maxima))

    @staticmethod
    def _corpo(resposta: httpx.Response) -> Any:
        try:
            return resposta.json()
        except ValueError:
            return None

    @classmethod
    def _corpo_ou_none(cls, resposta: httpx.Response) -> Any | None:
        if resposta.status_code in (204, 304):
            return None
        return cls._corpo(resposta)
