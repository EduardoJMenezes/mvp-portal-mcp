"""Leitura do .docx de simulado: do arquivo para blocos, e dos blocos para questões.

Duas etapas, separadas de propósito (ver docs/IMPORTADOR-SIMULADO.md):

1. **Blocos** (`ler_docx`): o documento em ordem, sem interpretar nada. Cada
   parágrafo vira Markdown — índice e expoente em Unicode, equação do Word em
   LaTeX, figura como referência `![](figura:f3)` — e cada tabela vira tabela.
2. **Questões** (`separar_questoes`): regras decidem onde começa cada questão,
   o que é alternativa, gabarito e resolução. O que não fecha vira aviso.

O texto das questões sai sempre dos blocos, nunca de uma redigitação: é o que
torna o importador mais fiel do que a transcrição pelo chat. Nada aqui toca o
banco — quem grava é `importacoes.py`.
"""

from __future__ import annotations

import io
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from app.errors import RegraDeNegocio


LETRAS = ("A", "B", "C", "D", "E")


class ParteDaQuestao:
    """Onde a figura aparece — o mesmo vocabulário do Java."""

    ENUNCIADO = "ENUNCIADO"
    ALTERNATIVA = "ALTERNATIVA"
    RESOLUCAO = "RESOLUCAO"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# Um .docx é um zip: limites contra arquivo inflado de propósito.
LIMITE_DESCOMPACTADO = 150 * 1024 * 1024
LIMITE_DE_ENTRADAS = 5000

FORMATOS_WEB = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "webp": "image/webp"}


@dataclass
class Figura:
    chave: str  # "f1", "f2"… na ordem em que aparece
    nome: str  # caminho dentro do .docx, ex.: word/media/image3.emf
    conteudo: bytes
    origem: str  # extensão original
    tipo: str | None  # MIME servível; None enquanto não convertida


@dataclass
class Bloco:
    indice: int
    texto: str  # Markdown com as referências de figura
    plano: str  # sem formatação: é o que as regras leem
    figuras: list[str] = field(default_factory=list)


@dataclass
class Documento:
    blocos: list[Bloco]
    figuras: dict[str, Figura]


# --- texto: índice, expoente e Markdown --------------------------------------

