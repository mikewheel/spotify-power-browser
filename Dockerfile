FROM python:3.13-slim-bookworm AS base
ARG APP_DIR="/src"
ENV TZ=America/New_York \
    PYTHONPATH=$APP_DIR \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/var/cache/pypoetry' \
    POETRY_HOME='/usr/local' \
    POETRY_VERSION=2.4.1
ENV PATH="$PATH:$POETRY_HOME/bin"

RUN apt-get -y update \
    && apt-get -y upgrade \
    && apt-get -y install curl gcc g++ libffi-dev \
    && curl -sSL https://install.python-poetry.org | python3 -
COPY poetry.lock pyproject.toml ./
RUN poetry install --no-interaction --no-ansi --no-root

WORKDIR $APP_DIR
COPY application/ ./application/
COPY mcp_server/ ./mcp_server/

CMD ["python3", "application/api_call_engine.py"]
