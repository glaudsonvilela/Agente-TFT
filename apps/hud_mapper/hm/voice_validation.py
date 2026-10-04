"""Explicit offline contract harness. Mock PCM is silence, never a real voice preview."""
import io
import wave
from .voice_api import ElevenLabsSpeech


class MockConnection:
    def __init__(self, host, timeout):
        self.status = 200
        self.data = io.BytesIO(b'\0\0'*2205)

    def request(self, method, path, body, headers):
        pass

    def getresponse(self):
        return self

    def getheader(self, name, default=''):
        return 'audio/pcm'

    def read1(self, size):
        return self.data.read(size)

    def close(self):
        pass


def mock_client():
    return ElevenLabsSpeech('mock-not-a-credential', 'mock-voice', connection_factory=MockConnection)


def package_contract():
    client=mock_client()
    wav=client.synthesize('Teste de transporte simulado.')
    with wave.open(io.BytesIO(wav),'rb') as audio:
        assert audio.getnframes()==2205 and audio.getframerate()==22050
    client.close()
    from importlib.util import find_spec
    assert not any(find_spec(name) for name in ('sherpa_onnx','supertonic'))
    return dict(api_only=True,local_tts_models_bundled=False,mock_transport_passed=True,
                provider_audio_validated=False,physical_audio_measured=False)
