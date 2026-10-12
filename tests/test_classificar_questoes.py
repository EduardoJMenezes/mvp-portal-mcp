"""Classificar pelo chat as questões que entraram sem assunto, todas de uma vez."""

import pytest
from fastmcp.exceptions import ToolError

from app.mcp_server.server import mcp
from tests.test_mcp import _quem_esta_pedindo

QUATRO = {"A": "1", "B": "2", "C": "3", "D": "4"}


async def test_as_sem_assunto_sao_listadas_e_classificadas_numa_chamada_so(db, mundo, api_java, monkeypatch):
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        async def tool(ferramenta, /, **argumentos):
            return (await cliente.call_tool(ferramenta, argumentos)).data

        antes = (await tool("listar_questoes_sem_assunto", limite=100))["total"]
        primeira = (await tool("criar_questao_rascunho", enunciado="Quantas ligações sigma e pi há no carbonato?",
                               alternativas=QUATRO, gabarito="A"))["questoes"][0]["questao_id"]
        segunda = (await tool("criar_questao_rascunho", enunciado="Qual a geometria da amônia?",
                              alternativas=QUATRO, gabarito="B"))["questoes"][0]["questao_id"]

        lista = await tool("listar_questoes_sem_assunto", limite=100)
        assert lista["total"] == antes + 2
        achadas = {q["questao_id"]: q for q in lista["questoes"]}
        assert achadas[primeira]["enunciado"].startswith("Quantas ligações")
        assert achadas[primeira]["alternativas"]["A"] == "1"
        # A taxonomia vem junto: é com ela que a proposta prefere o assunto que já existe.
        assert isinstance(lista["assuntos"], list)

        linhas = [
            {"questao": primeira, "assunto": "Ligações de teste do lote", "subassunto": "Sigma e pi"},
            {"questao": segunda, "assunto": "Ligações de teste do lote", "subassunto": "Geometria molecular"},
        ]
        # Assunto que não existe não nasce em silêncio: o erro diz o que falta e como seguir.
        with pytest.raises(ToolError, match="criar_novos=true"):
            await tool("classificar_questoes", classificacoes=linhas)
        assert (await tool("listar_questoes_sem_assunto", limite=100))["total"] == antes + 2

        feito = await tool("classificar_questoes", classificacoes=linhas, criar_novos=True)
        assert feito["classificadas"] == 2
        assert feito["assuntos_criados"] == ["Ligações de teste do lote"]
        assert len(feito["subassuntos_criados"]) == 2
        assert feito["restam_sem_assunto"] == antes

        detalhe = await tool("detalhar_questao", questao=segunda)
        assert detalhe["classificacao"] == [{"assunto": "Ligações de teste do lote", "subassunto": "Geometria molecular"}]
