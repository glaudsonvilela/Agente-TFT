"""Lossless frame and authenticated local transport contracts."""

from pathlib import Path
import socket
import sys
import threading
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hm45_protocol import ProtocolError, decode_rgb, encode_rgb, recv_packet, send_packet
from hm45_core_server import CoreTCPServer


class FakeCore:
    ready = {"version": "test"}

    def dispatch(self, header, payload):
        return {"id": header["frame_id"], "bytes": len(payload)}


class ProtocolContracts(unittest.TestCase):
    def test_rgb_is_bit_exact_and_bomb_is_rejected(self):
        rgb = bytes(range(256)) * 9
        codec, encoded = encode_rgb(rgb, 32, 24)
        self.assertEqual(decode_rgb(codec, encoded, 32, 24), rgb)
        with self.assertRaises(ProtocolError):
            decode_rgb("zlib-rgb8", zlib.compress(bytes(32*24*3 + 1)), 32, 24)
        with self.assertRaises(ProtocolError):
            decode_rgb("rgb8", rgb[:-1], 32, 24)

    def test_authenticated_loopback_preserves_request_identity(self):
        server = CoreTCPServer(FakeCore(), "token123")
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as sock:
                sock.settimeout(2)
                send_packet(sock, {"op": "hello", "token": "token123"})
                hello, _ = recv_packet(sock)
                self.assertTrue(hello["ok"])
                send_packet(sock, {"op": "health", "request_id": 17, "frame_id": 42}, b"abc")
                answer, _ = recv_packet(sock)
                self.assertEqual(answer["request_id"], 17)
                self.assertEqual(answer["result"], {"id": 42, "bytes": 3})
            with socket.create_connection(server.server_address, timeout=2) as sock:
                sock.settimeout(2)
                send_packet(sock, {"op": "hello", "token": "wrong"})
                with self.assertRaises(EOFError):
                    recv_packet(sock)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)


if __name__ == "__main__":
    unittest.main()
