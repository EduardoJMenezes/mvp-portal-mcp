"""A agenda pelo chat, pela ponte até a API de verdade (decisão 0012)."""

from fastmcp import Client

from app.mcp_server.server import mcp
from tests.test_mcp import _quem_esta_pedindo


async def test_cria_lista_edita_e_remove_eventos(db, mundo, api_java, monkeypatch):
    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        criados = (await cliente.call_tool("criar_eventos", {"eventos": [
            {"titulo": "K01", "inicio": "2090-02-01T08:00", "turmas": ["Extensivo 2027"],
             "modulo": "K01 - Estequiometria", "categoria": "Aula"},
            {"titulo": "Carnaval", "inicio": "2090-02-15T00:00", "fim": "2090-02-22T23:59",
             "turmas": ["Extensivo 2027", "Extensivo 2026"], "categoria": "Feriado"},
        ]})).structured_content["result"]
        editado = (await cliente.call_tool("editar_evento", {
            "evento": str(criados[0]["evento_id"]), "inicio": "2090-02-04T08:00",
        })).structured_content
        await cliente.call_tool("remover_evento", {"evento": str(criados[1]["evento_id"])})
        agenda = (await cliente.call_tool("listar_agenda", {})).structured_content["result"]

    assert criados[0]["destino"]["tipo"] == "MODULO"
    assert editado["inicio_em"].startswith("2090-02-04T08:00")
    assert [e["titulo"] for e in agenda] == ["K01"]
