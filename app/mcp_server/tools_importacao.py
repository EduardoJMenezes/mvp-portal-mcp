"""Tools do importador de simulado: .docx e prints (docs/IMPORTADOR-SIMULADO.md).

O arquivo não passa pela conversa — a chamada de tool só carrega texto. Por
isso o fluxo começa num link de envio. Com .docx, o servidor lê e cria o
rascunho, e aqui o Claude revisa (`revisar_importacao`, com as figuras) e
completa o que as regras não fecharam (`completar_questao_importada`). Com
prints, o Claude os vê (`ver_prints`), transcreve as questões e aponta onde
está cada figura, que o servidor recorta do print original (`recortar_figura`).

Toda a parte que exige julgamento fica na conversa; o servidor não chama
nenhum modelo.
"""

from __future__ import annotations

import base64
import json
from typing import Annotated

from fastmcp.utilities.types import Image
from pydantic import Field

from app.mcp_server.api import comando
from app.mcp_server.server import mcp
from app import imagens
from app.config import get_settings
from app.mcp_server.tools import ESCREVE_RASCUNHO, SOMENTE_LEITURA


def _traduzindo(funcao, *args):
    """O erro de domínio do Pillow vira erro de tool.

    `app/imagens.py` levanta `RegraDeNegocio` porque o portal usa a mesma conta
    e precisa dela virar 400. Aqui, a borda é o MCP: a mensagem vai inteira
    para o modelo, que é quem vai se corrigir com ela.
    """
    from fastmcp.exceptions import ToolError

    from app.errors import ErroDominio

    try:
        return funcao(*args)
    except ErroDominio as e:
        raise ToolError(str(e)) from e


def _com_link(resposta: dict, passos: str) -> dict:
    """Monta o endereço da página de envio a partir do token que a API devolveu.

    A API guarda só o hash do token e não sabe em que domínio a página de envio
    é servida — quem serve é este processo. Por isso o link nasce aqui, e o
    token não fica gravado em lugar nenhum: ele aparece uma vez, no chat.
    """
    base = (get_settings().mcp_base_url or "").rstrip("/")
    return {
        "importacao_id": resposta["importacao_id"],
        "link": f"{base}/enviar/{resposta['token']}",
        "expira_em": resposta["expira_em"],
        "instrucao": f"Passe o link ao professor: {passos} com importacao={resposta['importacao_id']}.",
    }


@mcp.tool(name="importar_simulado_docx", annotations=ESCREVE_RASCUNHO)
def importar_simulado_docx(
    turmas: Annotated[list[str], Field(description="Turmas que fazem a prova, ex.: ['Extensivo 2026']")],
    titulo: Annotated[
        str | None, Field(description="Nome do simulado; vazio usa o título do documento")
    ] = None,
    abre_em: Annotated[
        str | None, Field(description="Abertura, horário de Brasília: '2026-10-10T14:00'")
    ] = None,
    fecha_em: Annotated[
        str | None, Field(description="Fechamento, horário de Brasília: '2026-10-10T18:00'")
    ] = None,
    duracao_minutos: Annotated[int | None, Field(ge=1, description="Tempo de prova")] = None,
    pasta_resolucao: Annotated[
        str | None,
        Field(description="Id da pasta do Vimeo com os vídeos de resolução, se o professor disser"),
    ] = None,
) -> dict:
    """Importa um simulado de um arquivo .docx (Word): gera o link para o professor enviar o arquivo.

    É o caminho quando o professor pede para importar ou subir um simulado
    ("importa o SIMULADO 03 para o Extensivo 2026") sem anexar nada: o simulado
    da equipe está num documento do Word — questões numeradas, alternativas a)
    a e), gabarito e resolução — e ainda não existe na plataforma nem no Vimeo.
    Questões em print vão por importar_prints.

    O arquivo não passa pelo chat: devolva o link ao professor (vale 30
    minutos, uso único). Ele abre, envia o .docx e avisa aqui. O servidor lê o
    documento — texto, fórmulas, tabelas, figuras e resoluções comentadas — e
    cria o simulado em RASCUNHO. Quando ele avisar, chame revisar_importacao.

    Agenda e pasta de resolução podem ficar para depois (editar_simulado).
    """
    return _com_link(
        comando(
            "importar_simulado_docx",
            turmas=turmas,
            titulo=titulo,
            abre_em=abre_em,
            fecha_em=fecha_em,
            duracao_minutos=duracao_minutos,
            pasta_resolucao=pasta_resolucao,
        ),
        "ele envia o .docx e avisa; depois chame revisar_importacao",
    )


