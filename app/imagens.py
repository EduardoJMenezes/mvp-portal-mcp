"""O Pillow do recorte de figura: a única conta que sobrou deste lado.

Guardar a figura, pôr a referência no texto e tirar a pendência é da API — o
adaptador só faz o que precisa de pixel: ampliar o print para a escala em que
o Claude o vê, estender o retângulo até o desenho acabar e aparar o branco.

A divisão não é arbitrária. O retângulo que o Claude devolve vale na escala da
vista, e quem produziu a vista foi este módulo; mandar a imagem inteira para o
Java só para ele fazer a mesma conta seria trocar Pillow por uma biblioteca
pior, e ainda por cima com o arquivo indo e voltando duas vezes.
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageFilter

from app import leitor_docx
from app.errors import RegraDeNegocio

# O print que o Claude vê já cabe no limite de imagem do modelo, para não ser
# reduzido de novo no caminho: é isso que faz o retângulo que ele devolve valer
# aqui, na mesma escala. Print pequeno cresce, até 3 vezes: o erro do retângulo
# é em pixels da vista, e no original ele encolhe na mesma proporção.
LADO_DA_VISTA = 1568
PIXELS_DA_VISTA = 1_150_000
AMPLIACAO_MAXIMA = 3
# Escuro o bastante para ser traço de desenho, e não o esfumado da letra vizinha.
TRACO = 100


# --- o que é só pixel --------------------------------------------------------


def _tamanho_da_vista(largura: int, altura: int) -> tuple[int, int]:
    escala = min(AMPLIACAO_MAXIMA, LADO_DA_VISTA / max(largura, altura),
                 (PIXELS_DA_VISTA / (largura * altura)) ** 0.5)
    return int(largura * escala), int(altura * escala)  # arredondar para cima estoura o limite


def _estender_ate_o_desenho(imagem: Image.Image, caixa: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Empurra cada borda do retângulo enquanto ela corta traço, até uma faixa em branco.

    O retângulo estimado olhando a imagem erra por poucos pixels, e num print
    pequeno isso corta o anel de uma estrutura — no primeiro teste real, três de
    oito figuras saíram assim, e o Claude aceitou. A faixa em branco é o que
    separa o desenho do texto em volta. O traço engordado em 1 px atravessa o
    vão de 1 ou 2 px entre a ligação e o átomo ("O" sobre a dupla); a linha de
    texto vizinha, a 3 px ou mais, fica de fora.
    """
    traco = leitor_docx.tinta(imagem, TRACO).filter(ImageFilter.MaxFilter(3))
    e, t, d, b = caixa
    while True:
        antes = (e, t, d, b)
        if t > 0 and traco.crop((e, t, d, t + 1)).getbbox():
            t -= 1
        if b < imagem.height and traco.crop((e, b - 1, d, b)).getbbox():
            b += 1
        if e > 0 and traco.crop((e, t, e + 1, b)).getbbox():
            e -= 1
        if d < imagem.width and traco.crop((d - 1, t, d, b)).getbbox():
            d += 1
        if (e, t, d, b) == antes:
            return e, t, d, b


def _png(imagem: Image.Image) -> bytes:
    saida = io.BytesIO()
    imagem.save(saida, "PNG", optimize=True)
    return saida.getvalue()


def _jpeg(imagem: Image.Image) -> bytes:
    """A vista vai em JPEG: o print ampliado em PNG passa de 600 KB, e são cinco por chamada."""
    saida = io.BytesIO()
    imagem.save(saida, "JPEG", quality=90)
    return saida.getvalue()


# --- o que vem da API --------------------------------------------------------


def _ids_dos_prints(importacao_id: int) -> list[int]:
    return _comando()("prints_da_importacao", importacao=importacao_id)["figuras"]


def _comando():
    """A ponte, importada por dentro.

    Este módulo é a conta de pixel, e o portal usa a mesma conta — sem este
    adiamento, `app.services.importacoes` passaria a importar o adaptador MCP
    só para calcular a escala de um print.
    """
    from app.mcp_server.api import comando

    return comando


