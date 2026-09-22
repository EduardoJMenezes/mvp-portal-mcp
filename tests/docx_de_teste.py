"""Um .docx mínimo, montado à mão, e um print de questão, para testar o importador.

Os simulados reais da equipe não entram no repositório; este gerador reproduz
só o que o leitor lê: parágrafos com corridas (índice, expoente, negrito),
figuras, equações do Word e tabelas.
"""

import io
import zipfile

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
)


def corrida(texto: str, posicao: str | None = None, negrito: bool = False) -> str:
    propriedades = ""
    if posicao or negrito:
        alinhamento = f'<w:vertAlign w:val="{posicao}"/>' if posicao else ""
        propriedades = f"<w:rPr>{'<w:b/>' if negrito else ''}{alinhamento}</w:rPr>"
    return f'<w:r>{propriedades}<w:t xml:space="preserve">{texto}</w:t></w:r>'


def p(*partes: str) -> str:
    """Parágrafo: cada parte é texto simples ou uma corrida já montada."""
    return "<w:p>" + "".join(x if x.startswith("<") else corrida(x) for x in partes) + "</w:p>"


def figura(rid: str = "rId1") -> str:
    return f'<w:r><w:drawing><a:graphic><a:blip r:embed="{rid}"/></a:graphic></w:drawing></w:r>'


def tabela(*linhas: tuple[str, ...]) -> str:
    return "<w:tbl>" + "".join(
        "<w:tr>" + "".join(f"<w:tc>{p(celula)}</w:tc>" for celula in linha) + "</w:tr>"
        for linha in linhas
    ) + "</w:tbl>"


def questao(numero: int, enunciado: str, gabarito: str | None, resolucao: list[str],
            marcador: str = "GABARITO: ", figuras_nas_alternativas: bool = False) -> list[str]:
    blocos = [p(f"{numero:02d}. {enunciado}")]
    for letra in "abcde":
        if figuras_nas_alternativas:
            blocos += [p(f"{letra})"), p(figura())]
        else:
            blocos.append(p(f"{letra}) alternativa {letra} da {numero}"))
    if gabarito:
        blocos.append(p(f"{marcador}{gabarito}"))
    return blocos + [p(linha) for linha in resolucao]


def docx(*blocos: str, midias: dict[str, bytes] | None = None) -> bytes:
    midias = {"image1.png": PNG} if midias is None else midias
    rels = "".join(
        f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'relationships/image" Target="media/{nome}"/>'
        for n, nome in enumerate(midias, start=1)
    )
    arquivo = io.BytesIO()
    with zipfile.ZipFile(arquivo, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document {_NS}><w:body>{"".join(blocos)}</w:body></w:document>')
        z.writestr("word/_rels/document.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   f'relationships">{rels}</Relationships>')
        for nome, conteudo in midias.items():
            z.writestr(f"word/media/{nome}", conteudo)
    return arquivo.getvalue()


def print_de_questao(largura: int = 900, altura: int = 600) -> bytes:
    """Print de site: linhas de texto em cinza e, entre elas, a figura em (100, 150)–(300, 350)."""
    from PIL import Image, ImageDraw

    folha = Image.new("RGBA", (largura, altura), "white")
    desenho = ImageDraw.Draw(folha)
    for y in (20, 50, 80, 420):
        desenho.rectangle((20, y, largura - 40, y + 14), fill=(60, 60, 60))
    desenho.rectangle((100, 150, 300, 350), fill="black")
    saida = io.BytesIO()
    folha.save(saida, "PNG")
    return saida.getvalue()
