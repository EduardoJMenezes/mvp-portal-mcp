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


async def test_o_icone_do_modulo_se_escolhe_e_se_troca_pelo_chat(db, mundo, api_java, monkeypatch):
    """A capa do cartão do aluno: pelo chat vai o ícone; foto, só pelo portal."""
    import pytest
    from fastmcp.exceptions import ToolError

    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        # Posicional-only: criar_modulo tem um argumento chamado `nome`.
        async def tool(ferramenta, /, **argumentos):
            return (await cliente.call_tool(ferramenta, argumentos)).structured_content

        await tool("criar_modulo", turma="Extensivo 2027", nome="K07 - Termoquímica", icone="chama")
        criado = next(m for m in (await tool("listar_biblioteca"))["result"] if m["nome"] == "K07 - Termoquímica")
        trocado = await tool("editar_modulo", turma="Extensivo 2027", modulo="K07", novo_icone="termometro")
        automatico = await tool("editar_modulo", turma="Extensivo 2027", modulo="K07", novo_icone="automatico")

        # O nome errado volta com a lista do que existe, e nada é criado.
        with pytest.raises(ToolError, match="Ícone 'foguete' não existe. Ícones: atomo, frasco"):
            await tool("criar_modulo", turma="Extensivo 2027", nome="K08", icone="foguete")
        nomes = [m["nome"] for m in (await tool("listar_biblioteca"))["result"]]

    assert criado["icone"] == "chama"
    assert trocado["icone"] == "termometro"
    assert automatico["icone"] is None
    assert "K08" not in nomes
