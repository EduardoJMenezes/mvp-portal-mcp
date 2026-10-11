"""Sem confirmação no cliente, o professor é mandado ao portal — no domínio do portal, não no do MCP."""

from types import SimpleNamespace

from app.mcp_server import tools


def test_o_link_de_aprovar_e_do_portal(monkeypatch):
    monkeypatch.setattr(
        tools, "get_settings",
        lambda: SimpleNamespace(portal_url="https://portal.exemplo/", mcp_base_url="https://mcp.exemplo"),
    )
    onde = "https://portal.exemplo/admin/rascunhos/revisar/?id=7"
    assert tools._aprovar_no_portal(7)["aprovar_em"] == onde
    # A recusa silenciosa do aplicativo também aponta o caminho, em vez de só dizer "não".
    assert onde in tools._recusado(7)["mensagem"]


def test_sem_portal_configurado_diz_onde_clicar(monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: SimpleNamespace(portal_url=None))
    assert tools._aprovar_no_portal(7)["aprovar_em"] == "Admin › Rascunhos"


def test_a_questao_avulsa_volta_com_o_link_dela_no_banco_de_questoes(monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: SimpleNamespace(portal_url="https://portal.exemplo/"))
    criado = tools._com_onde_conferir({"rascunho_id": 3, "questoes": [{"questao_id": 41}]})
    assert criado["questao_id"] == 41
    assert criado["conferir_em"] == "https://portal.exemplo/admin/questoes/editar/?id=41"
    assert criado["rascunho_id"] == 3


def test_sem_portal_configurado_a_questao_e_achada_pelo_numero(monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: SimpleNamespace(portal_url=None))
    assert tools._com_onde_conferir({"questoes": [{"questao_id": 41}]})["conferir_em"] == "Banco de questões › #41"
