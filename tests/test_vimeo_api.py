"""VimeoAPI contra um Vimeo falso: paginação das pastas e pasta pedida pelo nome."""

import httpx
import pytest

from app.errors import RegraDeNegocio
from app.vimeo.client import VimeoAPI

PASTAS = {
    "1": [{"uri": "/users/1/projects/10", "name": "Aovivo"}, {"uri": "/users/1/projects/11", "name": "L03"}],
    "2": [{"uri": "/users/1/projects/12", "name": "L03"}],
}


def _vimeo(pedido: httpx.Request) -> httpx.Response:
    if pedido.url.path == "/me/folders":
        pagina = pedido.url.params.get("page", "1")
        proxima = "/me/folders?page=2&per_page=100" if pagina == "1" else None
        return httpx.Response(200, json={"data": PASTAS[pagina], "paging": {"next": proxima}})
    if pedido.url.path == "/me/folders/10/videos":
        return httpx.Response(200, json={"data": [{"uri": "/videos/7", "name": "Aula #1"}]})
    return httpx.Response(400)


@pytest.fixture
def api(monkeypatch):
    api = VimeoAPI("token", "https://vimeo.falso")
    monkeypatch.setattr(
        api, "_client", lambda: httpx.AsyncClient(base_url="https://vimeo.falso", transport=httpx.MockTransport(_vimeo))
    )
    return api


async def test_pastas_seguem_todas_as_paginas(api):
    assert [p.id for p in await api.listar_pastas()] == ["10", "11", "12"]


async def test_pasta_pelo_nome_vira_o_id(api):
    videos = await api.listar_videos("aovivo")
    assert [(v.id, v.pasta) for v in videos] == [("7", "Aovivo")]


async def test_nome_repetido_ou_inexistente_pede_o_id(api):
    with pytest.raises(RegraDeNegocio, match="11, 12"):
        await api.listar_videos("L03")
    with pytest.raises(RegraDeNegocio, match="Não há pasta"):
        await api.listar_videos("Nada")
