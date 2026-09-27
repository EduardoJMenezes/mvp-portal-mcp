"""O menu do aluno pelo chat: ler, montar e copiar de uma turma para outra.

Decisão 0009 do cofre: cada feature funciona sozinha e tem categoria livre em
cada item; o professor monta o menu de cada turma com botões "feature +
categoria". Definir e copiar mudam o menu na hora, como as tools de
`tools_estrutura.py`: a confirmação é o preview no chat.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.mcp_server.api import comando
from app.mcp_server.server import mcp
from app.mcp_server.tools import SOMENTE_LEITURA
from app.mcp_server.tools_estrutura import ALTERA


class Botao(BaseModel):
    rotulo: str = Field(description="O que o aluno lê no botão, ex.: 'Simulados Rodmelo' (até 40 letras)")
    funcionalidade: Literal["CURSO", "AULAS", "SIMULADOS", "MATERIAIS"] = Field(
        description="Para onde leva: CURSO (aulas gravadas), AULAS (aulas ao vivo), SIMULADOS ou MATERIAIS"
    )
    categoria: str | None = Field(
        default=None,
        description="Recorte da feature, ex.: 'Rodmelo', 'Monitoria'. Vazio mostra a feature inteira.",
    )


@mcp.tool(name="listar_menu", annotations=SOMENTE_LEITURA)
def listar_menu(turma: Annotated[str, Field(description="Nome ou id da turma")]) -> dict:
    """Mostra o menu que os alunos da turma veem, botão a botão, na ordem.

    Cada botão é uma feature (CURSO, AULAS, SIMULADOS, MATERIAIS) recortada por
    uma categoria: "Simulados Rodmelo" é SIMULADOS com categoria "Rodmelo".
    `padrao: true` quer dizer que a turma ainda não montou o dela e vê o menu
    de sempre. Início e Desempenho são fixos e não aparecem aqui.

    É daqui que sai o "antes" do preview de definir_menu.
    """
    return comando("listar_menu", turma=turma)


@mcp.tool(name="definir_menu", annotations=ALTERA)
def definir_menu(
    turma: Annotated[str, Field(description="Nome ou id da turma")],
    botoes: Annotated[
        list[Botao],
        Field(description="O menu inteiro, na ordem da tela. Lista vazia volta ao menu de sempre."),
    ],
) -> dict:
    """Troca o menu inteiro dos alunos de uma turma (até 12 botões).

    **Antes de chamar, mostre ao professor no chat como vai ficar — o menu de
    hoje (listar_menu) e o novo, botão a botão — e espere o ok dele.** Vale na
    hora para todos os alunos da turma.

    O botão só mostra o que tem aquela categoria: confira que os capítulos,
    aulas ao vivo, simulados ou materiais já estão com ela, senão o botão abre
    vazio. A categoria de cada item muda em editar_modulo, agendar_aula e
    editar_simulado (a de material, no portal).
    """
    return comando("definir_menu", turma=turma, botoes=[b.model_dump() for b in botoes])


@mcp.tool(name="copiar_menu", annotations=ALTERA)
def copiar_menu(
    de: Annotated[str, Field(description="Turma de onde o menu vem")],
    para: Annotated[str, Field(description="Turma que recebe o menu")],
) -> dict:
    """Copia o menu de uma turma para outra, substituindo o que ela tinha.

    **Antes de chamar, mostre ao professor no chat como vai ficar — o menu das
    duas turmas hoje — e espere o ok dele.** Vale na hora para os alunos da
    turma que recebe.
    """
    return comando("copiar_menu", de=de, para=para)
