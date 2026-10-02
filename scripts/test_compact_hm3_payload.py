import struct
import tempfile
import unittest
from pathlib import Path
from compact_hm3_payload import pe_imports, compact_payload


def image(names=(), delayed=False):
    data=bytearray(4096);data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,0x80)
    data[0x80:0x84]=b'PE\0\0';struct.pack_into('<H',data,0x86,1);struct.pack_into('<H',data,0x94,240)
    opt=0x98;struct.pack_into('<H',data,opt,0x20b);struct.pack_into('<Q',data,opt+24,0x140000000)
    struct.pack_into('<I',data,opt+60,512);struct.pack_into('<I',data,opt+108,16)
    struct.pack_into('<IIII',data,opt+240+8,3584,0x1000,3584,512)
    count=len(names);size=32 if delayed else 20;idx=13 if delayed else 1
    struct.pack_into('<II',data,opt+112+idx*8,0x1000,(count+1)*size)
    name_offset=0x600
    for i,name in enumerate(names):
        rva=0x1000+name_offset-512
        fields=(1,rva,0,0,0,0,0,0) if delayed else (0,0,0,rva,0)
        struct.pack_into('<'+'I'*len(fields),data,512+i*size,*fields)
        raw=name.encode()+b'\0';data[name_offset:name_offset+len(raw)]=raw;name_offset+=len(raw)
    return bytes(data)


class CompactionTests(unittest.TestCase):
    def make(self, root):
        t=root/'_internal/tesseract';t.mkdir(parents=True)
        (t/'tesseract.exe').write_bytes(image(['private.dll']))
        for name,deps in [('private.dll',[]),('shared.dll',['child.dll']),('child.dll',[])]:
            for folder in (t,t.parent):(folder/name).write_bytes(image(deps))
        (root/'app.exe').write_bytes(image(['shared.dll']))
        return t
    def test_imports(self):self.assertEqual(pe_imports(image(['KERNEL32.dll'])),{'kernel32.dll'})
    def test_delay_imports(self):self.assertEqual(pe_imports(image(['DELAY.dll'],True)),{'delay.dll'})
    def test_truncation_refused(self):
        with self.assertRaises(ValueError):pe_imports(b'MZ')
    def test_shared_dependency_closure_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);t=self.make(root);r=compact_payload(root)
            self.assertEqual(r['retained_shared_dlls'],['child.dll','shared.dll'])
            self.assertTrue((t/'private.dll').is_file());self.assertFalse((t.parent/'private.dll').exists())
    def test_nonidentical_names_not_removed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);t=self.make(root);(t.parent/'private.dll').write_bytes(image(['different.dll']))
            compact_payload(root);self.assertTrue((t.parent/'private.dll').is_file())
    def test_invalid_pe_aborts_before_removal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);t=self.make(root);(root/'broken.pyd').write_bytes(b'MZ')
            with self.assertRaises(ValueError):compact_payload(root)
            self.assertTrue((t.parent/'private.dll').is_file())
    def test_development_data_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make(root);test=root/'_internal/onnx/backend/test';test.mkdir(parents=True)
            (test/'fixture.pb').write_bytes(b'fixture');model=root/'model.onnx';model.write_bytes(b'keep')
            compact_payload(root);self.assertFalse(test.exists());self.assertEqual(model.read_bytes(),b'keep')
    def test_sealed_or_installed_payload_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);t=self.make(root);(root/'BUILD_MANIFEST.json').write_text('{}')
            with self.assertRaises(ValueError):compact_payload(root)
            self.assertTrue((t.parent/'private.dll').is_file())


if __name__=='__main__':unittest.main()
