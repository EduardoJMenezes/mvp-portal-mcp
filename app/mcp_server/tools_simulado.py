"""Tools que mantêm questões e simulados depois de propostos.

A mesma pegada de `tools_estrutura.py`: alteram direto, e a confirmação é o
preview no chat. A trava que não depende do modelo mora nos services — depois
que a prova abre, questão e gabarito não mudam, e o fechamento só é estendido.

Publicar continua exigindo aprovação gravada no rascunho (`publicar_rascunho`).
"""

from __future__ import annotations

from typing import Annotated

from fastmcp.exceptions import ToolError
from pydantic import Field

from app.mcp_server.auth import identidade_da_sessao
from app.mcp_server.api import comando, comando_async
from app.mcp_server.server import mcp
from app.mcp_server.tools import (
    SOMENTE_LEITURA,
    _questoes_com_resolucao,
    _resolucao_do_vimeo,
)
from app.mcp_server.tools_estrutura import ALTERA, REMOVE

# --- leitura -----------------------------------------------------------------


async def _resolucao_pedida(vimeo_id: str | None) -> dict | None:
    """O vídeo da resolução como a API o espera — ou o pedido explícito de tirá-lo.

    `vimeo_id` vazio quer dizer "tire a resolução", e isso é diferente de "não
    mexa nela": o primeiro precisa chegar do outro lado, o segundo não.
    """
    if vimeo_id is None:
        return None
    return await _resolucao_do_vimeo(vimeo_id) or {"vimeo_id": ""}


@mcp.tool(name="detalhar_questao", annotations=SOMENTE_LEITURA)
def detalhar_questao(
    questao: Annotated[int, Field(description="Id da questão (buscar_questoes, detalhar_simulado)")],
) -> dict:
    """A questão inteira e os simulados em que ela está.

    Enunciado, alternativas, gabarito, classificação, vídeo de resolução,
    imagem — é o "antes" do preview de editar_questao.
    """
    return comando("detalhar_questao", questao=questao)


@mcp.tool(name="detalhar_simulado", annotations=SOMENTE_LEITURA)
def detalhar_simulado(
    simulado: Annotated[str, Field(description="Título ou id do simulado")],
) -> dict:
    """O simulado como o professor vê: agenda, turmas e as questões com gabarito.

    Traz `pendencias_para_publicar` enquanto ele é rascunho. É o "antes" do
    preview de editar_simulado.
    """
    return comando("detalhar_simulado", simulado=simulado)


@mcp.tool(name="buscar_ranking_simulado", annotations=SOMENTE_LEITURA)
def buscar_ranking_simulado(
    simulado: Annotated[str, Field(description="Título ou id do simulado")],
) -> dict:
    """O ranking completo do simulado — um só, somando todas as turmas dele.

    Empate divide a posição (1º, 2º, 2º, 4º) e quem não começou a prova fica
    fora. Com o simulado aberto sai `parcial: true`: a posição ainda muda.

    O ranking é do professor. O aluno só vê a própria posição ("12º de 48"),
    no resultado dele — não repasse a lista a um aluno.
    """
    return comando("buscar_ranking_simulado", simulado=simulado)


# --- questão -----------------------------------------------------------------


