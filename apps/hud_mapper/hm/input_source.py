"""One source boundary for HM1 replay and HM2 explicit native capture."""
from pathlib import Path
from .core import sha


class InputPlan:
    def __init__(self, options, session_id):
        self.options = options
        self.capture = str(options.video).startswith('capture://')
        self.source = None
        if self.capture:
            from .capture_source import capture_target
            kind, identity = capture_target(options.video)
            if options.capture_consent is not True:
                raise ValueError('Confirme o monitor/janela antes de registrar imagens.')
            self.path = None; self.identity = None
            self.info = dict(source_kind='native_capture', path=None, sha256=None,
                capture_session_id=session_id, split_group='capture:'+session_id,
                split_unit='capture_session_id_not_independent_match',
                selected_kind=kind, selected_id=identity, scenario=options.scenario,
                closed_local_file=False, consented=True, source_hashed_before_measurement=False,
                latency_basis='native_QPC_acquisition_before_readback_not_compositor_or_scanout',
                identity_basis='explicit_target_selection_not_TFT_account_identity')
        else:
            from e1.source import local_video
            self.path = local_video(options.video)
            self.identity = (self.path.stat().st_size, self.path.stat().st_mtime_ns)
            digest = sha(self.path)
            if self.identity != (self.path.stat().st_size, self.path.stat().st_mtime_ns):
                raise ValueError('Vídeo mudou durante a verificação.')
            self.info = dict(source_kind='closed_video', path=str(self.path), sha256=digest,
                bytes=self.identity[0], scenario=options.scenario, closed_local_file=True,
                split_group=digest, split_unit='source_video_sha256',
                source_hashed_before_measurement=True, cold_disk_benchmark=False)

    def start(self):
        o = self.options
        if self.capture:
            from .capture_source import CaptureSource, native_path
            capture_hz=max(o.map_hz,o.reader_hz,o.sample_hz,
                           o.preview_hz if o.vm_core else 0)
            self.source = CaptureSource(o.video, o.configs, o.seconds, capture_hz,
                consent=o.capture_consent, expected=o.capture_expected,
                log=Path(o.output)/'capture-stderr.log')
            self.info.update(native=self.source.ready, clock_bridge=self.source.bridge.metadata(),
                             native_binary_sha256=sha(native_path(o.configs)))
        else:
            from e1.source import VideoSource
            self.source = VideoSource(o.video, o.ffmpeg, o.ffprobe)
        return self.source

    def verify(self, cancelled=False):
        if self.capture:
            if self.source:
                self.info['source_queue_replaced'] = self.source.source_replaced
                self.info['compositor_clock_anomalies'] = self.source.clock_anomalies
                self.info['latency_basis'] = 'native_QPC_acquisition_before_readback_not_compositor_or_scanout'
                self.info['geometry_events'] = list(self.source.control_events)
                self.info['native_end'] = self.source.end
                if self.source.error and not cancelled:
                    raise RuntimeError(self.source.error)
            return
        if self.identity != (self.path.stat().st_size, self.path.stat().st_mtime_ns):
            raise ValueError('Vídeo alterado durante a sessão.')


def source_group(source):
    """Grouping key is not necessarily a file hash, and never proof of a separate match."""
    if source.get('source_kind') == 'synthetic_fixture':
        group=source.get('sha256')
        if not isinstance(group,str) or not group.startswith('synthetic-'):
            raise ValueError('Identidade da fixture inválida.')
        return group
    if source.get('source_kind') == 'native_capture':
        group = source.get('split_group')
        if not isinstance(group,str) or not group.startswith('capture:') or len(group)<12:
            raise ValueError('Identidade de sessão de captura ausente.')
        return group
    group = source.get('sha256')
    if not isinstance(group,str) or len(group)!=64 or any(c not in '0123456789abcdef' for c in group):
        raise ValueError('Hash do vídeo de origem inválido.')
    return group
