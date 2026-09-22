"""A página de envio do .docx ou dos prints: o link é a credencial.

Quem abre o link não precisa estar logado — ele é de uso único, tem prazo e
está preso a quem o pediu no chat. Por isso estas rotas não têm operador para
mandar à API: elas batem em `/interno`, onde o token do link é conferido a
cada chamada e a identidade gravada é a do dono dele, no canal DOCX.

O que acontece aqui é só ler o formato: abrir o .docx, converter o EMF que o
LibreOffice der conta, conferir que cada print é imagem de verdade. Gravar é
do outro lado.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool

from app import leitor_docx
from app.errors import RegraDeNegocio
from app.integracoes.vimeo import importacao as vimeo
from app.mcp_server.api import interno_ou_erro

router = APIRouter(prefix="/api/importacoes", tags=["importacao"])

LIMITE_DO_ARQUIVO = 25 * 1024 * 1024
LIMITE_DO_PRINT = 5 * 1024 * 1024
LIMITE_DOS_PRINTS = 50
# PNG, JPEG, WEBP e GIF — os quatro que o navegador cola e o modelo lê.
ASSINATURAS = {
    b"\x89PNG": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
}


def _tipo_da_imagem(conteudo: bytes) -> str | None:
    """Pelos bytes, não pela extensão: quem envia escolhe o nome, não o conteúdo."""
    for assinatura, tipo in ASSINATURAS.items():
        if conteudo.startswith(assinatura):
            return tipo
    if conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("/{token}")
async def situacao(token: str) -> dict:
    return await run_in_threadpool(interno_ou_erro, "situacao_do_link", token=token)


@router.post("/{token}/arquivo")
async def enviar_arquivo(
    token: str,
    arquivo: UploadFile = File(description="O .docx do simulado"),
) -> dict:
    conteudo = await arquivo.read(LIMITE_DO_ARQUIVO + 1)
    if not (arquivo.filename or "").lower().endswith(".docx"):
        raise RegraDeNegocio("Envie o arquivo .docx do simulado.")
    if len(conteudo) > LIMITE_DO_ARQUIVO:
        raise RegraDeNegocio(f"O arquivo passa de {LIMITE_DO_ARQUIVO // 1024 // 1024} MB.")

    # A pasta de resoluções, quando o professor pediu uma: os vídeos entram
    # casados por número, e quem sabe ler o Vimeo é este lado.
    pasta = (await run_in_threadpool(
        interno_ou_erro, "situacao_do_link", token=token)).get("pasta_resolucao")
    resolucoes = (
        vimeo.resolucoes_por_numero(await vimeo.ler_plano(pasta)) if pasta else None
    )

    lido = await run_in_threadpool(_ler_docx, arquivo.filename, conteudo)
    lido["resolucoes"] = resolucoes
    return await run_in_threadpool(interno_ou_erro, "registrar_docx", token=token, lido=lido)


def _ler_docx(nome: str | None, conteudo: bytes) -> dict:
    """O documento no formato que `/interno/registrar_docx` recebe.

    As figuras vão pela chave que o parser deu (`f1`, `f2`…), não por id: ele
    leu um arquivo, não o banco. Trocar chave por id é do outro lado, junto com
    o resto da gravação — assim uma leitura que falhe no meio não deixa figura
    órfã.
    """
    documento = leitor_docx.ler_docx(conteudo)
    leitura = leitor_docx.separar_questoes(documento.blocos)
    completas = [q for q in leitura.questoes if q.completa]
    if not completas:
        raise RegraDeNegocio(
            "Não reconheci nenhuma questão completa neste arquivo (número, alternativas a) a e) "
            "e gabarito). Se ele não segue esse formato, monte o simulado pelo chat."
        )

    nao_convertidas = leitor_docx.converter_formatos_antigos(documento.figuras)
    avisos = list(leitura.avisos)
    if nao_convertidas:
        avisos.append(f"{len(nao_convertidas)} figura(s) em formato antigo não convertida(s): as "
                      "questões delas ficaram com imagem pendente.")

    numeros_completos = {q.numero for q in completas}
    return {
        "arquivo_nome": (nome or "")[:200],
        "titulo": leitura.titulo,
        "avisos": avisos,
        "figuras": [
            {"chave": chave, "nome": figura.nome.rsplit("/", 1)[-1][:200],
             "tipo": figura.tipo, "conteudo_base64": base64.b64encode(figura.conteudo).decode()}
            for chave, figura in documento.figuras.items()
            if figura.tipo is not None
        ],
        "questoes": [
            {"numero": q.numero, "avisos": q.avisos, "blocos": q.blocos, "dados": q.como_entrada()}
            for q in completas
        ],
        "incompletas": [
            {"numero": q.numero, "avisos": q.avisos, "blocos": q.blocos}
            for q in leitura.questoes if q.numero not in numeros_completos
        ],
        "blocos": [{"indice": b.indice, "texto": b.texto} for b in documento.blocos],
    }


@router.post("/{token}/prints")
async def enviar_prints(
    token: str,
    arquivos: list[UploadFile] = File(description="Os prints das questões, na ordem"),
) -> dict:
    if len(arquivos) > LIMITE_DOS_PRINTS:
        raise RegraDeNegocio(
            f"Mande até {LIMITE_DOS_PRINTS} prints por link; peça outro no chat para o resto."
        )

    lidos = []
    for numero, arquivo in enumerate(arquivos, start=1):
        # Um byte a mais que o limite basta para recusar sem carregar o resto.
        conteudo = await arquivo.read(LIMITE_DO_PRINT + 1)
        rotulo = f"O arquivo {numero} ({arquivo.filename or 'sem nome'})"
        tipo = _tipo_da_imagem(conteudo)
        if tipo is None:
            raise RegraDeNegocio(f"{rotulo} não é imagem PNG, JPEG, WEBP ou GIF.")
        if len(conteudo) > LIMITE_DO_PRINT:
            raise RegraDeNegocio(f"{rotulo} passa de {LIMITE_DO_PRINT // 1024 // 1024} MB.")
        await run_in_threadpool(_conferir_que_abre, conteudo, rotulo)
        lidos.append({
            "nome": (arquivo.filename or f"print {numero}")[:200],
            "tipo": tipo,
            "conteudo_base64": base64.b64encode(conteudo).decode(),
        })

    return await run_in_threadpool(
        interno_ou_erro, "registrar_prints", token=token, arquivos=lidos)


def _conferir_que_abre(conteudo: bytes, rotulo: str) -> None:
    """A assinatura diz o formato; só abrir diz que o arquivo não está corrompido."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(conteudo)) as imagem:
            imagem.verify()
    except Exception:
        raise RegraDeNegocio(f"{rotulo} não abriu como imagem.") from None
