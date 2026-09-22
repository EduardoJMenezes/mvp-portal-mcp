"""Importação de uma pasta do Vimeo como capítulo da plataforma.

Três passos, na ordem: ler a pasta no Vimeo, montar o plano (número inferido do
título, conflitos e avisos) e, só se o professor mandar, gravar como rascunho.

Só os dois primeiros passos moram aqui: ler e planejar não tocam no banco, e
por isso ficaram do lado do adaptador. Gravar é `_aplicar_plano`, em
`mcp_server/tools.py`, que chama a API — e publicar continua exigindo aprovação
humana, que a integração com o Vimeo não dispensa.

A leitura usa `app/integracoes/vimeo`, cuja allowlist só deixa passar GET e
HEAD: por construção, nenhuma importação altera coisa alguma no Vimeo.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from app.config import get_settings
from app.errors import RegraDeNegocio
from app.integracoes.vimeo import (
    VimeoErro,
    CAMPOS_VIDEO_IMPORTACAO,
    ClienteVimeoLeitura,
    TransporteVimeo,
    VideoVimeo,
)
from app.integracoes.vimeo.nomes import inferir_numero, interpretar_faixa


@dataclass
class ItemDoPlano:
    """Um vídeo do Vimeo, já com o número que ele teria na plataforma."""

    vimeo_id: str
    titulo: str
    numero: int | None
    confianca: str
    duracao_segundos: int | None
    url: str | None
    embed_url: str | None
    thumbnail_url: str | None
    publicavel: bool
    privacidade: str
    transcricao: str | None
    avisos: list[str] = field(default_factory=list)

    def para_importacao(self, assunto: str | None = None, subassunto: str | None = None) -> dict:
        """O formato que `rascunhos.importar_videos_como_itens` espera.

        O `nome` do item nasce do título do Vimeo. Antes daqui saía um
        enunciado sintético ("Questão 4 da apostila — resolução em vídeo"),
        porque o vídeo precisava virar uma `Questao` para caber no modelo: a
        questão da apostila mora na apostila, e o que a plataforma guarda é a
        resolução em vídeo.
        """
        return {
            "vimeo_id": self.vimeo_id,
            "titulo": self.titulo,
            "url": self.url,
            "embed_url": self.embed_url,
            "thumbnail_url": self.thumbnail_url,
            "duracao_segundos": self.duracao_segundos,
            "nome": self.titulo,
            "assunto": assunto,
            "subassunto": subassunto,
        }

    def resumo(self) -> dict:
        return {
            "numero": self.numero,
            "titulo": self.titulo,
            "vimeo_id": self.vimeo_id,
            "duracao_segundos": self.duracao_segundos,
            "confianca_do_numero": self.confianca,
            "avisos": self.avisos,
        }


@dataclass
class PlanoDeImportacao:
    pasta_id: str
    pasta_nome: str | None
    itens: list[ItemDoPlano]


@asynccontextmanager
async def abrir_leitura():
    """Cliente de leitura do Vimeo, criado a partir do .env e fechado no fim."""
    s = get_settings()
    if not s.vimeo_real:
        raise RegraDeNegocio(
            "O acervo real do Vimeo não está configurado: falta VIMEO_ACCESS_TOKEN no ambiente."
        )
    transporte = TransporteVimeo(s.vimeo_access_token, agente="mvp-portal-aluno/0.1")
    try:
        yield ClienteVimeoLeitura(transporte)
    finally:
        await transporte.aclose()


async def listar_pastas(busca: str | None = None, limite: int = 60) -> dict:
    """As pastas do Vimeo com a hierarquia — de onde sai o id que a importação pede."""
    async with abrir_leitura() as leitura:
        pastas = await leitura.listar_pastas()

    nomes = {pasta.uri: pasta.nome for pasta in pastas}
    filtradas = [p for p in pastas if not busca or busca.lower() in (p.nome or "").lower()]
    return {
        "total_no_vimeo": len(pastas),
        "mostrando": min(len(filtradas), limite),
        "pastas": [
            {
                "id": pasta.id,
                "nome": pasta.nome,
                "dentro_de": nomes.get(pasta.pai_uri) if pasta.pai_uri else None,
                "videos": pasta.total_videos,
                "videos_com_subpastas": pasta.total_videos_com_subpastas,
                "tem_subpasta": pasta.tem_subpasta,
            }
            for pasta in filtradas[:limite]
        ],
    }


async def ler_video(vimeo_id: str) -> dict:
    """Um vídeo avulso, no formato das tools — com o `embed_url` que faz tocar."""
    async with abrir_leitura() as leitura:
        video = await leitura.obter_video(vimeo_id, campos=CAMPOS_VIDEO_IMPORTACAO)
    return {
        "vimeo_id": video.id or vimeo_id,
        "titulo": video.nome or f"Vídeo {vimeo_id}",
        "url": video.link,
        "embed_url": video.embed_url,
        "thumbnail_url": video.thumbnail_url,
        "duracao_segundos": video.duracao_segundos,
    }


async def resolucao(vimeo_id: str | None) -> dict | None:
    """O vídeo da resolução como o player precisa: com o `embed_url` do Vimeo.

    Só o id não basta — vídeo unlisted não toca sem o hash que vem no embed.
    `None` é "não mexa"; vazio é "sem resolução". Sem Vimeo configurado (o
    acervo de demonstração), segue só com o id.
    """
    if vimeo_id is None:
        return None
    vimeo_id = str(vimeo_id).strip()
    if not vimeo_id or not get_settings().vimeo_real:
        return {"vimeo_id": vimeo_id}
    try:
        return await ler_video(vimeo_id)
    except VimeoErro as e:
        raise RegraDeNegocio(f"Vídeo {vimeo_id} do Vimeo: {e}") from e


async def questoes_com_resolucao(questoes: list | None) -> list | None:
    """Questão nova que cita `vimeo_id` ganha o vídeo inteiro, lido do Vimeo."""
    if questoes is None:
        return None
    return [
        {**q, "resolucao": await resolucao(q["vimeo_id"])}
        if isinstance(q, dict) and q.get("vimeo_id")
        else q
        for q in questoes
    ]


def resolucoes_por_numero(plano: PlanoDeImportacao) -> dict[int, dict]:
    """Os vídeos de resolução de uma pasta, pelo número lido do título.

    É o casamento do simulado: a questão 7 recebe o vídeo "Q07". Número
    repetido fica com o primeiro, na ordem em que o plano já vem.
    """
    resolucoes: dict[int, dict] = {}
    for item in plano.itens:
        if item.numero is not None:
            resolucoes.setdefault(item.numero, item.para_importacao())
    return resolucoes


def _avisos_do_video(video: VideoVimeo, numero: int | None) -> list[str]:
    avisos = []
    if numero is None:
        avisos.append("não consegui ler o número da questão no título")
    if not video.publicavel:
        avisos.append(f"ainda não está pronto no Vimeo (status {video.status})")
    if video.privacidade_embed == "private":
        avisos.append("o embed está desativado no Vimeo; o aluno não conseguiria assistir")
    if video.privacidade_embed == "whitelist":
        avisos.append("o embed é restrito a domínios: confirme que o domínio do portal está liberado")
    return avisos


async def ler_plano(pasta_id: str) -> PlanoDeImportacao:
    """Lê a pasta no Vimeo e ordena pelo número do título (a API devolve fora de ordem)."""
    async with abrir_leitura() as leitura:
        pasta = await leitura.obter_pasta(pasta_id)
        videos = await leitura.listar_videos_da_pasta(pasta_id, campos=CAMPOS_VIDEO_IMPORTACAO)

    itens = []
    for video in videos:
        inferido = inferir_numero(video.nome)
        itens.append(
            ItemDoPlano(
                vimeo_id=video.id or "",
                titulo=video.nome or "(sem título)",
                numero=inferido.numero,
                confianca=inferido.confianca,
                duracao_segundos=video.duracao_segundos,
                url=video.link,
                embed_url=video.embed_url,
                thumbnail_url=video.thumbnail_url,
                publicavel=video.publicavel,
                privacidade=f"{video.privacidade_view}/{video.privacidade_embed}",
                transcricao=video.transcricao_status,
                avisos=_avisos_do_video(video, inferido.numero),
            )
        )

    itens.sort(key=lambda item: (item.numero is None, item.numero or 0, item.titulo))
    return PlanoDeImportacao(pasta_id=str(pasta_id), pasta_nome=pasta.nome, itens=itens)


def distribuir(
    plano: PlanoDeImportacao, destinos: list[dict]
) -> tuple[list[dict], list[ItemDoPlano]]:
    """Casa cada vídeo com o destino cuja faixa contém o número dele.

    É o gesto que o professor faz em voz alta: "da 1 até a 14 é o K01, sub
    Questões da apostila; 15, 18, 22 e 25 são o K02". A faixa fala dos números
    da apostila, lidos do título — não da posição na lista.

    Um destino sem faixa recolhe o que sobrou, inclusive os vídeos cujo título
    não trouxe número legível. Sem nenhum destino assim, esses vídeos ficam de
    fora e a tool pergunta em vez de chutar.
    """
    if not destinos:
        raise RegraDeNegocio(
            "Informe ao menos um destino, ex.: faixa '1-14' para o módulo 'K01 - ...' "
            "e sub-módulo 'Questões da apostila'."
        )

    coringas = [d for d in destinos if not str(d.get("faixa") or "").strip()]
    if len(coringas) > 1:
        raise RegraDeNegocio("Só um destino pode ficar sem faixa — ele recolhe o que sobrar.")

    usados: set[str] = set()
    distribuicao: list[dict] = []

    for destino in destinos:
        texto = str(destino.get("faixa") or "").strip()
        if not texto:
            continue
        try:
            numeros = interpretar_faixa(texto)
        except ValueError as e:
            raise RegraDeNegocio(str(e)) from None

        escolhidos = [
            item
            for item in plano.itens
            if item.numero in numeros and item.vimeo_id not in usados
        ]
        usados.update(item.vimeo_id for item in escolhidos)
        faltando = sorted(numeros - {item.numero for item in escolhidos if item.numero})
        distribuicao.append({"destino": destino, "itens": escolhidos, "nao_encontrados": faltando})

    sobraram = [item for item in plano.itens if item.vimeo_id not in usados]
    if coringas:
        distribuicao.append({"destino": coringas[0], "itens": sobraram, "nao_encontrados": []})
        sobraram = []

    return distribuicao, sobraram
