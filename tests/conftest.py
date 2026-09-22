"""A API em Java no ar, contra um banco de teste — o outro lado da ponte.

O adaptador não tem modelo nem sessão de banco: quem cria o schema é o Flyway
da API, na partida. O que os testes precisam é de um mundo mínimo já gravado,
e para isso existe `tests/modelos.py` — um espelho SQLAlchemy das tabelas,
usado só aqui, para semear. Nada do `app/` o importa.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/plataforma_mvp_test")
os.environ.setdefault("API_BASE_URL", "http://127.0.0.1:8082")
os.environ.setdefault("SERVICO_TOKEN", "token-de-servico-so-para-teste-com-32+")
os.environ.setdefault("MCP_BASE_URL", "https://mcp.teste")

from app.config import get_settings  # noqa: E402
from app.identidade import Canal, Identidade, Papel  # noqa: E402
from tests.modelos import (  # noqa: E402
    Alternativa,
    Assunto,
    Base,
    Dificuldade,
    Item,
    Matricula,
    Modulo,
    Questao,
    QuestaoAssunto,
    Status,
    SubAssunto,
    SubModulo,
    TipoSubModulo,
    Turma,
    Usuario,
    Video,
    VideoAssunto,
)

get_settings.cache_clear()
URL_DO_BANCO = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
engine = create_engine(URL_DO_BANCO.replace("postgresql://", "postgresql+psycopg://"), future=True)
Sessao = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# A suíte apaga tudo entre um teste e outro: só roda contra um banco *_test.
if not (engine.url.database or "").endswith("_test"):
    raise RuntimeError(f"Os testes esvaziam o banco inteiro e DATABASE_URL aponta para '{engine.url.database}'.")


def _jdbc(url) -> str:
    return f"jdbc:postgresql://{url.host or 'localhost'}:{url.port or 5432}/{url.database}"


@pytest.fixture(scope="session")
def api_java():
    """Sobe o jar da API com o Flyway ligado: é ele que cria as tabelas no banco vazio."""
    jar = os.environ.get("API_JAR")
    if not jar or not os.path.exists(jar):
        if os.environ.get("CI"):
            raise RuntimeError(f"API_JAR não aponta para o jar da API: {jar!r}")
        pytest.skip("Sem API_JAR: construa a API (./mvnw -q package -DskipTests) e aponte a variável.")
    try:
        with engine.connect():
            pass
    except OperationalError:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"Postgres de teste indisponível em {engine.url}.")

    # Banco limpo: o Flyway da API recria tudo a partir da V1.
    with engine.begin() as conexao:
        conexao.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

    base = get_settings().api_base_url.rstrip("/")
    porta = str(urllib.parse.urlsplit(base).port or 8080)
    registro = tempfile.NamedTemporaryFile("w+", suffix=".log", prefix="api-", delete=False,
                                           encoding="utf-8", errors="replace")
    processo = subprocess.Popen(
        ["java", "-jar", jar],
        env={**os.environ,
             "SERVICO_TOKEN": get_settings().servico_token,
             "SPRING_DATASOURCE_URL": _jdbc(engine.url),
             "SPRING_DATASOURCE_USERNAME": engine.url.username or "",
             "SPRING_DATASOURCE_PASSWORD": engine.url.password or "",
             "SPRING_FLYWAY_BASELINE_ON_MIGRATE": "false",
             "PORTAL_MCP_BASE_URL": get_settings().mcp_base_url or "",
             "SERVER_PORT": porta},
        stdout=registro, stderr=subprocess.STDOUT,
    )

    def log() -> str:
        registro.flush()
        return pathlib.Path(registro.name).read_text(encoding="utf-8", errors="replace")[-3000:]

    try:
        for _ in range(240):
            if processo.poll() is not None:
                raise RuntimeError(f"a API morreu ao subir:\n{log()}")
            try:
                with urllib.request.urlopen(f"{base}/actuator/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        else:
            raise RuntimeError(f"a API não respondeu em {base} a tempo:\n{log()}")
        yield base
    finally:
        processo.terminate()
        try:
            processo.wait(timeout=20)
        except subprocess.TimeoutExpired:
            processo.kill()
        registro.close()


@pytest.fixture
def db(api_java):
    with Sessao() as sessao:
        yield sessao
        sessao.rollback()
    # Cada teste começa do zero. O Flyway não é tocado: só as tabelas do domínio.
    with Sessao() as limpeza:
        for tabela in reversed(Base.metadata.sorted_tables):
            limpeza.execute(tabela.delete())
        limpeza.commit()


@pytest.fixture
def mundo(db):
    """O mundo mínimo para as regras aparecerem: duas turmas, um módulo publicado
    em cada, a taxonomia compartilhada e três questões no acervo."""
    from tests.senhas import hash_senha

    professor = Usuario(nome="Helena", email="h@x.demo", senha_hash=hash_senha("x"), papel=Papel.ADMIN)
    joao = Usuario(nome="João", email="joao@x.demo", senha_hash=hash_senha("x"), papel=Papel.ALUNO)
    pedro = Usuario(nome="Pedro", email="pedro@x.demo", senha_hash=hash_senha("x"), papel=Papel.ALUNO)
    db.add_all([professor, joao, pedro])

    t2027 = Turma(nome="Extensivo 2027", ano=2027)
    t2026 = Turma(nome="Extensivo 2026", ano=2026)
    db.add_all([t2027, t2026])
    db.flush()
    db.add_all([Matricula(usuario_id=joao.id, turma_id=t2027.id), Matricula(usuario_id=pedro.id, turma_id=t2026.id)])

    esteq = Assunto(nome="Estequiometria")
    atom = Assunto(nome="Atomística")
    db.add_all([esteq, atom])
    db.flush()
    pureza = SubAssunto(assunto_id=esteq.id, nome="Pureza e rendimento")
    db.add(pureza)
    db.flush()

    def _modulo(turma, nome, ordem=1):
        modulo = Modulo(turma_id=turma.id, nome=nome, ordem=ordem)
        db.add(modulo)
        db.flush()
        aulas = SubModulo(modulo_id=modulo.id, nome="Aulas", tipo=TipoSubModulo.VIDEO, ordem=1)
        questoes = SubModulo(modulo_id=modulo.id, nome="Questões da apostila", tipo=TipoSubModulo.VIDEO, ordem=2)
        db.add_all([aulas, questoes])
        db.flush()
        return modulo, aulas, questoes

    modulo, aulas, questoes_sub = _modulo(t2027, "K01 - Estequiometria")
    itens = []
    for numero in (1, 2, 3):
        video = Video(vimeo_id=f"vid{numero}", titulo=f"Vídeo {numero}",
                      embed_url=f"https://player.vimeo.com/video/{numero}?h=abc")
        db.add(video)
        db.flush()
        db.add(VideoAssunto(video_id=video.id, assunto_id=esteq.id, subassunto_id=pureza.id))
        item = Item(submodulo_id=questoes_sub.id, video_id=video.id, nome=f"Q{numero:02d}", ordem=numero,
                    status=Status.PUBLICADO)
        db.add(item)
        itens.append(item)

    outro_modulo, _outras_aulas, outras_questoes = _modulo(t2026, "K03 - Estequiometria")
    video_alheio = Video(vimeo_id="vid-2026", titulo="Vídeo de outra turma",
                         embed_url="https://player.vimeo.com/video/99?h=xyz")
    db.add(video_alheio)
    db.flush()
    db.add(VideoAssunto(video_id=video_alheio.id, assunto_id=esteq.id, subassunto_id=pureza.id))
    db.add(Item(submodulo_id=outras_questoes.id, video_id=video_alheio.id, nome="Q01", ordem=1, status=Status.PUBLICADO))

    questoes = []
    for numero in (1, 2, 3):
        questao = Questao(enunciado=f"Enunciado {numero}", gabarito="B", dificuldade=Dificuldade.MEDIA,
                          status=Status.PUBLICADO, criado_por_id=professor.id)
        db.add(questao)
        db.flush()
        for letra in "ABCDE":
            db.add(Alternativa(questao_id=questao.id, letra=letra, texto=f"alt {letra}"))
        db.add(QuestaoAssunto(questao_id=questao.id, assunto_id=esteq.id, subassunto_id=pureza.id))
        questoes.append(questao)

    db.commit()

    return {
        "professor": Identidade(professor.id, "Helena", "h@x.demo", Papel.ADMIN, Canal.PORTAL),
        "professor_mcp": Identidade(professor.id, "Helena", "h@x.demo", Papel.ADMIN, Canal.MCP),
        "joao": Identidade(joao.id, "João", "joao@x.demo", Papel.ALUNO, Canal.PORTAL),
        "pedro": Identidade(pedro.id, "Pedro", "pedro@x.demo", Papel.ALUNO, Canal.PORTAL),
        "turma_2027": t2027,
        "turma_2026": t2026,
        "modulo": modulo,
        "aulas": aulas,
        "submodulo": questoes_sub,
        "modulo_2026": outro_modulo,
        "itens": itens,
        "questoes": questoes,
        "assunto": esteq,
        "atomistica": atom,
        "subassunto": pureza,
        "video_de_outra_turma": video_alheio,
    }
