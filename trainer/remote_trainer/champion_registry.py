from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

from .schemas import ChampionManifest, ChampionPublishRequest


class ChampionRegistryError(RuntimeError):
    pass


class ChampionRegistry:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.staging = self.root / "champion-staging"
        self.champions = self.root / "champions"
        self.staging.mkdir(parents=True, exist_ok=True)
        self.champions.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self, channel: str) -> Path:
        return self.champions / channel / "manifest.json"

    def latest(self, channel: str = "stable") -> ChampionManifest | None:
        path = self._manifest_path(channel)
        if not path.is_file():
            return None
        try:
            return ChampionManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ChampionRegistryError(f"invalid champion manifest: {exc}") from exc

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _verify_bundle(package: Path, request: ChampionPublishRequest) -> None:
        if package.stat().st_size > 512 * 1024 * 1024:
            raise ChampionRegistryError("champion package exceeds size limit")
        try:
            with zipfile.ZipFile(package) as archive:
                infos = archive.infolist()
                if not infos or len(infos) > 256:
                    raise ChampionRegistryError("champion package member count invalid")
                total = 0
                names = set()
                for info in infos:
                    name = info.filename
                    p = Path(name)
                    if (
                        p.is_absolute()
                        or ".." in p.parts
                        or name.endswith("/")
                        or name in names
                        or info.file_size > 256 * 1024 * 1024
                    ):
                        raise ChampionRegistryError("unsafe champion package member")
                    names.add(name)
                    total += info.file_size
                    if total > 768 * 1024 * 1024:
                        raise ChampionRegistryError("champion package expands beyond limit")
                    mode = (info.external_attr >> 16) & 0xFFFF
                    if mode and (mode & 0o170000) == 0o120000:
                        raise ChampionRegistryError("symlink not allowed in champion package")
                if "model-package.json" not in names:
                    raise ChampionRegistryError("model-package.json missing")
                raw = archive.read("model-package.json")
                if len(raw) > 128 * 1024:
                    raise ChampionRegistryError("model package manifest too large")
                doc = json.loads(raw)
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise ChampionRegistryError(f"invalid champion zip: {exc}") from exc

        if (
            doc.get("schema_version") != 1
            or doc.get("package_type") != "agente_tft_neural_runtime_bundle"
            or doc.get("version") != request.version
            or doc.get("generation") != request.generation
            or doc.get("runtime_min_version") != request.runtime_min_version
            or doc.get("model_identity_sha256") != request.model_identity_sha256
        ):
            raise ChampionRegistryError("model-package.json does not match publish request")

        files = doc.get("files")
        if not isinstance(files, list) or not files:
            raise ChampionRegistryError("model-package files missing")
        with zipfile.ZipFile(package) as archive:
            for row in files:
                if not isinstance(row, dict):
                    raise ChampionRegistryError("invalid model file entry")
                name = row.get("path")
                digest = row.get("sha256")
                size = row.get("bytes")
                if (
                    not isinstance(name, str)
                    or name not in names
                    or name == "model-package.json"
                    or not isinstance(digest, str)
                    or len(digest) != 64
                    or not isinstance(size, int)
                    or size < 1
                ):
                    raise ChampionRegistryError("invalid model file contract")
                payload = archive.read(name)
                if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
                    raise ChampionRegistryError(f"model file checksum mismatch: {name}")

    def publish(self, request: ChampionPublishRequest, published_at_ms: int) -> ChampionManifest:
        staged = (self.staging / request.staged_filename).resolve()
        if not staged.is_file() or not staged.is_relative_to(self.staging.resolve()):
            raise ChampionRegistryError("staged champion package not found")
        self._verify_bundle(staged, request)

        current = self.latest(request.channel)
        if current is not None and request.generation <= current.generation:
            raise ChampionRegistryError("champion generation must increase")

        channel_dir = self.champions / request.channel
        versions = channel_dir / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        final_name = f"{request.generation:012d}-{request.version}.zip"
        final = versions / final_name
        if final.exists():
            raise ChampionRegistryError("champion version already exists")

        temporary = final.with_suffix(".zip.partial")
        shutil.copy2(staged, temporary)
        package_sha = self._sha256(temporary)
        package_bytes = temporary.stat().st_size
        os.replace(temporary, final)

        manifest = ChampionManifest(
            channel=request.channel,
            version=request.version,
            generation=request.generation,
            published_at_ms=published_at_ms,
            package_sha256=package_sha,
            package_bytes=package_bytes,
            package_path=f"/v1/neural/champion/package/{request.channel}/{request.generation}",
            runtime_min_version=request.runtime_min_version,
            model_identity_sha256=request.model_identity_sha256,
            approved=request.channel == "stable",
            training_provenance=request.training_provenance,
        )

        manifest_dir = channel_dir
        manifest_dir.mkdir(parents=True, exist_ok=True)
        target = manifest_dir / "manifest.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, target)

        staged.unlink(missing_ok=True)
        return manifest

    def package_for(self, channel: str, generation: int) -> tuple[ChampionManifest, Path]:
        manifest = self.latest(channel)
        if manifest is None:
            raise ChampionRegistryError("champion not published")
        if generation != manifest.generation:
            # Allow rollback/history fetches by generation if file exists.
            prefix = f"{generation:012d}-"
            candidates = sorted((self.champions / channel / "versions").glob(prefix + "*.zip"))
            if len(candidates) != 1:
                raise ChampionRegistryError("champion generation not found")
            return manifest, candidates[0]
        path = self.champions / channel / "versions" / f"{generation:012d}-{manifest.version}.zip"
        if not path.is_file():
            raise ChampionRegistryError("champion package missing")
        if self._sha256(path) != manifest.package_sha256:
            raise ChampionRegistryError("champion package checksum mismatch")
        return manifest, path
