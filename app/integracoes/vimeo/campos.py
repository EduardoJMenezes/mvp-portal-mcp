"""Conjuntos de `fields` por caso de uso.

Todo GET manda `fields`. Não é só economia de payload: o guia oficial de rate
limit diz que usar filtro de campos dobra a cota de requisições por minuto.

A lista foi montada a partir da referência da API 3.4.9 e é validada contra a
conta real nos passos R4 e R8 da POC.
"""

CAMPOS_CONTA = "uri,name,membership,upload_quota"

CAMPOS_PASTA = (
    "uri,name,created_time,modified_time,has_subfolder,"
    "metadata.connections.parent_folder,metadata.connections.ancestor_path,"
    "metadata.connections.videos.total,metadata.connections.videos.deep_total,"
    "metadata.connections.folders.total"
)

# A sintaxe aninhada (`folder.`, `video.`) é confirmada na POC R4.
CAMPOS_ITEM_DE_PASTA = (
    "type,folder.uri,folder.name,folder.has_subfolder,"
    "folder.metadata.connections.videos.total,"
    "folder.metadata.connections.videos.deep_total,"
    "video.uri,video.name,video.duration"
)

CAMPOS_VIDEO_IMPORTACAO = (
    "uri,name,description,duration,link,player_embed_url,pictures.base_link,"
    "pictures.sizes,status,transcode.status,is_playable,privacy.view,privacy.embed,"
    "transcript.status,transcript.language,parent_project,resource_key,"
    "created_time,modified_time,is_cold_storage,is_cold_privacy_restricted,"
    "metadata.connections.versions.current_uri"
)

CAMPOS_VIDEO_SYNC = (
    "uri,name,duration,pictures.base_link,status,transcode.status,is_playable,"
    "privacy.view,privacy.embed,transcript.status,modified_time,"
    "is_cold_storage,is_cold_privacy_restricted,"
    "metadata.connections.versions.current_uri"
)

CAMPOS_VERSAO = "uri,filename,filesize,duration,active,upload_date,transcode.status"

CAMPOS_FAIXA_DE_TEXTO = (
    "id,type,language,display_language,provenance,active,link,link_expires_time,"
    "download_links,download_links_expires_time"
)

CAMPOS_THUMBNAIL = "uri,active,type,base_link,sizes"
