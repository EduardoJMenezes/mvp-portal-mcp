"""O resultado do simulado sai quando o professor libera, com a análise que o Claude dele escreveu."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import text

from app.mcp_server.server import mcp
from tests.modelos import (
    Alternativa,
    Dificuldade,
    Questao,
    QuestaoAssunto,
    Resposta,
    Simulado,
    SimuladoQuestao,
    Status,
    Tentativa,
)
from tests.test_mcp import ALTERAM_NA_HORA, _quem_esta_pedindo


def _simulado_encerrado(db, mundo):
    """João fez um simulado de cinco questões que já fechou: errou a 1 e a 5 e deixou a 4 em branco."""
    questoes = list(mundo["questoes"])
    for numero in (4, 5):
        questao = Questao(enunciado=f"Enunciado {numero}", gabarito="B", dificuldade=Dificuldade.MEDIA,
                          status=Status.PUBLICADO, criado_por_id=mundo["professor"].usuario_id)
        db.add(questao)
        db.flush()
        for letra in "ABCDE":
            db.add(Alternativa(questao_id=questao.id, letra=letra, texto=f"alt {letra}"))
        db.add(QuestaoAssunto(questao_id=questao.id, assunto_id=mundo["assunto"].id, subassunto_id=mundo["subassunto"].id))
        questoes.append(questao)

    ontem = datetime.now(UTC) - timedelta(days=1)
    simulado = Simulado(titulo="Simulado 02", status=Status.PUBLICADO, abre_em=ontem - timedelta(days=1), fecha_em=ontem,
                        criado_por_id=mundo["professor"].usuario_id)
    db.add(simulado)
    db.flush()
    for ordem, questao in enumerate(questoes, start=1):
        db.add(SimuladoQuestao(simulado_id=simulado.id, questao_id=questao.id, ordem=ordem))
    tentativa = Tentativa(simulado_id=simulado.id, aluno_id=mundo["joao"].usuario_id, finalizado_em=ontem)
    db.add(tentativa)
    db.flush()
    for questao, letra in zip(questoes, ["A", "B", "B", None, "C"], strict=True):
        if letra:
            db.add(Resposta(tentativa_id=tentativa.id, questao_id=questao.id, alternativa_marcada=letra, correta=letra == "B"))
    db.execute(text("UPDATE question_options SET comentario = :c WHERE questao_id = :q AND letra = 'A'"),
               {"c": "Você esqueceu de descontar a pureza. Falta revisar: pureza.", "q": questoes[0].id})
    db.commit()
    return simulado, questoes


async def test_gerar_o_resultado_do_simulado_e_listar_escrever_gravar_e_liberar(db, mundo, api_java, monkeypatch):
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)
    simulado, questoes = _simulado_encerrado(db, mundo)
    joao = mundo["joao"].usuario_id

    async with Client(mcp) as cliente:
        async def tool(ferramenta, /, **argumentos):
            return (await cliente.call_tool(ferramenta, argumentos)).data

        fila = await tool("listar_analises_pendentes", simulado="Simulado 02")
        assert (fila["recorte"], fila["simulado"], fila["resultado_liberado"]) == ("SIMULADO", "Simulado 02", False)
        assert (fila["participantes"], fila["na_fila"], fila["restam"]) == (1, 1, 0)
        # Só a primeira questão tem comentário: nas outras quatro, quem escreve só sabe que ele errou.
        assert (fila["questoes"], fila["questoes_sem_comentario"]) == (5, 4)
        aluno = fila["alunos"][0]
        assert (aluno["aluno_id"], aluno["aluno"]) == (joao, "João")
        assert (aluno["respostas"], aluno["acertos"], aluno["erros"]) == (5, 2, 3)
        assert aluno["por_assunto"][0]["nome"] == "Estequiometria"

        erros = {e["onde"]: e for e in aluno["erros_recentes"]}
        primeiro = erros["Simulado 02, questão 1"]
        assert primeiro["questao_id"] == questoes[0].id
        assert (primeiro["marcada"], primeiro["gabarito"]) == ("A", "B")
        assert primeiro["comentario_da_marcada"].startswith("Você esqueceu de descontar a pureza")
        assert erros["Simulado 02, questão 4"]["marcada"] is None
        assert "comentario_da_marcada" not in erros["Simulado 02, questão 5"]

        gravado = await tool("gravar_analises", simulado="Simulado 02", analises=[
            {"aluno_id": joao, "ponto_principal": "Seu ponto principal: pureza.", "proximos_passos": "Rever a questão 1."},
            {"aluno_id": mundo["pedro"].usuario_id, "ponto_principal": "Pedro não fez a prova."},
        ])
        assert (gravado["recorte"], gravado["gravadas"], gravado["alunos"]) == ("SIMULADO", 1, ["João"])
        assert (gravado["restam"], gravado["resultado_liberado"]) == (0, False)
        assert "não fez 'Simulado 02'" in gravado["recusadas"][0]["motivo"]
        assert (await tool("listar_analises_pendentes", simulado="Simulado 02"))["alunos"] == []

        # Até aqui o aluno não vê nada: quem solta o resultado é o professor.
        liberado = await tool("liberar_resultado_simulado", simulado="Simulado 02")
        assert (liberado["liberado_agora"], liberado["participantes"]) == (True, 1)
        assert (liberado["com_analise"], liberado["sem_analise"]) == (1, 0)
        assert (await tool("liberar_resultado_simulado", simulado="Simulado 02"))["liberado_agora"] is False
        assert (await tool("detalhar_simulado", simulado="Simulado 02"))["resultado_liberado_em"]

    linha = db.execute(text("SELECT aluno_id, simulado_id, escrita_por_id FROM student_analyses")).one()
    assert tuple(linha) == (joao, simulado.id, mundo["professor"].usuario_id)


async def test_a_analise_geral_e_pedida_pelo_nome_do_aluno_e_fica_com_o_professor(db, mundo, api_java, monkeypatch):
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)
    _simulado_encerrado(db, mundo)
    joao = mundo["joao"].usuario_id

    async with Client(mcp) as cliente:
        async def tool(ferramenta, /, **argumentos):
            return (await cliente.call_tool(ferramenta, argumentos)).data

        with pytest.raises(ToolError, match="Informe o simulado"):
            await tool("listar_analises_pendentes")

        geral = await tool("listar_analises_pendentes", aluno="João")
        assert (geral["recorte"], geral["simulado"]) == ("GERAL", None)
        assert geral["alunos"][0]["respostas"] == 5
        assert geral["alunos"][0]["outros_simulados"][0]["titulo"] == "Simulado 02"

        gravado = await tool("gravar_analises", analises=[{"aluno_id": joao, "ponto_principal": "O João esquece a pureza."}])
        assert (gravado["recorte"], gravado["gravadas"], gravado["restam"]) == ("GERAL", 1, None)
        de_novo = await tool("listar_analises_pendentes", aluno="João")
        assert de_novo["alunos"][0]["analise_anterior"]["ponto_principal"] == "O João esquece a pureza."

    assert db.execute(text("SELECT simulado_id FROM student_analyses")).scalar_one() is None


def test_as_descricoes_dizem_para_quem_se_escreve_e_quando_o_resultado_sai():
    """A descrição é o que segura quem escreve no material aprovado e na ordem certa."""
    tools = {t.name: t for t in asyncio.run(mcp._list_tools())}
    assert "liberar_resultado_simulado" in ALTERAM_NA_HORA
    assert "gravar_analises" not in ALTERAM_NA_HORA

    gravar = " ".join(tools["gravar_analises"].description.split())
    assert "Não explique a matéria por conta própria" in gravar
    assert "não invente o motivo" in gravar
    assert "PARA O ALUNO, em segunda pessoa" in gravar
    assert "PARA O PROFESSOR, sobre o aluno, em terceira pessoa" in gravar
    # O começo da listagem diz o caminho inteiro: é o que chega mesmo se a descrição for cortada.
    listar = " ".join(tools["listar_analises_pendentes"].description.split())[:700]
    assert "gravar_analises" in listar and "liberar_resultado_simulado" in listar
    liberar = " ".join(tools["liberar_resultado_simulado"].description.split())
    assert "não se desfaz" in liberar
    assert "só vê o resultado quando o professor libera" in " ".join(mcp.instructions.split())
