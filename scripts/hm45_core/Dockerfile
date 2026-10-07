FROM rust:1.85-bookworm AS builder
WORKDIR /src
ENV CARGO_TARGET_DIR=/tmp/agente-target
COPY rust/ rust/
COPY tools/e1-native/ tools/e1-native/
COPY tools/hm-hp-native/ tools/hm-hp-native/
RUN cargo build --locked --release --manifest-path tools/e1-native/Cargo.toml \
 && cargo build --locked --release --manifest-path tools/hm-hp-native/Cargo.toml

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/agente-tft:/opt/agente-tft/apps/hud_mapper:/opt/agente-tft/apps/e1_replay \
    OMP_THREAD_LIMIT=1 \
    OPENBLAS_NUM_THREADS=1 \
    AGENTE_TFT_RESIDENT_OCR=required \
    AGENTE_TFT_DISABLE_LOCAL_NEURAL=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libtesseract5 libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m pip install --no-cache-dir --only-binary=:all: \
      Pillow==12.1.0 numpy==2.2.6 onnxruntime==1.23.2
COPY app/ /opt/agente-tft/
COPY --from=builder /tmp/agente-target/release/agente-tft-e1-worker /opt/agente-tft/bin/agente-tft-e1-worker
COPY --from=builder /tmp/agente-target/release/agente-tft-hm-hp /opt/agente-tft/bin/agente-tft-hm-hp
RUN mkdir -p /opt/agente-tft/runtime \
 && chmod 755 /opt/agente-tft/bin/health-check /opt/agente-tft/bin/agente-tft-e1-worker /opt/agente-tft/bin/agente-tft-hm-hp
WORKDIR /opt/agente-tft
ENTRYPOINT ["python3", "/opt/agente-tft/hm45_core_server.py"]
