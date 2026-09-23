"""Aula ao vivo pelo chat, pela ponte até a API de verdade."""

from fastmcp import Client

from app.mcp_server.server import mcp
from tests.test_mcp import _quem_esta_pedindo


async def test_agendar_pelo_chat_nasce_em_rascunho_sem_sala(db, mundo, api_java, monkeypatch):
    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        saida = (await cliente.call_tool("agendar_aula", {
            "titulo": "Revisão ao vivo", "inicio": "2090-10-10T19:00", "minutos": 90,
            "turmas": ["Extensivo 2027"], "modulo": "K01 - Estequiometria",
        })).structured_content
        lista = (await cliente.call_tool("listar_aulas", {})).structured_content["result"]

    assert saida["aula"]["status"] == "RASCUNHO"
    assert saida["aula"]["tem_sala"] is False
    assert "Admin › Aulas ao vivo" in saida["mensagem"]
    assert [a["titulo"] for a in lista] == ["Revisão ao vivo"]
    # Não existe tool que publique aula: a sala no Zoom é decisão do professor, no portal.
    nomes = {t.name for t in await mcp.list_tools()}
    assert not {n for n in nomes if "aula" in n} - {"agendar_aula", "listar_aulas"}