_SUB = dict(zip("0123456789+-−=()aeoxhklmnpstijruv", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼᵣᵤᵥ"))
_SUP = dict(zip("0123456789+-−–=()abcdefghijklmnoprstuvwxyz",
                "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ"))

# O Word semeia espaço de largura zero dentro de equação e de fórmula colada.
_INVISIVEIS = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


def _escapar_md(texto: str) -> str:
    """Texto do Word literal no Markdown: `*`, `_`, `$`, `|`… não viram marcação."""
    return re.sub(r"([\\`*_\[\]$|~])", r"\\\1", texto)


def _escapar_tex(texto: str) -> str:
    return re.sub(r"([{}#%&_$])", r"\\\1", texto.replace("\\", r"\backslash "))


def _indice(texto: str, sobrescrito: bool) -> str:
    """CO₃²⁻ em Unicode quando dá — sai em pé, como em livro; senão, LaTeX."""
    tabela = _SUP if sobrescrito else _SUB
    if all(c in tabela or c.isspace() for c in texto):
        return "".join(tabela.get(c, c) for c in texto)
    if not any(c.isalnum() for c in texto):
        return _escapar_md(texto)  # ● do radical, por exemplo: fica como está
    marca = "^" if sobrescrito else "_"
    return f"${marca}{{\\text{{{_escapar_tex(texto)}}}}}$"


_SIMBOLO = {0xAE: "→", 0xAC: "←", 0xAB: "↔", 0xDE: "⇒", 0xDB: "⇔", 0xB3: "≥", 0xA3: "≤",
            0xB4: "×", 0xB1: "±", 0xB0: "°", 0xD7: "·", 0x44: "Δ", 0x61: "α", 0x62: "β",
            0x67: "γ", 0x70: "π", 0x6D: "μ", 0x6C: "λ"}


# --- equação do Word (OMML) para LaTeX ---------------------------------------

_TEX_SIMBOLOS = {"→": r"\rightarrow ", "←": r"\leftarrow ", "↔": r"\leftrightarrow ",
                 "⇌": r"\rightleftharpoons ", "⇄": r"\rightleftarrows ", "⇒": r"\Rightarrow ",
                 "×": r"\times ", "·": r"\cdot ", "⋅": r"\cdot ", "≈": r"\approx ",
                 "≠": r"\neq ", "≤": r"\leq ", "≥": r"\geq ", "±": r"\pm ", "Δ": r"\Delta ",
                 "∆": r"\Delta ", "α": r"\alpha ", "β": r"\beta ", "γ": r"\gamma ",
                 "λ": r"\lambda ", "μ": r"\mu ", "π": r"\pi ", "∞": r"\infty ", "−": "-",
                 "°": r"^{\circ}", "•": r"\bullet ", "●": r"\bullet ", "√": r"\surd "}
_SETAS = {"→": r"\xrightarrow", "←": r"\xleftarrow", "⇌": r"\xrightleftharpoons"}
_NARY = {"∑": r"\sum", "∏": r"\prod", "∫": r"\int", "∮": r"\oint", "∬": r"\iint"}
_ACENTOS = {"̂": r"\hat", "̃": r"\tilde", "⃗": r"\vec", "̅": r"\overline", "̇": r"\dot"}


def _val(no, caminho: str) -> str | None:
    alvo = no.find(caminho)
    return None if alvo is None else alvo.get(M + "val")


def _filho(no, nome: str) -> str:
    alvo = no.find(M + nome)
    return "" if alvo is None else _omml(alvo)


_SIMBOLO_TEX = re.compile("(" + "|".join(map(re.escape, _TEX_SIMBOLOS)) + ")")


def _texto_matematico(texto: str, estilo: str | None) -> str:
    """Seta e letra grega viram comando; palavra vira texto em pé; o resto, matemática."""
    saida = []
    for parte in _SIMBOLO_TEX.split(texto.translate(_INVISIVEIS).replace("\xa0", " ")):
        if not parte:
            continue
        if parte in _TEX_SIMBOLOS:
            saida.append(_TEX_SIMBOLOS[parte])
        elif " " in parte.strip() or re.search(r"[^\W\d_]{2,}", parte) or (
            estilo == "p" and re.search(r"[^\W\d_]", parte)
        ):
            saida.append(rf"\text{{{_escapar_tex(parte)}}}")
        else:
            saida.append(_escapar_tex(parte))
    return "".join(saida)


def _omml(no) -> str:  # noqa: C901 — um caso por elemento da especificação
    tag = no.tag.removeprefix(M)
    if tag == "r":
        texto = "".join(t.text or "" for t in no.iter(M + "t"))
        return _texto_matematico(texto, _val(no, f"{M}rPr/{M}sty"))
    if tag == "sSub":
        return f"{{{_filho(no, 'e')}}}_{{{_filho(no, 'sub')}}}"
    if tag == "sSup":
        return f"{{{_filho(no, 'e')}}}^{{{_filho(no, 'sup')}}}"
    if tag == "sSubSup":
        return f"{{{_filho(no, 'e')}}}_{{{_filho(no, 'sub')}}}^{{{_filho(no, 'sup')}}}"
    if tag == "sPre":  # notação nuclear: ⁹⁹₄₂Mo
        return f"{{}}_{{{_filho(no, 'sub')}}}^{{{_filho(no, 'sup')}}}{{{_filho(no, 'e')}}}"
    if tag == "f":
        if _val(no, f"{M}fPr/{M}type") == "lin":
            return f"{_filho(no, 'num')}/{_filho(no, 'den')}"
        return rf"\frac{{{_filho(no, 'num')}}}{{{_filho(no, 'den')}}}"
    if tag == "rad":
        grau = _filho(no, "deg")
        return rf"\sqrt[{grau}]{{{_filho(no, 'e')}}}" if grau else rf"\sqrt{{{_filho(no, 'e')}}}"
    if tag == "d":
        abre = _val(no, f"{M}dPr/{M}begChr")
        fecha = _val(no, f"{M}dPr/{M}endChr")
        separador = _val(no, f"{M}dPr/{M}sepChr") or ","
        miolo = separador.join(_omml(e) for e in no.findall(M + "e"))

        def delim(c, padrao):
            c = padrao if c is None else c
            return "." if c == "" else {"{": r"\{", "}": r"\}"}.get(c, c)

        return rf"\left{delim(abre, '(')}{miolo}\right{delim(fecha, ')')}"
    if tag == "nary":
        simbolo = _NARY.get(_val(no, f"{M}naryPr/{M}chr") or "∫", r"\int")
        return f"{simbolo}_{{{_filho(no, 'sub')}}}^{{{_filho(no, 'sup')}}}{{{_filho(no, 'e')}}}"
    if tag == "groupChr":
        caractere = _val(no, f"{M}groupChrPr/{M}chr") or "⏟"
        embaixo = (_val(no, f"{M}groupChrPr/{M}pos") or "bot") == "bot"
        if caractere in _SETAS:
            return f"{_SETAS[caractere]}[{_filho(no, 'e')}]{{}}" if embaixo else (
                f"{_SETAS[caractere]}{{{_filho(no, 'e')}}}")
        return rf"\underbrace{{{_filho(no, 'e')}}}" if embaixo else rf"\overbrace{{{_filho(no, 'e')}}}"
    if tag in ("limUpp", "limLow"):
        base, limite = _filho(no, "e"), _filho(no, "lim")
        seta = next((s for u, s in _SETAS.items() if base.strip() == _TEX_SIMBOLOS.get(u, u).strip()), None)
        if seta:
            return f"{seta}{{{limite}}}" if tag == "limUpp" else f"{seta}[{limite}]{{}}"
        return (rf"\overset{{{limite}}}{{{base}}}" if tag == "limUpp"
                else rf"\underset{{{limite}}}{{{base}}}")
    if tag == "acc":
        comando = _ACENTOS.get(_val(no, f"{M}accPr/{M}chr") or "̂", r"\hat")
        return f"{comando}{{{_filho(no, 'e')}}}"
    if tag == "bar":
        topo = (_val(no, f"{M}barPr/{M}pos") or "bot") == "top"
        return rf"\overline{{{_filho(no, 'e')}}}" if topo else rf"\underline{{{_filho(no, 'e')}}}"
    if tag == "eqArr":
        return r"\begin{gathered}" + r"\\".join(_omml(e) for e in no.findall(M + "e")) + r"\end{gathered}"
    if tag == "m":
        linhas = [" & ".join(_omml(e) for e in mr.findall(M + "e")) for mr in no.findall(M + "mr")]
        return r"\begin{matrix}" + r"\\".join(linhas) + r"\end{matrix}"
    if tag == "func":
        return f"{_filho(no, 'fName')}\\,{_filho(no, 'e')}"
    if tag.endswith("Pr") or tag in ("ctrlPr",):
        return ""
    return "".join(_omml(filho) for filho in no)  # oMath, e, box, borderBox…


def _xml(dados: bytes):
    """Lê XML que veio de fora: sem DTD e sem entidade declarada.

    Documento do Word não traz nenhuma das duas, e é por elas que um arquivo de
    poucos KB vira gigabytes de memória ao ser lido — a "billion laughs", que o
    limite de tamanho do zip não pega, porque a explosão acontece depois.
    """
    try:
        return ET.fromstring(dados, forbid_dtd=True)
    except DefusedXmlException:
        raise RegraDeNegocio(
            "Este .docx declara entidades ou DTD no XML, o que um documento do Word não faz. "
            "Recusado: um arquivo assim derruba o servidor ao ser lido."
        ) from None


# --- parágrafo, tabela e figura ----------------------------------------------


class _Leitor:
    def __init__(self, zipado: zipfile.ZipFile):
        self.zip = zipado
        self.figuras: dict[str, Figura] = {}
        self._por_nome: dict[str, str] = {}
        self.rels = {}
        try:
            raiz = _xml(zipado.read("word/_rels/document.xml.rels"))
            for rel in raiz.iter(REL + "Relationship"):
                if rel.get("TargetMode") != "External":
                    alvo = rel.get("Target") or ""
                    self.rels[rel.get("Id")] = (
                        alvo.lstrip("/") if alvo.startswith("/")
                        else posixpath.normpath(posixpath.join("word", alvo))
                    )
        except KeyError:
            pass

    def figura(self, rid: str | None) -> str | None:
        nome = self.rels.get(rid or "")
        if not nome:
            return None
        if nome not in self._por_nome:
            try:
                conteudo = self.zip.read(nome)
            except KeyError:
                return None
            origem = nome.rsplit(".", 1)[-1].lower()
            chave = f"f{len(self.figuras) + 1}"
            self.figuras[chave] = Figura(chave, nome, conteudo, origem, FORMATOS_WEB.get(origem))
            self._por_nome[nome] = chave
        return self._por_nome[nome]

    def paragrafo(self, p, indice: int) -> Bloco:
        pedacos: list[tuple[str, str, bool, bool]] = []  # (texto, posição, negrito, itálico)
        figuras: list[str] = []
        plano: list[str] = []

        def corrida(r):
            propriedades = r.find(W + "rPr")
            posicao, negrito, italico = "normal", False, False
            if propriedades is not None:
                alinhamento = propriedades.find(W + "vertAlign")
                if alinhamento is not None:
                    posicao = {"subscript": "sub", "superscript": "sup"}.get(alinhamento.get(W + "val"), "normal")
                negrito = _ligado(propriedades.find(W + "b"))
                italico = _ligado(propriedades.find(W + "i"))
            for filho in r:
                if filho.tag == W + "t":
                    texto = (filho.text or "").translate(_INVISIVEIS)
                    pedacos.append((texto, posicao, negrito, italico))
                    plano.append(texto)
                elif filho.tag in (W + "tab",):
                    pedacos.append((" ", "normal", False, False))
                    plano.append(" ")
                elif filho.tag in (W + "br", W + "cr"):
                    pedacos.append(("\n", "normal", False, False))
                    plano.append("\n")
                elif filho.tag == W + "sym":
                    caractere = _SIMBOLO.get(int(filho.get(W + "char") or "0", 16) & 0xFF, "")
                    pedacos.append((caractere, posicao, negrito, italico))
                    plano.append(caractere)
                elif filho.tag in (W + "drawing", W + "pict", W + "object"):
                    for no in filho.iter():
                        rid = no.get(R + "embed") if no.tag.endswith("}blip") else (
                            no.get(R + "id") if no.tag.endswith("}imagedata") else None)
                        chave = self.figura(rid)
                        if chave and chave not in figuras[-1:]:
                            figuras.append(chave)
                            pedacos.append((f"\x00{chave}\x00", "figura", False, False))

        def percorrer(no):
            for filho in no:
                if filho.tag == W + "r":
                    corrida(filho)
                elif filho.tag == M + "oMathPara":
                    for eq in filho.findall(M + "oMath"):
                        pedacos.append((f"\n$${_omml(eq)}$$\n", "latex", False, False))
                        plano.append(" ")
                elif filho.tag == M + "oMath":
                    pedacos.append((f"${_omml(filho)}$", "latex", False, False))
                    plano.append("".join(t.text or "" for t in filho.iter(M + "t")))
                elif filho.tag in (W + "del", W + "pPr", W + "moveFrom"):
                    continue
                else:  # hyperlink, ins, smartTag, sdt…
                    percorrer(filho)

        percorrer(p)
        return Bloco(indice, _montar_markdown(pedacos), "".join(plano).strip(), figuras)

    def tabela(self, tbl, indice: int) -> Bloco:
        linhas, figuras, plano = [], [], []
        for tr in tbl.findall(W + "tr"):
            celulas = []
            for tc in tr.findall(W + "tc"):
                partes = [self.paragrafo(p, indice) for p in tc.iter(W + "p")]
                figuras += [f for parte in partes for f in parte.figuras]
                texto = " ".join(parte.texto.replace("\n", " ") for parte in partes if parte.texto)
                celulas.append(texto.strip())  # o `|` já saiu escapado do parágrafo
                span = tc.find(f"{W}tcPr/{W}gridSpan")
                celulas += [""] * (int(span.get(W + "val") or 1) - 1 if span is not None else 0)
                plano.append(" ".join(parte.plano for parte in partes))
            linhas.append(celulas)
        if not linhas:
            return Bloco(indice, "", "", [])
        largura = max(len(linha) for linha in linhas)
        linhas = [linha + [""] * (largura - len(linha)) for linha in linhas]
        markdown = "\n".join(
            ["| " + " | ".join(linhas[0]) + " |", "|" + " --- |" * largura]
            + ["| " + " | ".join(linha) + " |" for linha in linhas[1:]]
        )
        return Bloco(indice, markdown, " | ".join(plano), figuras)


def _ligado(no) -> bool:
    return no is not None and (no.get(W + "val") or "true") not in ("0", "false", "none")


def _montar_markdown(pedacos: list[tuple[str, str, bool, bool]]) -> str:
    saida: list[str] = []
    grupo: list[str] = []
    estilo_atual = (False, False)

    def fechar():
        texto = "".join(grupo)
        grupo.clear()
        if not texto:
            return
        negrito, italico = estilo_atual
        miolo = texto.strip()
        if (negrito or italico) and miolo:
            marca = "***" if negrito and italico else ("**" if negrito else "*")
            inicio = texto[: len(texto) - len(texto.lstrip())]
            fim = texto[len(texto.rstrip()):]
            texto = f"{inicio}{marca}{miolo}{marca}{fim}"
        saida.append(texto)

    for texto, posicao, negrito, italico in pedacos:
        if posicao in ("figura", "latex"):
            fechar()
            saida.append(texto)
            continue
        convertido = _indice(texto, posicao == "sup") if posicao in ("sub", "sup") else _escapar_md(texto)
        estilo = (negrito, italico)
        if estilo != estilo_atual:
            fechar()
            estilo_atual = estilo
        grupo.append(convertido)
    fechar()
    markdown = "".join(saida)
    return re.sub(r"\x00(f\d+)\x00", r"![](figura:\1)", markdown).strip()


def ler_docx(conteudo: bytes) -> Documento:
    """O documento em blocos, na ordem. Recusa o que não for .docx de verdade."""
    try:
        zipado = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile:
        raise RegraDeNegocio("O arquivo não é um .docx válido.") from None
    with zipado:
        entradas = zipado.infolist()
        if len(entradas) > LIMITE_DE_ENTRADAS or sum(e.file_size for e in entradas) > LIMITE_DESCOMPACTADO:
            raise RegraDeNegocio("O .docx é grande demais depois de descompactado.")
        try:
            raiz = _xml(zipado.read("word/document.xml"))
        except KeyError:
            raise RegraDeNegocio("O arquivo não é um .docx: falta o documento do Word.") from None
        leitor = _Leitor(zipado)
        corpo = raiz.find(W + "body")
        blocos = []
        for no in (corpo if corpo is not None else []):
            if no.tag == W + "p":
                blocos.append(leitor.paragrafo(no, len(blocos)))
            elif no.tag == W + "tbl":
                blocos.append(leitor.tabela(no, len(blocos)))
        return Documento(blocos, leitor.figuras)


def converter_formatos_antigos(figuras: dict[str, Figura]) -> list[str]:
    """EMF, WMF e as prévias de equação antiga viram PNG, pelo LibreOffice.

    Devolve as chaves que não deu para converter. Sem LibreOffice instalado
    (máquina de desenvolvimento), nada é convertido e tudo é devolvido: a
    questão fica com imagem pendente, em vez de a importação quebrar.
    """
    antigas = [f for f in figuras.values() if f.tipo is None]
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if antigas and soffice:
        with tempfile.TemporaryDirectory() as pasta:
            entradas = []
            for n, figura in enumerate(antigas):
                caminho = Path(pasta) / f"figura{n}.{figura.origem}"
                caminho.write_bytes(figura.conteudo)
                entradas.append(str(caminho))
            # Folha A4 em dobro (96 dpi × 2): a tabela que vinha de "Equação 3.0"
            # sai legível. O branco em volta é recortado logo abaixo.
            png_em_dobro = ('png:draw_png_Export:{"PixelWidth":{"type":"long","value":"1588"},'
                            '"PixelHeight":{"type":"long","value":"2246"}}')
            subprocess.run(
                [soffice, "--headless", "--norestore",
                 f"-env:UserInstallation={(Path(pasta) / 'perfil').as_uri()}",
                 "--convert-to", png_em_dobro, "--outdir", pasta, *entradas],
                capture_output=True, timeout=180, check=False,
            )
            for n, figura in enumerate(antigas):
                png = Path(pasta) / f"figura{n}.png"
                if png.exists() and png.stat().st_size:
                    figura.conteudo, figura.tipo = aparar_margem(png.read_bytes()), "image/png"
    return [f.chave for f in figuras.values() if f.tipo is None]


def sobre_branco(imagem):
    """A imagem em RGB, com a parte transparente pintada de branco, como na página."""
    from PIL import Image

    rgba = imagem.convert("RGBA")
    return Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")


def tinta(imagem, tolerancia: int = 40):
    """Máscara do que se afasta do branco mais que a tolerância: traço, letra, foto."""
    from PIL import Image, ImageChops

    diferenca = ImageChops.difference(imagem, Image.new("RGB", imagem.size, "white")).convert("L")
    return diferenca.point(lambda v: 255 if v > tolerancia else 0)


def aparar_margem(png: bytes, folga: int = 8, tolerancia: int = 40) -> bytes:
    """Recorta o branco em volta do desenho.

    O LibreOffice exporta a folha A4 inteira, com a figura perdida no meio, e o
    recorte de um print vem com a sobra do retângulo; sem aparar, uma estrutura
    química viraria uma página em branco na tela do aluno. A tolerância deixa
    de fora o quase branco do fundo de site e a sujeira de JPEG. A folga é
    branco acrescentado, para o desenho não encostar na borda.
    """
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(png)) as original:
        imagem = sobre_branco(original)
    caixa = tinta(imagem, tolerancia).getbbox()
    if caixa is None:
        return png
    recorte = ImageOps.expand(imagem.crop(caixa), border=folga, fill="white")
    saida = io.BytesIO()
    recorte.save(saida, "PNG", optimize=True)
    return saida.getvalue()


# --- das regras às questões --------------------------------------------------

_INICIO = re.compile(r"^\s*(?:quest[aã]o\s*(\d{1,3})\s*[.):\-–]?|(\d{1,3})\s*[.)])\s*(.*)$",
                     re.IGNORECASE | re.DOTALL)
_ALTERNATIVA = re.compile(r"^\s*\(?([a-eA-E])\)\s*(.*)$", re.DOTALL)
_VARIAS = re.compile(r"(?:^|\s)\(?([a-e])\)\s", re.IGNORECASE)
_GABARITO = re.compile(
    r"^\s*(?:gabarito|letra|resposta(?:\s+correta)?|alternativa(?:\s+correta)?)"
    r"\s*[:\-–]?\s*\(?([A-Ea-e])\)?\s*[.;]?\s*$",
    re.IGNORECASE,
)
_PAR_DE_GABARITO = re.compile(r"\b(\d{1,3})\s*[.)\-–:]?\s*([A-E])\b")
_ROTULO_MD = re.compile(r"^\s*(?:\*{1,3})?\s*\\?\(?[a-eA-E]\\?\)(?:\*{1,3})?\s*")
_NUMERO_MD = re.compile(r"^\s*(?:\*{1,3})?\s*(?:quest[aã]o\s*\d{1,3}\s*[.):\-–]?|\d{1,3}\s*[.)])(?:\*{1,3})?\s*",
                        re.IGNORECASE)
_MARCA_RESOLUCAO = re.compile(r"^\s*(?:\*{1,3})?\s*resolu[cç][aã]o(?:\s+comentada)?\s*:?\s*(?:\*{1,3})?\s*",
                              re.IGNORECASE)


@dataclass
class QuestaoLida:
    numero: int
    blocos: list[int] = field(default_factory=list)
    enunciado: list[str] = field(default_factory=list)
    alternativas: dict[str, list[str]] = field(default_factory=dict)
    gabarito: str | None = None
    resolucao: list[str] = field(default_factory=list)
    figuras: dict[str, str] = field(default_factory=dict)  # chave → parte
    avisos: list[str] = field(default_factory=list)

    @property
    def faltas(self) -> list[str]:
        faltas = []
        if not "".join(self.enunciado).strip():
            faltas.append("enunciado")
        ausentes = [letra for letra in LETRAS if not "".join(self.alternativas.get(letra, [])).strip()]
        if ausentes:
            faltas.append(f"alternativas {', '.join(ausentes)}")
        if self.gabarito not in LETRAS:
            faltas.append("gabarito")
        return faltas

    @property
    def completa(self) -> bool:
        return not self.faltas

    def como_entrada(self) -> dict:
        """No formato que `criar_simulado_rascunho` recebe como questão nova."""
        return {
            "numero": self.numero,
            "enunciado": "\n\n".join(t for t in self.enunciado if t.strip()),
            "alternativas": {letra: "\n\n".join(t for t in self.alternativas[letra] if t.strip())
                             for letra in LETRAS},
            "gabarito": self.gabarito,
            "resolucao_comentada": "\n\n".join(t for t in self.resolucao if t.strip()) or None,
        }


@dataclass
class Leitura:
    titulo: str | None
    questoes: list[QuestaoLida]
    avisos: list[str]


def separar_questoes(blocos: list[Bloco]) -> Leitura:
    """As regras: número em sequência, alternativas a)–e), gabarito, e o resto é resolução."""
    titulo = None
    questoes: list[QuestaoLida] = []
    atual: QuestaoLida | None = None
    estado = None  # enunciado | alternativas | resolucao
    avisos: list[str] = []

    def guardar(parte: str, texto: str, bloco: Bloco, letra: str | None = None):
        tipo = {"enunciado": ParteDaQuestao.ENUNCIADO, "alternativas": ParteDaQuestao.ALTERNATIVA,
                "resolucao": ParteDaQuestao.RESOLUCAO}[parte]
        for chave in bloco.figuras:
            atual.figuras.setdefault(chave, tipo)
        if parte == "alternativas":
            atual.alternativas.setdefault(letra, []).append(texto)
        else:
            getattr(atual, "enunciado" if parte == "enunciado" else "resolucao").append(texto)

    for bloco in blocos:
        plano = bloco.plano
        inicio = _INICIO.match(plano)
        if inicio:
            numero = int(inicio.group(1) or inicio.group(2))
            pronta = atual is not None and (estado == "resolucao" or len(atual.alternativas) == 5)
            esperado = atual.numero + 1 if atual else None
            if atual is None or (pronta and numero in (esperado, esperado + 1)):
                if atual is not None and numero == esperado + 1:
                    avisos.append(f"Não encontrei a questão {esperado}: o documento pula de "
                                  f"{atual.numero} para {numero}.")
                atual = QuestaoLida(numero)
                questoes.append(atual)
                estado = "enunciado"
                atual.blocos.append(bloco.indice)
                resto = _NUMERO_MD.sub("", bloco.texto, count=1)
                if resto.strip():
                    guardar("enunciado", resto, bloco)
                else:
                    for chave in bloco.figuras:
                        atual.figuras.setdefault(chave, ParteDaQuestao.ENUNCIADO)
                continue

        if atual is None:
            titulo = titulo or (plano.strip() or None)
            continue
        atual.blocos.append(bloco.indice)

        if estado in ("enunciado", "alternativas") and _GABARITO.match(plano) and len(plano) <= 40:
            atual.gabarito = _GABARITO.match(plano).group(1).upper()
            estado = "resolucao"
            continue

        if estado in ("enunciado", "alternativas"):
            varias = list(_VARIAS.finditer(" " + plano))
            letras = [m.group(1).upper() for m in varias]
            if len(varias) >= 2 and letras == list(LETRAS[: len(letras)]) and plano.lstrip()[:2].lower() in ("a)", "(a"):
                partes = re.split(r"(?:^|\s)\\?\(?[a-eA-E]\\?\)\s", " " + bloco.texto)
                for letra, texto in zip(letras, [p for p in partes[1:]]):
                    atual.alternativas[letra] = [texto.strip()]
                for chave in bloco.figuras:
                    atual.figuras.setdefault(chave, ParteDaQuestao.ALTERNATIVA)
                estado = "alternativas"
                continue

            alternativa = _ALTERNATIVA.match(plano)
            if alternativa:
                letra = alternativa.group(1).upper()
                if letra == "A" and atual.alternativas:
                    # Um novo "a)" antes do gabarito: o que parecia alternativa era
                    # lista do enunciado. Devolve ao enunciado e recomeça.
                    for anterior in LETRAS:
                        atual.enunciado += [f"{anterior.lower()}) {t}" for t in atual.alternativas.get(anterior, [])]
                    atual.alternativas.clear()
                esperada = LETRAS[len(atual.alternativas)] if len(atual.alternativas) < 5 else None
                if letra == esperada:
                    guardar("alternativas", _ROTULO_MD.sub("", bloco.texto, count=1), bloco, letra)
                    estado = "alternativas"
                    continue

            if estado == "alternativas" and (bloco.texto.strip() or bloco.figuras):
                ultima = LETRAS[len(atual.alternativas) - 1]
                guardar("alternativas", bloco.texto, bloco, ultima)
            elif bloco.texto.strip() or bloco.figuras:
                guardar("enunciado", bloco.texto, bloco)
            continue

        # Resolução: tudo até a próxima questão — inclusive "a) Errada…".
        texto = _MARCA_RESOLUCAO.sub("", bloco.texto, count=1) if not atual.resolucao else bloco.texto
        if len(_PAR_DE_GABARITO.findall(plano)) >= 3 and questoes[-1] is atual:
            _gabarito_no_fim(questoes, plano, avisos)
            continue
        if texto.strip() or bloco.figuras:
            guardar("resolucao", texto, bloco)

    # Sem "GABARITO:" nas questões, a tabela de gabarito pode estar no fim.
    if any(q.gabarito is None for q in questoes):
        for bloco in blocos[-15:]:
            if len(_PAR_DE_GABARITO.findall(bloco.plano)) >= 3:
                _gabarito_no_fim(questoes, bloco.plano, avisos)

    for q in questoes:
        if q.faltas:
            q.avisos.append("Não fechou: falta " + "; ".join(q.faltas) + ".")
        if not q.resolucao:
            q.avisos.append("Sem resolução comentada.")
        longa = next((letra for letra, t in q.alternativas.items() if len("".join(t)) > 700), None)
        if longa:
            q.avisos.append(f"Alternativa {longa} longa demais: confira se não engoliu texto de fora.")
    return Leitura(titulo, questoes, avisos)


def _gabarito_no_fim(questoes: list[QuestaoLida], plano: str, avisos: list[str]) -> None:
    por_numero = {q.numero: q for q in questoes}
    preenchidas = 0
    for numero, letra in _PAR_DE_GABARITO.findall(plano):
        q = por_numero.get(int(numero))
        if q is not None and q.gabarito is None:
            q.gabarito = letra
            preenchidas += 1
    if preenchidas:
        avisos.append(f"Gabarito de {preenchidas} questão(ões) lido da tabela do fim do documento.")
