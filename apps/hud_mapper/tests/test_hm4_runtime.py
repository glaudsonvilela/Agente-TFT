import json, os, tempfile, unittest
from pathlib import Path

from hm.runtime_app import _valid_candidate_model
from hm.runtime_session import (
    HM4RuntimeSession, reader_plan, materialize_reader_frame, regions_to_source,
    async_hp_delivery
)
from hm.session import Options, neural_provenance, completion_state
from hm.capture_source import CapturedFrame
from hm.core import neural_regions


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
        self.assertEqual(HM4RuntimeSession.shop_interval_ms,2000.0)
        self.assertEqual(HM4RuntimeSession.__mro__[1].shop_interval_ms,0.0)
        self.assertTrue(HM4RuntimeSession.separate_hp_loop)
        self.assertEqual(HM4RuntimeSession.hp_hz,1.0)
        self.assertEqual(HM4RuntimeSession.hp_max_delivery_ms,2000.0)
        self.assertEqual(HM4RuntimeSession.native_worker_env,{"AGENTE_TFT_RESIDENT_OCR":"auto"})
        self.assertIsNone(getattr(HM4RuntimeSession.__mro__[1],"native_worker_env",None))
        self.assertIn("automatic", HM4RuntimeSession.primary_objective)

    def test_summary_neural_provenance_is_shadow_or_disabled(self):
        enabled=neural_provenance(True)
        disabled=neural_provenance(False)
        self.assertEqual(enabled["neural_mode"],"shadow_diagnostic")
        self.assertEqual(disabled["neural_mode"],"disabled")
        for row in (enabled,disabled):
            self.assertFalse(row["neural_training_label_allowed"])
            self.assertFalse(row["neural_game_state_write_allowed"])
            self.assertFalse(row["neural_reader_input_allowed"])

    def test_neural_regions_are_explicit_shadow_only(self):
        raw=[[[0.10,0.20,0.40,0.30,3.0],[0.20,0.50,0.80,0.70,3.0]]]
        regions=neural_regions(raw,1920,1080)
        self.assertEqual([r["id"] for r in regions],["neural.bench","neural.shop"])
        for reg in regions:
            self.assertTrue(reg["shadow_only"])
            self.assertEqual(reg["shadow_mode"],"diagnostic_only")
            self.assertFalse(reg["ground_truth"])
            self.assertFalse(reg["training_label_allowed"])
            self.assertFalse(reg["game_state_write_allowed"])
            self.assertFalse(reg["reader_input_allowed"])
            self.assertFalse(reg["map_usable_by_readers"])


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

    def test_async_hp_delivery_is_causal_and_bounded(self):
        f=self.frame(1920,1080)
        f=CapturedFrame(id=10,pts_ms=3000.0,due_ns=3_000_000_000,ready_ns=3_000_000_100,
                        width=1920,height=1080,rgb=f.rgb,epoch=2,capture={"test":True})
        latest=dict(frame_id=8,source_ms=2000.0,due_ns=2_000_000_000,ready_ns=2_900_000_000,epoch=2,
                    response={"hp":{"status":"accepted","signed_hp":72,"hp":72}})
        hp,meta=async_hp_delivery(f,latest,2000.0)
        self.assertEqual(hp["status"],"accepted")
        self.assertEqual(hp["hp"],72)
        self.assertEqual(meta["source_frame_id"],8)
        self.assertEqual(meta["age_ms"],1000.0)
        self.assertTrue(meta["fresh"])

        future=dict(latest,frame_id=11,due_ns=3_100_000_000)
        hp,meta=async_hp_delivery(f,future,2000.0)
        self.assertEqual(hp["status"],"async_pending")
        self.assertFalse(meta["fresh"])

        stale=dict(latest,due_ns=500_000_000)
        hp,meta=async_hp_delivery(f,stale,2000.0)
        self.assertEqual(hp["status"],"async_stale")
        self.assertIsNone(hp["hp"])
        self.assertEqual(hp["last_observation"]["hp"],72)
        self.assertFalse(meta["fresh"])

    def test_graceful_stop_is_complete_but_errors_are_partial(self):
        graceful=completion_state(None,True,True)
        self.assertTrue(graceful["execution_complete"])
        self.assertFalse(graceful["cancelled"])
        self.assertTrue(graceful["stopped_by_user"])
        natural=completion_state(None,False,False)
        self.assertTrue(natural["execution_complete"])
        failed=completion_state("boom",True,True)
        self.assertFalse(failed["execution_complete"])

if __name__=="__main__":
    unittest.main()
