"""Acesso ao Vimeo.

Existe um MCP oficial do Vimeo (beta, plano Pro ou superior), mas ele não entra
no produto: quem fala com o Vimeo é o backend, pela API REST oficial — que é a
alternativa prevista na seção 8 do MVP. O porquê está em docs/VIMEO.md e a
pesquisa completa da API em docs/vimeo-integracao/. O agente chega ao acervo
pelas nossas tools.

Duas implementações atrás da mesma interface: a real (`VimeoAPI`) e um acervo
de demonstração (`VimeoDemo`), usado enquanto não há token. Trocar uma pela
outra é só preencher VIMEO_ACCESS_TOKEN no .env.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.config import get_settings
from app.errors import RegraDeNegocio

_VERSAO_API = "application/vnd.vimeo.*+json;version=3.4"


@dataclass
class PastaVimeo:
    id: str
    nome: str
    total_videos: int | None = None


@dataclass
class VideoVimeo:
    id: str
    titulo: str
    url: str | None = None
    thumbnail_url: str | None = None
    duracao_segundos: int | None = None
    pasta: str | None = None
    descricao: str | None = None
    # URL de embed COMO O VIMEO DEVOLVE. Vídeo unlisted só toca com o hash de
    # privacidade (`?h=...`) que vem aqui dentro; montar a URL a partir do id
    # resulta em "This video does not exist" no player.
    embed_url: str | None = None


class ClienteVimeo(Protocol):
    async def listar_pastas(self) -> list[PastaVimeo]: ...

    async def listar_videos(
        self, pasta_id: str | None = None, busca: str | None = None, limite: int = 25
    ) -> list[VideoVimeo]: ...


# --- implementação real ------------------------------------------------------


def _id_do_uri(uri: str) -> str:
    """'/videos/12345' -> '12345'. O Vimeo devolve URIs, não ids soltos."""
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _melhor_thumb(video: dict) -> str | None:
    tamanhos = (video.get("pictures") or {}).get("sizes") or []
    return tamanhos[-1]["link"] if tamanhos else None


def _para_video(bruto: dict, pasta: str | None = None) -> VideoVimeo:
    return VideoVimeo(
        id=_id_do_uri(bruto.get("uri", "")),
        titulo=bruto.get("name") or "(sem título)",
        url=bruto.get("link"),
        thumbnail_url=_melhor_thumb(bruto),
        duracao_segundos=bruto.get("duration"),
        pasta=pasta,
        descricao=bruto.get("description"),
        embed_url=bruto.get("player_embed_url"),
    )


# Pedir campos explicitamente encolhe a resposta e garante que
# `player_embed_url` venha — sem ele não há como exibir vídeo unlisted.
CAMPOS_VIDEO = "uri,name,link,duration,description,pictures.sizes,player_embed_url,privacy.embed"


class VimeoAPI:
    """Cliente da API REST do Vimeo (somente leitura, que é o que a POC usa)."""

    def __init__(self, token: str, base_url: str) -> None:
        self._token = token
        self._base = base_url.rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base,
            headers={"Authorization": f"Bearer {self._token}", "Accept": _VERSAO_API},
            timeout=20.0,
        )

    async def _get(self, cli: httpx.AsyncClient, caminho: str, **params) -> dict:
        try:
            resp = await cli.get(caminho, params=params or None)
        except httpx.RequestError as e:
            # Filtro de DNS corporativo cai aqui: o host resolve para a página
            # de bloqueio e o TLS falha. Sem esta mensagem, o professor vê um
            # traceback de SSL no meio da demonstração.
            raise RegraDeNegocio(
                f"Não foi possível falar com {self._base} ({type(e).__name__}). "
                "Verifique se a rede libera api.vimeo.com — filtros corporativos "
                "costumam bloquear o domínio."
            ) from e

        if resp.status_code == 401:
            raise RegraDeNegocio(
                "Vimeo recusou o token (401). Confira VIMEO_ACCESS_TOKEN e o escopo "
                "'private', necessário para ler pastas e vídeos não públicos."
            )
        if resp.status_code == 403 and "application/json" not in (
            resp.headers.get("content-type") or ""
        ):
            # 403 em HTML não vem do Vimeo: é um proxy/filtro respondendo no
            # lugar dele.
            raise RegraDeNegocio(
                f"A requisição para {self._base} foi barrada por um filtro de rede "
                "(resposta 403 em HTML, não da API do Vimeo). Libere api.vimeo.com "
                "ou rode a demonstração em outra rede."
            )

        resp.raise_for_status()
        return resp.json()

    async def listar_pastas(self) -> list[PastaVimeo]:
        async with self._client() as cli:
            # /me/folders é o nome atual; /me/projects é o legado, ainda de pé
            # em contas antigas. Tentamos o atual e caímos no legado no 404.
            try:
                dados = await self._get(cli, "/me/folders", per_page=100)
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 404:
                    raise
                dados = await self._get(cli, "/me/projects", per_page=100)
            itens = list(dados.get("data", []))
            # O acervo passa de 100 pastas: segue as páginas até o fim.
            while proxima := (dados.get("paging") or {}).get("next"):
                dados = await self._get(cli, proxima)
                itens += dados.get("data", [])

        return [
            PastaVimeo(
                id=_id_do_uri(p.get("uri", "")),
                nome=p.get("name") or "(sem nome)",
                total_videos=(p.get("metadata", {}).get("connections", {}).get("videos", {}) or {}).get(
                    "total"
                ),
            )
            for p in itens
        ]

    async def listar_videos(
        self, pasta_id: str | None = None, busca: str | None = None, limite: int = 25
    ) -> list[VideoVimeo]:
        nome_pasta = None
        async with self._client() as cli:
            if pasta_id:
                pastas = await self.listar_pastas()
                alvo = next((p for p in pastas if p.id == pasta_id), None)
                if alvo is None and not pasta_id.isdigit():
                    # Quem chama é um LLM e costuma passar o nome; nomes se repetem no acervo.
                    mesmas = [p for p in pastas if p.nome.lower() == pasta_id.strip().lower()]
                    if len(mesmas) != 1:
                        raise RegraDeNegocio(
                            f"Há {len(mesmas)} pastas chamadas '{pasta_id}' no Vimeo: passe o id "
                            f"({', '.join(p.id for p in mesmas)})."
                            if mesmas
                            else f"Não há pasta '{pasta_id}' no Vimeo. Veja nomes e ids em listar_pastas_vimeo."
                        )
                    alvo = mesmas[0]
                if alvo is not None:
                    pasta_id, nome_pasta = alvo.id, alvo.nome
                caminho = f"/me/folders/{pasta_id}/videos"
                try:
                    dados = await self._get(
                        cli, caminho, per_page=limite, query=busca, fields=CAMPOS_VIDEO
                    )
                except httpx.HTTPStatusError as e:
                    if e.response.status_code != 404:
                        raise
                    dados = await self._get(
                        cli, f"/me/projects/{pasta_id}/videos", per_page=limite, query=busca,
                        fields=CAMPOS_VIDEO,
                    )
            else:
                dados = await self._get(
                    cli, "/me/videos", per_page=limite, query=busca, fields=CAMPOS_VIDEO
                )

        return [_para_video(v, nome_pasta) for v in dados.get("data", [])]


# --- acervo de demonstração --------------------------------------------------


def _demo(pasta: str, ids: list[tuple[str, str]]) -> list[VideoVimeo]:
    return [
        VideoVimeo(
            id=vid,
            titulo=titulo,
            url=f"https://vimeo.com/{vid}",
            thumbnail_url=None,
            duracao_segundos=300 + i * 37,
            pasta=pasta,
            descricao=f"Resolução em vídeo — {titulo}",
            embed_url=f"https://player.vimeo.com/video/{vid}",
        )
        for i, (vid, titulo) in enumerate(ids)
    ]


@dataclass
class VimeoDemo:
    """Acervo fixo, no formato exato da API, para a POC rodar sem credencial.

    Os títulos seguem o padrão do acervo real (capítulo + número da questão),
    porque é isso que o agente lê para propor o cadastro.
    """

    pastas: dict[str, list[VideoVimeo]] = field(
        default_factory=lambda: {
            "Atomística": _demo(
                "Atomística",
                [
                    ("910000101", "Atomística — Questão 01 — Modelo de Rutherford"),
                    ("910000102", "Atomística — Questão 02 — Distribuição eletrônica"),
                    ("910000103", "Atomística — Questão 03 — Isótopos e isóbaros"),
                ],
            ),
            "Estequiometria": _demo(
                "Estequiometria",
                [
                    ("920000201", "Estequiometria — Questão 01 — Balanceamento"),
                    ("920000202", "Estequiometria — Questão 02 — Mol e massa molar"),
                    ("920000203", "Estequiometria — Questão 03 — Reagente limitante"),
                    ("920000204", "Estequiometria — Questão 04 — Rendimento de reação"),
                    ("920000205", "Estequiometria — Questão 05 — Pureza de reagentes"),
                ],
            ),
            "Cinética": _demo(
                "Cinética",
                [
                    ("930000301", "Cinética — Questão 01 — Velocidade média"),
                    ("930000302", "Cinética — Questão 02 — Fatores que alteram a velocidade"),
                    ("930000303", "Cinética — Questão 03 — Energia de ativação"),
                ],
            ),
        }
    )

    async def listar_pastas(self) -> list[PastaVimeo]:
        return [
            PastaVimeo(id=f"demo-{i}", nome=nome, total_videos=len(vs))
            for i, (nome, vs) in enumerate(self.pastas.items(), start=1)
        ]

    async def listar_videos(
        self, pasta_id: str | None = None, busca: str | None = None, limite: int = 25
    ) -> list[VideoVimeo]:
        if pasta_id:
            pastas = await self.listar_pastas()
            alvo = next((p.nome for p in pastas if p.id == pasta_id), None)
            if alvo is None:
                # Cliente que passa o nome da pasta em vez do id é caso comum
                # quando quem chama é um LLM; aceitar os dois evita um
                # round-trip inteiro só para descobrir o id.
                alvo = next((n for n in self.pastas if n.lower() == pasta_id.lower()), None)
            videos = self.pastas.get(alvo, []) if alvo else []
        else:
            videos = [v for vs in self.pastas.values() for v in vs]

        if busca:
            termo = busca.lower()
            videos = [v for v in videos if termo in v.titulo.lower()]
        return videos[:limite]


def get_cliente_vimeo() -> ClienteVimeo:
    s = get_settings()
    if s.vimeo_real:
        return VimeoAPI(s.vimeo_access_token, s.vimeo_api_base)
    return VimeoDemo()
