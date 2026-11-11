import copy
import json

import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QDialog, QMessageBox

from bbox_canvas import BBoxCanvas, rect_from_box
from main import AnnotationTool, EvaluationDialog
from trace_recorder import TraceRecorder
from trace_schema import evaluation, validate_record


def mouse(canvas, kind, pos, button=Qt.LeftButton, modifiers=Qt.NoModifier):
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else button
    event = QMouseEvent(kind, QPointF(pos), button if kind != QEvent.MouseMove else Qt.NoButton, buttons, modifiers)
    {QEvent.MouseButtonPress: canvas.mousePressEvent,
     QEvent.MouseMove: canvas.mouseMoveEvent,
     QEvent.MouseButtonRelease: canvas.mouseReleaseEvent}[kind](event)


def drag(canvas, start, end, button=Qt.LeftButton, modifiers=Qt.NoModifier):
    mouse(canvas, QEvent.MouseButtonPress, start, button, modifiers)
    mouse(canvas, QEvent.MouseMove, end, button, modifiers)
    mouse(canvas, QEvent.MouseButtonRelease, end, button, modifiers)


@pytest.fixture
def canvas(app):
    widget = BBoxCanvas()
    widget.resize(800, 600)
    pixmap = QPixmap(4000, 2000)
    pixmap.fill(Qt.white)
    widget.set_image(pixmap)
    yield widget
    widget.close()


def test_original_pixel_mapping_after_nested_zoom_and_resize(canvas):
    assert canvas.to_image(QPointF(0, 100)) == QPointF(0, 0)
    assert canvas.to_image(QPointF(100, 0)).y() < 0  # Letterbox is not clipped for pointer events.
    drag(canvas, QPointF(200, 200), QPointF(600, 400), Qt.RightButton)
    assert [round(v) for v in (canvas.view_rect.x(), canvas.view_rect.y(), canvas.view_rect.width(), canvas.view_rect.height())] == [1000, 500, 2000, 1000]
    point = QPointF(1500, 700)
    assert canvas.to_image(canvas.to_widget(point)) == point
    drag(canvas, canvas.to_widget(QPointF(1200, 600)), canvas.to_widget(QPointF(1800, 900)), Qt.RightButton)
    drag(canvas, canvas.to_widget(QPointF(1400, 700)), canvas.to_widget(QPointF(1600, 800)))
    assert canvas.get_final_bboxes() == [[1400, 700, 1600, 800]]
    canvas.resize(1200, 700)
    assert canvas.to_image(canvas.to_widget(point)) == point
    canvas.reset_view()
    assert canvas.get_final_bboxes() == [[1400, 700, 1600, 800]]
    assert canvas.events[-1]["type"] == "zoom_reset"
    assert "x" not in canvas.events[-1]
    assert canvas.image.width() == 4000


def test_reverse_draw_zero_click_and_release_endpoint(canvas):
    drag(canvas, QPointF(600, 400), QPointF(200, 200))
    assert canvas.get_final_bboxes() == [[1000, 500, 3000, 1500]]
    drag(canvas, QPointF(100, 150), QPointF(100, 150))
    assert len(canvas.bboxes) == 1
    assert any(e["type"] == "delete_bbox" for e in canvas.events)
    mouse(canvas, QEvent.MouseButtonPress, QPointF(100, 170))
    mouse(canvas, QEvent.MouseButtonRelease, QPointF(130, 190))
    assert canvas.get_final_bboxes()[-1] == [500, 350, 650, 450]
    assert next(e for e in reversed(canvas.events) if e["type"] == "create_end")["bbox"] == [500, 350, 650, 450]


def test_edit_delete_clear_preserve_trace(canvas):
    drag(canvas, QPointF(200, 200), QPointF(400, 300))
    drag(canvas, QPointF(300, 250), QPointF(700, 500))
    assert canvas.get_final_bboxes() == [[3000, 1500, 4000, 2000]]
    assert any(e["type"] == "edit_end" and e["mode"] == "move" for e in canvas.events)
    count = len(canvas.events)
    canvas.clear_canvas()
    assert len(canvas.events) == count + 1
    assert not canvas.bboxes
    assert canvas.events[0]["t"] == 0
    assert canvas.events[-1]["type"] == "delete_bbox"
    assert "x" not in canvas.events[-1]


