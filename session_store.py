"""Atomic, versioned storage. Never overwrite a completed annotation."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from trace_schema import make_record, validate_record


def safe_id(sample_id):
    cleaned = re.sub(r"[^\w.-]", "_", sample_id, flags=re.UNICODE).strip(".")[:100] or "sample"
    if cleaned != sample_id:
        cleaned += "_" + hashlib.sha256(sample_id.encode()).hexdigest()[:10]
    return cleaned


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".writing-", delete=False) as handle:
            name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


class SessionStore:
    def __init__(self, output_dir, state_dir=None):
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = Path(state_dir).resolve() if state_dir else self.output_dir

    def save(self, task, index, boxes, events, grade):
        index = task.get("_source_index", index)
        stem = f"{safe_id(task['sample_id'])}_idx{index}"
        versions = [int(m.group(1)) for path in self.output_dir.glob(f"{stem}_v*.json")
                    if (m := re.fullmatch(re.escape(stem) + r"_v(\d+)\.json", path.name))]
        version = max([task.get("_source_version", 0)] + versions) + 1
        while True:
            session_id = f"{stem}_v{version}"
            record = make_record(task, session_id, boxes, events, grade)
            errors, _ = validate_record(record, strict=True)
            if errors:
                raise ValueError("；".join(errors))
            # Publish with an exclusive hard link after the complete file is durable.
            tmp = self.output_dir / f".session-{os.getpid()}-{os.urandom(8).hex()}.tmp"
            try:
                atomic_json(tmp, record)
                target = self.output_dir / f"{session_id}.json"
                try:
                    os.link(tmp, target)
                except FileExistsError:
                    version += 1
                    continue
                return target, record
            finally:
                tmp.unlink(missing_ok=True)

    def draft_path(self, dataset_path, index):
        key = hashlib.sha256(f"{Path(dataset_path).resolve()}:{index}".encode()).hexdigest()[:24]
        return self.state_dir / ".drafts" / f"{key}.json"

    def completed_records(self, tasks):
        identities = {}
        for path in self.output_dir.glob("*_idx*_v*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                if not validate_record(row)[0]:
                    key = (row["sample_id"], row["question"], row["image"])
                    version = int(re.search(r"_v(\d+)\.json$", path.name).group(1))
                    if key not in identities or version > identities[key][0]:
                        identities[key] = (version, row)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
        return {i: identities[key][1] for i, task in enumerate(tasks)
                if (key := (task["sample_id"], task["question"], Path(task["image"].replace("\\", "/")).name)) in identities}


class DatasetWorkspace:
    """Separate task files and revisions, even when their names/IDs overlap."""
    def __init__(self, root, processor, name=None):
        sources = {row["source_dataset"] for row in processor.data} - {"unknown", ""}
        fallback = processor.data_path.parent.name if processor.data_path.stem in ("tasks", "train", "test", "data") else processor.data_path.stem
        self.name = name or (next(iter(sources)) if len(sources) == 1 else fallback)
        self.source_sha256 = hashlib.sha256(processor.data_path.read_bytes()).hexdigest()
        identity = f"{processor.data_path}\0{self.source_sha256}"
        suffix = hashlib.sha256(identity.encode()).hexdigest()[:10]
        self.path = Path(root).expanduser().resolve() / f"{safe_id(self.name)}--{suffix}"
        self.path.mkdir(parents=True, exist_ok=True)
        self.store = SessionStore(self.path / "sessions", state_dir=self.path)
        manifest_path = self.path / "workspace.json"
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            if processor.images_root is None and previous.get("images_root"):
                processor.images_root = Path(previous["images_root"])
        for row in processor.data:
            if row["source_dataset"] in ("unknown", ""):
                row["source_dataset"] = self.name
        self.write_manifest(processor)

    def write_manifest(self, processor):
        atomic_json(self.path / "workspace.json", dict(
            dataset_name=self.name, task_file=str(processor.data_path),
            source_sha256=self.source_sha256, task_count=len(processor.data),
            images_root=str(processor.images_root) if processor.images_root else None,
            tool_version="2.0.1", sessions="sessions", exports="exports"))
