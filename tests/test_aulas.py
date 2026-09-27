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
    # Publicar é o `publicar` de agendar_aula, com o ok do professor no chat — não há outra tool.
    nomes = {t.name for t in await mcp.list_tools()}
    assert not {n for n in nomes if "aula" in n} - {"agendar_aula", "listar_aulas"}


async def test_com_publicar_a_sala_nasce_e_o_horario_da_outra_plataforma_e_recusado(
    db, mundo, api_java, monkeypatch
):
    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        saida = (await cliente.call_tool("agendar_aula", {
            "titulo": "Revisão ao vivo", "inicio": "2090-10-12T19:00",
            "turmas": ["Extensivo 2027"], "publicar": True,
        })).structured_content
        recusa = await cliente.call_tool("agendar_aula", {
            "titulo": "Terça 18h", "inicio": "2090-10-10T18:00",
            "turmas": ["Extensivo 2027"], "publicar": True,
        }, raise_on_error=False)

    assert saida["aula"]["status"] == "PUBLICADO"
    assert saida["aula"]["tem_sala"] is True
    assert recusa.is_error
    assert "outra plataforma" in recusa.content[0].text