@mcp.tool(name="revisar_importacao", annotations=SOMENTE_LEITURA)
def revisar_importacao(
    importacao: Annotated[int, Field(description="Id devolvido por importar_simulado_docx")],
    de: Annotated[int, Field(ge=1, description="Primeira questão a mostrar (ordem na prova)")] = 1,
    ate: Annotated[int | None, Field(ge=1, description="Última questão; vazio mostra até 10 depois de `de`")] = None,
) -> list:
    """Mostra o que o servidor leu do .docx — com as figuras — para revisar com o professor.

    Devolve as questões como estão no rascunho (enunciado, alternativas,
    gabarito, resolução comentada, avisos) e, em seguida, cada figura como
    imagem, identificada pelo número que aparece no texto (`figura:123`). Vá de
    10 em 10 questões num simulado grande.

    Na revisão:

    * confira se cada figura bate com a questão e está no lugar certo;
    * `incompletas` são questões que as regras não fecharam — monte-as com
      completar_questao_importada, apontando os blocos listados;
    * proponha assunto e sub-assunto de cada questão (listar_assuntos) e
      ajuste com editar_questao;
    * `pendencias_para_publicar` diz o que ainda barra a publicação.

    Mostre o preview ao professor e espere o ok antes de qualquer ajuste.
    """
    dados = comando("revisar_importacao", importacao=importacao, de=de, ate=ate)
    saida: list = [json.dumps(dados, ensure_ascii=False)]
    for questao in dados["questoes"]:
        for figura_id in questao["figuras"]:
            figura = comando("bytes_da_figura", figura=figura_id)
            saida.append(f"figura:{figura_id} — questão {questao['questao_id']}, "
                         f"{(figura['parte'] or '').lower()}")
            saida.append(Image(data=base64.b64decode(figura["conteudo_base64"]),
                               format=figura["tipo"].split("/")[-1]))
    return saida


@mcp.tool(name="completar_questao_importada", annotations=ESCREVE_RASCUNHO)
def completar_questao_importada(
    importacao: Annotated[int, Field(description="Id da importação")],
    numero: Annotated[int, Field(description="Número da questão no documento")],
    enunciado: Annotated[str, Field(description="Blocos do enunciado, ex.: '12-18'")],
    alternativas: Annotated[
        str | dict[str, str],
        Field(description="Cinco blocos, um por letra ('19-23'), ou uma faixa por letra ({'A': '19', ...})"),
    ],
    gabarito: Annotated[str, Field(description="Letra correta, A a E")],
    resolucao: Annotated[str | None, Field(description="Blocos da resolução, ex.: '25-30'")] = None,
) -> dict:
    """Monta, a partir dos blocos do documento, uma questão que as regras não fecharam.

    Os blocos vêm em `incompletas`, no revisar_importacao. Aponte as faixas —
    o texto e as figuras saem do documento, sem redigitar — e a questão entra
    no rascunho na posição do seu número.

    **Antes de chamar, mostre ao professor como a questão vai ficar e espere o
    ok dele.**
    """
    return comando(
        "completar_questao_importada",
        importacao=importacao,
        numero=numero,
        enunciado=enunciado,
        alternativas=alternativas,
        gabarito=gabarito,
        resolucao=resolucao,
    )


@mcp.tool(name="importar_prints", annotations=ESCREVE_RASCUNHO)
def importar_prints() -> dict:
    """Gera o link para o professor enviar prints de questões — de prova, PDF ou site.

    É o caminho quando as questões estão em imagem, sobretudo com figura
    (estrutura, gráfico, tabela desenhada): pelo link o servidor fica com o
    print original, e a figura sai recortada de dentro dele. Print colado
    direto no chat dá para transcrever, mas a figura fica pendente. Simulado
    que já está num .docx vai por importar_simulado_docx.

    Devolva o link ao professor (vale 30 minutos, uso único): ele cola os
    prints com Ctrl+V ou escolhe as imagens, envia e avisa aqui. Aí chame
    ver_prints.
    """
    return _com_link(comando("importar_prints"),
                     "ele envia os prints e avisa; depois chame ver_prints")


