"""Tools que montam e mantêm o curso: módulo, sub-módulo, item e assunto.

Separadas de `tools.py` por peso, não por natureza — são as mesmas regras e os
mesmos services. O que as distingue é que **todas alteram direto**: não há
rascunho entre a decisão e o efeito.

A confirmação acontece no chat: antes de chamar qualquer uma delas, o modelo
mostra ao professor como vai ficar e espera o ok. A regra está na descrição de
cada tool e nas instruções do servidor. Já foi um formulário de confirmação
(elicitation), mas o app do Claude responde a esse formulário sozinho, sem
mostrá-lo a ninguém — a trava bloqueava tudo e não protegia nada.

Publicar é outra conversa: continua exigindo aprovação gravada no banco (ver
`services/publicacao.py`).

Remover nunca apaga: preenche `removido_em`, e a resposta diz que é reversível.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.mcp_server.api import comando
from app.mcp_server.server import mcp
from app.mcp_server.tools import SOMENTE_LEITURA

ALTERA = {"read_only_hint": False, "destructive_hint": False, "open_world_hint": False}
REMOVE = {"read_only_hint": False, "destructive_hint": True, "open_world_hint": False}


# --- leitura -----------------------------------------------------------------


@mcp.tool(name="listar_modulos", annotations=SOMENTE_LEITURA)
def listar_modulos(
    turma: Annotated[
        str | None, Field(description="Nome ou id da turma, ex.: 'Extensivo 2026'")
    ] = None,
) -> list[dict]:
    """Mostra o curso como cada turma o vê: módulos, sub-módulos e itens.

    O módulo ("K01 - Introdução à química orgânica") mora numa biblioteca e
    as turmas o recebem: `turmas` diz quais. Dentro dele, os sub-módulos
    ("Aulas", "Questões da apostila") e os vídeos, com o status de publicação;
    o item com `turmas` preenchido aparece só para elas (vazio: para toda turma
    do módulo). Um módulo que é de várias turmas aparece uma vez em cada.

    É daqui que saem os nomes que as outras tools pedem — e é o que mostrar
    como "antes" no preview de uma alteração.
    """
    return comando("listar_modulos", turma=turma)


@mcp.tool(name="listar_assuntos", annotations=SOMENTE_LEITURA)
def listar_assuntos() -> list[dict]:
    """Lista a taxonomia: assuntos e seus sub-assuntos.

    Assunto é a etiqueta do conteúdo ("Estequiometria" › "Pureza e
    rendimento"), e **não** leva o número do capítulo: K03 é Estequiometria em
    2026 e Tabela Periódica em 2025, então uma etiqueta com K03 no nome não
    serviria para as duas.

    É por esta etiqueta que a plataforma liga o erro do aluno no simulado aos
    vídeos que explicam aquilo.
    """
    return comando("listar_assuntos")


# --- estrutura do curso ------------------------------------------------------


@mcp.tool(name="criar_modulo", annotations=ALTERA)
def criar_modulo(
    turma: Annotated[
        str | None, Field(description="Turma que já recebe o módulo; vazio cria só na biblioteca")
    ],
    nome: Annotated[str, Field(description="Ex.: 'K01 - Introdução à química orgânica'")],
    submodulos: Annotated[
        list[str] | None,
        Field(description="Sub-módulos a criar junto, ex.: ['Aulas', 'Questões da apostila']"),
    ] = None,
    categoria: Annotated[str | None, Field(description="Categoria livre, a gaveta do menu (ex.: 'Extensivo'); vazio tira")] = None,
) -> dict:
    """Cria um módulo (capítulo) na turma, com os sub-módulos que ele terá.

    **Antes de chamar, mostre ao professor no chat como vai ficar e espere o
    ok dele.**

    O módulo mora numa biblioteca: com `turma`, já nasce atribuído a ela; as
    outras turmas se acrescentam com atribuir_turmas (Q1, Q2, Q4 e Q5 recebem
    o mesmo K01). Sem `submodulos`, nasce com 'Aulas' e 'Questões da apostila'.
    Módulo novo nasce vazio: nada aparece para o aluno até haver item
    publicado dentro.
    """
    return comando("criar_modulo", turma=turma, nome=nome, submodulos=submodulos, categoria=categoria)


@mcp.tool(name="criar_submodulo", annotations=ALTERA)
def criar_submodulo(
    turma: Annotated[str, Field(description="Nome ou id da turma")],
    modulo: Annotated[str, Field(description="Nome ou id do módulo")],
    nome: Annotated[str, Field(description="Ex.: 'Questões da apostila', 'Revisão'")],
) -> dict:
    """Acrescenta um sub-módulo a um módulo que já existe.

    **Antes de chamar, mostre ao professor no chat como vai ficar e espere o
    ok dele.**

    Cada sub-módulo guarda um tipo só de conteúdo — hoje, vídeo. É o que
    separa 'Aulas' (poucos vídeos longos) de 'Questões da apostila' (muitos e
    curtos) sem precisar de duas estruturas diferentes.
    """
    return comando("criar_submodulo", turma=turma, modulo=modulo, nome=nome)


@mcp.tool(name="editar_modulo", annotations=ALTERA)
def editar_modulo(
    turma: Annotated[str, Field(description="Nome ou id da turma")],
    modulo: Annotated[str, Field(description="Módulo a alterar")],
    novo_nome: Annotated[str | None, Field(description="Novo nome, se for renomear")] = None,
    nova_ordem: Annotated[int | None, Field(description="Posição na lista da turma")] = None,
    nova_categoria: Annotated[str | None, Field(description="Categoria livre, a gaveta do menu (ex.: 'Extensivo'); vazio tira")] = None,
) -> dict:
    """Renomeia um módulo, muda a posição dele na turma ou a categoria.

    A categoria é o que um botão do menu usa para mostrar só alguns capítulos
    (ex.: "Extensivo 2027" = CURSO › "Extensivo"). Ver listar_menu.

    **Antes de chamar, mostre ao professor no chat como vai ficar e espere o
    ok dele.** A alteração vale na hora, inclusive para os alunos. Quem mexeu
    fica registrado no próprio módulo.
    """
    return comando(
        "editar_modulo",
        turma=turma,
        modulo=modulo,
        novo_nome=novo_nome,
        nova_ordem=nova_ordem,
        nova_categoria=nova_categoria,
    )


@mcp.tool(name="editar_item", annotations=ALTERA)
def editar_item(
    turma: Annotated[str, Field(description="Nome ou id da turma")],
    modulo: Annotated[str, Field(description="Módulo onde o item está")],
    submodulo: Annotated[str, Field(description="Sub-módulo onde o item está")],
    item: Annotated[str, Field(description="Nome ou id do item, ex.: 'Q04'")],
    novo_nome: Annotated[str | None, Field(description="Novo nome do item")] = None,
    nova_ordem: Annotated[int | None, Field(description="Posição na lista")] = None,
    mover_para_submodulo: Annotated[
        str | None, Field(description="Sub-módulo de destino, para mover o item")
    ] = None,
) -> dict:
    """Renomeia, reordena ou move um item de lugar.

    **Antes de chamar, mostre ao professor no chat como vai ficar e espere o
    ok dele.** Item publicado muda na tela do aluno na hora.

    `nome` é a identidade editorial ("Q04", "Aula 1 — cadeias carbônicas") e
    `ordem` é a posição na tela — são coisas diferentes, e é por isso que dá
    para exibir a Q52 antes da Q04 sem renumerar nada.
    """
    return comando(
        "editar_item",
        turma=turma,
        modulo=modulo,
        submodulo=submodulo,
        item=item,
        novo_nome=novo_nome,
        nova_ordem=nova_ordem,
        mover_para_submodulo=mover_para_submodulo,
    )


@mcp.tool(name="remover_do_curso", annotations=REMOVE)
def remover_do_curso(
    turma: Annotated[str, Field(description="Nome ou id da turma")],
    modulo: Annotated[str, Field(description="Módulo alvo, ou onde está o alvo")],
    submodulo: Annotated[
        str | None, Field(description="Informe para remover o sub-módulo (ou o item dentro dele)")
    ] = None,
    item: Annotated[str | None, Field(description="Informe para remover só este item")] = None,
) -> dict:
    """Remove um item, um sub-módulo ou um módulo inteiro — o mais específico
    que você informar.

    **Antes de chamar, mostre ao professor no chat o que vai sair — use
    listar_modulos para dizer quantos itens publicados somem da tela — e
    espere o ok dele.**

    Remover um módulo tira-o de **todas** as turmas que o recebem. Para
    tirar de uma turma só, use atribuir_turmas sem ela.

    Nada é apagado de verdade. A remoção é lógica e reversível: o conteúdo
    sai da tela do aluno e continua no banco. Remover um módulo não cascateia
    — os sub-módulos e itens ficam intactos e voltam junto se ele for
    restaurado.
    """
    return comando("remover_do_curso", turma=turma, modulo=modulo, submodulo=submodulo, item=item)


# --- biblioteca e atribuição às turmas (decisão 0011) -------------------------


@mcp.tool(name="listar_biblioteca", annotations=SOMENTE_LEITURA)
def listar_biblioteca() -> list[dict]:
    """Lista todos os módulos da biblioteca, com as turmas que recebem cada um.

    Módulo com `turmas` vazia não aparece para ninguém: está só guardado. É o
    "antes" do preview de atribuir_turmas.
    """
    return comando("listar_biblioteca")


@mcp.tool(name="atribuir_turmas", annotations=ALTERA)
def atribuir_turmas(
    modulo: Annotated[str, Field(description="Módulo (nome ou id)")],
    turmas: Annotated[list[str], Field(description="A lista completa de turmas, ex.: ['Q1', 'Q2', 'Q4', 'Q5']")],
    turma: Annotated[
        str | None, Field(description="Uma turma que já tem o módulo, para achá-lo pelo nome")
    ] = None,
    submodulo: Annotated[str | None, Field(description="Sub-módulo da aula, para restringir uma aula")] = None,
    item: Annotated[str | None, Field(description="A aula a restringir, ex.: 'Aula 6'")] = None,
) -> dict:
    """Diz quais turmas recebem um módulo — ou, com `item`, deixa uma aula só para algumas turmas.

    **Antes de chamar, mostre ao professor no chat como vai ficar — as turmas
    de hoje (listar_biblioteca) e as novas — e espere o ok dele.** Vale na
    hora para os alunos.

    * Sem `item`: `turmas` é a lista completa de quem recebe o módulo. Turma
      que sai deixa de ver o módulo (menos as aulas restritas a ela).
    * Com `item` (e `submodulo`): a aula aparece só para `turmas`, mesmo que o
      módulo seja de outras também. Lista vazia devolve a aula a toda turma do
      módulo. Dar uma aula a uma turma que não tem o módulo faz o módulo
      aparecer para ela só com aquela aula.
    """
    return comando(
        "atribuir_turmas", modulo=modulo, turmas=turmas, turma=turma, submodulo=submodulo, item=item
    )


@mcp.tool(name="copiar_modulos", annotations=ALTERA)
def copiar_modulos(
    de: Annotated[str, Field(description="Turma de onde os módulos vêm")],
    para: Annotated[str, Field(description="Turma que passa a recebê-los")],
) -> dict:
    """A turma `para` passa a receber os mesmos módulos e aulas restritas da turma `de`.

    **Antes de chamar, mostre ao professor no chat o que a turma vai ganhar e
    espere o ok dele.** Acrescenta: o que a turma `para` já tinha continua.
    """
    return comando("copiar_modulos", de=de, para=para)


# --- taxonomia ---------------------------------------------------------------


@mcp.tool(name="cadastrar_assunto", annotations=ALTERA)
def cadastrar_assunto(
    nome: Annotated[str, Field(description="Ex.: 'Estequiometria' — sem o K03 na frente")],
    subassuntos: Annotated[
        list[str] | None, Field(description="Ex.: ['Pureza e rendimento', 'Reagente limitante']")
    ] = None,
) -> dict:
    """Cadastra um assunto e, se quiser, os sub-assuntos dele de uma vez.

    **Antes de chamar, mostre ao professor no chat como vai ficar e espere o
    ok dele** — a grafia é a que vai aparecer em toda classificação.

    O nome **não** leva numeração de capítulo. "K03" é a posição na apostila
    de uma turma, e as apostilas mudam de um ano para o outro — um assunto
    chamado "K03 - Estequiometria" precisaria ser recriado a cada turma, que é
    exatamente o que a etiqueta existe para evitar.
    """
    return comando("cadastrar_assunto", nome=nome, subassuntos=subassuntos)


@mcp.tool(name="classificar_videos", annotations=ALTERA)
def classificar_videos(
    turma: Annotated[str, Field(description="Nome ou id da turma")],
    modulo: Annotated[str, Field(description="Módulo onde estão os vídeos")],
    submodulo: Annotated[str, Field(description="Sub-módulo onde estão os vídeos")],
    assunto: Annotated[str, Field(description="Assunto já cadastrado")],
    subassunto: Annotated[str | None, Field(description="Sub-assunto, quando houver")] = None,
    itens: Annotated[
        str | None,
        Field(description="Quais itens, por nome ou faixa: 'Q01-Q03' ou 'Q04,Q07'. Vazio = todos"),
    ] = None,
) -> dict:
    """Etiqueta os vídeos de um sub-módulo com um assunto — em lote.

    **Antes de chamar, mostre ao professor no chat quais vídeos recebem qual
    etiqueta e espere o ok dele.** A etiqueta vale para todas as turmas onde
    esses vídeos aparecem.

    Aceita o mesmo jeito de falar da importação: "Q01 a Q03 são cadeias
    carbônicas, Q04 a Q08 nomenclatura". Vazio, classifica o sub-módulo
    inteiro de uma vez.

    A etiqueta vai no **vídeo**, não no item: o mesmo vídeo em 2026 e 2027
    ensina a mesma coisa, então classificar uma vez basta. É por ela que a
    análise do aluno encontra o que explica o erro dele.
    """
    return comando(
        "classificar_videos",
        turma=turma,
        modulo=modulo,
        submodulo=submodulo,
        assunto=assunto,
        subassunto=subassunto,
        itens=itens,
    )