def _print(ids: list[int], numero: int) -> Image.Image:
    if not 1 <= numero <= len(ids):
        raise RegraDeNegocio(f"O print {numero} não existe: esta importação tem de 1 a {len(ids)}.")
    figura = _comando()("bytes_da_figura", figura=ids[numero - 1])
    bytes_ = base64.b64decode(figura["conteudo_base64"])
    with Image.open(io.BytesIO(bytes_)) as original:
        return leitor_docx.sobre_branco(original)


# --- as duas tools -----------------------------------------------------------


def ver_prints(importacao_id: int, de: int = 1, ate: int | None = None) -> tuple[dict, list[bytes]]:
    """Os prints como o Claude os vê, na escala em que o retângulo do recorte vale."""
    ids = _ids_dos_prints(importacao_id)
    ate = min(ate or de + 4, len(ids))
    descricao, vistas = [], []
    for numero in range(de, ate + 1):
        imagem = _print(ids, numero)
        tamanho = _tamanho_da_vista(*imagem.size)
        if tamanho != imagem.size:
            imagem = imagem.resize(tamanho, Image.Resampling.LANCZOS)
        descricao.append({"print": numero, "largura": tamanho[0], "altura": tamanho[1]})
        vistas.append(_jpeg(imagem))
    if not vistas:
        raise RegraDeNegocio(f"Esta importação tem {len(ids)} print(s); peça de 1 a {len(ids)}.")
    return {
        "importacao_id": importacao_id,
        "total_prints": len(ids),
        "mostrando": f"{de} a {ate}",
        "prints": descricao,
    }, vistas


def recortar_figura(
    importacao_id: int,
    numero: int,
    questao_id: int,
    retangulo: list[float],
    parte: str = "ENUNCIADO",
    alternativa: str | None = None,
    substituir: int | None = None,
    estender: bool = True,
) -> tuple[dict, bytes]:
    """Recorta a figura de dentro do print e a manda para a API pôr na questão.

    `retangulo` é [x0, y0, x1, y1] na escala de `ver_prints`. O recorte sai do
    print original: estendido até o desenho acabar (`estender`), com a margem
    branca aparada. Devolve o resultado e a prévia, na escala da vista, para o
    Claude conferir. `substituir` troca um recorte que saiu errado sem mexer no
    texto. Quem recusa questão já publicada é a API.
    """
    ids = _ids_dos_prints(importacao_id)
    imagem = _print(ids, numero)
    largura, altura = _tamanho_da_vista(*imagem.size)
    try:
        x0, y0, x1, y1 = (float(v) for v in retangulo)
    except (TypeError, ValueError):
        raise RegraDeNegocio("O retângulo vai como [x0, y0, x1, y1], em pixels.") from None
    folga = 10  # o que passa um pouco da borda é só a borda
    if not (-folga <= x0 < x1 <= largura + folga and -folga <= y0 < y1 <= altura + folga):
        raise RegraDeNegocio(
            f"O retângulo {list(retangulo)} não cabe no print {numero}, que tem {largura}×{altura} px "
            "na escala de ver_prints. Use [x0, y0, x1, y1] com x0 < x1 e y0 < y1."
        )

    fx, fy = imagem.width / largura, imagem.height / altura
    e = min(max(0, round(x0 * fx)), imagem.width - 1)
    t = min(max(0, round(y0 * fy)), imagem.height - 1)
    caixa = (e, t, max(e + 1, min(imagem.width, round(x1 * fx))), max(t + 1, min(imagem.height, round(y1 * fy))))
    if estender:
        caixa = _estender_ate_o_desenho(imagem, caixa)
    recorte = leitor_docx.aparar_margem(_png(imagem.crop(caixa)))
    em_base64 = base64.b64encode(recorte).decode()

    if substituir is not None:
        saida = _comando()("trocar_figura", figura=substituir, questao=str(questao_id),
                           conteudo_base64=em_base64)
    else:
        saida = _comando()(
            "anexar_figura",
            questao=str(questao_id),
            conteudo_base64=em_base64,
            nome=f"print {numero}",
            parte=parte,
            alternativa=alternativa,
        )

    # O Claude confere na escala em que viu o print: recorte de print pequeno,
    # do tamanho original, é miúdo demais para ele notar um corte.
    previa = recorte
    if fx < 1:
        with Image.open(io.BytesIO(recorte)) as pequena:
            previa = _png(pequena.resize((round(pequena.width / fx), round(pequena.height / fy)),
                                         Image.Resampling.LANCZOS))
    return saida, previa
