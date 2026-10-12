FROM golang:1.26-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-reportlab nodejs ca-certificates file poppler-utils tesseract-ocr && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 1000 --create-home candidate
WORKDIR /workspace
USER 1000:1000
