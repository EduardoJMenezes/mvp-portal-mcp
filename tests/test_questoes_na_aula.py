"""Questões da apostila dentro da aula: pelo Claude, continuam nascendo em rascunho."""

import json

import pytest
from fastmcp.exceptions import ToolError

from app.mcp_server.server import mcp
from tests.test_mcp import _detalhe, _quem_esta_pedindo

QUATRO = {"A": "36 g", "B": "18 g", "C": "20 g", "D": "34 g"}


async def test_questoes_na_aula_nascem_em_rascunho_com_o_numero_no_nome(db, mundo, api_java, monkeypatch):
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        resposta = (await cliente.call_tool("criar_questoes_como_itens", {
            "turma": "Extensivo 2027", "modulo": "K01 - Estequiometria", "submodulo": "Questões da apostila",
            "questoes": [
                {"numero": 4, "enunciado": "Qual a massa de 2 mol de água?", "alternativas": QUATRO,
                 "gabarito": "A", "assunto": "Estequiometria"},
                {"questao_id": mundo["questoes"][0].id, "nome": "Desafio"},
            ],
        })).data

    assert resposta["aviso"].startswith("Nada foi publicado")
    rascunho = resposta["rascunho"]
    assert [(i["nome"], i["status"]) for i in rascunho["itens"]] == [("Q04", "RASCUNHO"), ("Desafio", "RASCUNHO")]
    # A apostila para na D: quatro alternativas fazem uma questão completa.
    assert list(rascunho["questoes"][0]["alternativas"]) == ["A", "B", "C", "D"]
    assert rascunho["questoes"][0]["completa"] is True
    assert rascunho["aprovado_por"] is None


async def test_questoes_na_aula_nao_publicam_sem_o_ok_do_professor(db, mundo, api_java, monkeypatch):
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        rid = (await cliente.call_tool("criar_questoes_como_itens", {
            "modulo": "K01 - Estequiometria", "submodulo": "Questões da apostila",
            "questoes": [{"enunciado": "Sem turma: acha o módulo na biblioteca", "alternativas": QUATRO,
                          "gabarito": "B"}],
        })).data["rascunho"]["rascunho_id"]

        # O cliente de teste não mostra formulário: a tool não publica, manda aprovar no portal.
        publicado = (await cliente.call_tool("publicar_rascunho", {"rascunho_id": rid})).data

    assert publicado["publicado"] is False
    assert _detalhe(rid)["status"] == "RASCUNHO"


async def test_questao_em_rascunho_de_outro_lugar_nao_vira_linha(db, mundo, api_java, monkeypatch):
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        avulsa = (await cliente.call_tool("criar_questao_rascunho", {
            "enunciado": "Ainda não aprovada", "alternativas": QUATRO, "gabarito": "A",
        })).data["questoes"][0]["questao_id"]

        with pytest.raises(ToolError, match="ainda é rascunho"):
            await cliente.call_tool("criar_questoes_como_itens", {
                "modulo": "K01 - Estequiometria", "submodulo": "Questões da apostila", "questoes": [avulsa],
            })


async def test_docx_da_apostila_vira_linhas_do_submodulo(db, mundo, api_java, monkeypatch):
    """O mesmo link de envio, com outro destino: as questões viram linhas da aula, sem prova."""
    from fastapi.testclient import TestClient
    from fastmcp import Client

    from app import main
    from tests.docx_de_teste import docx, questao

    _quem_esta_pedindo(monkeypatch, mundo)
    arquivo = docx(*questao(1, "Com quatro alternativas", "D", ["A D é a certa."], letras="abcd"),
                   *questao(2, "Com cinco", "E", ["ok"]))

    async with Client(mcp) as cliente:
        link = (await cliente.call_tool("importar_questoes_docx", {
            "turma": "Extensivo 2027", "modulo": "K01 - Estequiometria", "submodulo": "Questões da apostila",
        })).data
        enviado = TestClient(main.app).post(
            f"/api/importacoes/{link['link'].rsplit('/', 1)[-1]}/arquivo",
            files={"arquivo": ("k01.docx", arquivo,
                               "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert enviado.status_code == 200, enviado.text
        revisao = await cliente.call_tool("revisar_importacao", {"importacao": link["importacao_id"]})

    # A revisão volta como texto mais as figuras; o texto é o JSON da leitura.
    lido = json.loads(revisao.content[0].text)
    lido = json.loads(lido[0]) if isinstance(lido, list) else lido
    assert lido["simulado_id"] is None
    assert lido["total_questoes"] == 2
    assert lido["titulo"] == "K01 - Estequiometria › Questões da apostila"
    rascunho = _detalhe(enviado.json()["rascunho_id"])
    assert [i["nome"] for i in rascunho["itens"]] == ["Q01", "Q02"]
    assert [list(q["alternativas"]) for q in rascunho["questoes"]] == [list("ABCD"), list("ABCDE")]
    assert rascunho["simulado"] is None
