"""Cliente de leitura do Vimeo: rotas, parâmetros e parsing.

Os payloads seguem o formato da referência oficial da API 3.4.9 (as respostas
reais da POC entram depois como fixtures). Nada sai para a internet.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest

from app.integracoes.vimeo.erros import VimeoNaoEncontrado
from app.integracoes.vimeo.leitura import ClienteVimeoLeitura
from app.integracoes.vimeo.modelos import PastaVimeo, VideoVimeo
from app.integracoes.vimeo.transporte import TransporteVimeo

PASTA_RAIZ = {
    "uri": "/users/999/projects/100",
    "name": "Extensivo 2027",
    "created_time": "2026-01-10T12:00:00+00:00",
    "modified_time": "2026-09-01T08:30:00+00:00",
    "has_subfolder": True,
    "metadata": {
        "connections": {
            "parent_folder": None,
            "ancestor_path": [],
            "videos": {"total": 0, "deep_total": 412},
            "folders": {"total": 2},
        }
    },
}

SUBPASTA_ESTEQUIOMETRIA = {
    "uri": "/users/999/projects/101",
    "name": "Estequiometria",
    "has_subfolder": True,
    "metadata": {
        "connections": {
            "parent_folder": {"uri": "/users/999/projects/100"},
            "ancestor_path": [{"uri": "/users/999/projects/100", "name": "Extensivo 2027"}],
            "videos": {"total": 70, "deep_total": 75},
            "folders": {"total": 1},
        }
    },
}

SUBPASTA_ATOMISTICA = {
    "uri": "/users/999/projects/102",
    "name": "Atomística",
    "has_subfolder": False,
    "metadata": {
        "connections": {
            "parent_folder": {"uri": "/users/999/projects/100"},
            "ancestor_path": [{"uri": "/users/999/projects/100", "name": "Extensivo 2027"}],
            "videos": {"total": 55, "deep_total": 55},
            "folders": {"total": 0},
        }
    },
}

SUBPASTA_REVISAO = {
    "uri": "/users/999/projects/103",
    "name": "Revisão",
    "has_subfolder": False,
    "metadata": {
        "connections": {
            "parent_folder": {"uri": "/users/999/projects/101"},
            "ancestor_path": [
                {"uri": "/users/999/projects/101", "name": "Estequiometria"},
                {"uri": "/users/999/projects/100", "name": "Extensivo 2027"},
            ],
            "videos": {"total": 5, "deep_total": 5},
            "folders": {"total": 0},
        }
    },
}

VIDEO = {
    "uri": "/videos/920000201",
    "name": "Estequiometria — Questão 01 — Balanceamento",
    "description": "Resolução em vídeo",
    "duration": 372,
    "link": "https://vimeo.com/920000201/8272103f6e",
    "player_embed_url": "https://player.vimeo.com/video/920000201?h=8272103f6e",
    "pictures": {
        "base_link": "https://i.vimeocdn.com/video/1",
        "sizes": [
            {"width": 295, "height": 166, "link": "https://i.vimeocdn.com/video/1_295x166"},
            {"width": 1280, "height": 720, "link": "https://i.vimeocdn.com/video/1_1280x720"},
        ],
    },
    "status": "available",
    "transcode": {"status": "complete"},
    "is_playable": True,
    "privacy": {"view": "disable", "embed": "whitelist"},
    "transcript": {"status": "completed", "language": "pt-BR"},
    "parent_project": {"uri": "/users/999/projects/101", "name": "Estequiometria"},
    "resource_key": "abc123",
    "created_time": "2022-03-01T10:00:00+00:00",
    "modified_time": "2026-08-20T10:00:00+00:00",
    "is_cold_storage": False,
    "is_cold_privacy_restricted": False,
    "metadata": {"connections": {"versions": {"current_uri": "/videos/920000201/versions/5"}}},
}


def colecao(*itens: dict) -> dict:
    return {"total": len(itens), "page": 1, "per_page": 100, "data": list(itens), "paging": {"next": None}}


@asynccontextmanager
async def cliente(rotas: dict, *, usuario: str = "me"):
    """Cliente de leitura falando com um Vimeo de mentira, roteado por caminho."""
    requisicoes: list[httpx.Request] = []

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        requisicoes.append(requisicao)
        rota = rotas.get(requisicao.url.path)
        if rota is None:
            return httpx.Response(
                404,
                json={"error_code": 5000, "developer_message": f"sem rota para {requisicao.url.path}"},
            )
        resultado = rota(requisicao) if callable(rota) else rota
        if isinstance(resultado, httpx.Response):
            return resultado
        return httpx.Response(200, json=resultado)

    async def dormir(_: float) -> None:
        return None

    transporte = TransporteVimeo(
        "token-de-teste",
        transporte_http=httpx.MockTransport(manipulador),
        dormir=dormir,
        agora=lambda: datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
    )
    try:
        yield ClienteVimeoLeitura(transporte, usuario=usuario), requisicoes
    finally:
        await transporte.aclose()


# --- parsing ------------------------------------------------------------------


def test_video_guarda_o_embed_com_hash_e_os_estados():
    video = VideoVimeo.de_payload(VIDEO)

    assert video.id == "920000201"
    # O hash de privacidade precisa sobreviver: sem ele o player recusa vídeo unlisted.
    assert video.embed_url.endswith("?h=8272103f6e")
    assert (video.status, video.transcode_status, video.reproduzivel) == ("available", "complete", True)
    assert (video.privacidade_view, video.privacidade_embed) == ("disable", "whitelist")
    assert (video.transcricao_status, video.transcricao_idioma) == ("completed", "pt-BR")
    assert video.pasta_uri == "/users/999/projects/101"
    assert video.versao_atual_uri == "/videos/920000201/versions/5"
    assert video.thumbnail_url.endswith("1280x720")
    assert video.criado_em == datetime(2022, 3, 1, 10, 0, tzinfo=UTC)
    assert video.publicavel is True


def test_video_aceita_parent_project_como_string_ou_ausente():
    assert VideoVimeo.de_payload({**VIDEO, "parent_project": "/users/999/projects/101"}).pasta_uri == (
        "/users/999/projects/101"
    )
    assert VideoVimeo.de_payload({k: v for k, v in VIDEO.items() if k != "parent_project"}).pasta_uri is None


def test_video_em_processamento_nao_e_publicavel():
    """Seção 24: aluno não recebe vídeo que ainda não está pronto."""
    video = VideoVimeo.de_payload(
        {**VIDEO, "status": "transcoding", "is_playable": False, "transcode": {"status": "in_progress"}}
    )

    assert video.publicavel is False


def test_pasta_traz_pai_ancestrais_e_contagem_com_subpastas():
    raiz = PastaVimeo.de_payload(PASTA_RAIZ)
    filha = PastaVimeo.de_payload(SUBPASTA_REVISAO)

    assert (raiz.id, raiz.pai_uri, raiz.profundidade) == ("100", None, 0)
    assert raiz.total_videos_com_subpastas == 412
    assert filha.pai_uri == "/users/999/projects/101"
    assert filha.profundidade == 2


# --- rotas e parâmetros -------------------------------------------------------


async def test_arvore_em_largura_respeita_a_profundidade():
    rotas = {
        "/me/projects/100/items": colecao(
            {"type": "folder", "folder": SUBPASTA_ESTEQUIOMETRIA},
            {"type": "folder", "folder": SUBPASTA_ATOMISTICA},
        ),
        "/me/projects/101/items": colecao({"type": "folder", "folder": SUBPASTA_REVISAO}),
        "/me/projects/103/items": colecao(),
    }

    async with cliente(rotas) as (leitura, requisicoes):
        tudo = await leitura.percorrer_arvore("100")
        rasa = await leitura.percorrer_arvore("100", profundidade_maxima=1)

    assert [(no.profundidade, no.pasta.nome) for no in tudo] == [
        (1, "Estequiometria"),
        (1, "Atomística"),
        (2, "Revisão"),
    ]
    assert [no.pasta.nome for no in rasa] == ["Estequiometria", "Atomística"]
    assert all(req.url.params.get("filter") == "folder" for req in requisicoes)


async def test_videos_da_pasta_mandam_include_subfolders_e_fields():
    rotas = {"/me/projects/101/videos": colecao(VIDEO)}

    async with cliente(rotas) as (leitura, requisicoes):
        videos = await leitura.listar_videos_da_pasta("101", incluir_subpastas=True)

    assert [v.id for v in videos] == ["920000201"]
    parametros = requisicoes[0].url.params
    assert parametros.get("include_subfolders") == "true"
    assert parametros.get("per_page") == "100"
    assert "player_embed_url" in parametros.get("fields")


async def test_videos_da_conta_mandam_if_modified_since_e_lidam_com_304():
    chamadas: list[httpx.Request] = []

    def rota(requisicao: httpx.Request) -> httpx.Response:
        chamadas.append(requisicao)
        return httpx.Response(304)

    async with cliente({"/me/videos": rota}) as (leitura, _):
        videos = await leitura.listar_videos_da_conta(
            modificados_desde=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            ordem="modified_time",
            direcao="desc",
        )

    assert videos == []
    assert chamadas[0].headers["if-modified-since"] == "Tue, 01 Sep 2026 12:00:00 GMT"
    assert chamadas[0].url.params.get("sort") == "modified_time"


async def test_obter_video_apagado_vira_nao_encontrado():
    async with cliente({}) as (leitura, _):
        with pytest.raises(VimeoNaoEncontrado):
            await leitura.obter_video("920000201")


async def test_faixas_de_texto_identificam_legenda_automatica():
    faixas = colecao(
        {
            "id": 77,
            "type": "captions",
            "language": "pt-BR",
            "provenance": "autogen_source_audio",
            "active": True,
            "download_links": {"vtt": "https://vimeo/x.vtt", "srt": "https://vimeo/x.srt"},
            "download_links_expires_time": "2026-09-12T12:00:00+00:00",
        },
        {
            "id": 78,
            "type": "subtitles",
            "language": "en",
            "provenance": "user_uploaded",
            "active": False,
            "download_links": {},
        },
    )

    async with cliente({"/videos/920000201/texttracks": faixas}) as (leitura, _):
        resultado = await leitura.listar_faixas_de_texto("920000201")

    assert [f.gerada_automaticamente for f in resultado] == [True, False]
    assert resultado[0].link_vtt == "https://vimeo/x.vtt"
    assert resultado[0].links_expiram_em is not None


async def test_versoes_trazem_nome_original_do_arquivo():
    versoes = colecao(
        {
            "uri": "/videos/920000201/versions/5",
            "filename": "estequiometria-q01-v2.mp4",
            "filesize": 148_000_000,
            "duration": 372,
            "active": True,
            "upload_date": "2026-08-20T10:00:00+00:00",
            "transcode": {"status": "complete"},
        }
    )

    async with cliente({"/videos/920000201/versions": versoes}) as (leitura, _):
        resultado = await leitura.listar_versoes("920000201")

    assert resultado[0].arquivo_nome == "estequiometria-q01-v2.mp4"
    assert resultado[0].arquivo_tamanho == 148_000_000
    assert resultado[0].ativa is True


async def test_dominios_de_embed():
    rotas = {"/videos/920000201/privacy/domains": colecao({"domain": "portal.exemplo.com"}, {})}

    async with cliente(rotas) as (leitura, _):
        dominios = await leitura.listar_dominios_de_embed("920000201")

    assert dominios == ["portal.exemplo.com"]


async def test_verificar_token_invalido_devolve_falso():
    rotas = {"/oauth/verify": httpx.Response(401, json={"error_code": 8000})}

    async with cliente(rotas) as (leitura, _):
        assert await leitura.verificar_token() is False


async def test_conta_informa_plano_e_acesso_de_upload():
    rotas = {
        "/me": {
            "uri": "/users/999",
            "name": "Prof. Helena",
            "membership": {"type": "advanced", "display": "Advanced"},
            "upload_quota": {"space": {"free": 100}},
        }
    }

    async with cliente(rotas) as (leitura, _):
        conta = await leitura.obter_conta()

    assert conta.nome == "Prof. Helena"
    assert conta.tem_acesso_de_upload is True
    assert conta.plano["type"] == "advanced"


async def test_pasta_de_time_usa_o_prefixo_do_dono():
    rotas = {"/users/555/projects/100": PASTA_RAIZ}

    async with cliente(rotas, usuario="555") as (leitura, requisicoes):
        pasta = await leitura.obter_pasta("100")

    assert pasta.nome == "Extensivo 2027"
    assert requisicoes[0].url.path == "/users/555/projects/100"