def test_resize_and_nested_box(canvas):
    drag(canvas, QPointF(200, 200), QPointF(400, 300))
    drag(canvas, QPointF(400, 300), QPointF(450, 350))
    assert canvas.get_final_bboxes() == [[1000, 500, 2250, 1250]]
    drag(canvas, QPointF(250, 220), QPointF(300, 260), modifiers=Qt.ShiftModifier)
    assert len(canvas.bboxes) == 2
    assert canvas.get_final_bboxes()[1] == [1250, 600, 1500, 800]


def test_clock_throttle_pause_and_negative_positions():
    now = [100.0]
    recorder = TraceRecorder(clock=lambda: now[0])
    recorder.record("canvas_enter", QPointF(-2, 10))
    recorder.record("hover_move", QPointF(0, 0))
    now[0] += .05
    assert recorder.record("hover_move", QPointF(1, 0)) is None
    now[0] += .15
    event = recorder.record("hover_move", QPointF(20, 0))
    assert event["t"] == 200
    assert event["v"] == 100
    assert event["a"] == 0  # Two measured velocities are needed for acceleration.
    recorder.pause()
    now[0] += 80
    assert recorder.record("canvas_enter", QPointF(9, 9)) is None
    recorder.resume()
    now[0] += .1
    recorder.record("hover_move", QPointF(21, 0))
    assert recorder.events[-1]["t"] == 300
    assert recorder.events[-1]["v"] == 0  # reset baseline, no false jump


@pytest.fixture
def window(app, tmp_path):
    image = QPixmap(4000, 2000)
    image.fill(Qt.white)
    image.save(str(tmp_path / "image.png"))
    rows = [dict(id=f"item{i}", image="image.png" if i != 2 else "missing.png", question=f"Q{i}", answer="hidden-answer") for i in range(3)]
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(rows))
    widget = AnnotationTool(output_dir=tmp_path / "output")
    widget.show()
    assert widget.load_path(path)
    app.processEvents()
    yield widget
    widget.close()


def draw(window):
    canvas = window.canvas
    drag(canvas, canvas.to_widget(QPointF(1000, 500)), canvas.to_widget(QPointF(2000, 1000)))


def test_submit_hides_answer_until_success_and_does_not_advance(window, monkeypatch):
    draw(window)
    assert "hidden-answer" not in window.answer_label.text()
    before = copy.deepcopy(window.canvas.events)
    monkeypatch.setattr(EvaluationDialog, "exec_", lambda self: QDialog.Accepted)
    assert window.save_annotation()
    assert "hidden-answer" in window.answer_label.text()
    assert window.data_processor.current_index == 0
    assert window.canvas.events == before
    assert window.canvas.read_only
    assert not window.save_annotation()
    path = next(window.store.output_dir.glob("*.json"))
    row = json.loads(path.read_text())
    assert row["events"] == before
    assert row["annotation_time"] == round(before[-1]["t"] / 1000, 2)
    assert validate_record(row, strict=True)[0] == []
    window.navigate(1)
    assert "hidden-answer" not in window.answer_label.text()
    window.navigate(-1)
    assert window.canvas.read_only


def test_cancel_and_disk_failure_never_reveal_or_navigate(window, monkeypatch):
    draw(window)
    monkeypatch.setattr(EvaluationDialog, "exec_", lambda self: QDialog.Rejected)
    assert not window.save_annotation()
    assert window.canvas.recorder.enabled
    monkeypatch.setattr(EvaluationDialog, "exec_", lambda self: QDialog.Accepted)
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(window.store, "save", fail)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: None)
    assert not window.save_annotation()
    assert window.data_processor.current_index == 0
    assert "hidden-answer" not in window.answer_label.text()
    assert not window.canvas.read_only


def test_skipping_restores_draft_without_submitting(window):
    draw(window)
    events, boxes = window.canvas.get_events(), window.canvas.get_final_bboxes()
    window.navigate(1)
    assert not list(window.store.output_dir.glob("*.json"))
    assert not window.canvas.bboxes
    window.navigate(-1)
    assert window.canvas.get_final_bboxes() == boxes
    assert window.canvas.get_events() == events
    assert window.resumed_segments == 1
    assert "hidden-answer" not in window.answer_label.text()


