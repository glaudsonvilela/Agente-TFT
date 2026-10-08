from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave

from PIL import Image

from hm.speech_highlights import SpeechHighlightsRecorder, compile_highlights


def sample_jpeg():
    image = Image.new('RGB', (320, 180), '#36304e')
    out = BytesIO()
    image.save(out, 'JPEG')
    return out.getvalue()


def sample_wav():
    out = BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b'\0\0' * 11025)
    return out.getvalue()


class SpeechHighlightsTests(unittest.TestCase):
    def test_successful_playback_creates_a_downloadable_montage(self):
        with tempfile.TemporaryDirectory() as temp:
            recorder = SpeechHighlightsRecorder(temp)
            picture = sample_jpeg()
            base = 10_000_000_000
            for index in range(12):
                recorder.preview(picture, base + index * 200_000_000, index * 200)
                if index == 6:
                    recorder.spoken(sample_wav(), 'Role uma vez agora.',
                                    {'decision_key': 'roll:one', 'family': 'roll'},
                                    base + 600_000_000, base + 1_200_000_000)
            manifest_path = recorder.seal()
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest['clips'], 1)
            self.assertEqual(manifest['moments'][0]['selection'], 'successful_playback')
            video = compile_highlights(temp)
            self.assertTrue(video.is_file())
            self.assertGreater(video.stat().st_size, 1000)
            result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                'stream=codec_type', '-of', 'csv=p=0', str(video)],
                capture_output=True, text=True, check=True)
            self.assertEqual(set(result.stdout.splitlines()), {'video', 'audio'})
            self.assertEqual(json.loads(manifest_path.read_text())['montage'], 'complete')

    def test_unsaid_tip_does_not_make_a_video(self):
        with tempfile.TemporaryDirectory() as temp:
            recorder = SpeechHighlightsRecorder(temp)
            recorder.preview(sample_jpeg(), 1_000_000_000, 0)
            recorder.seal()
            self.assertIsNone(compile_highlights(temp))
            self.assertEqual(list((Path(temp) / 'speech-highlights').glob('*.mp4')), [])


if __name__ == '__main__':
    unittest.main()
