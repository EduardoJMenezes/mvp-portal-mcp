"""Leitura do número da questão no título do vídeo.

Os casos vêm do acervo real de 2026 (pasta K03 do Extensivo), onde os vídeos se
chamam Q04, Q30, Q52 e a API devolve fora de ordem.
"""

from __future__ import annotations

import pytest

from app.integracoes.vimeo.nomes import inferir_numero, numero_do_titulo


@pytest.mark.parametrize(
    "titulo,esperado",
    [
        ("Q04", 4),
        ("Q30", 30),
        ("Q52", 52),
        ("q7", 7),
        ("Q 12", 12),
        ("Questão 12", 12),
        ("Questao 3 - reagente limitante", 3),
        ("001 - Balanceamento", 1),
        ("012) Mol e massa molar", 12),
    ],
)
def test_le_o_numero_dos_padroes_conhecidos(titulo: str, esperado: int):
    assert numero_do_titulo(titulo) == esperado


@pytest.mark.parametrize("titulo", ["", None, "Estequiometria particulares 26.2", "revisão geral"])
def test_titulo_sem_numero_de_questao(titulo):
    assert numero_do_titulo(titulo) is None


def test_titulo_curto_tem_confianca_alta():
    resultado = inferir_numero("Q04")

    assert (resultado.numero, resultado.confianca) == (4, "alta")


def test_numero_no_meio_de_titulo_longo_tem_confianca_baixa():
    """O professor precisa revisar: o número pode ser de outra coisa."""
    resultado = inferir_numero("Aula sobre a Q15 e outras questões de revisão")

    assert resultado.numero == 15
    assert resultado.confianca == "baixa"


def test_ordena_a_pasta_pelo_numero_do_titulo():
    """É este o uso: a API devolve fora de ordem, o título dá a ordem."""
    como_a_api_devolve = ["Q52", "Q51", "Q47", "Q34", "Q04", "Q70"]

    ordenados = sorted(como_a_api_devolve, key=lambda t: numero_do_titulo(t) or 10**6)

    assert ordenados == ["Q04", "Q34", "Q47", "Q51", "Q52", "Q70"]