@mcp.tool(name="editar_questao", annotations=ALTERA)
async def editar_questao(
    questao: Annotated[int, Field(description="Id da questão")],
    enunciado: Annotated[str | None, Field(description="Novo enunciado (Markdown e LaTeX)")] = None,
    alternativas: Annotated[
        dict[str, str] | None, Field(description="Só as letras que mudam, ex.: {'C': '...'}")
    ] = None,
    gabarito: Annotated[str | None, Field(description="Nova letra correta")] = None,
    dificuldade: Annotated[str | None, Field(description="FACIL, MEDIA ou DIFICIL")] = None,
    imagem_pendente: Annotated[
        bool | None, Field(description="true se falta anexar figura; anexar tira sozinho")
    ] = None,
    assunto: Annotated[
        str | None, Field(description="Troca a classificação inteira; '' tira a classificação")
    ] = None,
    subassunto: Annotated[str | None, Field(description="Vai junto com o assunto")] = None,
    vimeo_id: Annotated[
        str | None, Field(description="Vídeo da resolução no Vimeo; '' tira a resolução")
    ] = None,
    resolucao_comentada: Annotated[
        str | None, Field(description="Resolução escrita (Markdown e LaTeX); '' tira")
    ] = None,
) -> dict:
    """Corrige uma questão: texto, alternativas, gabarito, classificação ou resolução.

    **Antes de chamar, mostre ao professor no chat como vai ficar — use
    detalhar_questao para o antes — e espere o ok dele.** Vale na hora,
    inclusive nos simulados publicados que ainda não abriram.

    Depois que abre uma prova com esta questão, enunciado, alternativas,
    gabarito e figuras travam: a tool recusa e diz em qual simulado.
    Classificação, dificuldade e as resoluções continuam editáveis.

    A figura não passa por aqui: o arquivo não cabe numa chamada de tool. Ponha
    `![](figura:pendente)` onde ela vai; ela entra por recortar_figura, se a
    questão veio de print pelo link, ou o professor anexa pela plataforma.
    """
    mudancas = (enunciado, alternativas, gabarito, dificuldade, imagem_pendente, assunto,
                subassunto, vimeo_id, resolucao_comentada)
    if all(v is None for v in mudancas):
        raise ToolError("Diga o que mudar na questão.")
    return await comando_async(
        "editar_questao",
        questao=questao, enunciado=enunciado, alternativas=alternativas, gabarito=gabarito,
        dificuldade=dificuldade, imagem_pendente=imagem_pendente, assunto=assunto,
        subassunto=subassunto, resolucao=await _resolucao_pedida(vimeo_id),
        resolucao_comentada=resolucao_comentada,
    )


@mcp.tool(name="remover_questao", annotations=REMOVE)
def remover_questao(questao: Annotated[int, Field(description="Id da questão")]) -> dict:
    """Tira uma questão do acervo.

    **Antes de chamar, mostre ao professor no chat qual questão sai e espere o
    ok dele.**

    A remoção é lógica e reversível. Questão em simulado que ainda não
    terminou não sai — tire-a da prova antes, com editar_simulado. As provas
    que já aconteceram continuam com ela.
    """
    return comando("remover_questao", questao=questao)


# --- simulado ----------------------------------------------------------------


@mcp.tool(name="editar_simulado", annotations=ALTERA)
async def editar_simulado(
    simulado: Annotated[str, Field(description="Título ou id do simulado")],
    titulo: Annotated[str | None, Field(description="Novo título")] = None,
    abre_em: Annotated[
        str | None, Field(description="Abertura, horário de Brasília: '2026-10-10T14:00'")
    ] = None,
    fecha_em: Annotated[
        str | None, Field(description="Fechamento, horário de Brasília: '2026-10-10T18:00'")
    ] = None,
    duracao_minutos: Annotated[int | None, Field(ge=1, description="Tempo de prova")] = None,
    turmas: Annotated[list[str] | None, Field(description="A lista completa de turmas")] = None,
    questoes: Annotated[
        list[int | dict] | None,
        Field(
            description=(
                "A lista completa, na ordem: ids das questões que ficam ou entram e, "
                "enquanto o simulado é rascunho, questões novas inteiras "
                "(mesmo formato de criar_simulado_rascunho)."
            ),
        ),
    ] = None,
) -> dict:
    """Ajusta agenda, turmas, tempo de prova, título ou as questões de um simulado.

    **Antes de chamar, mostre ao professor no chat como vai ficar — use
    detalhar_simulado para o antes — e espere o ok dele.** Vale na hora.

    O que muda depende de onde o simulado está:

    * rascunho ou publicado sem ter aberto: tudo — e o publicado precisa
      continuar pronto para ir ao ar;
    * aberto: só título e fechamento, e o fechamento só para mais tarde;
    * encerrado: só o título.

    Datas no horário de Brasília.
    """
    return await comando_async(
        "editar_simulado",
        simulado=simulado, titulo=titulo, abre_em=abre_em, fecha_em=fecha_em,
        duracao_minutos=duracao_minutos, turmas=turmas,
        questoes=await _questoes_com_resolucao(questoes),
    )


@mcp.tool(name="remover_simulado", annotations=REMOVE)
def remover_simulado(
    simulado: Annotated[str, Field(description="Título ou id do simulado")],
) -> dict:
    """Remove um simulado.

    **Antes de chamar, mostre ao professor no chat qual simulado sai — e, se
    já publicado, para quais turmas — e espere o ok dele.**

    A remoção é lógica e reversível. Aberto, não remove: há aluno fazendo a
    prova. Em rascunho, as questões novas que nasceram com ele saem junto.
    """
    return comando("remover_simulado", simulado=simulado)
