FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# LibreOffice sem interface: o importador de simulado converte com ele as
# figuras em formato antigo do Word (EMF, WMF, prévia de "Equação 3.0") para
# PNG. Pesa algumas centenas de MB — ver docs/IMPORTADOR-SIMULADO.md.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-draw-nogui fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app/ ./app/
RUN python -m pip install --no-cache-dir .

# Um processo só: a sessão do conector MCP mora na memória.
CMD ["python", "-m", "app.servir"]