def test_missing_image_clears_previous_canvas_and_disables_submit(window):
    draw(window)
    window.navigate(2)
    assert window.current_image_path is None
    assert window.canvas.image.isNull()
    assert not window.canvas.events
    assert not window.canvas.bboxes
    assert not window.save_btn.isEnabled()
    assert window.prev_btn.isEnabled()


def test_released_record_loaded_as_fresh_task_hides_annotations(window, tmp_path):
    from trace_schema import make_record
    item = window.data_processor.get_current_item()
    record = make_record(item, "item0_idx0_v1", [[100, 100, 200, 200]], [], evaluation())
    path = tmp_path / "source.jsonl"
    path.write_text(json.dumps(record) + "\n")
    assert window.load_path(path)
    assert not window.canvas.bboxes
    assert not window.canvas.events
    assert "hidden-answer" not in window.answer_label.text()


def test_review_does_not_collect_events(app, tmp_path):
    image = QPixmap(100, 100)
    image.fill(Qt.white)
    image.save(str(tmp_path / "image.png"))
    from data_processor import normalize_task
    from trace_schema import make_record
    task = normalize_task(dict(id="x", image="image.png", question="Q", answer="A"), 0)
    row = make_record(task, "x_idx0_v1", [[10, 10, 50, 50]], [], evaluation())
    path = tmp_path / "source.json"
    path.write_text(json.dumps(row))
    widget = AnnotationTool(output_dir=tmp_path / "out", review=True)
    assert widget.load_path(path)
    canvas = widget.canvas
    drag(canvas, canvas.to_widget(QPointF(10, 10)), canvas.to_widget(QPointF(70, 70)), Qt.RightButton)
    canvas.reset_view()
    assert not canvas.events
    assert canvas.get_final_bboxes() == [[10, 10, 50, 50]]
    assert not widget.save_btn.isEnabled()
    widget.close()


def test_datasets_with_same_ids_have_separate_outputs_and_image_roots(app, tmp_path):
    datasets = []
    for label, width in (("A", 100), ("B", 200)):
        folder = tmp_path / label
        folder.mkdir()
        images = folder / "photos"
        images.mkdir()
        pixmap = QPixmap(width, 100)
        pixmap.fill(Qt.white)
        pixmap.save(str(images / "same.png"))
        path = folder / "tasks.jsonl"
        path.write_text(json.dumps(dict(id="same_id", image="same.png", question="Same question?", answer="same answer")))
        datasets.append((path, images))
    window = AnnotationTool(output_dir=tmp_path / "output", images_root=datasets[0][1], dataset_name="study")
    assert window.load_path(datasets[0][0])
    first_workspace = window.workspace.path
    assert window.canvas.image.width() == 100
    assert window.commit_submission(evaluation())
    assert window.load_path(datasets[1][0])
    assert window.current_image_path is None  # Never reuse A/photos/same.png for B.
    assert window.workspace.path != first_workspace
    window.data_processor.images_root = datasets[1][1]
    window.workspace.write_manifest(window.data_processor)
    window.load_current_image()
    assert window.canvas.image.width() == 200
    assert not window.canvas.read_only
    second_workspace = window.workspace.path
    assert window.commit_submission(evaluation())
    assert len(list(first_workspace.joinpath("sessions").glob("*.json"))) == 1
    assert len(list(second_workspace.joinpath("sessions").glob("*.json"))) == 1
    assert window.load_path(datasets[0][0])
    assert window.workspace.path == first_workspace
    assert window.canvas.image.width() == 100
    assert window.canvas.read_only
    window.close()


def test_changed_task_file_creates_new_workspace(app, tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps([dict(id="x", image="absent.jpg", question="Q", answer="A")]))
    window = AnnotationTool(output_dir=tmp_path / "out")
    assert window.load_path(path)
    old_workspace = window.workspace.path
    path.write_text(json.dumps([dict(id="x", image="absent.jpg", question="Changed Q", answer="A")]))
    assert window.load_path(path)
    assert window.workspace.path != old_workspace
    assert old_workspace.joinpath("workspace.json").exists()
    window.close()
