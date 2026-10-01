import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from training.player_hp_dense import (
    analyze_window, build_plan, extract_window, parse_pts, validate_reads,
    video_metadata, write_json, MAX_WINDOWS,
)


def row(at, hp=None, status="accepted", located=True):
    return {"read": {"timestamp_ms": at, "status": status, "hp": hp,
                     "signed_hp": hp, "confidence": 0.95 if hp is not None else None,
                     "location": {"candidates": [{}] if located else []}},
            "freshness": {"current": None}}


def report(rows):
    return {"records": rows, "summary": {"game_state_updated": False, "profile_promoted": False}}


class PlannerTests(unittest.TestCase):
    def test_increase_is_selected_without_correcting_value(self):
        r = report([row(10000, 36), row(60000, 56), row(110000, 36)])
        before = copy.deepcopy(r)
        plan = build_plan(r)
        self.assertEqual(r, before)
        self.assertIn(60000, [w["center_ms"] for w in plan["windows"]])
        self.assertIn("observed_increase_not_proven_error", plan["windows"][1]["reasons"])
        self.assertTrue(plan["selection_is_retrospective"])

    def test_failures_are_selected_and_prehud_is_not_called_drift(self):
        r = report([row(0, status="badge_not_found", located=False), row(10000, 100),
                    row(60000, status="ocr_uncertain"), row(110000, status="badge_not_found", located=False)])
        self.assertEqual([w["center_ms"] for w in build_plan(r)["windows"]], [10000, 60000, 110000])

    def test_labels_and_suggestions_never_choose_answer_or_window(self):
        a = report([row(10000, 36), row(60000, 56)])
        b = copy.deepcopy(a)
        b["records"][1].update(expected=36, suggestions={"hp": 36}, correct=False)
        self.assertEqual(build_plan(a), build_plan(b))

    def test_budget_is_bounded_and_omissions_are_explicit(self):
        r = report([row(1000, 100)] + [row(10000 + i * 5000, status="ocr_uncertain") for i in range(30)])
        plan = build_plan(r)
        self.assertEqual(len(plan["windows"]), MAX_WINDOWS)
        self.assertEqual(len(plan["skipped_budget"]), 30 - MAX_WINDOWS + 1)

    def test_nearby_events_do_not_create_overlapping_sessions(self):
        r = report([row(1000, 100), row(1500, status="ocr_uncertain")])
        windows = build_plan(r)["windows"]
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["nearby_events"][0]["center_ms"], 1500)

    def test_duplicate_out_of_order_and_invalid_records_fail(self):
        for rows in ([row(2000, 100), row(2000, 100)], [row(2000, 100), row(1000, 100)],
                     [row(True, 100)], [row(1000, 301)], [row(1000, True)]):
            with self.assertRaises(ValueError):
                validate_reads(report(rows))

    def test_new_file_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "evidence.json"
            write_json(p, {"value": 1})
            with self.assertRaises(FileExistsError):
                write_json(p, {"value": 2})
            self.assertEqual(json.loads(p.read_text()), {"value": 1})


class PtsTests(unittest.TestCase):
    def test_pts_not_requested_counter_and_rounding_never_goes_back(self):
        log = "config in time_base: 1/30000, frame_rate: 30000/1001\n"
        log += "n: 0 pts: 1001 pts_time:0.0333667 checksum:ABCDE123\n"
        log += "n: 1 pts: 9009 pts_time:0.3003 checksum:ABCD1234\n"
        rows = parse_pts(log)
        self.assertEqual([r["timestamp_ms"] for r in rows], [34, 301])
        self.assertEqual(rows[1]["source_pts"], 9009)

    def test_repeated_pts_or_missing_metadata_fail(self):
        for log in ("n: 0 pts: 0 pts_time:0 checksum:ABCD\n",
                    "config in time_base: 1/1000\nn: 0 pts: 5 pts_time:0 checksum:ABCD\n"
                    "n: 1 pts: 5 pts_time:0 checksum:ABCD\n"):
            with self.assertRaises(ValueError):
                parse_pts(log)


