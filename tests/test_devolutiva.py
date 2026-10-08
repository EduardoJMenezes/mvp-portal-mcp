"""A devolutiva pelo chat: o comentário de cada alternativa e o desempenho por assunto."""

import pytest
from fastmcp.exceptions import ToolError

from app.mcp_server.server import mcp
from tests.test_mcp import _quem_esta_pedindo

QUATRO = {"A": "36 g", "B": "18 g", "C": "20 g", "D": "34 g"}


async def test_o_comentario_por_alternativa_nasce_no_rascunho_e_se_corrige_pelo_chat(db, mundo, api_java, monkeypatch):
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        async def tool(ferramenta, /, **argumentos):
            return (await cliente.call_tool(ferramenta, argumentos)).data

        rascunho = await tool(
            "criar_questao_rascunho", enunciado="Qual a massa de 2 mol de água?", alternativas=QUATRO, gabarito="A",
            comentarios={"B": "18 g é a massa de 1 mol: faltou multiplicar por 2."},
        )
        questao = rascunho["questoes"][0]

        # O professor lê o comentário no rascunho, antes de aprovar.
        assert questao["comentarios"] == {"B": "18 g é a massa de 1 mol: faltou multiplicar por 2."}
        assert rascunho["status"] == "RASCUNHO"

        editada = await tool("editar_questao", questao=questao["questao_id"],
                             comentarios={"C": "20 g não sai de nenhuma conta com H2O.", "B": ""})
        assert editada["comentarios"] == {"C": "20 g não sai de nenhuma conta com H2O."}

        with pytest.raises(ToolError, match="não tem a alternativa E para comentar"):
            await tool("editar_questao", questao=questao["questao_id"], comentarios={"E": "não existe"})


async def test_o_desempenho_por_assunto_sai_da_turma_ou_de_um_aluno(db, mundo, api_java, monkeypatch):
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        async def tool(ferramenta, /, **argumentos):
            return (await cliente.call_tool(ferramenta, argumentos)).data

        da_turma = await tool("buscar_desempenho_por_assunto", turma="Extensivo 2027")
        do_aluno = await tool("buscar_desempenho_por_assunto", aluno="João")

        # Ninguém respondeu nada neste mundo: a resposta diz isso, em vez de inventar.
        assert da_turma["turma"] == "Extensivo 2027"
        assert da_turma["geral"]["respostas"] == 0
        assert da_turma["geral"]["assuntos"] == []
        assert "questoes_da_aula" in da_turma
        assert do_aluno["respostas"] == 0 and do_aluno["assuntos"] == []

        with pytest.raises(ToolError, match="um dos dois"):
            await tool("buscar_desempenho_por_assunto")
        with pytest.raises(ToolError, match="um dos dois"):
            await tool("buscar_desempenho_por_assunto", turma="Extensivo 2027", aluno="João")
        with pytest.raises(ToolError, match="Turma 'Noturno' não existe"):
            await tool("buscar_desempenho_por_assunto", turma="Noturno")
