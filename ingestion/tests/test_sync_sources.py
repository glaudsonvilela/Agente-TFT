from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingestion.sync_sources import (
    SourceSpec,
    is_fresh,
    read_manifest,
    sha256_bytes,
    sync_source,
)


class SyncSourcesTests(unittest.TestCase):
    def test_sha256_is_deterministic(self) -> None:
        self.assertEqual(
            sha256_bytes(b'{"ok":true}'),
            sha256_bytes(b'{"ok":true}'),
        )

    def test_sync_json_source_writes_payload_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "raw"
            manifest = output / "manifest.json"
            payload = b'{"hello":"tft"}'

            with patch(
                "ingestion.sync_sources.fetch_bytes",
                return_value=(payload, {"etag": "abc"}),
            ):
                result = sync_source(
                    "fixture",
                    SourceSpec(
                        url="https://example.invalid/fixture.json",
                        format="json",
                        ttl_seconds=3600,
                    ),
                    output,
                    manifest,
                    force=True,
                    now_epoch=1000,
                )

            self.assertEqual(result["status"], "updated")
            self.assertEqual(
                (output / "fixture.json").read_bytes(),
                payload,
            )

            parsed = read_manifest(manifest)
            entry = parsed["sources"]["fixture"]
            self.assertEqual(entry["sha256"], sha256_bytes(payload))
            self.assertEqual(entry["etag"], "abc")
            self.assertEqual(entry["downloaded_at_epoch"], 1000)

    def test_fresh_cache_skips_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "raw"
            output.mkdir()
            target = output / "fixture.json"
            target.write_text("{}", encoding="utf-8")
            manifest = output / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "manifest_version": 1,
                        "sources": {
                            "fixture": {
                                "downloaded_at_epoch": 1000,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(
                is_fresh(
                    read_manifest(manifest),
                    "fixture",
                    target,
                    ttl_seconds=3600,
                    now_epoch=1200,
                )
            )


if __name__ == "__main__":
    unittest.main()
