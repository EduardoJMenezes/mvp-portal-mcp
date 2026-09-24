"""Aulas ao vivo pelo chat: agendar e consultar.

Agendar cria a aula em rascunho, sem sala no Zoom. A sala nasce quando o
professor publica no portal — por aqui não há como publicar. A conta do Zoom é
dividida com outra plataforma, e a agenda dela não é lugar para proposta.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.mcp_server.api import comando
from app.mcp_server.server import mcp
from app.mcp_server.tools import SOMENTE_LEITURA


@mcp.tool(name="listar_aulas", annotations=SOMENTE_LEITURA)
def listar_aulas() -> list[dict]:
    """Lista as aulas ao vivo: horário, turmas, se já tem sala no Zoom e se grava.

    `estado` é RASCUNHO, AGENDADA (publicada, a porta ainda não abriu),
    AGUARDANDO (a porta abriu 15 minutos antes, o professor ainda não iniciou),
    ABERTA (a sala está no ar) ou ENCERRADA (o horário passou, ou o professor
    encerrou a sala). `assistir` aponta a gravação no curso depois de aprovada.
    Horários em UTC — converta para
    Brasília ao falar com o professor. `gravacao` diz em que pé está a gravação
    (vazio, "enviando" ou o id do vídeo no Vimeo), e `presentes`, quem entrou
    pelo link do portal.
    """
    return comando("listar_aulas")


@mcp.tool(
    name="agendar_aula",
    annotations={"read_only_hint": False, "destructive_hint": False, "open_world_hint": False},
)
def agendar_aula(
    titulo: Annotated[str, Field(description="Ex.: 'Revisão de estequiometria'")],
    inicio: Annotated[str, Field(description="Início no horário de Brasília: '2026-10-10T19:00'")],
    turmas: Annotated[
        list[str] | None, Field(description="Turmas que entram, ex.: ['Extensivo 2026']")
    ] = None,
    minutos: Annotated[int, Field(ge=5, le=480, description="Duração")] = 60,
    descricao: Annotated[str | None, Field(description="Aparece para o aluno junto do horário")] = None,
    alunos: Annotated[
        list[str] | None, Field(description="E-mails de alunos avulsos, que entram mesmo fora da turma")
    ] = None,
    gravar: Annotated[bool, Field(description="Grava na nuvem do Zoom para virar aula gravada")] = True,
    modulo: Annotated[
        str | None,
        Field(description="Módulo da primeira turma onde a gravação entra, ex.: 'K03 - Estequiometria'"),
    ] = None,
    submodulo: Annotated[
        str | None, Field(description="Sub-módulo do destino; vazio é 'Aulas'")
    ] = None,
) -> dict:
    """Agenda uma aula ao vivo, em RASCUNHO e sem sala no Zoom.

    Mostre ao professor título, dia e hora (Brasília), duração, turmas e o
    destino da gravação antes de chamar. A aula não aparece para aluno nenhum e
    não ocupa a agenda do Zoom até o professor publicá-la em Admin › Aulas ao
    vivo — repasse isso a ele. Não há tool para publicar: é de propósito.

    Com `modulo`, a gravação, quando o Zoom avisar que ficou pronta, sobe ao
    Vimeo e entra naquele sub-módulo como rascunho, para o professor aprovar.
    Sem `modulo`, ela só sobe ao Vimeo.
    """
    return comando(
        "agendar_aula",
        titulo=titulo,
        inicio=inicio,
        turmas=turmas or [],
        minutos=minutos,
        descricao=descricao,
        alunos=alunos or [],
        gravar=gravar,
        modulo=modulo,
        submodulo=submodulo,
    )
