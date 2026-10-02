"""Conservative build-directory compaction; never touches installed/user files.

Retain Tesseract's complete private DLL directory. Remove root-level *identical*
DLL copies only when no remaining PE binary imports them, including delay imports.
Remove development test-data directories, never models supplied by the user.
"""
from pathlib import Path
import hashlib
import struct


def pe_imports(data):
    """Read PE import names without executing/loading the binary; fail closed."""
    def unpack(fmt, offset):
        if offset < 0 or offset + struct.calcsize(fmt) > len(data):
            raise ValueError('Truncated PE structure')
        return struct.unpack_from(fmt, data, offset)
    if data[:2] != b'MZ':
        raise ValueError('Not a PE image')
    pe = unpack('<I', 0x3c)[0]
    if data[pe:pe+4] != b'PE\0\0':
        raise ValueError('Invalid PE signature')
    sections = unpack('<H', pe+6)[0]
    optional_size = unpack('<H', pe+20)[0]
    optional = pe+24
    magic = unpack('<H', optional)[0]
    if magic == 0x20b:
        directory, count_at, image_base = optional+112, optional+108, unpack('<Q', optional+24)[0]
    elif magic == 0x10b:
        directory, count_at, image_base = optional+96, optional+92, unpack('<I', optional+28)[0]
    else:
        raise ValueError('Unsupported PE format')
    if not 1 <= sections <= 96:
        raise ValueError('Invalid PE sections')
    header_size = unpack('<I', optional+60)[0]
    section_map = [unpack('<IIII', optional+optional_size+i*40+8) for i in range(sections)]
    def file_offset(rva):
        if 0 <= rva < min(header_size, len(data)):
            return rva
        for virtual_size, virtual_address, raw_size, raw_at in section_map:
            delta = rva-virtual_address
            if 0 <= delta < raw_size and delta < max(virtual_size, raw_size):
                at = raw_at+delta
                if at < len(data):
                    return at
        raise ValueError('Unmapped import RVA')
    def name_at(rva):
        at = file_offset(rva)
        end = data.find(b'\0', at, min(len(data), at+512))
        if end == -1:
            raise ValueError('Unterminated import name')
        return data[at:end].decode('ascii').lower()
    count = unpack('<I', count_at)[0]
    names = set()
    for index, record_size, name_field in ((1, 20, 3), (13, 32, 1)):
        if count <= index:
            continue
        rva, size = unpack('<II', directory+index*8)
        if not rva:
            continue
        at = file_offset(rva)
        for i in range(min(4096, size//record_size+1)):
            fields = unpack('<'+'I'*(record_size//4), at+i*record_size)
            if not any(fields):
                break
            name_rva = fields[name_field]
            if index == 13 and not fields[0] & 1:
                name_rva -= image_base
            names.add(name_at(name_rva))
        else:
            raise ValueError('Unbounded PE imports')
    return names


def compact_payload(folder):
    folder = Path(folder).resolve(strict=True)
    if (folder/'BUILD_MANIFEST.json').exists():
        raise ValueError('Already sealed/installed payload; build a fresh directory')
    internal = folder/'_internal'
    tesseract = internal/'tesseract'
    if not internal.is_dir() or not (tesseract/'tesseract.exe').is_file():
        raise ValueError('Expected private HM3 build payload')
    if any(p.is_symlink() for p in folder.rglob('*')):
        raise ValueError('Do not compact symlinked payload')
    candidates = {}
    for private in tesseract.glob('*.dll'):
        duplicate = internal/private.name
        if duplicate.is_file() and duplicate.read_bytes() == private.read_bytes():
            candidates[private.name.lower()] = duplicate
    imports = {}
    roots = set()
    for path in folder.rglob('*'):
        if path.suffix.lower() not in {'.dll', '.pyd', '.exe'} or not path.is_file():
            continue
        if path.is_relative_to(tesseract):
            continue
        names = pe_imports(path.read_bytes())
        key = path.name.lower()
        if path.parent == internal and key in candidates:
            imports[key] = names
        else:
            roots.update(names)
    required = set()
    pending = list(roots & candidates.keys())
    while pending:
        key = pending.pop()
        if key in required:
            continue
        required.add(key)
        pending.extend((imports.get(key, set()) & candidates.keys())-required)
    removed = []
    def remove(path, reason):
        raw = path.read_bytes()
        removed.append(dict(path=path.relative_to(folder).as_posix(), bytes=len(raw),
                            sha256=hashlib.sha256(raw).hexdigest(), reason=reason))
        path.unlink()
    for name, path in candidates.items():
        if name not in required:
            remove(path, 'identical_copy_retained_beside_tesseract_no_other_PE_importer')
    for relative in ('onnx/backend/test', 'onnx/test', 'onnx/tests'):
        directory = internal/relative
        if directory.is_dir():
            for path in directory.rglob('*'):
                if path.is_file():
                    remove(path, 'development_test_data_not_runtime_input')
            for path in sorted(directory.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if path.is_dir():
                    path.rmdir()
            directory.rmdir()
    return dict(policy='hm3_private_payload_compaction_v1', removed_files=removed,
                removed_bytes=sum(x['bytes'] for x in removed), retained_shared_dlls=sorted(required),
                tesseract_private_dlls_preserved=True, execution_tests_required=True)
