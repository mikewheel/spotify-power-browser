FROM python:3.11-slim-bookworm AS base
ARG APP_DIR="/src"
ENV TZ=America/New_York \
    PYTHONPATH=$APP_DIR \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/var/cache/pypoetry' \
    POETRY_HOME='/usr/local' \
    POETRY_VERSION=1.8.3
ENV PATH="$PATH:$POETRY_HOME/bin"

RUN apt-get -y update \
    && apt-get -y upgrade \
    && apt-get -y install curl gcc \
    && curl -sSL https://install.python-poetry.org | python3.11 -
COPY poetry.lock pyproject.toml ./
RUN poetry install --no-interaction --no-ansi

WORKDIR $APP_DIR
COPY application/ ./application/

CMD ["python3.11", "application/api_call_engine.py"]
