FROM rust:1.88-bookworm AS builder
WORKDIR /src
ENV CARGO_TARGET_DIR=/tmp/agente-target
COPY rust/ rust/
COPY tools/e1-native/ tools/e1-native/
COPY tools/hm-hp-native/ tools/hm-hp-native/
COPY tools/unit-features-lab/ tools/unit-features-lab/
RUN cargo build --locked --release --manifest-path tools/e1-native/Cargo.toml \
 && cargo build --locked --release --manifest-path tools/hm-hp-native/Cargo.toml \
 && cargo test --release --manifest-path tools/unit-features-lab/Cargo.toml training::tests \
 && cargo build --release --manifest-path tools/unit-features-lab/Cargo.toml \
      --bin vod-collector \
      --bin mine-shop-transitions \
      --bin mine-tooltip-labels \
      --bin adjudicate-autonomous-gold \
      --bin propagate-autonomous-anchors \
      --bin train-classifier

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/agente-tft:/opt/agente-tft/apps/hud_mapper:/opt/agente-tft/apps/e1_replay \
    OMP_THREAD_LIMIT=1 \
    OPENBLAS_NUM_THREADS=1 \
    AGENTE_TFT_RESIDENT_OCR=required \
    AGENTE_TFT_UNIT_LAB_BIN_DIR=/opt/agente-tft/bin
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng libtesseract5 libgomp1 ffmpeg \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m pip install --no-cache-dir --only-binary=:all: \
      Pillow==12.1.0 numpy==2.2.6 onnxruntime==1.23.2
COPY app/ /opt/agente-tft/
COPY --from=builder /tmp/agente-target/release/agente-tft-e1-worker /opt/agente-tft/bin/agente-tft-e1-worker
COPY --from=builder /tmp/agente-target/release/agente-tft-hm-hp /opt/agente-tft/bin/agente-tft-hm-hp
COPY --from=builder /tmp/agente-target/release/vod-collector /opt/agente-tft/bin/vod-collector
COPY --from=builder /tmp/agente-target/release/mine-shop-transitions /opt/agente-tft/bin/mine-shop-transitions
COPY --from=builder /tmp/agente-target/release/mine-tooltip-labels /opt/agente-tft/bin/mine-tooltip-labels
COPY --from=builder /tmp/agente-target/release/adjudicate-autonomous-gold /opt/agente-tft/bin/adjudicate-autonomous-gold
COPY --from=builder /tmp/agente-target/release/propagate-autonomous-anchors /opt/agente-tft/bin/propagate-autonomous-anchors
COPY --from=builder /tmp/agente-target/release/train-classifier /opt/agente-tft/bin/train-classifier
RUN mkdir -p /opt/agente-tft/runtime \
 && ONNX_LIB="$(find /usr/local/lib/python3.12/site-packages/onnxruntime/capi -maxdepth 1 -type f -name 'libonnxruntime.so*' | head -n 1)" \
 && test -n "$ONNX_LIB" \
 && ln -s "$ONNX_LIB" /opt/agente-tft/learner/libonnxruntime.so \
 && chmod 755 /opt/agente-tft/bin/health-check \
      /opt/agente-tft/bin/agente-tft-e1-worker \
      /opt/agente-tft/bin/agente-tft-hm-hp \
      /opt/agente-tft/bin/vod-collector \
      /opt/agente-tft/bin/mine-shop-transitions \
      /opt/agente-tft/bin/mine-tooltip-labels \
      /opt/agente-tft/bin/adjudicate-autonomous-gold \
      /opt/agente-tft/bin/propagate-autonomous-anchors \
      /opt/agente-tft/bin/train-classifier \
 && test -f /opt/agente-tft/learner/selection.json \
 && test -f /opt/agente-tft/learner/run-metadata.json \
 && test -f /opt/agente-tft/learner/learner-package.json
WORKDIR /opt/agente-tft
ENTRYPOINT ["python3", "/opt/agente-tft/hm45_core_server.py"]
