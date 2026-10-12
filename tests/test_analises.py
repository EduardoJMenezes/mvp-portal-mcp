"""A análise personalizada do aluno: a plataforma entrega o resumo e guarda o texto; quem escreve é o Claude."""

import asyncio
from datetime import UTC, datetime, timedelta

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
    return questoes


async def test_a_fila_entrega_o_resumo_e_a_analise_gravada_tira_o_aluno_dela(db, mundo, api_java, monkeypatch):
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)
    questoes = _simulado_encerrado(db, mundo)
    joao = mundo["joao"].usuario_id

    async with Client(mcp) as cliente:
        async def tool(ferramenta, /, **argumentos):
            return (await cliente.call_tool(ferramenta, argumentos)).data

        fila = await tool("listar_analises_pendentes")
        assert fila["na_fila"] == 1 and fila["restam"] == 0
        aluno = fila["alunos"][0]
        assert (aluno["aluno_id"], aluno["aluno"], aluno["motivo"]) == (joao, "João", "primeira análise")
        assert (aluno["respostas"], aluno["acertos"], aluno["erros"]) == (5, 2, 3)
        assert aluno["por_assunto"][0]["nome"] == "Estequiometria"
        assert aluno["por_assunto"][0]["subassuntos"][0]["nome"] == "Pureza e rendimento"

        erros = {e["onde"]: e for e in aluno["erros_recentes"]}
        primeiro = erros["Simulado 02, questão 1"]
        assert primeiro["questao_id"] == questoes[0].id
        assert (primeiro["marcada"], primeiro["gabarito"]) == ("A", "B")
        # O que o professor escreveu para a alternativa marcada: é o material de quem escreve.
        assert primeiro["comentario_da_marcada"].startswith("Você esqueceu de descontar a pureza")
        # Em branco conta como erro, sem alternativa; sem comentário, só se sabe que ele errou.
        assert erros["Simulado 02, questão 4"]["marcada"] is None
        assert erros["Simulado 02, questão 5"]["comentario_da_marcada"] is None

        gravado = await tool("gravar_analises", analises=[
            {"aluno_id": joao, "ponto_principal": "Seu ponto principal agora: pureza.",
             "proximos_passos": "Rever a questão 1 do Simulado 02."},
            {"aluno_id": joao, "ponto_principal": "Repetida."},
            {"aluno_id": mundo["pedro"].usuario_id, "ponto_principal": "Pedro não respondeu nada."},
        ])
        assert gravado["gravadas"] == 1 and gravado["alunos"] == ["João"]
        assert gravado["restam_na_fila"] == 0
        assert [r["aluno_id"] for r in gravado["recusadas"]] == [joao, mundo["pedro"].usuario_id]
        assert "duas vezes" in gravado["recusadas"][0]["motivo"]
        assert "não tem resposta que conte" in gravado["recusadas"][1]["motivo"]

        assert (await tool("listar_analises_pendentes"))["alunos"] == []
        # Pedido pelo nome, ele vem mesmo fora da fila, com a análise anterior junto.
        de_novo = (await tool("listar_analises_pendentes", aluno="João"))["alunos"][0]
        assert de_novo["motivo"] == "pedida pelo professor"
        assert de_novo["analise_anterior"]["ponto_principal"] == "Seu ponto principal agora: pureza."

    linha = db.execute(text("SELECT aluno_id, escrita_por_id, respostas FROM student_analyses")).one()
    assert tuple(linha) == (joao, mundo["professor"].usuario_id, 5)


def test_gravar_analises_e_a_excecao_escrita_e_diz_o_que_nao_pode():
    """Vai ao aluno sem ok um a um; a descrição é o que segura quem escreve no material aprovado."""
    tools = {t.name: t for t in asyncio.run(mcp._list_tools())}
    assert "gravar_analises" not in ALTERAM_NA_HORA

    gravar = " ".join(tools["gravar_analises"].description.split())
    assert "sem aprovação uma a uma" in gravar
    assert "Não explique a matéria por conta própria" in gravar
    assert "não invente o motivo" in gravar
    assert "mostre o texto e grave depois do ok" in gravar
    # O começo da listagem diz o que fazer: é o que chega mesmo se a descrição for cortada.
    listar = " ".join(tools["listar_analises_pendentes"].description.split())[:500]
    assert "gravar_analises" in listar and "100 alunos" in listar
    assert "ÚNICA escrita que chega ao aluno sem o ok" in " ".join(mcp.instructions.split())
