"""Aulas ao vivo pelo chat: agendar, publicar e consultar.

Com o ok do professor no chat, `agendar_aula(publicar=True)` já cria a sala no
Zoom (decisão 0008 do cofre). A conta do Zoom é dividida com outra plataforma:
a API recusa publicar pelo chat nos horários dela (terça 17h–19h, quarta
19h–21h).
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
    encerrou a sala). `assistir` aponta a gravação no curso.
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
    publicar: Annotated[
        bool,
        Field(description="Cria a sala no Zoom e mostra a aula à turma. Só depois do ok do professor no chat."),
    ] = False,
) -> dict:
    """Agenda uma aula ao vivo e, com `publicar`, já abre a sala no Zoom.

    Antes de chamar, mostre ao professor título, dia e hora (Brasília),
    duração, turmas e o capítulo (módulo › sub-módulo), e pergunte se pode
    publicar. Com o ok dele no chat, chame uma vez só com `publicar=True`: a
    sala nasce no Zoom e a turma já vê a aula no capítulo. Sem `publicar`, a
    aula fica em RASCUNHO, sem sala, até alguém publicar em Admin › Aulas ao
    vivo — não chame de novo para publicar, isso criaria outra aula.

    Terça das 17h às 19h e quarta das 19h às 21h (Brasília) a conta do Zoom é
    da outra plataforma: publicar nesses horários é recusado. Repasse ao
    professor e proponha outro horário.

    Com `modulo`, a gravação, quando o Zoom avisar que ficou pronta, sobe ao
    Vimeo e entra publicada naquele sub-módulo.
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
        publicar=publicar,
    )
