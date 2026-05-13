# =============================================================================
# Stage 1: Tailwind CSS をビルド
#   - 公式の Tailwind スタンドアロンバイナリを使用（Node.js 不要）
#   - linux-arm64 / linux-x64 を自動判定
# =============================================================================
FROM debian:bookworm-slim AS css-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY app ./app

RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
      x86_64)  asset="tailwindcss-linux-x64" ;; \
      aarch64) asset="tailwindcss-linux-arm64" ;; \
      *) echo "Unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -sLo /usr/local/bin/tailwindcss \
      "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/${asset}"; \
    chmod +x /usr/local/bin/tailwindcss; \
    tailwindcss -i app/static/src.css -o app/static/tailwind.css --minify


# =============================================================================
# Stage 2: 本体イメージ
# =============================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=css-builder /build/app/static/tailwind.css ./app/static/tailwind.css

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
