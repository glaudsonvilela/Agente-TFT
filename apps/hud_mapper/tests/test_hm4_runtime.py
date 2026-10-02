import json, os, tempfile, unittest
from pathlib import Path

from hm.runtime_app import _valid_candidate_model
from hm.runtime_session import (
    HM4RuntimeSession, reader_plan, materialize_reader_frame, regions_to_source
)
from hm.session import Options
from hm.capture_source import CapturedFrame


class HM4RuntimeTests(unittest.TestCase):
    def test_reader_only_is_allowed_only_when_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            worker=Path(td)/("worker.exe" if os.name=="nt" else "worker")
            worker.write_bytes(b"x")
            Options(video="capture://window/1", output=td, model="", worker=str(worker),
                    configs=td, dataset_only=True).validate()
            with self.assertRaises(ValueError):
                Options(video="capture://window/1", output=td, model="", worker=str(worker),
                        configs=td, dataset_only=False).validate()

    def test_candidate_metadata_requires_neighbor_onnx(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            meta=p/"deployment-candidate.json"
            meta.write_text(json.dumps(dict(schema_version=2,coordinate_format="normalized_tlbr",
                                            panels=["bench","shop"])),encoding="utf-8")
            self.assertFalse(_valid_candidate_model(meta))
            (p/"candidate-model.onnx").write_bytes(b"not-loaded-by-discovery")
            self.assertTrue(_valid_candidate_model(meta))

    def test_hm4_policy_is_distinct(self):
        self.assertEqual(HM4RuntimeSession.policy_name,"hud_mapper_hm4_auto")
        self.assertTrue(HM4RuntimeSession.normalize_reader_input)
        self.assertIn("automatic", HM4RuntimeSession.primary_objective)

    def frame(self,w,h):
        return CapturedFrame(id=7,pts_ms=1000.0,due_ns=10,ready_ns=11,width=w,height=h,
                             rgb=bytes([17])*(w*h*3),epoch=2,capture={"test":True})

    def test_1280x720_has_explicit_reversible_reader_plan(self):
        f=self.frame(1280,720)
        plan=reader_plan(f,allow_normalize=True)
        self.assertTrue(plan["supported"])
        self.assertTrue(plan["normalized"])
        self.assertEqual(plan["reader_size"],[1920,1080])
        derived,elapsed=materialize_reader_frame(f,plan)
        self.assertEqual((derived.width,derived.height),(1920,1080))
        self.assertEqual(len(derived.rgb),1920*1080*3)
        self.assertGreaterEqual(elapsed,0)
        self.assertEqual((f.width,f.height),(1280,720))
        self.assertEqual(len(f.rgb),1280*720*3)

    def test_non_16_9_is_rejected_not_stretched(self):
        f=self.frame(1000,700)
        plan=reader_plan(f,allow_normalize=True)
        self.assertFalse(plan["supported"])
        self.assertEqual(plan["reason"],"source_aspect_ratio_not_16_9")
        derived,elapsed=materialize_reader_frame(f,plan)
        self.assertIsNone(derived)
        self.assertEqual(elapsed,0)

    def test_canonical_region_returns_to_source_coordinates(self):
        f=self.frame(1280,720)
        plan=reader_plan(f,allow_normalize=True)
        regions=[dict(id="hud.gold",box=[960,540,1920,1080],
                      coordinate_space="source_pixel_edges",ground_truth=False)]
        out=regions_to_source(regions,f,plan)
        self.assertEqual(out[0]["reader_box_1920x1080"],[960,540,1920,1080])
        self.assertEqual(out[0]["box"],[640.0,360.0,1280.0,720.0])
        self.assertEqual(regions[0]["box"],[960,540,1920,1080])

if __name__=="__main__":
    unittest.main()
