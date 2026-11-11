"""Released Human-Search-Traces fields; validation never mutates source data."""
import math
from pathlib import PurePosixPath

FIELDS = {"id", "sample_id", "image", "question", "answer", "final_bboxes_pixels",
          "events", "annotation_time", "task_evaluation", "source_format", "source_dataset"}
EVENT_CATEGORIES = {
    **dict.fromkeys(("canvas_enter", "canvas_leave"), "canvas"),
    **dict.fromkeys(("hover_start", "hover_move", "hover_end"), "hover"),
    **dict.fromkeys(("zoom_start", "zoom_move", "zoom_end", "zoom_reset"), "zoom"),
    **dict.fromkeys(("down", "create_start", "drag_move", "create_end", "up"), "drag"),
    **dict.fromkeys(("select_bbox", "edit_start", "edit_move", "edit_end", "delete_bbox"), "edit"),
}


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_box(value):
    return isinstance(value, list) and len(value) == 4 and all(finite_number(n) for n in value)


def valid_index(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def difficulty_level(score):
    return "easy" if score <= 0.3 else "medium" if score <= 0.6 else "hard"


def evaluation(difficulty=0.5, confidence=1.0, ambiguous=False):
    if ambiguous:
        return dict(difficulty_score=None, difficulty_level="ambiguous",
                    is_ambiguous=True, confidence_score=None)
    if not all(finite_number(v) and 0 <= v <= 1 for v in (difficulty, confidence)):
        raise ValueError("难度和置信度必须在 0–1 之间")
    return dict(difficulty_score=round(difficulty, 2), difficulty_level=difficulty_level(difficulty),
                is_ambiguous=False, confidence_score=round(confidence, 2))


def validate_record(record, strict=False):
    """Return (errors, warnings). Historical degeneracies are warnings by default."""
    errors, warnings = [], []
    if not isinstance(record, dict):
        return ["记录不是对象"], []
    missing = FIELDS - record.keys()
    if missing:
        return [f"缺少字段: {', '.join(sorted(missing))}"], []
    for key in ("id", "sample_id", "image", "question", "answer", "source_format", "source_dataset"):
        if not isinstance(record[key], str):
            errors.append(f"{key} 必须为字符串")
    if isinstance(record["image"], str) and ("/" in record["image"] or "\\" in record["image"]):
        errors.append("image 必须只包含文件名")
    boxes = record["final_bboxes_pixels"]
    if not isinstance(boxes, list):
        errors.append("final_bboxes_pixels 必须为数组")
        boxes = []
    if not boxes:
        warnings.append("没有最终证据框")
    for i, box in enumerate(boxes):
        if not valid_box(box):
            errors.append(f"框 {i} 格式错误")
        elif box[0] >= box[2] or box[1] >= box[3] or min(box) < 0:
            (errors if strict else warnings).append(f"框 {i} 零面积、倒置或越出原点")
    events = record["events"]
    if not isinstance(events, list):
        errors.append("events 必须为数组")
        events = []
    previous_t = -1
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append(f"事件 {i} 不是对象")
            continue
        kind = event.get("type")
        if not isinstance(kind, str) or kind not in EVENT_CATEGORIES or event.get("category") != EVENT_CATEGORIES[kind]:
            errors.append(f"事件 {i} type/category 不匹配")
            continue
        if any(not finite_number(event.get(k)) for k in ("t", "v", "a")):
            errors.append(f"事件 {i} t/v/a 不是有限数值")
        else:
            if event["t"] < previous_t or event["t"] < 0:
                errors.append(f"事件 {i} 时间倒退")
            previous_t = event["t"]
        if ("x" in event) != ("y" in event) or any(not finite_number(event[k]) for k in ("x", "y") if k in event):
            errors.append(f"事件 {i} 坐标错误")
        if kind not in ("zoom_reset", "delete_bbox") and not all(k in event for k in ("x", "y")):
            errors.append(f"事件 {i} 缺少坐标")
        if kind == "create_start":
            if not isinstance(event.get("bbox"), dict) or not valid_index(event["bbox"].get("index")):
                errors.append(f"事件 {i} create_start.bbox.index 错误")
        elif kind == "drag_move":
            box = event.get("bbox")
            if not isinstance(box, dict) or not valid_box(box.get("bbox")) or not valid_index(box.get("index")):
                errors.append(f"事件 {i} drag_move.bbox 错误")
        elif kind in ("create_end", "select_bbox", "edit_start", "edit_move", "edit_end", "delete_bbox"):
            if not valid_box(event.get("bbox")) or not valid_index(event.get("index")):
                errors.append(f"事件 {i} bbox/index 错误")
            if kind.startswith("edit_") and (event.get("mode") not in ("move", "resize") or
                    event.get("handle") not in (None, "tl", "tr", "bl", "br")):
                errors.append(f"事件 {i} mode/handle 错误")
        elif kind in ("zoom_move", "zoom_end"):
            if not (kind == "zoom_end" and event.get("canceled") is True) and not valid_box(event.get("bbox")):
                errors.append(f"事件 {i} zoom.bbox 错误")
    duration = record["annotation_time"]
    if not finite_number(duration) or duration < 0:
        errors.append("annotation_time 必须为非负秒数")
    elif events and isinstance(events[-1], dict) and finite_number(events[-1].get("t")) and abs(duration - round(events[-1]["t"] / 1000, 2)) > 0.011:
        errors.append("annotation_time 不等于最后事件时间 / 1000")
    if events and isinstance(events[0], dict) and events[0].get("t") != 0:
        warnings.append("首事件时间不为 0")
    grade = record["task_evaluation"]
    if not isinstance(grade, dict) or not isinstance(grade.get("is_ambiguous"), bool):
        errors.append("task_evaluation 格式错误")
    else:
        try:
            expected = evaluation(grade.get("difficulty_score"), grade.get("confidence_score"), grade["is_ambiguous"])
            if grade != expected:
                errors.append("task_evaluation 分数、等级或 null 口径不一致")
        except (ValueError, TypeError):
            errors.append("task_evaluation 分数范围错误")
    return errors, warnings


def make_record(task, session_id, boxes, events, grade):
    return {
        "id": session_id, "sample_id": task["sample_id"],
        "image": PurePosixPath(task["image"].replace("\\", "/")).name,
        "question": task["question"], "answer": task["answer"],
        "final_bboxes_pixels": boxes, "events": events,
        "annotation_time": round(events[-1]["t"] / 1000, 2) if events else 0.0,
        "task_evaluation": grade, "source_format": task["source_format"],
        "source_dataset": task["source_dataset"],
    }
