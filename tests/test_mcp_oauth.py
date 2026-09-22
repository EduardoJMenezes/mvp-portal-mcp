"""O MCP precisa ser alcançável pelos dois tipos de cliente.

O Claude Code manda um header fixo e se contenta com o token opaco. Conector
remoto (claude.ai) não tem onde escrever header: ele descobre o servidor pelos
`/.well-known/...` **na raiz do domínio** e faz OAuth. Foi por não ter essas
rotas na raiz — o portal estático respondia HTML no lugar do JSON — que o
conector não conectava.

Estes testes seguram as duas pontas: o que a configuração produz e onde as
rotas caem no app que vai para o ar.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fastmcp.server.auth import MultiAuth
from starlette.routing import Mount

from app import main
from app.config import get_settings
from app.mcp_server.auth import (
    ESCOPOS_EXIGIDOS,
    GitHubDaPlataforma,
    TokenDaPlataforma,
    _consultar,
    _operador_do_github,
    construir_auth,
)
from app.identidade import Papel
from tests.modelos import TokenMCP, Usuario
from tests.senhas import hash_senha, hash_token, novo_token_mcp

BASE = "https://exemplo.up.railway.app"


@pytest.fixture
def com_oauth(monkeypatch):
    """Liga o OAuth do GitHub por variável de ambiente, como no Railway."""
    monkeypatch.setenv("MCP_BASE_URL", BASE)
    monkeypatch.setenv("MCP_OAUTH_GITHUB_CLIENT_ID", "Ov23liDEMONSTRACAO")
    monkeypatch.setenv("MCP_OAUTH_GITHUB_CLIENT_SECRET", "segredo-de-teste")
    monkeypatch.setenv("MCP_OAUTH_OPERADORES", "EduardoJMenezes=professor@escola.demo")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- o que a configuração produz ---------------------------------------------


def test_sem_credencial_do_github_o_servidor_segue_so_com_o_token_opaco() -> None:
    get_settings.cache_clear()
    assert isinstance(construir_auth(), TokenDaPlataforma)


def test_com_credencial_o_servidor_aceita_as_duas_portas(com_oauth) -> None:
    auth = construir_auth()

    assert isinstance(auth, MultiAuth), "o OAuth não pode substituir o token opaco"
    assert isinstance(auth.server, GitHubDaPlataforma)
    assert any(isinstance(v, TokenDaPlataforma) for v in auth.verifiers), (
        "sem isto o Claude Code perde o acesso que tem hoje"
    )


def test_rotas_de_descoberta_nascem_na_raiz_apontando_para_o_mcp(com_oauth) -> None:
    rotas = {r.path for r in construir_auth().get_routes(mcp_path=main.CAMINHO_MCP)}

    # É exatamente aqui que o cliente procura (RFC 9728). Um prefixo a mais
    # nesses caminhos é o bastante para o conector não conectar.
    assert "/.well-known/oauth-protected-resource/mcp" in rotas
    assert "/.well-known/oauth-authorization-server" in rotas
    assert {"/authorize", "/token", "/register", "/auth/callback"} <= rotas


def test_o_recurso_anunciado_e_o_endpoint_do_mcp(com_oauth) -> None:
    auth = construir_auth()
    auth.get_routes(mcp_path=main.CAMINHO_MCP)  # é o que define a URL do recurso

    assert str(auth._get_resource_url(main.CAMINHO_MCP)) == f"{BASE}/mcp"


# --- onde as rotas caem no app que vai para o ar ------------------------------


def test_a_pagina_de_envio_e_a_ultima_a_ser_consultada() -> None:
    """Um mount em "/" casa com qualquer caminho e encerra o roteamento: tudo que
    o MCP precisa expor na raiz tem que estar declarado antes dele."""
    rotas = main.app.router.routes

    assert isinstance(rotas[-1], Mount), "o FastAPI tem que ser o último recurso"
    assert main.CAMINHO_MCP in [getattr(r, "path", None) for r in rotas[:-1]]


def test_o_endpoint_do_mcp_pede_credencial_em_vez_de_devolver_o_portal() -> None:
    cliente = TestClient(main.app)

    for caminho in (main.CAMINHO_MCP, f"{main.CAMINHO_MCP}/"):
        resposta = cliente.post(caminho, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})

        assert resposta.status_code == 401, f"{caminho} devia exigir credencial"
        assert "bearer" in resposta.headers.get("www-authenticate", "").lower()
        assert "<!doctype html" not in resposta.text.lower()


def test_a_pagina_de_envio_continua_atras_do_mcp() -> None:
    """O MCP hospeda o FastAPI do envio; a página não pode ter sumido no caminho."""
    cliente = TestClient(main.app, raise_server_exceptions=False)

    assert cliente.get("/saude").json() == {"status": "ok", "papel": "mcp"}
    pagina = cliente.get("/enviar/qualquer-token")
    assert pagina.status_code == 200 and "Enviar" in pagina.text


# --- quem entra pelo GitHub --------------------------------------------------


def _operador(db, email: str, papel: str = Papel.ADMIN) -> Usuario:
    usuario = Usuario(nome="Helena", email=email, senha_hash=hash_senha("x"), papel=papel)
    db.add(usuario)
    db.commit()
    return usuario


def test_login_mapeado_vira_o_operador_da_plataforma(db, com_oauth, api_java) -> None:
    _operador(db, "professor@escola.demo")

    claims = _operador_do_github(["eduardojmenezes"])

    assert claims is not None
    assert claims["email"] == "professor@escola.demo"
    assert claims["papel"] == Papel.ADMIN


def test_email_publico_do_github_vale_quando_bate_com_um_operador(db, com_oauth, api_java) -> None:
    _operador(db, "helena@escola.demo")

    assert _operador_do_github(["helena@escola.demo"])["email"] == "helena@escola.demo"


def test_login_desconhecido_nao_abre_sessao(db, com_oauth, api_java) -> None:
    _operador(db, "professor@escola.demo")

    assert _operador_do_github(["estranho", "estranho@exemplo.com"]) is None


def test_aluno_nao_entra_pelo_github_nem_estando_no_mapa(db, com_oauth, api_java, monkeypatch) -> None:
    """O GitHub diz quem é; o papel na plataforma diz se opera (seção 4)."""
    _operador(db, "joao@aluno.demo", papel=Papel.ALUNO)
    monkeypatch.setenv("MCP_OAUTH_OPERADORES", "joaogithub=joao@aluno.demo")
    get_settings.cache_clear()

    assert _operador_do_github(["joaogithub"]) is None


def test_o_token_opaco_satisfaz_o_escopo_que_o_servidor_exige(com_oauth) -> None:
    """A regressão que ligar o OAuth causou na primeira tentativa.

    Com OAuth, o middleware passa a exigir escopo de **qualquer** credencial, e
    o token da plataforma nascia sem nenhum: o Claude Code, que funcionava,
    passou a levar "Insufficient scope" em toda chamada.
    """
    assert set(construir_auth().required_scopes) <= set(ESCOPOS_EXIGIDOS)


def test_a_sessao_do_token_opaco_carrega_esse_escopo(db, com_oauth, api_java) -> None:
    operador = _operador(db, "professor@escola.demo")
    valor = novo_token_mcp()
    db.add(TokenMCP(usuario_id=operador.id, nome="Claude", token_hash=hash_token(valor)))
    db.commit()

    acesso = _consultar(valor)

    assert acesso is not None
    assert set(ESCOPOS_EXIGIDOS) <= set(acesso.scopes)
