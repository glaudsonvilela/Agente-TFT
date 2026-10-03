"""Bounded, versioned loopback protocol shared by Windows host and WSL core."""

from __future__ import annotations

import json
import socket
import struct
import zlib

VERSION = 1
MAX_HEADER = 64 * 1024
MAX_PAYLOAD = 8 * 1024 * 1024
MAX_RAW_RGB = 1920 * 1080 * 3


class ProtocolError(ValueError):
    pass


def _read_exact(sock: socket.socket, count: int) -> bytes:
    out = bytearray()
    while len(out) < count:
        chunk = sock.recv(count - len(out))
        if not chunk:
            raise EOFError("Conexão com o núcleo encerrada durante um pacote.")
        out.extend(chunk)
    return bytes(out)


def send_packet(sock: socket.socket, header: dict, payload: bytes = b"") -> None:
    if not isinstance(payload, bytes) or len(payload) > MAX_PAYLOAD:
        raise ProtocolError("Payload acima do limite.")
    value = dict(header, protocol=VERSION, payload_bytes=len(payload))
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_HEADER:
        raise ProtocolError("Cabeçalho acima do limite.")
    sock.sendall(struct.pack("<I", len(raw)) + raw + payload)


def recv_packet(sock: socket.socket) -> tuple[dict, bytes]:
    length = struct.unpack("<I", _read_exact(sock, 4))[0]
    if not 0 < length <= MAX_HEADER:
        raise ProtocolError("Tamanho de cabeçalho inválido.")
    try:
        header = json.loads(_read_exact(sock, length))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Cabeçalho inválido.") from exc
    if not isinstance(header, dict) or header.get("protocol") != VERSION:
        raise ProtocolError("Versão de protocolo incompatível.")
    size = header.get("payload_bytes")
    if type(size) is not int or not 0 <= size <= MAX_PAYLOAD:
        raise ProtocolError("Tamanho de payload inválido.")
    return header, _read_exact(sock, size)


def encode_rgb(rgb: bytes, width: int, height: int) -> tuple[str, bytes]:
    expected = width * height * 3
    if not 0 < expected <= MAX_RAW_RGB or len(rgb) != expected:
        raise ProtocolError("Frame RGB fora do contrato 1920×1080.")
    # Full-frame zlib cost ~135 ms on two real 1080p HM4 samples. Loopback raw
    # transfer is cheaper; analysis is only 1-2 Hz, never preview frame rate.
    return "rgb8", rgb


def decode_rgb(codec: str, payload: bytes, width: int, height: int) -> bytes:
    expected = width * height * 3
    if not 0 < expected <= MAX_RAW_RGB:
        raise ProtocolError("Dimensões RGB fora do limite.")
    if codec == "rgb8":
        raw = payload
    elif codec == "zlib-rgb8":
        decoder = zlib.decompressobj()
        try:
            raw = decoder.decompress(payload, expected + 1)
            if len(raw) > expected:
                raise ProtocolError("RGB descomprimido excede o limite.")
            raw += decoder.flush(expected + 1 - len(raw))
        except zlib.error as exc:
            raise ProtocolError("RGB comprimido inválido.") from exc
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ProtocolError("RGB comprimido incompleto ou excedente.")
    else:
        raise ProtocolError("Codec RGB não reconhecido.")
    if len(raw) != expected:
        raise ProtocolError("Tamanho RGB incompatível.")
    return raw
