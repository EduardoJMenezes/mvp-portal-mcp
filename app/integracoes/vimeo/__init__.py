"""Integração com a API REST do Vimeo (versão 3.4).

A pesquisa que sustenta as decisões deste pacote está em
`docs/vimeo-integracao/`: a matriz de capacidades diz o que a API entrega, e o
documento de gaps diz onde ela não entrega e o que fazemos no lugar.

Fase 1 (leitura) é o que existe aqui. Escrita e upload entram depois da POC na
conta real, em módulos separados, porque exigem token com outros escopos.
"""

from app.integracoes.vimeo.campos import (
    CAMPOS_CONTA,
    CAMPOS_FAIXA_DE_TEXTO,
    CAMPOS_ITEM_DE_PASTA,
    CAMPOS_PASTA,
    CAMPOS_VERSAO,
    CAMPOS_VIDEO_IMPORTACAO,
    CAMPOS_VIDEO_SYNC,
)
from app.integracoes.vimeo.erros import (
    VimeoConflitoDeOffset,
    VimeoCredencialInvalida,
    VimeoErro,
    VimeoIndisponivel,
    VimeoLimiteDeRequisicoes,
    VimeoNaoEncontrado,
    VimeoParametroInvalido,
    VimeoRotaBloqueada,
    VimeoSemPermissao,
)
from app.integracoes.vimeo.leitura import ClienteVimeoLeitura, NoDaArvore
from app.integracoes.vimeo.modelos import (
    ContaVimeo,
    FaixaDeTexto,
    ItemDePasta,
    LimiteDeRequisicoes,
    PastaVimeo,
    ThumbnailVimeo,
    VersaoVimeo,
    VideoVimeo,
)
from app.integracoes.vimeo.transporte import TransporteVimeo

__all__ = [
    "CAMPOS_CONTA",
    "CAMPOS_FAIXA_DE_TEXTO",
    "CAMPOS_ITEM_DE_PASTA",
    "CAMPOS_PASTA",
    "CAMPOS_VERSAO",
    "CAMPOS_VIDEO_IMPORTACAO",
    "CAMPOS_VIDEO_SYNC",
    "ClienteVimeoLeitura",
    "ContaVimeo",
    "FaixaDeTexto",
    "ItemDePasta",
    "LimiteDeRequisicoes",
    "NoDaArvore",
    "PastaVimeo",
    "ThumbnailVimeo",
    "TransporteVimeo",
    "VersaoVimeo",
    "VideoVimeo",
    "VimeoConflitoDeOffset",
    "VimeoCredencialInvalida",
    "VimeoErro",
    "VimeoIndisponivel",
    "VimeoLimiteDeRequisicoes",
    "VimeoNaoEncontrado",
    "VimeoParametroInvalido",
    "VimeoRotaBloqueada",
    "VimeoSemPermissao",
]
