"""Zero-click neural model updater for HM4/HM4.5.

Approved champions are learned/validated on BigBANANA, but inference remains
local. The updater never activates a model while a match is running.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import zipfile

from .neural_service import NeuralServiceClient, NeuralServiceError

RUNTIME_VERSION = "0.7.0"


class ModelUpdateError(RuntimeError):
    pass


def _local_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "AgenteTFT-HUD-HM4" / "neural-models"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        parts = tuple(int(x) for x in value.split("."))
    except Exception as exc:
        raise ModelUpdateError(f"Versão incompatível: {value!r}") from exc
    if not parts or any(x < 0 for x in parts):
        raise ModelUpdateError("Versão inválida.")
    return parts


def _safe_member(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    path = Path(name)
    if (
        path.is_absolute()
        or "\\" in name
        or ":" in name
        or ".." in path.parts
        or name.endswith("/")
    ):
        return False
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode and (mode & 0o170000) == 0o120000:
        return False
    return True


def _probe_l3(metadata: Path) -> str:
    try:
        from e1.model import MapObserver
        observer = MapObserver(str(metadata))
        return observer.hash
    except Exception as exc:
        raise ModelUpdateError(f"Health-check L3 falhou: {type(exc).__name__}") from exc


def _runtime_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))


def _probe_optional_components(bundle_root: Path) -> dict:
    checked = {}
    runtime_root = _runtime_root()
    unit_plan = bundle_root / "configs/catalog/active-unit-head-v1.json"
    if unit_plan.is_file():
        try:
            from .unit_head import UnitHeadObserver
            observer = UnitHeadObserver(runtime_root, bundle_root)
            checked["unit_head_sha256"] = observer.sha
        except Exception as exc:
            raise ModelUpdateError(
                f"Health-check do reconhecedor de unidades falhou: {type(exc).__name__}"
            ) from exc

    item_plan = bundle_root / "configs/catalog/active-item-neural-v1.json"
    if item_plan.is_file():
        try:
            from .item_neural import ItemIconObserver
            observer = ItemIconObserver(runtime_root, bundle_root)
            checked["item_model_sha256"] = observer.sha
        except Exception as exc:
            raise ModelUpdateError(
                f"Health-check do reconhecedor de itens falhou: {type(exc).__name__}"
            ) from exc
    return checked


def rollback_active_model(
    *,
    root: Path | None = None,
    reason: str = "runtime_load_failure",
) -> Path | None:
    root = root or _local_root()
    try:
        previous = _json(root / "previous.json")
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    path = _valid_pointer(previous, root)
    if path is None:
        return None
    restored = {
        **previous,
        "status": "active_rollback",
        "rollback_at_ms": int(time.time() * 1000),
        "rollback_reason": reason,
    }
    _write_atomic(root / "active.json", restored)
    return path


def _verify_and_extract(
    package: Path,
    destination: Path,
    server_manifest: dict,
) -> dict:
    if package.stat().st_size != int(server_manifest["package_bytes"]):
        raise ModelUpdateError("Tamanho do pacote neural não confere.")
    if _sha256(package) != server_manifest["package_sha256"]:
        raise ModelUpdateError("SHA-256 do pacote neural não confere.")

    with zipfile.ZipFile(package) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > 256 or any(not _safe_member(i) for i in infos):
            raise ModelUpdateError("Pacote neural contém caminhos não permitidos.")
        names = {i.filename for i in infos}
        if "model-package.json" not in names:
            raise ModelUpdateError("Manifesto interno do modelo ausente.")
        raw = archive.read("model-package.json")
        if len(raw) > 128 * 1024:
            raise ModelUpdateError("Manifesto interno excedeu o limite.")
        manifest = json.loads(raw)

        if (
            manifest.get("schema_version") != 1
            or manifest.get("package_type") != "agente_tft_neural_runtime_bundle"
            or manifest.get("version") != server_manifest.get("version")
            or manifest.get("generation") != server_manifest.get("generation")
            or manifest.get("runtime_min_version") != server_manifest.get("runtime_min_version")
            or manifest.get("model_identity_sha256") != server_manifest.get("model_identity_sha256")
        ):
            raise ModelUpdateError("Manifesto interno diverge do champion publicado.")
        if _version_tuple(RUNTIME_VERSION) < _version_tuple(manifest["runtime_min_version"]):
            raise ModelUpdateError("Champion exige uma versão mais nova do Agente TFT.")

        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise ModelUpdateError("Bundle neural não contém arquivos.")
        roles: dict[str, str] = {}
        declared_paths: set[str] = set()
        total = 0
        for row in files:
            if not isinstance(row, dict):
                raise ModelUpdateError("Entrada de arquivo neural inválida.")
            name = row.get("path")
            digest = row.get("sha256")
            size = row.get("bytes")
            role = row.get("role")
            if (
                not isinstance(name, str)
                or name not in names
                or name == "model-package.json"
                or name in declared_paths
                or not isinstance(digest, str)
                or len(digest) != 64
                or not isinstance(size, int)
                or size < 1
                or not isinstance(role, str)
                or not role
            ):
                raise ModelUpdateError("Contrato de arquivo neural inválido.")
            payload = archive.read(name)
            total += len(payload)
            if total > 768 * 1024 * 1024:
                raise ModelUpdateError("Bundle neural expandido excede o limite.")
            if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
                raise ModelUpdateError(f"Arquivo neural corrompido: {name}")
            if role in roles:
                raise ModelUpdateError(f"Role neural duplicado: {role}")
            declared_paths.add(name)
            roles[role] = name

        if names != declared_paths | {"model-package.json"}:
            raise ModelUpdateError("Pacote neural contém arquivo não declarado.")
        for role in ("l3_metadata", "l3_onnx"):
            if role not in roles:
                raise ModelUpdateError(f"Champion não contém {role}.")
        meta = Path(roles["l3_metadata"])
        model = Path(roles["l3_onnx"])
        if meta.parent != model.parent or model.name != "candidate-model.onnx":
            raise ModelUpdateError("Layout L3 incompatível com o runtime atual.")

        if destination.exists():
            raise ModelUpdateError("Diretório de versão neural já existe.")
        destination.mkdir(parents=True)
        try:
            for info in infos:
                target = destination / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    internal = destination / "model-package.json"
    if not internal.is_file():
        shutil.rmtree(destination, ignore_errors=True)
        raise ModelUpdateError("Extração neural incompleta.")

    # Repeat hashes from disk after extraction; ZIP verification alone is not enough
    # for the eventual runtime path.
    for row in manifest["files"]:
        path = destination / row["path"]
        if (
            not path.is_file()
            or path.stat().st_size != row["bytes"]
            or _sha256(path) != row["sha256"]
        ):
            shutil.rmtree(destination, ignore_errors=True)
            raise ModelUpdateError(f"Verificação pós-extração falhou: {row['path']}")

    l3_metadata = destination / roles["l3_metadata"]
    l3_hash = _probe_l3(l3_metadata)
    if l3_hash != server_manifest["model_identity_sha256"]:
        shutil.rmtree(destination, ignore_errors=True)
        raise ModelUpdateError("Identidade do modelo L3 não confere com o champion.")
    optional_health = _probe_optional_components(destination)

    return {
        "manifest": manifest,
        "roles": roles,
        "l3_metadata": str(l3_metadata),
        "bundle_root": str(destination),
        "runtime_model_sha256": l3_hash,
        "optional_health": optional_health,
    }


def _valid_pointer(value: dict, root: Path) -> Path | None:
    try:
        path = Path(value["l3_metadata"]).resolve()
        bundle_root = Path(value["bundle_root"]).resolve()
        if (
            not path.is_file()
            or not path.is_relative_to(root.resolve())
            or not bundle_root.is_dir()
            or not bundle_root.is_relative_to(root.resolve())
        ):
            return None
        expected = value.get("model_identity_sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            return None
        if _probe_l3(path) != expected:
            return None
        # Re-check optional neural overlays on every startup. A champion whose
        # unit/item component was corrupted after installation must roll back
        # just like a corrupted L3 model.
        _probe_optional_components(bundle_root)
        return path
    except Exception:
        return None


def active_model_metadata(root: Path | None = None) -> Path | None:
    root = root or _local_root()
    pointer = root / "active.json"
    try:
        active = _json(pointer)
    except (OSError, ValueError, json.JSONDecodeError):
        active = None
    if isinstance(active, dict):
        path = _valid_pointer(active, root)
        if path is not None:
            return path

    # Automatic rollback: an invalid active model never blocks startup.
    return rollback_active_model(root=root, reason="active_model_health_check_failed")


def active_bundle_for_model(model_path: str | Path, root: Path | None = None) -> Path | None:
    """Return an approved bundle only for the model frozen into this session."""
    if not model_path:
        return None
    root = root or _local_root()
    active_metadata = active_model_metadata(root)
    if active_metadata is None or active_metadata.resolve() != Path(model_path).resolve():
        return None
    try:
        pointer = _json(root / "active.json")
        bundle = Path(pointer["bundle_root"]).resolve()
        if bundle.is_dir() and bundle.is_relative_to(root.resolve()):
            return bundle
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return None


class ModelUpdater:
    def __init__(
        self,
        *,
        root: Path | None = None,
        is_idle=lambda: True,
        client_factory=NeuralServiceClient,
    ):
        self.root = root or _local_root()
        self.is_idle = is_idle
        self.client_factory = client_factory
        self.lock = threading.Lock()
        self.running = False
        self.last_result: dict | None = None

    def _active(self) -> dict | None:
        try:
            value = _json(self.root / "active.json")
            if isinstance(value.get("generation"), int):
                return value
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return None

    def _cleanup(self, keep: int = 2) -> None:
        versions = self.root / "versions"
        if not versions.is_dir():
            return
        active = self._active() or {}
        active_generation = active.get("generation")
        try:
            previous_generation = _json(self.root / "previous.json").get("generation")
        except (OSError, ValueError, json.JSONDecodeError):
            previous_generation = None
        rows = []
        for folder in versions.iterdir():
            if not folder.is_dir():
                continue
            try:
                generation = int(folder.name.split("-", 1)[0])
            except ValueError:
                continue
            rows.append((generation, folder))
        rows.sort(reverse=True)
        protected = {active_generation, previous_generation}
        for generation, folder in rows[:keep]:
            protected.add(generation)
        for generation, folder in rows:
            if generation not in protected:
                shutil.rmtree(folder, ignore_errors=True)

    def _prepare_download_storage(self, package_bytes: int, keep_name: str) -> Path:
        if not isinstance(package_bytes, int) or not 1 <= package_bytes <= 512 * 1024**2:
            raise ModelUpdateError("Tamanho do champion fora do limite local.")
        downloads = self.root / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)

        # A previous network/process failure may leave temporary files. This
        # updater is single-flight, so no .partial belongs to another active
        # download when check_once() reaches this point.
        for path in downloads.iterdir():
            if not path.is_file():
                continue
            if path.name.endswith(".partial"):
                path.unlink(missing_ok=True)
            elif path.suffix == ".zip" and path.name != keep_name:
                path.unlink(missing_ok=True)

        # Keep enough headroom for the ZIP plus extraction/rollback metadata.
        required_free = package_bytes + 1024**3
        free = shutil.disk_usage(self.root).free
        if free < required_free:
            raise ModelUpdateError(
                "Espaço local insuficiente para atualizar a rede neural."
            )
        return downloads

    def _activate(self, ready: dict) -> dict:
        if not self.is_idle():
            pending = {
                **ready,
                "status": "ready_waiting_for_idle",
                "activated": False,
            }
            _write_atomic(self.root / "pending.json", pending)
            return pending

        old = self._active()
        if old:
            _write_atomic(self.root / "previous.json", old)
        active = {
            **ready,
            "status": "active",
            "activated": True,
            "activated_at_ms": int(time.time() * 1000),
        }
        _write_atomic(self.root / "active.json", active)
        (self.root / "pending.json").unlink(missing_ok=True)
        self._cleanup(keep=2)
        return active

    def activate_pending_if_idle(self) -> dict | None:
        if not self.is_idle():
            return None
        try:
            pending = _json(self.root / "pending.json")
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if pending.get("status") != "ready_waiting_for_idle":
            return None
        return self._activate(pending)

    def check_once(self) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.is_idle():
            applied = self.activate_pending_if_idle()
            if applied:
                return applied

        client = self.client_factory()
        client.connect()
        manifest = client.champion_manifest("stable")
        if manifest.get("approved") is not True:
            raise ModelUpdateError("Servidor não marcou o champion como aprovado.")
        generation = manifest.get("generation")
        if not isinstance(generation, int) or generation < 1:
            raise ModelUpdateError("Generation do champion inválida.")

        current = self._active()
        if current and int(current.get("generation", 0)) >= generation:
            return {
                "status": "up_to_date",
                "generation": current["generation"],
                "version": current.get("version"),
            }

        package_name = f"{generation:012d}-{manifest['version']}.zip"
        downloads = self._prepare_download_storage(
            int(manifest.get("package_bytes", 0)),
            package_name,
        )
        package = downloads / package_name
        download = client.download_champion_package("stable", generation, package)
        if download["sha256"] != manifest["package_sha256"]:
            package.unlink(missing_ok=True)
            raise ModelUpdateError("Download não corresponde ao manifest do champion.")

        version_dir = self.root / "versions" / f"{generation:012d}-{manifest['version']}"
        ready = _verify_and_extract(package, version_dir, manifest)
        package.unlink(missing_ok=True)
        record = {
            "schema_version": 1,
            "generation": generation,
            "version": manifest["version"],
            "model_identity_sha256": manifest["model_identity_sha256"],
            "package_sha256": manifest["package_sha256"],
            "runtime_min_version": manifest["runtime_min_version"],
            "bundle_root": ready["bundle_root"],
            "l3_metadata": ready["l3_metadata"],
            "roles": ready["roles"],
            "runtime_model_sha256": ready["runtime_model_sha256"],
            "optional_health": ready["optional_health"],
            "downloaded_at_ms": int(time.time() * 1000),
        }
        _write_atomic(version_dir / "installed.json", record)
        return self._activate(record)

    def check_async(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True

        def work():
            try:
                self.last_result = self.check_once()
            except Exception as exc:
                self.last_result = {
                    "status": "update_check_failed",
                    "error": f"{type(exc).__name__}:{str(exc)[:300]}",
                }
            finally:
                with self.lock:
                    self.running = False

        threading.Thread(
            target=work,
            daemon=True,
            name="tft-neural-model-updater",
        ).start()
        return True
