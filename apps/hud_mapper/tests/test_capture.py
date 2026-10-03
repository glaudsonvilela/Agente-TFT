"""Capture contracts use synthetic packets; actual WGC is separately required in Windows CI."""
import io, json, struct, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
from hm.capture_source import capture_target, read_packet, target_signature, CaptureSource, CapturedFrame
from hm.capture_app import target_label
from hm.input_source import InputPlan, source_group
from hm.dataset import Store


def packet(h, data=b''):
    raw=json.dumps(h).encode();return io.BytesIO(struct.pack('<I',len(raw))+raw+data)

class CaptureContracts(unittest.TestCase):
    def frame(self):
        return dict(type='frame',bytes=6,width=2,height=1,stride_bytes=6,pixel_format='RGB8',capture_ns=123)
    def test_valid_target(self):self.assertEqual(capture_target('capture://monitor/aF'),('monitor','af'))
    def test_no_arbitrary_url(self):
        for s in ('http://x','capture://monitor/0','capture://driver/1','capture://window/12?hidden=1','capture://window/../a'):
            with self.assertRaises(ValueError):capture_target(s)
    def test_consent_required_before_platform_access(self):
        with self.assertRaises(ValueError):CaptureSource('capture://window/1','x',3,4)
    def test_bgra_not_mislabelled_rgb(self):
        h=self.frame();h['pixel_format']='BGRA8'
        with self.assertRaises(ValueError):read_packet(packet(h,b'123456'))
    def test_stride_rejected(self):
        h=self.frame();h['stride_bytes']=8
        with self.assertRaises(ValueError):read_packet(packet(h,b'123456'))
    def test_truncated_packet(self):
        with self.assertRaises(EOFError):read_packet(packet(self.frame(),b'123'))
    def test_valid_pixels_preserved(self):self.assertEqual(read_packet(packet(self.frame(),b'\x00\x01\x02\x03\x04\x05'))[1],bytes(range(6)))
    def test_preview_pixels_have_the_same_strict_rgb_contract(self):
        h=self.frame();h.update(type='preview',source_width=4,source_height=2)
        self.assertEqual(read_packet(packet(h,b'\x00\x01\x02\x03\x04\x05'))[1],bytes(range(6)))
        h['stride_bytes']=8
        with self.assertRaises(ValueError):read_packet(packet(h,b'123456'))
    def test_control_packet_has_no_pixels(self):
        with self.assertRaises(ValueError):read_packet(packet(dict(type='ready',bytes=1),b'x'))
    def test_header_budget(self):
        with self.assertRaises(ValueError):read_packet(io.BytesIO(struct.pack('<I',1000000)))
    def test_capture_plan_is_not_video_hash(self):
        o=N(video='capture://monitor/123',capture_consent=True,scenario='multi-monitor')
        p=InputPlan(o,'a'*32)
        self.assertIsNone(p.info['sha256']);self.assertFalse(p.info['closed_local_file'])
        self.assertEqual(source_group(p.info),'capture:'+'a'*32)
    def test_capture_plan_refuses_consent_missing(self):
        with self.assertRaises(ValueError):InputPlan(N(video='capture://monitor/1',capture_consent=False),'a'*32)
    def test_source_selection_identity_includes_pid(self):
        a=dict(kind='window',id='abc',pid=1,label='TFT',device='')
        self.assertNotEqual(target_signature(a),target_signature(dict(a,pid=2)))
    def test_negative_monitor_origin_is_preserved(self):
        m=dict(kind='monitor',id='1',device='DISPLAY2',label='Second',adapter='GPU',bounds=[-1920,0,0,1080])
        self.assertIn('1920 × 1080',target_label(m));self.assertEqual(m['bounds'][0],-1920)
    def test_two_monitor_labels_distinct(self):
        m=dict(kind='monitor',label='Monitor',adapter='GPU',bounds=[0,0,1920,1080])
        self.assertNotEqual(target_label(dict(m,device='DISPLAY1')),target_label(dict(m,device='DISPLAY2')))
    def test_bad_video_hash_not_capture(self):
        with self.assertRaises(ValueError):source_group(dict(sha256='capture:abc'))
    def test_native_metadata_saved_with_png(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'session',max_samples=2,max_bytes=1024**2,reserve_bytes=0)
            f=CapturedFrame(7,10.,100,120,2,1,b'\xff\x00\x00\x00\xff\x00',3,dict(capture_ns=90,geometry_segment=3))
            store.emit('periodic',dict(frame_id=7,source_ms=10.),f,True)
            result=store.close(dict(session_id='test',source=dict(source_kind='native_capture',split_unit='capture_session_id'),execution_complete=True))
            m=json.loads((Path(d)/'session/training-manifest.json').read_text())
            self.assertEqual(m['split_unit'],'capture_session_id')
            self.assertEqual(m['samples'][0]['capture']['capture_ns'],90)
            self.assertEqual(m['samples'][0]['geometry_segment'],3)
            self.assertIsNone(m['samples'][0]['targets'])

    def test_long_capture_keeps_early_and_late_samples_without_exceeding_budget(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'session',max_samples=4,max_bytes=1024**2,reserve_bytes=0)
            for i in range(24):
                f=CapturedFrame(i,i*10000.,i+1,i+2,2,1,bytes([i,0,0,i,0,0]),0,{})
                while not store.emit('periodic',dict(frame_id=i,source_ms=f.pts_ms),f,True):
                    time.sleep(.001)
            result=store.close(dict(session_id='test',source=dict(source_kind='native_capture'),execution_complete=True))
            rows=json.loads((Path(d)/'session/training-manifest.json').read_text())['samples']
            self.assertTrue(result['execution_complete'])
            self.assertEqual(rows[0]['frame_id'],0)
            self.assertGreaterEqual(rows[-1]['frame_id'],16)
            self.assertLessEqual(len(rows),4)
            self.assertGreater(result['collection']['sample_evicted'],0)
            self.assertTrue(all((Path(d)/'session'/row['image']).is_file() for row in rows))

    def test_log_budget_drops_telemetry_without_ending_capture(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'session',max_samples=2,max_bytes=1024**2,
                        reserve_bytes=0,max_log_bytes=180)
            for i in range(15):
                while not store.emit('telemetry',dict(frame_id=i,note='x'*40)):
                    time.sleep(.001)
            result=store.close(dict(session_id='test',source={},execution_complete=True))
            self.assertTrue(result['execution_complete'])
            self.assertGreater(result['collection']['log_budget_dropped'],0)
            self.assertLessEqual(result['collection']['log_bytes'],180)

if __name__=='__main__':unittest.main()
