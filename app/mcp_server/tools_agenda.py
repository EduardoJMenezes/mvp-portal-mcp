"""A agenda pelo chat: ler, criar (inclusive a partir da foto do calendário), editar e remover.

Decisão 0012 do cofre: a agenda é uma lista de eventos por turma. O evento pode
ligar a uma aula, um módulo, uma aula ao vivo ou um simulado — o clique do aluno
leva até lá —, e a aula ou o módulo ligado fica escondido para aquelas turmas até
a hora do evento. Criar, editar e remover mudam na hora: preview e ok no chat.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from app.mcp_server.api import comando
from app.mcp_server.server import mcp
from app.mcp_server.tools import SOMENTE_LEITURA
from app.mcp_server.tools_estrutura import ALTERA, REMOVE


class Evento(BaseModel):
    titulo: str = Field(description="Ex.: 'K03 - Estequiometria', 'SIM 1', 'Carnaval'")
    inicio: str = Field(description="Início no horário de Brasília: '2027-02-01T19:00'")
    turmas: list[str] = Field(description="As turmas para as quais o evento vale, ex.: ['Q1']")
    fim: str | None = Field(default=None, description="Fim, para períodos (Recesso, Carnaval)")
    categoria: str | None = Field(default=None, description="Categoria livre: 'Aula', 'Simulado', 'Feriado', 'Revisão'…")
    descricao: str | None = None
    modulo: str | None = Field(default=None, description="Liga ao módulo (ex.: 'K03'); com aula, é o módulo dela")
    submodulo: str | None = Field(default=None, description="Sub-módulo da aula ligada, ex.: 'Aulas'")
    aula: str | None = Field(default=None, description="Liga a uma aula do módulo, ex.: 'Aula 2'")
    aula_ao_vivo: str | None = Field(default=None, description="Liga a uma aula ao vivo (id, de listar_aulas)")
    simulado: str | None = Field(default=None, description="Liga a um simulado (título ou id)")


@mcp.tool(name="listar_agenda", annotations=SOMENTE_LEITURA)
def listar_agenda(
    turma: Annotated[str | None, Field(description="Só os eventos desta turma")] = None,
) -> list[dict]:
    """Lista os eventos da agenda, em ordem de data, com as turmas e o conteúdo ligado (`destino`).

    Horários com fuso — fale com o professor no horário de Brasília. É o
    "antes" do preview de criar_eventos, editar_evento e remover_evento.
    """
    return comando("listar_agenda", turma=turma)


@mcp.tool(name="criar_eventos", annotations=ALTERA)
def criar_eventos(eventos: Annotated[list[Evento], Field(description="Os eventos a criar")]) -> list[dict]:
    """Cria eventos na agenda, de uma vez (todos ou nenhum).

    **Antes de chamar, mostre ao professor no chat a lista que vai criar — dia,
    hora, turmas, título e o que cada um abre — e espere o ok dele.** Vale na
    hora: o aluno vê o evento no dia, e a aula ou o módulo ligado fica escondido
    para aquelas turmas até a hora do evento. Conteúdo sem evento continua
    aparecendo normalmente.

    Foto do calendário: leia os eventos (na segunda, o módulo da semana — "K03",
    "L01"; nos sábados, "SIM 1"; pausas como Carnaval e Recesso) e **pergunte
    sempre as turmas** e o dia e a hora de cada uma ("Q1 segunda 8h, Q2 terça
    19h"): o mesmo módulo vira um evento por turma, no dia dela. "K01/02" são
    dois módulos na mesma semana. Ligue o módulo pelo nome ("K03" acha "K03 -
    Estequiometria"); simulado e evento sem conteúdo podem ficar sem ligação.
    """
    return comando("criar_eventos", eventos=[e.model_dump(exclude_none=True) for e in eventos])


@mcp.tool(name="editar_evento", annotations=ALTERA)
def editar_evento(
    evento: Annotated[str, Field(description="Id do evento (de listar_agenda)")],
    titulo: str | None = None,
    inicio: Annotated[str | None, Field(description="Novo início, Brasília; muda o fim junto")] = None,
    fim: Annotated[str | None, Field(description="Novo fim (vai junto com o início)")] = None,
    turmas: Annotated[list[str] | None, Field(description="A lista completa de turmas")] = None,
    categoria: str | None = None,
    descricao: str | None = None,
    modulo: str | None = None,
    submodulo: str | None = None,
    aula: str | None = None,
    aula_ao_vivo: str | None = None,
    simulado: str | None = None,
    sem_ligacao: Annotated[bool | None, Field(description="true tira a ligação com o conteúdo")] = None,
) -> dict:
    """Muda um evento: horário (a exceção de uma semana, ex.: da segunda para a quinta), turmas, título ou ligação.

    **Antes de chamar, mostre ao professor no chat o antes e o depois e espere o
    ok dele.** Mudar o horário muda também quando o conteúdo ligado sai para
    aquelas turmas.
    """
    return comando(
        "editar_evento", evento=evento, titulo=titulo, inicio=inicio, fim=fim, turmas=turmas,
        categoria=categoria, descricao=descricao, modulo=modulo, submodulo=submodulo, aula=aula,
        aula_ao_vivo=aula_ao_vivo, simulado=simulado, sem_ligacao=sem_ligacao,
    )


@mcp.tool(name="remover_evento", annotations=REMOVE)
def remover_evento(evento: Annotated[str, Field(description="Id do evento (de listar_agenda)")]) -> dict:
    """Tira um evento da agenda.

    **Antes de chamar, mostre ao professor no chat qual evento sai e espere o ok
    dele.** Se o evento liberava uma aula ou módulo, o conteúdo volta a
    aparecer normalmente para aquelas turmas. Nada é apagado de verdade.
    """
    return comando("remover_evento", evento=evento)
