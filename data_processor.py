"""Task loading. Source records are never rewritten or used as fresh annotations."""
import copy
import json
import re
from pathlib import Path


def read_records(path):
    path = Path(path)
    with path.open(encoding="utf-8-sig") as handle:
        if path.suffix.lower() == ".jsonl":
            records = []
            for line_number, line in enumerate(handle, 1):
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"第 {line_number} 行不是有效 JSON: {exc.msg}") from exc
        else:
            records = json.load(handle)
            if isinstance(records, dict):
                records = [records]
    if not isinstance(records, list) or not records:
        raise ValueError("数据必须是非空 JSON 数组、单条 JSON 或 JSONL")
    if any(not isinstance(row, dict) for row in records):
        raise ValueError("每条数据必须是 JSON 对象")
    return records


def normalize_task(row, index):
    """Accept HST, native VisualProbe, old standard tasks and VLM-R1."""
    item = copy.deepcopy(row)
    messages = row.get("messages", [])
    question = row.get("question", row.get("problem", row.get("instruction")))
    answer = row.get("answer", row.get("solution", row.get("original_response")))
    if question is None and messages:
        question = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    if answer is None and messages:
        answer = next((m.get("content", "") for m in messages if m.get("role") == "assistant"), "")
    images = row.get("images", [])
    image = row.get("image", images[0] if isinstance(images, list) and images else "")
    sample_id = row.get("sample_id") or row.get("doc_id") or row.get("id") or f"vlmr1_{index:06d}"
    if not isinstance(image, str) or not image:
        raise ValueError(f"第 {index + 1} 条数据缺少图片路径")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"第 {index + 1} 条数据缺少 question / problem / instruction")
    if not isinstance(sample_id, str) or not sample_id:
        raise ValueError(f"第 {index + 1} 条数据的 ID 必须为字符串")
    source_session = re.fullmatch(re.escape(sample_id) + r"_idx(\d+)_v(\d+)", str(row.get("id", "")))
    legacy_vlmr1 = bool(messages) or row.get("original_format") == "vlmr1" or str(row.get("type", "")).startswith("vlmr1")
    source_dataset = row.get("source_dataset", row.get("data_source", "unknown"))
    if source_dataset == "visual_probe_train":
        source_dataset = "visualprobe_train"  # The published HST spelling.
    item.update(sample_id=sample_id, image=image, question=question,
                answer="" if answer is None else str(answer),
                source_format=row.get("source_format", "vlmr1" if legacy_vlmr1 else "standard"),
                source_dataset=source_dataset)
    item["_source_index"] = int(source_session.group(1)) if source_session else index
    item["_source_version"] = int(source_session.group(2)) if source_session else 0
    return item


class DataProcessor:
    def __init__(self, data_path, images_root=None):
        self.data_path = Path(data_path).expanduser().resolve()
        self.images_root = Path(images_root).expanduser().resolve() if images_root else None
        self.data = []
        self.raw_data = []
        self.current_index = 0
        self.error = ""

    def load_data(self):
        try:
            raw = read_records(self.data_path)
            normalized = [normalize_task(row, i) for i, row in enumerate(raw)]
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            self.error = str(exc)
            return False
        self.raw_data, self.data = raw, normalized
        self.current_index = 0
        self.error = ""
        return True

    def resolve_image(self, item=None):
        item = item or self.get_current_item()
        if not item:
            return None
        image = Path(item["image"].replace("\\", "/"))
        candidates = []
        if self.images_root:
            if not image.is_absolute():
                candidates.append(self.images_root / image)
            candidates.extend([self.images_root / image.name, self.images_root / "data" / image.name])
        candidates.extend([image] if image.is_absolute() else [self.data_path.parent / image])
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return None

    def get_current_item(self):
        return self.data[self.current_index] if 0 <= self.current_index < len(self.data) else None

    def next_item(self):
        if self.current_index + 1 < len(self.data):
            self.current_index += 1
            return self.get_current_item()
        return None

    def prev_item(self):
        if self.current_index > 0:
            self.current_index -= 1
            return self.get_current_item()
        return None

    def get_all_ids(self):
        return list(dict.fromkeys(item["sample_id"] for item in self.data))

    def find_index_by_id(self, target_id):
        return next((i for i, item in enumerate(self.data)
                     if target_id in (item.get("id"), item["sample_id"])), -1)
