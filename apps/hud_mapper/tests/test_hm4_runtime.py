import json, os, tempfile, unittest
from pathlib import Path

from hm.runtime_app import _valid_candidate_model
from hm.runtime_session import HM4RuntimeSession
from hm.session import Options

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
        self.assertIn("automatic", HM4RuntimeSession.primary_objective)

if __name__=="__main__":
    unittest.main()
