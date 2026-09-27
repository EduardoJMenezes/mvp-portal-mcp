"""Biblioteca de módulos pelo chat, pela ponte até a API de verdade (decisão 0011)."""

from fastmcp import Client

from app.mcp_server.server import mcp
from tests.test_mcp import _quem_esta_pedindo


async def test_atribui_o_modulo_a_duas_turmas_e_copia(db, mundo, api_java, monkeypatch):
    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        solto = (await cliente.call_tool("criar_modulo", {"turma": None, "nome": "K99 - Revisão"})).structured_content
        atribuido = (await cliente.call_tool("atribuir_turmas", {
            "modulo": "K99 - Revisão", "turmas": ["Extensivo 2027", "Extensivo 2026"],
        })).structured_content
        biblioteca = (await cliente.call_tool("listar_biblioteca", {})).structured_content["result"]

    assert solto["turma"] is None
    assert atribuido["turmas"] == ["Extensivo 2027", "Extensivo 2026"]
    k99 = next(m for m in biblioteca if m["nome"] == "K99 - Revisão")
    assert sorted(k99["turmas"]) == ["Extensivo 2026", "Extensivo 2027"]
