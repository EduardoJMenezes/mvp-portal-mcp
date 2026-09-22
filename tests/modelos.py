"""Espelho SQLAlchemy do schema, SÓ para semear os testes.

O app não importa este módulo: o adaptador não tem banco. A fonte de verdade
do schema é a V1 do Flyway, no repositório da API.

Modelo de dados da POC (seção 18 do MVP).

Quatro decisões que valem explicação. As três primeiras vêm de
[docs/MODELO-CONTEUDO.md](../../docs/MODELO-CONTEUDO.md), escrito antes deste
código:

1. **O conteúdo do curso é vídeo, organizado em módulo › sub-módulo › item.**
   `Questao` — enunciado, alternativas, gabarito — existe só para o simulado.
   A questão da apostila mora na apostila; aqui fica o vídeo da resolução dela.

2. **Organização é da turma; acervo e taxonomia são globais.** `Modulo`
   pertence a uma `Turma` e carrega o "K01"; `Video`, `Questao` e `Assunto`
   atravessam turmas e anos. É por isso que o nome de um assunto nunca leva
   numeração de capítulo: K03 é Estequiometria em 2026 e Tabela Periódica em
   2025, e uma etiqueta presa a um ano não etiqueta nada.

3. **Nada é apagado.** Remoção é `removido_em` preenchido. Em troca, toda
   consulta precisa filtrar — ver `services/consultas.py`, que existe para que
   esse filtro não seja escrito à mão em cada lugar.

4. `Rascunho` é uma entidade de primeira classe. Tudo que a IA cria nasce
   apontando para um rascunho, e a publicação é uma transição desse rascunho —
   não de cada linha solta. É o que faz `publicar_rascunho(id)` ser uma
   operação atômica e auditável.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- vocabulário fechado do domínio -----------------------------------------


class Papel:
    ADMIN = "ADMIN"
    GERENCIADOR = "GERENCIADOR"
    ALUNO = "ALUNO"

    TODOS = (ADMIN, GERENCIADOR, ALUNO)
    # Quem pode operar o MCP administrativo (seção 4).
    OPERADORES = (ADMIN, GERENCIADOR)


class Status:
    RASCUNHO = "RASCUNHO"
    PUBLICADO = "PUBLICADO"


class TipoRascunho:
    ITENS = "ITENS"
    QUESTOES = "QUESTOES"
    SIMULADO = "SIMULADO"


class TipoSubModulo:
    """O que o sub-módulo guarda. Um sub-módulo é de um tipo só.

    Hoje existe VIDEO. TEXTO e PDF estão aqui para dizer que a estrutura os
    comporta — quando entrarem, o item ganha a coluna correspondente.
    """

    VIDEO = "VIDEO"

    TODOS = (VIDEO,)


class ParteDaQuestao:
    """Onde a figura aparece — e, por isso, quando o aluno pode vê-la."""

    ENUNCIADO = "ENUNCIADO"
    ALTERNATIVA = "ALTERNATIVA"
    RESOLUCAO = "RESOLUCAO"

    TODAS = (ENUNCIADO, ALTERNATIVA, RESOLUCAO)


class Dificuldade:
    FACIL = "FACIL"
    MEDIA = "MEDIA"
    DIFICIL = "DIFICIL"

    TODAS = (FACIL, MEDIA, DIFICIL)


LETRAS = ("A", "B", "C", "D", "E")


def _agora() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _vivo(nome: str, *colunas: str) -> Index:
    """Unicidade que só vale entre os não removidos.

    Com remoção lógica, um `unique` comum tornaria o nome de um módulo
    removido impossível de reutilizar para sempre. O índice parcial resolve:
    duas linhas podem repetir o nome desde que uma delas esteja removida.
    """
    return Index(nome, *colunas, unique=True, postgresql_where=text("removido_em IS NULL"))


class Rastreavel:
    """Quem mexeu por último, quando, e se está removido.

    Editar e remover são operações diretas (não nascem como rascunho), então
    é esta linha que guarda o rastro — em vez de uma tabela de auditoria, que
    a §20 deixou fora do escopo.
    """

    alterado_por_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    alterado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def removido(self) -> bool:
        return self.removido_em is not None


# --- pessoas e turmas --------------------------------------------------------


class Usuario(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    papel: Mapped[str] = mapped_column(String(20), nullable=False)
    criado_em: Mapped[datetime] = _agora()
    # Senha que outra pessoa definiu (o professor cadastrando ou redefinindo):
    # até o dono trocar, a sessão só serve para trocar a senha.
    senha_temporaria: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Sessão emitida antes deste instante deixa de valer: trocar a senha
    # derruba quem entrou com a antiga.
    senha_alterada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("papel in ('ADMIN','GERENCIADOR','ALUNO')", name="ck_users_papel"),
    )

    matriculas: Mapped[list[Matricula]] = relationship(back_populates="aluno")

    @property
    def opera_mcp(self) -> bool:
        return self.papel in Papel.OPERADORES


class Turma(Base, Rastreavel):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    ano: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (_vivo("uq_turma_nome", "nome"),)

    matriculas: Mapped[list[Matricula]] = relationship(back_populates="turma")
    modulos: Mapped[list[Modulo]] = relationship(back_populates="turma", order_by="Modulo.ordem")


class Matricula(Base):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    turma_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    criado_em: Mapped[datetime] = _agora()

    __table_args__ = (UniqueConstraint("usuario_id", "turma_id", name="uq_matricula"),)

    aluno: Mapped[Usuario] = relationship(back_populates="matriculas")
    turma: Mapped[Turma] = relationship(back_populates="matriculas")


# --- acervo ------------------------------------------------------------------


class Video(Base, Rastreavel):
    """Espelho local do mínimo necessário para exibir/relacionar um vídeo.

    O vídeo continua morando no Vimeo; aqui guardamos só o id e os metadados
    que a plataforma precisa (seção 3).
    """

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identidade externa, não nome editável: `unique` comum mesmo. Reimportar
    # um vídeo removido reativa o registro em vez de criar outro.
    vimeo_id: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str | None] = mapped_column(String(400))
    # Guardada como o Vimeo devolveu: para vídeo unlisted ela traz o hash de
    # privacidade, sem o qual o player recusa tocar. Nunca sai do backend para
    # quem não tem acesso — ver `services/acesso.py`.
    embed_url: Mapped[str | None] = mapped_column(String(400))
    thumbnail_url: Mapped[str | None] = mapped_column(String(400))
    duracao_segundos: Mapped[int | None] = mapped_column(Integer)
    pasta_vimeo: Mapped[str | None] = mapped_column(String(200))
    criado_em: Mapped[datetime] = _agora()

    assuntos: Mapped[list[VideoAssunto]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )


class Imagem(Base):
    """Figura de uma questão: no enunciado, numa alternativa ou na resolução.

    O texto aponta para ela no lugar exato onde aparece — `![](figura:123)` —,
    e é assim que uma questão tem quantas figuras precisar. `parte` decide
    quando o aluno pode vê-la: a da resolução só depois que o simulado fecha.

    ponytail: bytes no próprio Postgres. Serve para a POC; com volume, vira
    bucket e esta tabela guarda só a chave.
    """

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True)
    conteudo: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    nome: Mapped[str | None] = mapped_column(String(200))
    # Vazio enquanto a figura veio de uma importação e ainda não tem questão.
    questao_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"))
    parte: Mapped[str | None] = mapped_column(String(20))
    criado_em: Mapped[datetime] = _agora()


class Questao(Base, Rastreavel):
    """Questão de simulado: enunciado, alternativas e gabarito.

    **Não** é a questão da apostila — essa mora na apostila, e o que a
    plataforma guarda dela é o vídeo da resolução, como item de sub-módulo.

    Enunciado, alternativas e resolução comentada são texto formatado
    (Markdown, fórmulas em LaTeX), com as figuras referenciadas no ponto onde
    aparecem. A figura que ainda não chegou vira `imagem_pendente`, e o
    simulado não publica enquanto ela não for anexada.
    """

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    enunciado: Mapped[str] = mapped_column(Text, nullable=False)
    gabarito: Mapped[str] = mapped_column(String(1), nullable=False)
    dificuldade: Mapped[str] = mapped_column(String(10), nullable=False, default=Dificuldade.MEDIA)
    imagem_pendente: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # A resolução escrita, que o aluno lê com o gabarito depois do fechamento.
    resolucao_comentada: Mapped[str | None] = mapped_column(Text)
    # Vídeo da resolução desta questão, quando houver.
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=Status.RASCUNHO)
    rascunho_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"))
    criado_por_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    criado_em: Mapped[datetime] = _agora()

    __table_args__ = (
        CheckConstraint("gabarito in ('A','B','C','D','E')", name="ck_questions_gabarito"),
        CheckConstraint("status in ('RASCUNHO','PUBLICADO')", name="ck_questions_status"),
        CheckConstraint(
            "dificuldade in ('FACIL','MEDIA','DIFICIL')", name="ck_questions_dificuldade"
        ),
    )

    alternativas: Mapped[list[Alternativa]] = relationship(
        back_populates="questao", cascade="all, delete-orphan", order_by="Alternativa.letra"
    )
    assuntos: Mapped[list[QuestaoAssunto]] = relationship(
        back_populates="questao", cascade="all, delete-orphan"
    )
    video: Mapped[Video | None] = relationship()


class Alternativa(Base):
    __tablename__ = "question_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    questao_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    letra: Mapped[str] = mapped_column(String(1), nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("questao_id", "letra", name="uq_alternativa"),
        CheckConstraint("letra in ('A','B','C','D','E')", name="ck_options_letra"),
    )

    questao: Mapped[Questao] = relationship(back_populates="alternativas")


# --- taxonomia ---------------------------------------------------------------


class Assunto(Base, Rastreavel):
    """Do que o conteúdo trata — a etiqueta, não o endereço.

    Global de propósito: o mesmo assunto vale para 2025, 2026 e 2027. Por isso
    o nome **nunca** carrega numeração de capítulo ("Estequiometria", não
    "K03 - Estequiometria"): K03 é a posição na apostila de uma turma, e
    apostilas mudam de um ano para o outro.
    """

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    criado_em: Mapped[datetime] = _agora()

    __table_args__ = (_vivo("uq_assunto_nome", "nome"),)

    subassuntos: Mapped[list[SubAssunto]] = relationship(
        back_populates="assunto", order_by="SubAssunto.nome"
    )


class SubAssunto(Base, Rastreavel):
    __tablename__ = "subtopics"

    id: Mapped[int] = mapped_column(primary_key=True)
    assunto_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    criado_em: Mapped[datetime] = _agora()

    __table_args__ = (_vivo("uq_subassunto_nome", "assunto_id", "nome"),)

    assunto: Mapped[Assunto] = relationship(back_populates="subassuntos")


class VideoAssunto(Base):
    """Etiqueta de um vídeo. `subassunto_id` vazio = classificado só no nível
    do assunto, que é o suficiente para a recomendação grossa."""

    __tablename__ = "video_subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False)
    assunto_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    subassunto_id: Mapped[int | None] = mapped_column(ForeignKey("subtopics.id"))

    __table_args__ = (
        UniqueConstraint("video_id", "assunto_id", "subassunto_id", name="uq_video_assunto"),
    )

    video: Mapped[Video] = relationship(back_populates="assuntos")
    assunto: Mapped[Assunto] = relationship()
    subassunto: Mapped[SubAssunto | None] = relationship()


class QuestaoAssunto(Base):
    """A mesma etiqueta na questão de simulado. É o que liga o erro do aluno
    ao vídeo que explica aquilo — os dois lados usam a mesma taxonomia."""

    __tablename__ = "question_subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    questao_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    assunto_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    subassunto_id: Mapped[int | None] = mapped_column(ForeignKey("subtopics.id"))

    __table_args__ = (
        UniqueConstraint("questao_id", "assunto_id", "subassunto_id", name="uq_questao_assunto"),
    )

    questao: Mapped[Questao] = relationship(back_populates="assuntos")
    assunto: Mapped[Assunto] = relationship()
    subassunto: Mapped[SubAssunto | None] = relationship()


# --- organização do curso ----------------------------------------------------


class Modulo(Base, Rastreavel):
    """O capítulo como a turma o enxerga: "K01 - Introdução à química orgânica".

    Pertence a uma turma justamente porque a numeração é da apostila dela. Não
    tem `status`: o módulo aparece para o aluno quando tem item publicado
    dentro, e some quando não tem. Assim não existe o estado contraditório de
    módulo oculto com item publicado.
    """

    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    turma_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criado_em: Mapped[datetime] = _agora()

    __table_args__ = (_vivo("uq_modulo_nome", "turma_id", "nome"),)

    turma: Mapped[Turma] = relationship(back_populates="modulos")
    submodulos: Mapped[list[SubModulo]] = relationship(
        back_populates="modulo", order_by="SubModulo.ordem"
    )


class SubModulo(Base, Rastreavel):
    """A seção dentro do módulo: "Aulas", "Questões da apostila".

    O nome é do professor; o `tipo` é do sistema, e diz ao portal como
    renderizar a lista. Um sub-módulo é de um tipo só — nada de PDF no meio
    dos vídeos.
    """

    __tablename__ = "submodules"

    id: Mapped[int] = mapped_column(primary_key=True)
    modulo_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default=TipoSubModulo.VIDEO)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criado_em: Mapped[datetime] = _agora()

    __table_args__ = (
        CheckConstraint("tipo in ('VIDEO')", name="ck_submodules_tipo"),
        _vivo("uq_submodulo_nome", "modulo_id", "nome"),
    )

    modulo: Mapped[Modulo] = relationship(back_populates="submodulos")
    itens: Mapped[list[Item]] = relationship(back_populates="submodulo", order_by="Item.ordem")


class Item(Base, Rastreavel):
    """Uma linha na lista do aluno — hoje, sempre um vídeo.

    `nome` é a identidade editorial ("Q04", "Aula 1 — cadeias carbônicas") e
    `ordem` é a posição na tela. São coisas diferentes de propósito: o
    `TurmaQuestao.numero` de antes acumulava as duas e impedia exibir a Q52
    antes da Q04.

    É esta linha que o aluno enxerga, e é nela que vive o `status`: publicar é
    item a item, com uma tool de lote para quando forem vinte e um de uma vez.
    """

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    submodulo_id: Mapped[int] = mapped_column(ForeignKey("submodules.id"), nullable=False)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False)
    nome: Mapped[str] = mapped_column(String(300), nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=Status.RASCUNHO)
    rascunho_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"))
    criado_em: Mapped[datetime] = _agora()

    __table_args__ = (
        CheckConstraint("status in ('RASCUNHO','PUBLICADO')", name="ck_items_status"),
        _vivo("uq_item_video", "submodulo_id", "video_id"),
    )

    submodulo: Mapped[SubModulo] = relationship(back_populates="itens")
    video: Mapped[Video] = relationship()


# --- rascunho ----------------------------------------------------------------


class Rascunho(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    turma_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    submodulo_id: Mapped[int | None] = mapped_column(ForeignKey("submodules.id"))
    resumo: Mapped[str] = mapped_column(Text, nullable=False)
    origem: Mapped[str] = mapped_column(String(40), nullable=False, default="MCP")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=Status.RASCUNHO)

    criado_por_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    criado_em: Mapped[datetime] = _agora()

    # A aprovação humana mora aqui, e é ela que `services/publicacao.py`
    # exige antes de publicar. Não é uma checagem no cliente: é estado no
    # banco, verificado a cada publicação.
    aprovado_por_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    aprovado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aprovado_via: Mapped[str | None] = mapped_column(String(40))
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("tipo in ('ITENS','QUESTOES','SIMULADO')", name="ck_drafts_tipo"),
        CheckConstraint("status in ('RASCUNHO','PUBLICADO')", name="ck_drafts_status"),
    )

    turma: Mapped[Turma | None] = relationship()
    submodulo: Mapped[SubModulo | None] = relationship()
    criado_por: Mapped[Usuario] = relationship(foreign_keys=[criado_por_id])
    aprovado_por: Mapped[Usuario | None] = relationship(foreign_keys=[aprovado_por_id])


# --- simulados ---------------------------------------------------------------


class Simulado(Base, Rastreavel):
    """A prova: uma janela só (`abre_em` → `fecha_em`) e um tempo de prova.

    Vale para uma ou mais turmas, com um ranking só entre os participantes de
    todas elas. A agenda é opcional no rascunho e obrigatória para publicar.
    """

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    abre_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duracao_minutos: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=Status.RASCUNHO)
    rascunho_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"))
    criado_por_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    criado_em: Mapped[datetime] = _agora()
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("status in ('RASCUNHO','PUBLICADO')", name="ck_exams_status"),)

    turmas: Mapped[list[Turma]] = relationship(secondary="exam_classes", order_by="Turma.nome")
    questoes: Mapped[list[SimuladoQuestao]] = relationship(
        back_populates="simulado", cascade="all, delete-orphan", order_by="SimuladoQuestao.ordem"
    )


class SimuladoTurma(Base):
    __tablename__ = "exam_classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    simulado_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), nullable=False)
    turma_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)

    __table_args__ = (UniqueConstraint("simulado_id", "turma_id", name="uq_simulado_turma"),)


class SimuladoQuestao(Base):
    __tablename__ = "exam_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    simulado_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), nullable=False)
    questao_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("simulado_id", "questao_id", name="uq_simulado_questao"),)

    simulado: Mapped[Simulado] = relationship(back_populates="questoes")
    questao: Mapped[Questao] = relationship()


class Tentativa(Base):
    """A prova de um aluno. Existir já é "ter feito": entra no ranking.

    `prazo_em` é o que vier primeiro entre início + duração e o fechamento do
    simulado. Passou do prazo sem entregar, a entrega é automática — decidida
    na próxima consulta, sem job agendado.
    """

    __tablename__ = "exam_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    simulado_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), nullable=False)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    iniciado_em: Mapped[datetime] = _agora()
    prazo_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entregue_automaticamente: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (UniqueConstraint("simulado_id", "aluno_id", name="uq_tentativa"),)

    simulado: Mapped[Simulado] = relationship()
    aluno: Mapped[Usuario] = relationship()
    respostas: Mapped[list[Resposta]] = relationship(
        back_populates="tentativa", cascade="all, delete-orphan"
    )


class Resposta(Base):
    __tablename__ = "exam_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    tentativa_id: Mapped[int] = mapped_column(ForeignKey("exam_attempts.id"), nullable=False)
    questao_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    alternativa_marcada: Mapped[str] = mapped_column(String(1), nullable=False)
    correta: Mapped[bool] = mapped_column(Boolean, nullable=False)
    respondido_em: Mapped[datetime] = _agora()

    __table_args__ = (
        UniqueConstraint("tentativa_id", "questao_id", name="uq_resposta"),
        CheckConstraint(
            "alternativa_marcada in ('A','B','C','D','E')", name="ck_answers_alternativa"
        ),
    )

    tentativa: Mapped[Tentativa] = relationship(back_populates="respostas")
    questao: Mapped[Questao] = relationship()


# --- importação de .docx -----------------------------------------------------


class StatusImportacao:
    AGUARDANDO = "AGUARDANDO"
    PROCESSADA = "PROCESSADA"


class Importacao(Base):
    """Um .docx de simulado chegando pelo link de envio.

    O link é a credencial — uso único, com prazo —, então aqui fica só o hash
    do token, como em `api_tokens`. Depois do envio, a linha guarda o arquivo
    original, os blocos lidos e o relatório: é com eles que o Claude completa,
    na revisão, a questão que as regras não fecharam.
    """

    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    criado_por_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StatusImportacao.AGUARDANDO
    )
    parametros: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    arquivo_nome: Mapped[str | None] = mapped_column(String(200))
    arquivo: Mapped[bytes | None] = mapped_column(LargeBinary)
    blocos: Mapped[list | None] = mapped_column(JSON)
    relatorio: Mapped[dict | None] = mapped_column(JSON)
    rascunho_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"))
    criado_em: Mapped[datetime] = _agora()
    recebido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    criado_por: Mapped[Usuario] = relationship()


# --- credencial do MCP -------------------------------------------------------


class TokenMCP(Base):
    """Token Bearer que identifica quem está do outro lado do MCP.

    Guardamos só o hash: o valor em claro existe uma vez, na criação. Cada
    token pertence a um usuário, e é o papel desse usuário que decide o que a
    sessão pode fazer — o MCP não tem permissão própria.
    """

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    criado_em: Mapped[datetime] = _agora()
    ultimo_uso_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revogado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    usuario: Mapped[Usuario] = relationship()


# --- materiais ---------------------------------------------------------------


class Material(Base, Rastreavel):
    """PDF que o professor publica: apostila, lista de exercícios, gabarito.

    O arquivo mora aqui mesmo. A coluna é `EXTERNAL` (ver `migracoes.py`): sem
    compressão, o Postgres devolve uma faixa de bytes com `substring`, e o
    leitor abre a página 180 de uma apostila de 323 sem baixar as anteriores.
    PDF já vem comprimido por dentro, então não se perde espaço com isso.

    ponytail: bytes no Postgres servem à escala desta escola (menos de 1 GB por
    ano, ver docs/MATERIAIS.md). Com dezenas de GB isto vira bucket, e só quem
    lê e grava os bytes muda.
    """

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    arquivo_nome: Mapped[str | None] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    tamanho: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=Status.RASCUNHO)
    criado_por_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    criado_em: Mapped[datetime] = _agora()
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Carregada só por quem lê o arquivo: sem isto, listar 20 materiais traria
    # meio giga de PDF junto.
    conteudo: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)

    __table_args__ = (
        CheckConstraint("status in ('RASCUNHO','PUBLICADO')", name="ck_materials_status"),
    )

    turmas: Mapped[list[Turma]] = relationship(secondary="material_classes", order_by="Turma.nome")
    alunos: Mapped[list[Usuario]] = relationship(
        secondary="material_students", order_by="Usuario.nome"
    )


class MaterialTurma(Base):
    """Acesso da turma inteira."""

    __tablename__ = "material_classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    turma_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)

    __table_args__ = (UniqueConstraint("material_id", "turma_id", name="uq_material_turma"),)


class MaterialAluno(Base):
    """Acesso de uma pessoa só — é aqui que uma compra futura escreve."""

    __tablename__ = "material_students"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    criado_em: Mapped[datetime] = _agora()

    __table_args__ = (UniqueConstraint("material_id", "usuario_id", name="uq_material_aluno"),)


class MaterialAnotacao(Base):
    """O que um aluno riscou numa página — só dele, nem o professor lê.

    Uma linha por página: salvar é gravar a página que mudou, e uma apostila de
    323 páginas não vira um documento único que se reescreve inteiro a cada
    traço. Os traços vão em coordenadas relativas (0 a 1), para zoom e rotação
    não mexerem no dado.
    """

    __tablename__ = "material_annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    pagina: Mapped[int] = mapped_column(Integer, nullable=False)
    dados: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    criado_em: Mapped[datetime] = _agora()
    atualizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("material_id", "usuario_id", "pagina", name="uq_material_anotacao"),
    )


# --- aula ao vivo ------------------------------------------------------------


class Aula(Base, Rastreavel):
    """Aula ao vivo: a sala é do Zoom, a porta é nossa.

    Quem alcança a aula é decidido aqui, do mesmo jeito que num material —
    turma inteira ou pessoa a pessoa. O Zoom não sabe quem é aluno: ele só
    hospeda a sala, e o `zoom_meeting_id` é o único fio entre as duas coisas.

    O link de iniciar do professor **não tem coluna**: expira em duas horas, e
    é buscado na hora (ver docs/AULAS-AO-VIVO.md).
    """

    __tablename__ = "live_classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    inicio_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minutos: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=Status.RASCUNHO)
    gravar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    zoom_meeting_id: Mapped[str | None] = mapped_column(String(40), index=True)
    zoom_join_url: Mapped[str | None] = mapped_column(String(500))

    # Onde a gravação deve cair quando ficar pronta, e se cai sozinha.
    submodulo_id: Mapped[int | None] = mapped_column(ForeignKey("submodules.id"))
    publicar_gravacao: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gravacao_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"))

    criado_por_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    criado_em: Mapped[datetime] = _agora()
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status in ('RASCUNHO','PUBLICADO')", name="ck_live_classes_status"),
    )

    turmas: Mapped[list[Turma]] = relationship(secondary="live_class_classes", order_by="Turma.nome")
    alunos: Mapped[list[Usuario]] = relationship(
        secondary="live_class_students", order_by="Usuario.nome"
    )
    submodulo: Mapped[SubModulo | None] = relationship()


class AulaTurma(Base):
    """Acesso da turma inteira."""

    __tablename__ = "live_class_classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    aula_id: Mapped[int] = mapped_column(ForeignKey("live_classes.id"), nullable=False)
    turma_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)

    __table_args__ = (UniqueConstraint("aula_id", "turma_id", name="uq_aula_turma"),)


class AulaAluno(Base):
    """Acesso de uma pessoa só."""

    __tablename__ = "live_class_students"

    id: Mapped[int] = mapped_column(primary_key=True)
    aula_id: Mapped[int] = mapped_column(ForeignKey("live_classes.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    criado_em: Mapped[datetime] = _agora()

    __table_args__ = (UniqueConstraint("aula_id", "usuario_id", name="uq_aula_aluno"),)


class AulaPresenca(Base):
    """O link pessoal do aluno naquela aula — e, depois, se ele entrou.

    O link é guardado porque o Zoom só deixa inscrever o mesmo e-mail três
    vezes por dia na mesma reunião: pedir de novo a cada clique queimaria a
    cota e devolveria erro na cara do aluno.
    """

    __tablename__ = "live_class_attendance"

    id: Mapped[int] = mapped_column(primary_key=True)
    aula_id: Mapped[int] = mapped_column(ForeignKey("live_classes.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    join_url: Mapped[str] = mapped_column(String(500), nullable=False)
    criado_em: Mapped[datetime] = _agora()
    entrou_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    saiu_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("aula_id", "usuario_id", name="uq_aula_presenca"),)


class TentativaDeLogin(Base):
    """Falha de login recente, para a trava valer entre processos.

    Antes isto era um dicionário na memória do processo: com quatro processos
    servindo o portal, cada um contava sozinho e o limite de cinco viraria
    vinte (ver docs/CARGA.md). A chave é o e-mail tentado ou o IP.
    """

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    chave: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    criado_em: Mapped[datetime] = _agora()
