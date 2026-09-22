"""Representações do Vimeo que a plataforma usa.

Os parsers são tolerantes de propósito: o payload real é validado na POC, e um
campo que venha faltando não pode derrubar uma importação de 3.000 vídeos — ele
vira `None` e aparece como aviso no preview.

A chave canônica é sempre o `uri` (`/videos/{id}`, `/users/{uid}/projects/{id}`).
Nunca o título: ver a seção 13 do MVP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# --- ajudantes de parsing -----------------------------------------------------


def id_do_uri(uri: str | None) -> str | None:
    """'/videos/12345' -> '12345'. O Vimeo devolve URIs, não ids soltos."""
    if not uri:
        return None
    return uri.rstrip("/").rsplit("/", 1)[-1] or None


def mergulhar(dados: Any, caminho: str) -> Any:
    """Lê um campo em notação de ponto, do jeito que o `fields` do Vimeo escreve."""
    atual = dados
    for parte in caminho.split("."):
        if not isinstance(atual, dict) or parte not in atual:
            return None
        atual = atual[parte]
    return atual


def data(valor: Any) -> datetime | None:
    """ISO 8601 do Vimeo (com Z) para datetime com fuso."""
    if not isinstance(valor, str) or not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None


def _inteiro(valor: Any) -> int | None:
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _uri_de(valor: Any) -> str | None:
    """Aceita tanto `{"uri": "..."}` quanto a string crua.

    `parent_project` é documentado como objeto, mas o formato exato só será
    conhecido na POC R6; aceitar as duas formas evita retrabalho.
    """
    if isinstance(valor, dict):
        return valor.get("uri")
    if isinstance(valor, str):
        return valor
    return None


# --- modelos ------------------------------------------------------------------


@dataclass(frozen=True)
class LimiteDeRequisicoes:
    """Retrato da cota, lido dos headers `X-RateLimit-*`."""

    limite: int | None = None
    restante: int | None = None
    reinicia_em: datetime | None = None

    @classmethod
    def de_cabecalhos(cls, cabecalhos: Any) -> LimiteDeRequisicoes | None:
        def ler(nome: str) -> str | None:
            try:
                return cabecalhos.get(nome)
            except AttributeError:
                return None

        limite = ler("X-RateLimit-Limit")
        restante = ler("X-RateLimit-Remaining")
        reinicio = ler("X-RateLimit-Reset")
        if limite is None and restante is None and reinicio is None:
            return None
        return cls(
            limite=_inteiro(limite),
            restante=_inteiro(restante),
            reinicia_em=data(reinicio),
        )


@dataclass(frozen=True)
class ContaVimeo:
    uri: str | None
    nome: str | None
    plano: Any = None
    tem_acesso_de_upload: bool = False

    @classmethod
    def de_payload(cls, dados: dict) -> ContaVimeo:
        return cls(
            uri=dados.get("uri"),
            nome=dados.get("name"),
            plano=dados.get("membership"),
            tem_acesso_de_upload=bool(dados.get("upload_quota")),
        )


@dataclass(frozen=True)
class PastaVimeo:
    uri: str | None
    id: str | None
    nome: str | None
    pai_uri: str | None = None
    ancestrais: tuple[str, ...] = ()
    tem_subpasta: bool = False
    total_videos: int | None = None
    total_videos_com_subpastas: int | None = None
    criada_em: datetime | None = None
    modificada_em: datetime | None = None

    @property
    def profundidade(self) -> int:
        """Quantos níveis acima desta pasta existem, conforme o `ancestor_path`."""
        return len(self.ancestrais)

    @classmethod
    def de_payload(cls, dados: dict) -> PastaVimeo:
        ancestrais = mergulhar(dados, "metadata.connections.ancestor_path") or []
        return cls(
            uri=dados.get("uri"),
            id=id_do_uri(dados.get("uri")),
            nome=dados.get("name"),
            pai_uri=_uri_de(mergulhar(dados, "metadata.connections.parent_folder")),
            ancestrais=tuple(
                item.get("uri") for item in ancestrais if isinstance(item, dict) and item.get("uri")
            ),
            tem_subpasta=bool(dados.get("has_subfolder")),
            total_videos=_inteiro(mergulhar(dados, "metadata.connections.videos.total")),
            total_videos_com_subpastas=_inteiro(
                mergulhar(dados, "metadata.connections.videos.deep_total")
            ),
            criada_em=data(dados.get("created_time")),
            modificada_em=data(dados.get("modified_time")),
        )


@dataclass(frozen=True)
class VideoVimeo:
    uri: str | None
    id: str | None
    nome: str | None
    descricao: str | None = None
    duracao_segundos: int | None = None
    link: str | None = None
    # Guardado como o Vimeo devolve: vídeo unlisted só toca com o hash `?h=`.
    embed_url: str | None = None
    thumbnail_base_link: str | None = None
    thumbnail_url: str | None = None
    status: str | None = None
    transcode_status: str | None = None
    reproduzivel: bool | None = None
    privacidade_view: str | None = None
    privacidade_embed: str | None = None
    transcricao_status: str | None = None
    transcricao_idioma: str | None = None
    pasta_uri: str | None = None
    versao_atual_uri: str | None = None
    resource_key: str | None = None
    criado_em: datetime | None = None
    modificado_em: datetime | None = None
    em_cold_storage: bool = False
    privacidade_suprimida: bool = False

    @property
    def publicavel(self) -> bool:
        """Regra da seção 24: aluno não recebe vídeo que ainda não está pronto."""
        return self.reproduzivel is True and self.status == "available"

    @classmethod
    def de_payload(cls, dados: dict) -> VideoVimeo:
        tamanhos = mergulhar(dados, "pictures.sizes") or []
        maior = tamanhos[-1] if isinstance(tamanhos, list) and tamanhos else None
        return cls(
            uri=dados.get("uri"),
            id=id_do_uri(dados.get("uri")),
            nome=dados.get("name"),
            descricao=dados.get("description"),
            duracao_segundos=_inteiro(dados.get("duration")),
            link=dados.get("link"),
            embed_url=dados.get("player_embed_url"),
            thumbnail_base_link=mergulhar(dados, "pictures.base_link"),
            thumbnail_url=maior.get("link") if isinstance(maior, dict) else None,
            status=dados.get("status"),
            transcode_status=mergulhar(dados, "transcode.status"),
            reproduzivel=dados.get("is_playable"),
            privacidade_view=mergulhar(dados, "privacy.view"),
            privacidade_embed=mergulhar(dados, "privacy.embed"),
            transcricao_status=mergulhar(dados, "transcript.status"),
            transcricao_idioma=mergulhar(dados, "transcript.language"),
            pasta_uri=_uri_de(dados.get("parent_project")),
            versao_atual_uri=mergulhar(dados, "metadata.connections.versions.current_uri"),
            resource_key=dados.get("resource_key"),
            criado_em=data(dados.get("created_time")),
            modificado_em=data(dados.get("modified_time")),
            em_cold_storage=bool(dados.get("is_cold_storage")),
            privacidade_suprimida=bool(dados.get("is_cold_privacy_restricted")),
        )


@dataclass(frozen=True)
class ItemDePasta:
    """Item de `/items`: pode ser pasta, vídeo, showcase ou evento ao vivo."""

    tipo: str | None
    pasta: PastaVimeo | None = None
    video: VideoVimeo | None = None

    @classmethod
    def de_payload(cls, dados: dict) -> ItemDePasta:
        tipo = dados.get("type")
        bruto_pasta = dados.get("folder")
        bruto_video = dados.get("video")
        return cls(
            tipo=tipo,
            pasta=PastaVimeo.de_payload(bruto_pasta) if isinstance(bruto_pasta, dict) else None,
            video=VideoVimeo.de_payload(bruto_video) if isinstance(bruto_video, dict) else None,
        )


@dataclass(frozen=True)
class VersaoVimeo:
    uri: str | None
    arquivo_nome: str | None = None
    arquivo_tamanho: int | None = None
    duracao_segundos: int | None = None
    ativa: bool = False
    enviada_em: datetime | None = None
    transcode_status: str | None = None

    @classmethod
    def de_payload(cls, dados: dict) -> VersaoVimeo:
        return cls(
            uri=dados.get("uri"),
            arquivo_nome=dados.get("filename"),
            arquivo_tamanho=_inteiro(dados.get("filesize")),
            duracao_segundos=_inteiro(dados.get("duration")),
            ativa=bool(dados.get("active")),
            enviada_em=data(dados.get("upload_date")),
            transcode_status=mergulhar(dados, "transcode.status"),
        )


@dataclass(frozen=True)
class FaixaDeTexto:
    id: int | None
    tipo: str | None = None
    idioma: str | None = None
    idioma_exibicao: str | None = None
    origem: str | None = None
    ativa: bool = False
    link: str | None = None
    link_vtt: str | None = None
    link_srt: str | None = None
    links_expiram_em: datetime | None = None

    @property
    def gerada_automaticamente(self) -> bool:
        return bool(self.origem) and self.origem.startswith("autogen")

    @classmethod
    def de_payload(cls, dados: dict) -> FaixaDeTexto:
        return cls(
            id=_inteiro(dados.get("id")),
            tipo=dados.get("type"),
            idioma=dados.get("language"),
            idioma_exibicao=dados.get("display_language"),
            origem=dados.get("provenance"),
            ativa=bool(dados.get("active")),
            link=dados.get("link"),
            link_vtt=mergulhar(dados, "download_links.vtt"),
            link_srt=mergulhar(dados, "download_links.srt"),
            links_expiram_em=data(dados.get("download_links_expires_time")),
        )


@dataclass(frozen=True)
class ThumbnailVimeo:
    uri: str | None
    ativa: bool = False
    tipo: str | None = None
    base_link: str | None = None
    tamanhos: tuple[dict, ...] = field(default_factory=tuple)

    def maior_link(self) -> str | None:
        return self.tamanhos[-1].get("link") if self.tamanhos else None

    @classmethod
    def de_payload(cls, dados: dict) -> ThumbnailVimeo:
        tamanhos = dados.get("sizes") or []
        return cls(
            uri=dados.get("uri"),
            ativa=bool(dados.get("active")),
            tipo=dados.get("type"),
            base_link=dados.get("base_link"),
            tamanhos=tuple(t for t in tamanhos if isinstance(t, dict)),
        )
