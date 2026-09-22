"""O leitor do .docx: regras que separam as questões e a fidelidade do texto.

As variações testadas aqui saíram dos simulados reais da equipe (05, 03 e
"Camada N"), medidos antes de o importador existir.
"""

import pytest

from app.errors import RegraDeNegocio
from app.leitor_docx import ParteDaQuestao, ler_docx, separar_questoes
from tests.docx_de_teste import corrida, docx, figura, p, questao, tabela


def _ler(*blocos, **kwargs):
    documento = ler_docx(docx(*blocos, **kwargs))
    return documento, separar_questoes(documento.blocos)


def test_separa_questoes_nos_dois_formatos_de_gabarito():
    _, leitura = _ler(
        p("SIMULADO 07"),
        *questao(1, "Qual o reagente?", "B", ["a) Errada: não reage.", "1. Metanol: combustível."]),
        *questao(2, "Qual a cadeia?", "C", ["Normal e saturada."], marcador="LETRA "),
    )

    assert leitura.titulo == "SIMULADO 07"
    assert [(q.numero, q.gabarito, q.completa) for q in leitura.questoes] == [(1, "B", True), (2, "C", True)]
    primeira = leitura.questoes[0].como_entrada()
    assert primeira["alternativas"]["E"] == "alternativa e da 1"
    # O que parece alternativa ou questão numerada dentro da resolução continua resolução.
    assert "a) Errada" in primeira["resolucao_comentada"].replace("\\", "")
    assert "Metanol" in primeira["resolucao_comentada"]


def test_alternativas_em_figura_e_figura_no_enunciado():
    documento, leitura = _ler(
        p("01. Observe a estrutura:"), p(figura()),
        *questao(1, "", "E", ["A E é aldeído."], figuras_nas_alternativas=True)[1:],
    )

    q = leitura.questoes[0]
    assert q.completa
    assert q.como_entrada()["alternativas"]["A"] == "![](figura:f1)"
    assert q.figuras["f1"] == ParteDaQuestao.ENUNCIADO, "a primeira aparição decide a parte"
    assert len(documento.figuras) == 1, "a mesma mídia usada várias vezes vira uma figura só"


def test_indice_e_expoente_viram_unicode_e_o_que_nao_cabe_vira_latex():
    documento, _ = _ler(p("CO", corrida("3", "subscript"), corrida("2-", "superscript"),
                          corrida("(aq)", "subscript"), " e ", corrida("99m", "superscript"), "Tc"))

    texto = documento.blocos[0].texto
    assert texto.startswith("CO₃²⁻")
    assert "$_{\\text{(aq)}}$" in texto, "o 'q' não tem índice em Unicode"
    assert "⁹⁹ᵐTc" in texto


def test_equacao_do_word_vira_latex():
    equacao = (
        "<m:oMath><m:sPre><m:sub><m:r><m:t>42</m:t></m:r></m:sub>"
        "<m:sup><m:r><m:t>99</m:t></m:r></m:sup><m:e><m:r><m:t>Mo</m:t></m:r></m:e></m:sPre>"
        "<m:r><m:t>​→</m:t></m:r>"
        "<m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>2</m:t></m:r></m:den></m:f>"
        "</m:oMath>"
    )
    documento, _ = _ler(f"<w:p>{equacao}</w:p>")

    assert documento.blocos[0].texto == "${}_{42}^{99}{\\text{Mo}}\\rightarrow \\frac{1}{2}$"


def test_tabela_vira_markdown_e_texto_do_word_nao_vira_marcacao():
    documento, _ = _ler(tabela(("Íon", "mg/L"), ("Na*", "1,20 | 2")), p("R$ 5 e 2_3"))

    assert documento.blocos[0].texto.splitlines() == [
        "| Íon | mg/L |", "| --- | --- |", "| Na\\* | 1,20 \\| 2 |"
    ]
    assert documento.blocos[1].texto == "R\\$ 5 e 2\\_3"


def test_questao_sem_gabarito_vira_aviso_e_nao_chute():
    _, leitura = _ler(*questao(1, "Sem gabarito?", None, []), *questao(2, "Com", "A", ["ok"]))

    assert leitura.questoes[0].completa is False
    assert "falta gabarito" in leitura.questoes[0].avisos[0]


def test_gabarito_numa_tabela_no_fim_do_documento():
    _, leitura = _ler(*questao(1, "Uma", None, []), *questao(2, "Outra", None, []),
                      p("GABARITO"), p("01 - B   02 - D   03 - A"))

    assert [q.gabarito for q in leitura.questoes] == ["B", "D"]
    assert any("tabela do fim" in a for a in leitura.avisos)


def test_arquivo_que_nao_e_docx_e_recusado():
    with pytest.raises(RegraDeNegocio):
        ler_docx(b"isto nao e um zip")


def test_figura_convertida_perde_a_folha_em_branco_em_volta():
    """O LibreOffice devolve a A4 inteira; o aluno tem de ver só o desenho."""
    import io

    from PIL import Image, ImageDraw

    from app.leitor_docx import aparar_margem

    folha = Image.new("RGB", (794, 1123), "white")
    ImageDraw.Draw(folha).rectangle((300, 500, 500, 560), fill="black")
    arquivo = io.BytesIO()
    folha.save(arquivo, "PNG")

    with Image.open(io.BytesIO(aparar_margem(arquivo.getvalue()))) as recortada:
        assert recortada.size == (201 + 16, 61 + 16)


def test_docx_com_bomba_de_entidades_e_recusado():
    """Poucos KB no disco, gigabytes na memória: o XML de fora não declara entidade."""
    import io
    import zipfile

    bomba = io.BytesIO()
    with zipfile.ZipFile(bomba, "w") as z:
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
            '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>'
            "<w:document><w:body>&lol3;</w:body></w:document>",
        )

    with pytest.raises(RegraDeNegocio, match="entidades ou DTD"):
        ler_docx(bomba.getvalue())
