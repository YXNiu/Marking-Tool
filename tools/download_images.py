"""Fetch only original VisualProbe images referenced by a task file."""
import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_processor import DataProcessor


def image_patterns(data):
    patterns = []
    for row in data:
        name = Path(row["image"].replace("\\", "/")).name
        if not re.fullmatch(r"visual_probe_train_\d+\.jpg", name):
            raise ValueError(f"此脚本仅下载 VisualProbe 原图，不支持 {name}")
        patterns.append(f"data/{name}")
    return sorted(set(patterns))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path, help="任务 JSON / 已发布 JSONL")
    parser.add_argument("destination", type=Path, help="图片缓存根目录；图像存放在其 data 子目录")
    parser.add_argument("--limit", type=int, help="只下载前 N 个任务所需的图像")
    parser.add_argument("--list-only", action="store_true", help="只列清单，不联网")
    args = parser.parse_args()
    processor = DataProcessor(args.data)
    if not processor.load_data():
        parser.error(processor.error)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须大于 0")
    try:
        patterns = image_patterns(processor.data[:args.limit])
    except ValueError as exc:
        parser.error(str(exc))
    print(f"需要 {len(patterns)} 张原图；来源 Mini-o3/VisualProbe_train")
    if args.list_only:
        print("\n".join(patterns))
        return
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        parser.exit(2, "请先安装下载依赖：python -m pip install -r requirements-download.txt\n")
    snapshot_download(repo_id="Mini-o3/VisualProbe_train", repo_type="dataset", allow_patterns=patterns,
                      local_dir=args.destination, max_workers=4)
    missing = [name for name in patterns if not (args.destination / name).is_file()]
    if missing:
        parser.exit(2, f"上游缺少 {len(missing)} 张图片，示例：{missing[0]}\n")
    print(f"下载完成。启动时设置 --images-root \"{args.destination / 'data'}\"")


if __name__ == "__main__":
    main()
