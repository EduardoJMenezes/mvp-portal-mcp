"""A leitura do .docx que a API pede para a tela de "Novo simulado".

Nada é gravado: a rota só lê e devolve. Por isso quem a chama é a API, com o
segredo de serviço — sem ele, ninguém de fora lê um documento por aqui.
"""

from fastapi.testclient import TestClient

from app.config import get_settings
from tests.docx_de_teste import docx, figura, p, questao

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _enviar(arquivo: bytes, nome: str = "simulado.docx", segredo: str | None = "certo"):
    from app import main

    cabecalhos = {}
    if segredo is not None:
        cabecalhos["X-Servico"] = get_settings().servico_token if segredo == "certo" else segredo
    return TestClient(main.app).post(
        "/api/leitura/docx", files={"arquivo": (nome, arquivo, DOCX)}, headers=cabecalhos)


def test_sem_o_segredo_de_servico_a_rota_nao_le():
    arquivo = docx(*questao(1, "Enunciado", "A", ["Porque sim."]))
    assert _enviar(arquivo, segredo=None).status_code == 403
    assert _enviar(arquivo, segredo="errado").status_code == 403


def test_devolve_as_questoes_e_as_figuras_sem_gravar_nada():
    arquivo = docx(p("SIMULADO 09"), p("01. Observe:"), p(figura()),
                   *[p(f"{letra}) item {letra}") for letra in "abcde"], p("GABARITO: B"), p("Porque sim."))
    lido = _enviar(arquivo)
    assert lido.status_code == 200, lido.text
    corpo = lido.json()
    assert corpo["arquivo_nome"] == "simulado.docx"
    assert [q["numero"] for q in corpo["questoes"]] == [1]
    dados = corpo["questoes"][0]["dados"]
    assert dados["gabarito"] == "B" and sorted(dados["alternativas"]) == list("ABCDE")
    # A figura vai pela chave do leitor; trocar por id é da API, que é quem a guarda.
    assert "figura:f1" in dados["enunciado"]
    assert [f["chave"] for f in corpo["figuras"]] == ["f1"]


def test_a_questao_que_nao_fechou_vai_com_o_que_deu_para_ler():
    """Na tela o professor completa: por isso só incompletas também é leitura válida."""
    arquivo = docx(*questao(1, "Sem gabarito", None, []))
    lido = _enviar(arquivo)
    assert lido.status_code == 200, lido.text
    corpo = lido.json()
    assert corpo["questoes"] == []
    incompleta = corpo["incompletas"][0]
    assert incompleta["numero"] == 1
    assert incompleta["dados"]["enunciado"].startswith("Sem gabarito")
    assert any("gabarito" in aviso for aviso in incompleta["avisos"])


def test_recusa_o_que_nao_e_docx():
    recusado = _enviar(b"qualquer coisa", nome="prova.pdf")
    assert recusado.status_code == 400
    assert "docx" in recusado.json()["detail"]
