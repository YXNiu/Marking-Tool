"""Export completed session JSON files; drafts and metadata are never included."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trace_schema import validate_record


def export_sessions(source, target, latest_only=False):
    source, target = Path(source), Path(target)
    paths = sorted(source.glob("*_idx*_v*.json"))
    if not paths:
        raise ValueError("目录中没有已提交的标注 JSON")
    rows, seen, latest = [], set(), {}
    for path in paths:
        row = json.loads(path.read_text(encoding="utf-8"))
        errors, _ = validate_record(row)
        if errors:
            raise ValueError(f"{path.name}: {'；'.join(errors)}")
        if row["id"] in seen:
            raise ValueError(f"会话 ID 重复: {row['id']}")
        seen.add(row["id"])
        if latest_only:
            key = (row["sample_id"], row["image"], row["question"])
            match = re.search(r"_v(\d+)\.json$", path.name)
            version = int(match.group(1)) if match else 0
            if key not in latest or version > latest[key][0]:
                latest[key] = version, row
        else:
            rows.append(row)
    if latest_only:
        rows = [pair[1] for pair in latest.values()]
    if target.exists():
        raise FileExistsError(f"目标已存在，不覆盖：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as handle:
            temp = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, target)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--latest-only", action="store_true", help="每个 sample_id + image + question 只导出最高版本")
    args = parser.parse_args()
    try:
        count = export_sessions(args.source, args.target, args.latest_only)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"导出失败: {exc}\n")
    print(f"已导出 {count} 个会话到 {args.target}")


if __name__ == "__main__":
    main()
