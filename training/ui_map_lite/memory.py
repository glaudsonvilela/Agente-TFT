"""Process telemetry, not a model-size estimator. No training dependencies."""
from pathlib import Path
import resource


def snapshot():
    # ru_maxrss may retain a pre-exec peak. Keep it raw, but also read the
    # current process image's VmRSS/VmHWM instead of labeling it model RAM.
    result = dict(current_rss_kib=None, current_image_hwm_kib=None,
                  rusage_maxrss_raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  source="/proc/self/status",
                  note="Process includes interpreter, runtime and loaded data; not neural weights alone. Raw rusage may retain a pre-exec peak.")
    try:
        lines = Path('/proc/self/status').read_text().splitlines()
        for label, key in [('VmRSS:', 'current_rss_kib'), ('VmHWM:', 'current_image_hwm_kib')]:
            for line in lines:
                tokens = line.split()
                if len(tokens) == 3 and tokens[0] == label and tokens[2] == 'kB':
                    result[key] = int(tokens[1])
                    break
    except (OSError, ValueError):
        result['source'] = 'unavailable'
    return result