class AnalysisTests(unittest.TestCase):
    def test_temporal_increase_is_flag_not_correction_or_accuracy(self):
        r = report([row(1000, 36), row(1250, 56), row(1500, 36)])
        m = {"window": {"id": "test"}, "frames": [
            {"timestamp_ms": at, "decoded_checksum": "same"} for at in (1000, 1250, 1500)]}
        before = copy.deepcopy(r)
        result = analyze_window(r, m)
        self.assertEqual(result["flags"][0]["to"], 56)
        self.assertEqual(result["confirmed_frames"], 0)
        self.assertEqual(result["repeated_decoded_checksums"], 2)
        self.assertEqual(r, before)

    def test_mismatched_manifest_is_not_summarized_as_success(self):
        with self.assertRaises(ValueError):
            analyze_window(report([row(1000, 36)]), {"frames": [{"timestamp_ms": 1001}]})

    def test_unknown_breaks_transition_chain(self):
        r = report([row(1000, 36), row(1250, status="ocr_uncertain"), row(1500, 56)])
        m = {"window": {}, "frames": [{"timestamp_ms": at, "decoded_checksum": "x"} for at in (1000,1250,1500)]}
        self.assertEqual(analyze_window(r,m)["flags"], [])


class MediaTests(unittest.TestCase):
    def setUp(self):
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            if os.getenv("TFT_HP2_REQUIRE_MEDIA"):
                self.fail("required FFmpeg/FFprobe missing")
            self.skipTest("FFmpeg/FFprobe unavailable")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / "source.mkv"
        subprocess.run(["ffmpeg","-nostdin","-v","error","-f","lavfi","-i",
                        "color=c=black:s=96x64:r=20:d=6", "-c:v","ffv1", "-threads","1", str(self.video)],
                       check=True, timeout=30)

    def test_dense_extraction_has_distinct_real_pts_and_no_overwrite(self):
        meta = video_metadata(self.video)
        self.assertEqual(meta["streams"][0]["width"], 96)
        w = {"id":"window-00","center_ms":3000,"start_ms":2000,"end_ms":4001}
        m = extract_window(self.video,w,self.root/"clip",6000)
        times = [r["timestamp_ms"] for r in m["frames"]]
        self.assertEqual(times, list(range(2000,4001,250)))
        self.assertTrue(all((self.root/"clip"/r["image"]).is_file() for r in m["frames"]))
        # Real static video may contain identical pictures; never claim independent evidence.
        self.assertEqual(len({r["decoded_checksum"] for r in m["frames"]}), 1)
        with self.assertRaises(FileExistsError):
            extract_window(self.video,w,self.root/"clip",6000)

    def test_native_rust_probe_consumes_pts_manifest_without_labels(self):
        binary = os.getenv("TFT_HP2_PROBE_BIN")
        if not binary:
            if os.getenv("TFT_HP2_REQUIRE_MEDIA"):
                self.fail("required native HP1 probe path missing")
            self.skipTest("native Rust probe unavailable locally")
        w = {"id":"window-00","center_ms":3000,"start_ms":2000,"end_ms":4001}
        folder = self.root/"clip"
        m = extract_window(self.video,w,folder,6000)
        profile = {"schema_version":1,"name":"blank-fixture","reference_width":96,"reference_height":64,
                   "search_rect":{"x":0,"y":0,"width":96,"height":64},
                   "anchor_width":26,"anchor_height":49,"gold_points":[[1,1],[2,2]],"dark_points":[[12,12]],
                   "min_gold_fraction":0.94,"min_dark_fraction":0.85,"nms_radius_px":14,"max_raw_peaks":256,
                   "hp_offset_x":18,"hp_offset_y":12,"hp_width":44,"hp_height":25,"max_hp_abs":300,"min_confidence":0.70}
        write_json(self.root/"profile.json",profile)
        result = subprocess.run([binary,str(folder/"manifest.json"),str(folder),str(self.root/"profile.json"),str(folder/"report.json")],
                                capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors="replace"))
        r = json.loads((folder/"report.json").read_text())
        summary = analyze_window(r,m)
        self.assertEqual(summary["statuses"],{"badge_not_found":9})
        self.assertEqual(summary["confirmed_frames"],0)

    def test_nonzero_timestamp_origin_is_explicitly_rejected(self):
        other = self.root/"nonzero.mkv"
        subprocess.run(["ffmpeg","-nostdin","-v","error","-i",str(self.video),"-vf","setpts=PTS+5/TB",
                        "-c:v","ffv1","-threads","1",str(other)],check=True,timeout=30)
        with self.assertRaises(ValueError):
            video_metadata(other)

    def test_beyond_eof_fails_before_decoding(self):
        with self.assertRaises(ValueError):
            extract_window(self.video,{"center_ms":7000,"start_ms":6000,"end_ms":8001},self.root/"bad",6000)


if __name__ == "__main__":
    unittest.main()
