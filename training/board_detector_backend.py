"""Pinned public weights downloaded once, then fully local CPU inference. No remote Python or pickle."""
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import time
from training.board_detector_core import require, policy_contract, detections

FILES = ('config.json', 'preprocessor_config.json', 'tokenizer.json', 'tokenizer_config.json',
         'special_tokens_map.json', 'added_tokens.json', 'vocab.txt', 'model.safetensors')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def model_files(directory, policy):
    result = {}
    for name in FILES:
        path = directory/name
        require(path.is_file() and not path.is_symlink(), 'model snapshot missing/nonlocal file: '+name)
        require(0 < path.stat().st_size <= (750*1024*1024 if name.endswith('.safetensors') else 4*1024*1024),
                'model file byte budget: '+name)
        result[name] = digest(path)
    require(result['model.safetensors'] == policy['weights_sha256'], 'pretrained weights checksum mismatch')
    return result


def prepare_model(cache, policy):
    policy_contract(policy)
    os.environ.update(HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                      HF_HUB_DISABLE_XET='1', HF_HUB_DOWNLOAD_TIMEOUT='60', TOKENIZERS_PARALLELISM='false')
    from huggingface_hub import hf_hub_download
    directory = Path(cache)/policy['model_revision']
    directory.mkdir(parents=True, exist_ok=True)
    # Exact revision and explicit allowlist. pytorch_model.bin and repository code are never fetched.
    for name in FILES:
        if not (directory/name).is_file():
            print('BOARD3_DOWNLOAD='+name, flush=True)
            hf_hub_download(repo_id=policy['model_id'], revision=policy['model_revision'],
                            filename=name, local_dir=directory, token=False)
    hashes = model_files(directory, policy)
    stamp = directory/'BOARD3_FILES.json'
    if stamp.exists():
        require(json.loads(stamp.read_text()) == hashes, 'model auxiliary files changed after initial download')
    else:
        with stamp.open('x') as f:
            json.dump(hashes, f, sort_keys=True)
    return directory, hashes


def decode(path, width, height):
    """Same FFmpeg PPM conversion as B1. Decode once for this detector, no JPEG re-encoding."""
    from PIL import Image
    cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(path),
           '-map', '0:v:0', '-frames:v', '1', '-an', '-sn', '-c:v', 'ppm', '-f', 'image2pipe', 'pipe:1']
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=True)
    require(len(r.stdout) <= 64*1024*1024 and r.stdout.startswith(b'P6'), 'invalid decoded frame')
    image = Image.open(io.BytesIO(r.stdout))
    require(image.size == (width, height) and image.mode == 'RGB', 'decoded resolution/color mismatch')
    image.load()
    return image, hashlib.sha256(image.tobytes()).hexdigest()


class GroundedPresence:
    def __init__(self, cache, policy):
        self.policy = policy_contract(policy)
        started = time.perf_counter()
        self.directory, self.hashes = prepare_model(cache, policy)
        self.download_and_verify_ms = (time.perf_counter()-started)*1000
        os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        import torch
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
        torch.set_num_threads(policy['cpu_threads'])
        torch.set_num_interop_threads(1)
        self.torch = torch
        started = time.perf_counter()
        self.processor = AutoProcessor.from_pretrained(str(self.directory), local_files_only=True,
                                                       trust_remote_code=False, use_fast=False)
        self.model, loading = AutoModelForZeroShotObjectDetection.from_pretrained(
            str(self.directory), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, disable_custom_kernels=True, output_loading_info=True)
        require(not loading.get('missing_keys') and not loading.get('mismatched_keys') and
                not loading.get('error_msgs'), 'model weights did not load completely')
        self.model.to('cpu').eval()
        self.load_ms = (time.perf_counter()-started)*1000
        self.provenance = dict(model_id=policy['model_id'], revision=policy['model_revision'],
            files_sha256=self.hashes, pretrained_parameters=self.model.num_parameters(),
            model_class=type(self.model).__name__, prompt=policy['prompt'], device='cpu',
            cpu_threads=policy['cpu_threads'], remote_code=False, pickle_loaded=False,
            local_images_uploaded=False, download_and_verify_ms=self.download_and_verify_ms,
            model_load_ms=self.load_ms, unexpected_weight_keys=loading.get('unexpected_keys', []),
            versions={p: importlib.metadata.version(p) for p in
                      ['torch', 'transformers', 'huggingface-hub', 'Pillow', 'safetensors', 'tokenizers', 'numpy']})

    def infer(self, image, roi):
        p = self.policy
        crop = image.crop((roi['x'], roi['y'], roi['x']+roi['width'], roi['y']+roi['height']))
        started = time.perf_counter()
        inputs = self.processor(images=crop, text=p['prompt'], return_tensors='pt',
                                size={'shortest_edge': p['shortest_edge'], 'longest_edge': p['longest_edge']})
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(outputs, inputs.input_ids,
            threshold=p['box_threshold'], text_threshold=p['text_threshold'],
            target_sizes=[(crop.height, crop.width)])[0]
        labels = result.get('text_labels', result.get('labels'))
        raw = [dict(box=b.tolist(), score=s.item(), label=str(label)) for b, s, label in
               zip(result['boxes'], result['scores'], labels)]
        model = detections(raw, roi, p)
        model['model_ms'] = (time.perf_counter()-started)*1000
        return model

    def verify(self):
        require(model_files(self.directory, self.policy) == self.hashes, 'model files changed during inference')
