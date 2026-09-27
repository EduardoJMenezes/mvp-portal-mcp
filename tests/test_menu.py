"""O menu do aluno pelo chat, pela ponte até a API de verdade."""

from fastmcp import Client

from app.mcp_server.server import mcp
from tests.test_mcp import _quem_esta_pedindo


async def test_monta_le_e_copia_o_menu_com_categoria(db, mundo, api_java, monkeypatch):
    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        antes = (await cliente.call_tool("listar_menu", {"turma": "Extensivo 2027"})).structured_content
        montado = (await cliente.call_tool("definir_menu", {
            "turma": "Extensivo 2027",
            "botoes": [
                {"rotulo": "Simulados Rodmelo", "funcionalidade": "SIMULADOS", "categoria": "Rodmelo"},
                {"rotulo": "Monitoria online", "funcionalidade": "AULAS", "categoria": "Monitoria"},
            ],
        })).structured_content
        copiado = (await cliente.call_tool("copiar_menu", {
            "de": "Extensivo 2027", "para": "Extensivo 2027",
        })).structured_content

    assert antes["padrao"] is True
    assert [b["rotulo"] for b in montado["botoes"]] == ["Simulados Rodmelo", "Monitoria online"]
    assert montado["botoes"][1]["categoria"] == "Monitoria"
    assert copiado["padrao"] is False
