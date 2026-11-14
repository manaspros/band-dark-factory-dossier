# Dossier service, stage 1. Every dependency is installed at build time: at run time the
# container reaches only the provider endpoints.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8080
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN useradd --system --no-create-home dossier
USER dossier

EXPOSE 8080
CMD ["python", "-m", "app.main"]
