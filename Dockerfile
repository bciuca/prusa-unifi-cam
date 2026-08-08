FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 bridge && useradd --system --uid 10001 --gid bridge --home /nonexistent bridge
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
ENTRYPOINT ["python", "-m", "bridge.main"]
