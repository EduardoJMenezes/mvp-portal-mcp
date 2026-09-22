"""Transporte da integração com o Vimeo.

Nada sai para a internet: tudo passa por `httpx.MockTransport`. O sono e o
relógio são injetados, então o teste não espera de verdade e o cálculo da espera
fica verificável.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.integracoes.vimeo.erros import (
    VimeoErro,
    VimeoIndisponivel,
    VimeoNaoEncontrado,
    VimeoParametroInvalido,
    VimeoRotaBloqueada,
)
from app.integracoes.vimeo.transporte import TransporteVimeo

AGORA = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def montar(manipulador, **kwargs) -> tuple[TransporteVimeo, list[float]]:
    dormidas: list[float] = []

    async def dormir(segundos: float) -> None:
        dormidas.append(segundos)

    transporte = TransporteVimeo(
        "token-de-teste",
        transporte_http=httpx.MockTransport(manipulador),
        dormir=dormir,
        aleatorio=lambda: 0.0,
        agora=lambda: AGORA,
        **kwargs,
    )
    return transporte, dormidas


def sempre(resposta_factory):
    def manipulador(_: httpx.Request) -> httpx.Response:
        return resposta_factory()

    return manipulador


async def test_manda_versao_agente_e_fields():
    vistos: dict[str, object] = {}

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        vistos["headers"] = requisicao.headers
        vistos["url"] = str(requisicao.url)
        return httpx.Response(200, json={"uri": "/me"})

    transporte, _ = montar(manipulador)
    async with transporte:
        corpo = await transporte.get("/me", campos="uri,name")

    cabecalhos = vistos["headers"]
    assert corpo == {"uri": "/me"}
    assert cabecalhos["accept"] == "application/vnd.vimeo.*+json;version=3.4"
    assert cabecalhos["authorization"] == "bearer token-de-teste"
    assert "mvp-portal-aluno" in cabecalhos["user-agent"]
    assert "fields=uri%2Cname" in str(vistos["url"])


async def test_get_sem_fields_nao_sai_da_nossa_camada():
    """`fields` é obrigatório: dobra a cota e encolhe o payload."""
    chamadas: list[httpx.Request] = []

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        chamadas.append(requisicao)
        return httpx.Response(200, json={})

    transporte, _ = montar(manipulador)
    async with transporte:
        with pytest.raises(VimeoErro):
            await transporte.get("/me")
        # já o `/oauth/verify` não tem campos para pedir
        await transporte.get("/oauth/verify", permitir_sem_campos=True)

    assert len(chamadas) == 1


async def test_404_vira_nao_encontrado_com_o_error_code_do_vimeo():
    transporte, _ = montar(
        sempre(lambda: httpx.Response(404, json={"error_code": 5000, "developer_message": "No such folder"}))
    )
    async with transporte:
        with pytest.raises(VimeoNaoEncontrado) as capturado:
            await transporte.get("/me/projects/1", campos="uri")

    erro = capturado.value
    assert erro.codigo == "VIMEO_RESOURCE_NOT_FOUND"
    assert erro.error_code == 5000
    assert erro.retentavel is False
    assert erro.para_log()["developer_message"] == "No such folder"


async def test_400_nao_repete():
    chamadas: list[httpx.Request] = []

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        chamadas.append(requisicao)
        return httpx.Response(400, json={"error_code": 2204})

    transporte, dormidas = montar(manipulador, tentativas=3)
    async with transporte:
        with pytest.raises(VimeoParametroInvalido):
            await transporte.get("/me/videos", campos="uri")

    assert len(chamadas) == 1
    assert dormidas == []


async def test_429_espera_a_janela_virar_e_repete():
    respostas = [
        httpx.Response(
            429,
            json={"error_code": 9000},
            headers={
                "X-RateLimit-Limit": "250",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "2026-09-11T12:00:30+00:00",
            },
        ),
        httpx.Response(200, json={"ok": True}, headers={"X-RateLimit-Remaining": "249"}),
    ]

    def manipulador(_: httpx.Request) -> httpx.Response:
        return respostas.pop(0)

    transporte, dormidas = montar(manipulador, tentativas=3)
    async with transporte:
        corpo = await transporte.get("/me/videos", campos="uri")

    assert corpo == {"ok": True}
    # 30 segundos até o reset, mais 1 de folga. Nada de Retry-After: a API não manda.
    assert dormidas == [31.0]


async def test_503_faz_backoff_e_desiste_depois_das_tentativas():
    chamadas: list[httpx.Request] = []

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        chamadas.append(requisicao)
        return httpx.Response(503)

    transporte, dormidas = montar(manipulador, tentativas=3)
    async with transporte:
        with pytest.raises(VimeoIndisponivel):
            await transporte.get("/me", campos="uri")

    assert len(chamadas) == 3
    assert dormidas == [1.0, 2.0]


async def test_timeout_de_rede_vira_indisponivel():
    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("estourou", request=requisicao)

    transporte, _ = montar(manipulador, tentativas=2)
    async with transporte:
        with pytest.raises(VimeoIndisponivel) as capturado:
            await transporte.get("/me", campos="uri")

    assert capturado.value.retentavel is True


async def test_metodo_fora_da_allowlist_nao_sai():
    chamadas: list[httpx.Request] = []

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        chamadas.append(requisicao)
        return httpx.Response(200, json={})

    transporte, _ = montar(manipulador, metodos_permitidos=("GET",))
    async with transporte:
        with pytest.raises(VimeoRotaBloqueada):
            await transporte.head("https://api.vimeo.com/upload/algo")

    assert chamadas == []


@pytest.mark.parametrize(
    "caminho",
    [
        "/videos/123",
        "/users/999/videos",
        "/me/projects/100",
        "/users/999/projects/100",
        "/me/projects/100/items?uris=/videos/1",
    ],
)
async def test_rota_destrutiva_nunca_sai(caminho: str):
    """Mesmo com DELETE liberado no cliente, estas rotas ficam barradas."""
    chamadas: list[httpx.Request] = []

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        chamadas.append(requisicao)
        return httpx.Response(204)

    transporte, _ = montar(manipulador, metodos_permitidos=("GET", "HEAD", "DELETE"))
    async with transporte:
        with pytest.raises(VimeoRotaBloqueada):
            await transporte.requisitar("DELETE", caminho)

    assert chamadas == []


async def test_delete_permitido_continua_passando():
    """Tirar um domínio da allowlist de embed é DELETE, e não destrói conteúdo."""

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        assert requisicao.method == "DELETE"
        return httpx.Response(204)

    transporte, _ = montar(manipulador, metodos_permitidos=("GET", "DELETE"))
    async with transporte:
        resposta = await transporte.requisitar("DELETE", "/videos/123/privacy/domains/exemplo.com")

    assert resposta.status_code == 204


async def test_paginar_segue_paging_next():
    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        pagina = requisicao.url.params.get("page")
        if pagina is None:
            return httpx.Response(
                200,
                json={
                    "total": 2,
                    "data": [{"uri": "/videos/1"}],
                    "paging": {"next": "/me/videos?page=2&fields=uri&per_page=100"},
                },
            )
        return httpx.Response(200, json={"data": [{"uri": "/videos/2"}], "paging": {"next": None}})

    transporte, _ = montar(manipulador)
    async with transporte:
        itens = [item async for item in transporte.paginar("/me/videos", campos="uri")]

    assert [item["uri"] for item in itens] == ["/videos/1", "/videos/2"]


async def test_paginar_respeita_o_maximo_de_paginas():
    def manipulador(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"uri": "/videos/1"}], "paging": {"next": "/me/videos?page=9&fields=uri"}},
        )

    transporte, _ = montar(manipulador)
    async with transporte:
        itens = [item async for item in transporte.paginar("/me/videos", campos="uri", maximo_paginas=2)]

    assert len(itens) == 2


async def test_304_devolve_none():
    transporte, _ = montar(sempre(lambda: httpx.Response(304)))
    async with transporte:
        assert await transporte.get("/me/videos", campos="uri") is None


async def test_guarda_a_cota_da_ultima_resposta():
    transporte, _ = montar(
        sempre(
            lambda: httpx.Response(
                200,
                json={},
                headers={
                    "X-RateLimit-Limit": "500",
                    "X-RateLimit-Remaining": "499",
                    "X-RateLimit-Reset": "2026-09-11T12:01:00+00:00",
                },
            )
        )
    )
    async with transporte:
        await transporte.get("/me", campos="uri")

    limite = transporte.ultimo_limite
    assert limite is not None
    assert (limite.limite, limite.restante) == (500, 499)
    assert limite.reinicia_em is not None


async def test_espera_antes_de_estourar_a_cota():
    """Com a cota no fim, o transporte espera a janela virar em vez de tomar 429."""
    transporte, dormidas = montar(
        sempre(
            lambda: httpx.Response(
                200,
                json={},
                headers={
                    "X-RateLimit-Remaining": "1",
                    "X-RateLimit-Reset": "2026-09-11T12:00:20+00:00",
                },
            )
        ),
        piso_da_cota=5,
    )
    async with transporte:
        await transporte.get("/me", campos="uri")  # aprende que sobrou 1
        await transporte.get("/me", campos="uri")  # e espera antes de mandar

    assert dormidas == [21.0]
