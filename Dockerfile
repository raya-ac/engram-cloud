FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./

RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && python -c 'import subprocess,tomllib; subprocess.check_call(["pip","install","--no-cache-dir",*tomllib.load(open("pyproject.toml","rb"))["project"]["dependencies"]])'

COPY app ./app
RUN pip install --no-cache-dir --no-deps -e .

ARG SOURCE_REVISION=development
ENV ENGRAM_CLOUD_SOURCE_REVISION=$SOURCE_REVISION
LABEL org.opencontainers.image.revision=$SOURCE_REVISION

EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
