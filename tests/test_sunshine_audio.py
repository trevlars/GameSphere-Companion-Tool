import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SunshineAudioTests(unittest.TestCase):
    def test_overwrites_stereo_channels_and_dedupes(self):
        from host_tuning import sunshine_audio

        original = (
            "audio_sink = bazzite-stream-surround51\n"
            "channels = 2\n"
            "hevc_mode = 0\n"
            "channels = 2\n"
        )
        tmp = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
        tmp.write(original)
        tmp.close()
        try:
            with mock.patch.object(sunshine_audio, "CAPTURE_SCRIPT", tmp.name + ".missing"), mock.patch.object(
                sunshine_audio, "PERSIST_MODE", tmp.name + ".mode"
            ), mock.patch.dict(os.environ, {"BAZZITE_STREAM_AUDIO": "surround51"}, clear=False):
                # manage_tap via bazzite-stream in conf
                result = sunshine_audio.apply_stream_audio(
                    tmp.name, dry_run=False, run_capture_ensure=False
                )
            self.assertTrue(result["ok"])
            self.assertIn("channels", result["changed"])
            with open(tmp.name, encoding="utf-8") as fh:
                text = fh.read()
            self.assertEqual(text.count("channels ="), 1)
            self.assertIn("channels = 6", text)
            self.assertIn("audio_sink = bazzite-stream-surround51", text)
            self.assertIn("hevc_mode = 0", text)
            self.assertNotIn("channels = 2", text)
        finally:
            os.unlink(tmp.name)

    def test_stereo_mode_pins_2ch(self):
        from host_tuning import sunshine_audio

        tmp = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
        tmp.write("audio_sink = bazzite-stream-surround51\nchannels = 6\n")
        tmp.close()
        try:
            with mock.patch.dict(os.environ, {"BAZZITE_STREAM_AUDIO": "stereo"}, clear=False):
                result = sunshine_audio.apply_stream_audio(
                    tmp.name, dry_run=False, run_capture_ensure=False
                )
            self.assertTrue(result["ok"])
            with open(tmp.name, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("channels = 2", text)
            self.assertIn("audio_sink = bazzite-stream-stereo", text)
        finally:
            os.unlink(tmp.name)

    def test_skips_generic_hosts_without_tap(self):
        from host_tuning import sunshine_audio

        tmp = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
        tmp.write("upnp = disabled\nchannels = 2\n")
        tmp.close()
        try:
            with mock.patch.object(sunshine_audio, "CAPTURE_SCRIPT", "/no/such/capture"), mock.patch.object(
                sunshine_audio, "PERSIST_MODE", "/no/such/persist"
            ), mock.patch.object(sunshine_audio, "ENV_DROPIN", "/no/such/env"):
                os.environ.pop("BAZZITE_STREAM_AUDIO", None)
                result = sunshine_audio.apply_stream_audio(
                    tmp.name, dry_run=False, run_capture_ensure=False
                )
            self.assertTrue(result["ok"])
            self.assertTrue(result.get("skipped"))
            with open(tmp.name, encoding="utf-8") as fh:
                text = fh.read()
            self.assertEqual(text, "upnp = disabled\nchannels = 2\n")
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
