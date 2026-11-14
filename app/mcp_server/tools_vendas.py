"""A venda do curso pelo chat: montar o plano e acompanhar pedidos e envios.

É o mesmo plano da tela Admin › Vendas: o que o professor monta aqui aparece lá,
e o contrário. Valores em reais; o cartão como "N parcelas de R$ X", que é como
a página de vendas anuncia. Plano novo nasce FORA DO AR (a API garante): o
professor confere na tela e só depois pede para pôr no ar.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field

from app.config import get_settings
from app.mcp_server.api import comando
from app.mcp_server.server import mcp
from app.mcp_server.tools import SOMENTE_LEITURA
from app.mcp_server.tools_estrutura import ALTERA


class Preco(BaseModel):
    a_partir_de: date | None = Field(
        default=None,
        description="Desde quando a linha vale (AAAA-MM-DD). A primeira linha fica sem data: vale desde já.",
    )
    pix: float | None = Field(default=None, description="Pix à vista, em reais, ex.: 1700. Vazio: sem Pix nesta linha.")
    cartao_parcelas: int | None = Field(default=None, description="Em quantas vezes no cartão, de 1 a 12, ex.: 12")
    cartao_parcela: float | None = Field(
        default=None, description="Valor de CADA parcela no cartão, em reais, ex.: 159.90. Vazio: sem cartão nesta linha."
    )


def _links(plano: dict) -> dict:
    base = (get_settings().portal_url or "").rstrip("/")
    return {
        "conferir_em": f"{base}/admin/vendas/" if base else "Admin › Vendas",
        "link_publico": f"{base}/assinar/{plano['link']}" if base else f"/assinar/{plano['link']}",
    }


@mcp.tool(name="montar_venda", annotations=ALTERA)
def montar_venda(
    link: Annotated[str, Field(description="Fim do endereço de compra, ex.: 'extensivo-2027' (vira /assinar/extensivo-2027). Acha o plano para editar; se não existir, cria.")],
    nome: Annotated[str | None, Field(description="O que o aluno lê na página de compra, ex.: 'Extensivo 2027'. Obrigatório ao criar.")] = None,
    turmas: Annotated[list[str] | None, Field(description="Turmas que o pagamento abre, ex.: ['Extensivo 2027', 'Revisão 2027']. Obrigatório ao criar.")] = None,
    precos: Annotated[list[Preco] | None, Field(description="A tabela INTEIRA de preços do curso (substitui a anterior). Uma linha sem data e, se o preço muda com o tempo, outras com a_partir_de.")] = None,
    matricula: Annotated[float | None, Field(description="Matrícula em reais, cobrada no início, à parte do curso, ex.: 330. 0 tira a matrícula.")] = None,
    matricula_parcelas: Annotated[int | None, Field(description="Até quantas vezes a matrícula no cartão, ex.: 3")] = None,
    acesso_ate: Annotated[date | None, Field(description="Até quando o aluno tem acesso às turmas (AAAA-MM-DD)")] = None,
    a_venda_ate: Annotated[str | None, Field(description="Último dia de matrícula (AAAA-MM-DD); depois o link mostra 'matrículas encerradas'. '' tira o prazo.")] = None,
    a_venda: Annotated[bool | None, Field(description="true põe o link no ar; false tira. Plano NOVO sempre nasce fora do ar: pôr no ar é uma segunda chamada, depois do ok.")] = None,
) -> dict:
    """Cria ou edita, pelo link, o que se vende do curso: preço do curso (Pix
    à vista ou parcelado no cartão, cada um com o seu valor), matrícula,
    turmas que o pagamento abre e até quando se vende.

    **Antes de chamar, mostre ao professor no chat a tabela como o aluno vai
    ver** — por linha: "a partir de [data]: Nx de R$ X no cartão (total R$ Y)
    ou R$ Z no Pix" —, a matrícula, as turmas e o último dia de venda, e
    espere o ok dele.

    O cartão vai como a página de vendas anuncia: `cartao_parcelas` e o valor
    de cada parcela (`cartao_parcela`); o total é a conta das duas. Quando o
    preço muda com a data (ex.: proporcional a partir de abril), cada mudança
    é uma linha com `a_partir_de`; a primeira linha não tem data. Na edição,
    `precos` troca a tabela inteira e o que não vier fica como está.

    Plano novo nasce FORA DO AR, mesmo com a_venda=true. Passe ao professor o
    link `conferir_em` (a tela de Vendas, onde ele confere) e só depois do ok
    dele chame de novo com o mesmo `link` e a_venda=true. `link_publico` é o
    endereço para os botões da página de vendas.
    """
    feito = comando(
        "montar_venda",
        link=link,
        nome=nome,
        turmas=turmas,
        precos=[p.model_dump(mode="json") for p in precos] if precos is not None else None,
        matricula=matricula,
        matricula_parcelas=matricula_parcelas,
        acesso_ate=acesso_ate.isoformat() if acesso_ate else None,
        a_venda_ate=a_venda_ate,
        a_venda=a_venda,
    )
    return {**feito, **_links(feito["plano"])}


@mcp.tool(name="ver_vendas", annotations=SOMENTE_LEITURA)
def ver_vendas() -> dict:
    """Mostra a venda do curso: cada plano com o preço que vale hoje
    (`hoje`, em centavos, e até quando vale), se está no ar e até quando
    vende; quantos pedidos há por situação, quantos alunos pagaram a
    matrícula e ainda não o curso; e quem pagou e ainda não recebeu o
    material (1º envio: apostila; 2º: camisa e revisão), com o endereço.

    Use para "como estão as vendas?", "quem falta receber a apostila?" e para
    conferir a tabela antes de mexer nela com montar_venda. Marcar envio feito
    é pela tela (Admin › Vendas › Envios do material).
    """
    resumo = comando("ver_vendas")
    for item in resumo.get("planos", []):
        item.update(_links(item["plano"]))
    return resumo
