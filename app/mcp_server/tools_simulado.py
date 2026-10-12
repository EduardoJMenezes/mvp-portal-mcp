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
    comentarios: Annotated[
        dict[str, str] | None,
        Field(
            description=(
                "Comentário por alternativa, só as letras que mudam: por que o aluno marca "
                "aquela e onde está o erro. '' tira o comentário. Ex.: {'B': '...'}"
            )
        ),
    ] = None,
) -> dict:
    """Corrige uma questão: texto, alternativas, gabarito, classificação, resolução ou comentários.

    **Antes de chamar, mostre ao professor no chat como vai ficar — use
    detalhar_questao para o antes — e espere o ok dele.** Vale na hora,
    inclusive nos simulados publicados que ainda não abriram.

    Questão publicada se corrige mesmo com prova aberta ou encerrada, e o
    aluno não é avisado. Quem está fazendo a prova recebe a versão nova ao
    trocar de questão. Se o gabarito mudar, o acerto de quem já respondeu é
    refeito, no simulado e na aula — diga isso ao professor antes de aplicar,
    porque nota e posição mudam. Alternativa com texto vazio é alternativa
    removida (ficam pelo menos duas, e o gabarito entre elas): as outras não
    mudam de letra, e quem tinha marcado a removida fica sem resposta nela.
    Cada correção fica no histórico da questão, que detalhar_questao mostra.

    A figura não passa por aqui: o arquivo não cabe numa chamada de tool. Ponha
    `![](figura:pendente)` onde ela vai; ela entra por recortar_figura, se a
    questão veio de print pelo link, ou o professor anexa pela plataforma.
    """
    mudancas = (enunciado, alternativas, gabarito, dificuldade, imagem_pendente, assunto,
                subassunto, vimeo_id, resolucao_comentada, comentarios)
    if all(v is None for v in mudancas):
        raise ToolError("Diga o que mudar na questão.")
    return await comando_async(
        "editar_questao",
        questao=questao, enunciado=enunciado, alternativas=alternativas, gabarito=gabarito,
        dificuldade=dificuldade, imagem_pendente=imagem_pendente, assunto=assunto,
        subassunto=subassunto, resolucao=await _resolucao_pedida(vimeo_id),
        resolucao_comentada=resolucao_comentada, comentarios=comentarios,
    )


@mcp.tool(name="listar_questoes_sem_assunto", annotations=SOMENTE_LEITURA)
def listar_questoes_sem_assunto(
    limite: Annotated[int, Field(ge=1, le=100, description="Quantas questões por vez")] = 20,
    deslocamento: Annotated[int, Field(ge=0, description="Para ler a página seguinte: quantas já foram lidas")] = 0,
) -> dict:
    """As questões do acervo que ainda não têm assunto, com a taxonomia de hoje junto.

    É o começo de "quero classificar as questões que estão sem assunto". Quem
    importa um .docx costuma não saber o assunto de cada questão; o professor
    vem depois e classifica todas de uma vez, com você.

    Cada questão vem enxuta — enunciado, alternativas, gabarito e o começo da
    resolução, sem a figura — e com `origem`, o envio de onde ela veio ("20
    questões de SIMULADO 02.docx"). `assuntos` é a lista de assuntos e
    sub-assuntos que já existem; `total` é quantas estão sem assunto e `restam`
    as que ficaram para a próxima página.

    O que fazer com isto:
      1. leia as questões e proponha, para cada uma, o assunto e o sub-assunto,
         preferindo os que já existem;
      2. mostre ao professor uma tabela (número, começo do enunciado, assunto ›
         sub-assunto) e, à parte, os assuntos e sub-assuntos NOVOS que você
         sugere criar. Se ele tiver uma lista de tópicos do simulado ou da
         apostila, peça: ela vale mais que o seu palpite;
      3. com o ok dele, aplique tudo numa chamada só de classificar_questoes.
    Não classifique uma por uma com editar_questao.
    """
    return comando("listar_questoes_sem_assunto", limite=limite, deslocamento=deslocamento)


@mcp.tool(name="classificar_questoes", annotations=ALTERA)
def classificar_questoes(
    classificacoes: Annotated[
        list[dict],
        Field(
            min_length=1,
            max_length=200,
            description=(
                "Uma linha por questão: {'questao': 81, 'assunto': 'Ligações Químicas', "
                "'subassunto': 'Geometria molecular'}. O sub-assunto é opcional. A mesma questão não se repete"
            ),
        ),
    ],
    criar_novos: Annotated[
        bool,
        Field(description="true só depois de o professor aprovar os assuntos e sub-assuntos novos que você mostrou"),
    ] = False,
) -> dict:
    """Classifica várias questões de uma vez: cada uma fica com o assunto e o sub-assunto da linha dela.

    **Antes de chamar, mostre ao professor no chat a tabela inteira — qual
    questão recebe qual assunto › sub-assunto — e espere o ok dele.** Vale na
    hora e troca a classificação que a questão tinha. Ou valem todas as linhas,
    ou nenhuma.

    O nome do assunto e do sub-assunto tem de ser o de um que já existe,
    escrito por inteiro (listar_questoes_sem_assunto e listar_assuntos mostram
    quais). Se algum não existir, nada é classificado e o erro diz quais
    faltam: ou era engano de nome, e você corrige, ou é assunto novo — então
    mostre ao professor o que vai ser criado e, com o ok dele, chame de novo
    com `criar_novos=true`, que cria o que falta e classifica.

    Assunto é a etiqueta do conteúdo e **não** leva número de capítulo ("K03",
    "L02"): a apostila muda de um ano para o outro. Prefira poucos assuntos,
    com o detalhe no sub-assunto — é por eles que o aluno vê o desempenho dele
    e que a plataforma indica o que revisar.

    A resposta diz quantas foram classificadas, o que foi criado e quantas
    questões ainda `restam_sem_assunto`.
    """
    return comando("classificar_questoes", classificacoes=classificacoes, criar_novos=criar_novos)


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
    categoria: Annotated[
        str | None,
        Field(description="Categoria livre, a gaveta do menu (ex.: 'Rodmelo', 'Nacional'); vazio tira"),
    ] = None,
) -> dict:
    """Ajusta agenda, turmas, tempo de prova, título, categoria ou as questões de um simulado.

    **Antes de chamar, mostre ao professor no chat como vai ficar — use
    detalhar_simulado para o antes — e espere o ok dele.** Vale na hora.

    O que muda depende de onde o simulado está:

    * rascunho ou publicado sem ter aberto: tudo — e o publicado precisa
      continuar pronto para ir ao ar;
    * aberto: só título e fechamento, e o fechamento só para mais tarde;
    * encerrado: só o título.

    A categoria muda em qualquer situação: é o que o botão do menu usa para
    separar, por exemplo, "Simulados Rodmelo" de "Simulados nacionais".

    Datas no horário de Brasília.
    """
    return await comando_async(
        "editar_simulado",
        simulado=simulado, titulo=titulo, abre_em=abre_em, fecha_em=fecha_em,
        duracao_minutos=duracao_minutos, turmas=turmas,
        questoes=await _questoes_com_resolucao(questoes),
        categoria=categoria,
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