@mcp.tool(name="ver_prints", annotations=SOMENTE_LEITURA)
def ver_prints(
    importacao: Annotated[int, Field(description="Id devolvido por importar_prints")],
    de: Annotated[int, Field(ge=1, description="Primeiro print a mostrar")] = 1,
    ate: Annotated[int | None, Field(ge=1, description="Último print; vazio mostra 5 a partir de `de`")] = None,
) -> list:
    """Mostra os prints que o professor enviou pelo link, para transcrever as questões.

    Cada print volta como imagem, com largura e altura — print pequeno vem
    ampliado —, e é nessa escala, em pixels, que recortar_figura recebe o
    retângulo. Vá de 5 em 5.

    Para montar:

    * transcreva como em criar_simulado_rascunho — Markdown, índice em Unicode
      (CO₃²⁻), fórmula em LaTeX — e ponha `![](figura:pendente)` no lugar exato
      de cada figura; estrutura, gráfico e tabela desenhada não se descrevem
      em texto;
    * print quase nunca traz o gabarito: pergunte ao professor. Se ele pedir
      que você resolva, mostre as respostas como proposta e espere o ok;
    * crie as questões (criar_simulado_rascunho, ou editar_simulado numa prova
      que já existe) e chame recortar_figura para cada marca.
    """
    dados, vistas = _traduzindo(imagens.ver_prints, importacao, de, ate)
    saida: list = [json.dumps(dados, ensure_ascii=False)]
    for descricao, vista in zip(dados["prints"], vistas):
        saida.append(f"print {descricao['print']} — {descricao['largura']}×{descricao['altura']} px")
        saida.append(Image(data=vista, format="jpeg"))
    return saida


@mcp.tool(name="recortar_figura", annotations=ESCREVE_RASCUNHO)
def recortar_figura(
    importacao: Annotated[int, Field(description="Id da importação dos prints")],
    print: Annotated[int, Field(ge=1, description="Número do print, como em ver_prints")],
    questao: Annotated[int, Field(description="questao_id da questão que tem a marca da figura")],
    retangulo: Annotated[
        list[float],
        Field(min_length=4, max_length=4, description="[x0, y0, x1, y1] em pixels, na escala de ver_prints"),
    ],
    parte: Annotated[str, Field(description="ENUNCIADO, ALTERNATIVA ou RESOLUCAO")] = "ENUNCIADO",
    alternativa: Annotated[str | None, Field(description="Letra, quando a parte é ALTERNATIVA")] = None,
    substituir: Annotated[
        int | None, Field(description="figura_id de um recorte que saiu errado, para trocar")
    ] = None,
    estender: Annotated[
        bool, Field(description="false só quando o desenho encosta no texto e o recorte veio com letra junto")
    ] = True,
) -> list:
    """Recorta uma figura de dentro de um print e a põe na questão, no lugar da marca.

    O retângulo pode sair um pouco curto: o servidor estende cada borda até o
    desenho acabar, numa faixa em branco, e apara o branco em volta. Só não o
    deixe pegar o texto de cima, de baixo ou do lado. A figura entra na
    primeira marca `![](figura:pendente)` da parte; numa alternativa, diga a
    letra.

    O recorte volta como imagem, na escala em que você viu o print. Confira se
    o desenho está inteiro — anel, ramificações, átomos e cargas — e sem texto
    em volta. Se não, chame de novo com `substituir` = o figura_id devolvido,
    que troca o arquivo sem mexer no texto; se veio letra junto porque o desenho
    encosta no texto, use `estender=false` com o retângulo exato. Vale só para
    questão em rascunho: o professor vê tudo no preview antes de aprovar.
    """
    dados, previa = _traduzindo(
        imagens.recortar_figura,
        importacao, print, questao, retangulo, parte, alternativa, substituir, estender,
    )
    return [json.dumps(dados, ensure_ascii=False), Image(data=previa, format="png")]
