"""Inspect all raw records without silently repairing historical annotations."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_processor import read_records
from trace_schema import validate_record


def audit(path):
    rows = read_records(path)
    issues, types, levels, boxes, top_fields = [], Counter(), defaultdict(set), Counter(), Counter()
    negative, zoom, edit, nonmonotonic = 0, 0, 0, 0
    replay_mismatch, deltas = [], Counter()
    for row in rows:
        errors, warnings = validate_record(row)
        if errors or warnings:
            issues.append(dict(id=row.get("id"), errors=errors, warnings=warnings))
        if errors:
            continue
        top_fields.update([tuple(sorted(row))])
        events = row["events"]
        types.update(e["type"] for e in events)
        boxes[len(row["final_bboxes_pixels"])] += 1
        grade = row["task_evaluation"]
        levels[grade["difficulty_level"]].add(grade["difficulty_score"])
        negative += any(e.get("x", 0) < 0 or e.get("y", 0) < 0 for e in events)
        zoom += any(e["type"] == "zoom_start" for e in events)
        edit += any(e["category"] == "edit" for e in events)
        replay = []
        for event in events:
            kind, index = event["type"], event.get("index", -1)
            if kind == "create_end":
                if index == len(replay):
                    replay.append(event["bbox"])
                elif 0 <= index < len(replay):
                    replay[index] = event["bbox"]
            elif kind == "edit_end" and 0 <= index < len(replay):
                replay[index] = event["bbox"]
            elif kind == "delete_bbox" and 0 <= index < len(replay):
                replay.pop(index)
        if len(replay) != len(row["final_bboxes_pixels"]):
            replay_mismatch.append(row["id"])
        else:
            deltas.update(b - a for first, final in zip(replay, row["final_bboxes_pixels"])
                          for a, b in zip(first, final))
    durations = [row["annotation_time"] for row in rows if isinstance(row.get("annotation_time"), (int, float))]
    return dict(sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(), records=len(rows),
        unique_ids=len({row.get("id") for row in rows}),
        unique_samples=len({row.get("sample_id") for row in rows}),
        events=sum(types.values()), event_types=dict(types), final_box_counts=dict(boxes),
        sessions_with_negative_pointer=negative, sessions_with_zoom=zoom, sessions_with_edit=edit,
        difficulty_values={k: sorted(v, key=lambda x: -1 if x is None else x) for k, v in levels.items()},
        seconds=dict(min=min(durations), median=statistics.median(durations), max=max(durations)) if durations else {},
        replay_box_count_mismatches=replay_mismatch, final_minus_event_coordinate_deltas=dict(deltas),
        error_records=sum(bool(i["errors"]) for i in issues),
        warning_records=sum(bool(i["warnings"]) for i in issues), issues=issues)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = audit(args.data)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"读取失败: {exc}\n")
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"记录 {report['records']} / 事件 {report['events']} / 错误 {report['error_records']} / 警告 {report['warning_records']}")
        print(f"报告: {args.output}")
    else:
        print(text)
    return 1 if report["error_records"] else 0


if __name__ == "__main__":
    sys.exit(main())
