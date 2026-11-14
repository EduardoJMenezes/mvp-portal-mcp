"""A venda montada pelo chat, pela ponte até a API de verdade."""

from fastmcp import Client

from app.mcp_server.server import mcp
from tests.test_mcp import _quem_esta_pedindo

TABELA = [
    {"pix": 1700, "cartao_parcelas": 12, "cartao_parcela": 159.90},
    {"a_partir_de": "2027-04-01", "pix": 1240, "cartao_parcelas": 8, "cartao_parcela": 174.90},
]


async def test_monta_a_venda_fora_do_ar_e_poe_no_ar_depois(db, mundo, api_java, monkeypatch):
    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        criada = (await cliente.call_tool("montar_venda", {
            "link": "extensivo-2027",
            "nome": "Extensivo 2027",
            "turmas": ["Extensivo 2027", "Extensivo 2026"],
            "precos": TABELA,
            "matricula": 330,
            "matricula_parcelas": 3,
            "a_venda_ate": "2027-08-31",
            "a_venda": True,
        })).structured_content
        no_ar = (await cliente.call_tool("montar_venda", {"link": "extensivo-2027", "a_venda": True})).structured_content
        resumo = (await cliente.call_tool("ver_vendas", {})).structured_content

    assert criada["criada"] is True
    assert criada["plano"]["ativo"] is False, "plano novo pelo chat nasce fora do ar"
    assert criada["aviso"]
    assert [l["cartao_centavos"] for l in criada["plano"]["precos"]] == [191880, 139920]
    assert criada["plano"]["matricula_centavos"] == 33000
    assert criada["link_publico"].endswith("/assinar/extensivo-2027")
    assert criada["conferir_em"].endswith("/admin/vendas/") or criada["conferir_em"] == "Admin › Vendas"

    assert no_ar["criada"] is False and no_ar["plano"]["ativo"] is True
    assert len(no_ar["plano"]["precos"]) == 2, "pôr no ar não mexe na tabela"

    plano = resumo["planos"][0]
    assert plano["hoje"]["pix_centavos"] == 170000
    assert plano["link_publico"].endswith("/assinar/extensivo-2027")
    assert resumo["envios_pendentes"] == []
