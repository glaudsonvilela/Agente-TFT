from __future__ import annotations

import os
import socket
import threading
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from hm.dataset import Latest
from hm.studio_bridge import StudioController, StudioServer, design_root, package_contract, run_studio


class StudioBridgeTests(unittest.TestCase):
    def test_voice_remains_paused_in_text_coaching_mode(self):
        from hm.voice import VOICE_NARRATION_ENABLED
        self.assertFalse(VOICE_NARRATION_ENABLED)
        controller = object.__new__(StudioController)
        controller.voice = None
        self.assertEqual(controller.set_voice(True), {"enabled": False, "paused": True})
        self.assertTrue(controller._voice_state()["paused"])

    def test_feedback_bridge_passes_the_visible_decision_key(self):
        calls = []
        controller = object.__new__(StudioController)
        controller.lock = threading.RLock()
        controller.session = SimpleNamespace(feedback_tip=lambda helpful, decision_key=None:
            calls.append((helpful, decision_key)) or decision_key == 'provisional:one')
        self.assertFalse(controller.rate_tip('provisional:one', 'yes')['accepted'])
        self.assertTrue(controller.rate_tip('provisional:one', True)['accepted'])
        self.assertEqual(calls, [(True, 'provisional:one')])

    def test_slow_preview_encoding_does_not_delay_tip_delivery(self):
        preview = Latest()
        preview.put(SimpleNamespace(width=2, height=1, rgb=b'\0' * 6))
        session = SimpleNamespace(finished=False, preview=preview,
            latest_replay_tip=dict(actionable=True, decision_key='test:buy',
                                   text='Compre Rakan agora.', source_ms=2000),
            done=threading.Event())
        controller = object.__new__(StudioController)
        controller.lock = threading.RLock()
        controller.session = session
        controller.closed = threading.Event()
        controller.voice = None
        controller.history = deque(maxlen=100)
        controller.last_tip_key = None
        controller.last_error = None
        controller.preview_condition = threading.Condition()
        controller.preview_jpeg = None
        controller.preview_sequence = 0
        controller.preview_times = deque(maxlen=90)
        controller.preview_encode_ms = deque(maxlen=90)
        controller.next_preview_telemetry = 0.0
        controller.model_updater = SimpleNamespace()
        encoding = threading.Event()
        release = threading.Event()

        def slow_save(*args, **kwargs):
            encoding.set()
            release.wait(2)

        try:
            with patch('PIL.Image.Image.save', slow_save):
                worker = threading.Thread(target=controller._preview_pump, daemon=True)
                advice = threading.Thread(target=controller._pump, daemon=True)
                worker.start()
                self.assertTrue(encoding.wait(1), 'preview did not start encoding')
                advice.start()
                deadline = time.monotonic() + 1
                while not controller.history and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertEqual(controller.history[0]['text'], 'Compre Rakan agora.')
        finally:
            controller.closed.set()
            release.set()
            with controller.preview_condition:
                controller.preview_condition.notify_all()

    def test_preview_records_capture_and_encode_diagnostics(self):
        events = []
        source = SimpleNamespace(preview_received=12,
            preview_frames=SimpleNamespace(replaced=2),
            last_preview_received_ns=time.perf_counter_ns())
        preview = Latest()
        preview.put(SimpleNamespace(width=2, height=1, rgb=b'\0' * 8))
        session = SimpleNamespace(finished=False, preview=preview, source=source,
            store=SimpleNamespace(emit=lambda stream, event: events.append((stream, event))))
        controller = object.__new__(StudioController)
        controller.lock = threading.RLock()
        controller.session = session
        controller.closed = threading.Event()
        controller.preview_condition = threading.Condition()
        controller.preview_jpeg = None
        controller.preview_sequence = 0
        controller.preview_times = deque(maxlen=90)
        controller.preview_encode_ms = deque(maxlen=90)
        controller.next_preview_telemetry = 0.0
        controller.last_error = None
        worker = threading.Thread(target=controller._preview_pump, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 1
            while not events and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(events[0][0], 'telemetry')
            self.assertEqual(events[0][1]['event'], 'studio_preview_pipeline')
            self.assertEqual(events[0][1]['native_preview_received'], 12)
            self.assertEqual(events[0][1]['native_preview_queue_replaced'], 2)
            self.assertGreater(controller.preview_sequence, 0)
        finally:
            controller.closed.set()
            worker.join(1)

    def test_closing_stalled_capture_stops_then_seals(self):
        class FirstWaitTimesOut(threading.Event):
            def __init__(self):
                super().__init__()
                self.waits = 0
            def wait(self, timeout=None):
                self.waits += 1
                return False if self.waits == 1 else super().wait(0)
        class Session:
            finished = False
            options = type('Options', (), {'replay_review': True})()
            def __init__(self):
                self.done = FirstWaitTimesOut()
                self.stops = 0
            def request_stop(self):
                pass
            def stop(self):
                self.stops += 1
                self.done.set()
            def finish(self):
                self.finished = True
                return {'execution_complete': True}
        controller = object.__new__(StudioController)
        controller.lock = threading.RLock()
        controller.session = Session()
        controller.last_result = controller.last_error = None
        controller.closed = threading.Event()
        controller.preview_condition = threading.Condition()
        controller.voice = None
        controller.model_updater = type('Updater', (), {
            'activate_pending_if_idle': lambda self: None,
            'check_async': lambda self: None,
        })()
        controller.close()
        self.assertEqual(controller.session.stops, 1)
        self.assertEqual(controller.last_result, {'execution_complete': True})

    def test_package_contract_serves_connected_layout(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as temp:
            report = package_contract(Path(temp) / 'studio.json')
            self.assertTrue(report['studio_assets_served'])
            self.assertTrue((Path(temp) / 'studio.json').is_file())

    def test_single_frame_endpoint_waits_for_new_sequence(self):
        from tempfile import TemporaryDirectory
        controller = SimpleNamespace(closed=threading.Event(),
                                     preview_condition=threading.Condition(),
                                     preview_sequence=1, preview_jpeg=b'first')
        with TemporaryDirectory() as temp:
            server = StudioServer(controller, temp)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = server.url.split('?')[0] + 'frame.jpg?after='
            try:
                with urlopen(base + '0', timeout=3) as response:
                    self.assertEqual(response.read(), b'first')
                    self.assertEqual(response.headers['X-Frame-Sequence'], '1')
                def publish():
                    time.sleep(.05)
                    with controller.preview_condition:
                        controller.preview_sequence = 2
                        controller.preview_jpeg = b'second'
                        controller.preview_condition.notify_all()
                threading.Thread(target=publish, daemon=True).start()
                with urlopen(base + '1', timeout=3) as response:
                    self.assertEqual(response.read(), b'second')
                    self.assertEqual(response.headers['X-Frame-Sequence'], '2')
                with urlopen(base + '2', timeout=3) as response:
                    self.assertEqual(response.status, 204)
                    self.assertEqual(response.read(), b'')
            finally:
                controller.closed.set()
                with controller.preview_condition:
                    controller.preview_condition.notify_all()
                server.shutdown()
                server.server_close()

    def test_highlights_download_only_after_compilation_and_with_local_token(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            video = Path(temp) / 'highlights.mp4'
            video.write_bytes(b'mp4-sample')
            ready = False
            controller = SimpleNamespace(highlight_video=lambda: video if ready else None)
            server = StudioServer(controller, temp)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            path = server.url.split('?')[0] + 'highlights.mp4'
            try:
                with self.assertRaises(HTTPError) as pending:
                    urlopen(path, timeout=2)
                self.assertEqual(pending.exception.code, 404)
                ready = True
                with urlopen(path, timeout=2) as response:
                    self.assertEqual(response.read(), b'mp4-sample')
                    self.assertEqual(response.headers['Content-Type'], 'video/mp4')
                with self.assertRaises(HTTPError) as untrusted:
                    urlopen(f'http://127.0.0.1:{server.server_port}/highlights.mp4', timeout=2)
                self.assertEqual(untrusted.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()

    def test_installer_handoff_reuses_the_open_browser_window(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as temp:
            handoff = Path(temp) / 'studio-url.txt'
            closed = threading.Event()
            closed.set()
            controller = SimpleNamespace(closed=closed, session=None, close=lambda: None)
            with patch('hm.studio_bridge.StudioController', return_value=controller), \
                 patch('browser_shell.open_local_window') as open_window, \
                 patch.dict(os.environ, {'AGENTE_TFT_STUDIO_URL_FILE': str(handoff)}):
                self.assertEqual(run_studio(), 0)
            self.assertIn('?connected=1#studio', handoff.read_text(encoding='utf-8'))
            open_window.assert_not_called()

    def test_capture_uses_bundled_model_without_waiting_for_server(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            controller = object.__new__(StudioController)
            controller.lock = threading.RLock()
            controller.session = None
            controller.model_updater = SimpleNamespace(ensure_active=lambda:
                self.fail('capture waited for the remote model'))
            controller.history = deque(maxlen=100)
            controller.preview_jpeg = None
            controller.preview_condition = threading.Condition()
            controller.preview_times = deque(maxlen=90)
            controller.preview_encode_ms = deque(maxlen=90)
            controller.last_error = controller.last_result = controller.last_tip_key = None
            target = {'kind': 'monitor', 'id': '1', 'label': 'Monitor',
                      'bounds': [0, 0, 1920, 1080]}
            fake_session = SimpleNamespace(id='local', finished=False)
            with patch('hm.capture_source.list_targets', return_value=[target]), \
                 patch('hm.studio_bridge.runtime_paths', return_value={
                     'configs': temp, 'worker': 'worker', 'tesseract': 'tesseract'}), \
                 patch('hm.studio_bridge.discover_model', return_value='bundled-model'), \
                 patch('hm.studio_bridge.default_hm4_output_root', return_value=temp), \
                 patch('hm.studio_bridge.HM4RuntimeSession') as runtime:
                runtime.return_value.start.return_value = fake_session
                result = controller.start_session('monitor', '1', False, True)
            self.assertEqual(result['session_id'], 'local')
            self.assertEqual(runtime.call_args.args[0].model, 'bundled-model')

    def test_closing_window_seals_finished_capture(self):
        class Session:
            finished = False
            options = type('Options', (), {'replay_review': True})()
            def __init__(self):
                self.done = threading.Event()
                self.finish_calls = 0
            def request_stop(self):
                self.done.set()
            def finish(self):
                self.finish_calls += 1
                self.finished = True
                return {'execution_complete': True}

        controller = object.__new__(StudioController)
        controller.lock = threading.RLock()
        controller.session = Session()
        controller.last_result = controller.last_error = None
        controller.closed = threading.Event()
        controller.preview_condition = threading.Condition()
        controller.voice = None
        controller.model_updater = type('Updater', (), {
            'activate_pending_if_idle': lambda self: None,
            'check_async': lambda self: None,
        })()
        controller.close()
        self.assertTrue(controller.closed.is_set())
        self.assertEqual(controller.session.finish_calls, 1)
        self.assertEqual(controller.last_result, {'execution_complete': True})

    def test_local_design_server_serves_only_its_tokenized_directory(self):
        server = StudioServer(object(), design_root())
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with urlopen(server.url, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b'AGENTE TFT', response.read())
            with urlopen(server.url.split('?')[0] + 'connected.js', timeout=2) as response:
                self.assertIn(b'connectedCoach', response.read())
            for path in ('/index.html', server.url.split('?')[0] + '../../etc/passwd'):
                with self.assertRaises(HTTPError) as error:
                    urlopen('http://127.0.0.1:' + str(server.server_port) + path
                            if path.startswith('/') else path, timeout=2)
                self.assertIn(error.exception.code, (403, 404))
        finally:
            server.shutdown()
            server.server_close()

    def test_preview_stream_does_not_resend_a_stale_frame(self):
        controller = SimpleNamespace(closed=threading.Event(),
            preview_condition=threading.Condition(), preview_sequence=1,
            preview_jpeg=b'jpeg-fixture')
        server = StudioServer(controller, design_root())
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with socket.create_connection(('127.0.0.1', server.server_port), timeout=3) as client:
                path = '/' + server.token + '/preview.mjpg'
                client.sendall(f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{server.server_port}\r\n\r\n'.encode())
                first = b''
                while b'jpeg-fixture\r\n' not in first:
                    first += client.recv(4096)
                client.settimeout(2.3)
                with self.assertRaises(socket.timeout):
                    client.recv(1)
        finally:
            controller.closed.set()
            with controller.preview_condition:
                controller.preview_condition.notify_all()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
