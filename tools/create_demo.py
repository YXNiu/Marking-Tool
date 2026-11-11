"""Create a clearly synthetic local practice task, never a research annotation."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    folder = args.destination
    if (folder / "tasks.json").exists():
        parser.error("目标已有 tasks.json，不覆盖")
    folder.mkdir(parents=True, exist_ok=True)
    # Portable PPM is supported by Qt and requires no image library.
    width, height = 1600, 1000
    pixels = bytearray([236, 241, 247] * (width * height))
    for x1, y1, x2, y2, color in [(950, 620, 1080, 730, (205, 60, 60)), (250, 200, 600, 450, (55, 100, 170))]:
        for y in range(y1, y2):
            for x in range(x1, x2):
                i = (y * width + x) * 3
                pixels[i:i+3] = bytes(color)
    (folder / "practice.ppm").write_bytes(f"P6\n{width} {height}\n255\n".encode() + pixels)
    rows = [dict(id="synthetic_practice", image="practice.ppm", question="请框出右下方的红色矩形。此题仅用于练习，不是研究数据。",
                 answer="红色矩形，原图坐标约 [950, 620, 1080, 730]", source_dataset="synthetic_practice")]
    (folder / "tasks.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"练习任务：{folder / 'tasks.json'}")


if __name__ == "__main__":
    main()
