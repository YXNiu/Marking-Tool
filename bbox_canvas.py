"""Original-resolution image canvas with explicit image/view transformations."""
import copy

from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

from trace_recorder import TraceRecorder


def box_values(rect):
    rect = rect.normalized()
    return [round(rect.left()), round(rect.top()), round(rect.right()), round(rect.bottom())]


def rect_from_box(box):
    return QRectF(QPointF(box[0], box[1]), QPointF(box[2], box[3])).normalized()


class BBoxCanvas(QWidget):
    contentChanged = pyqtSignal()
    boxTransformed = pyqtSignal(dict)
    viewChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(360, 280)
        self.image = QPixmap()
        self.view_rect = QRectF()
        self.bboxes = []
        self.recorder = TraceRecorder()
        self.selected_bbox_index = -1
        self.operation = None
        self.preview = None
        self.last_pos = None
        self.mouse_in_canvas = False
        self.hovering = False
        self.has_changes = False
        self.read_only = False
        self.message = "请加载数据文件并选择原图目录"

    @property
    def events(self):
        return self.recorder.events

    @property
    def image_rect(self):
        return QRectF(0, 0, self.image.width(), self.image.height())

    def set_image(self, pixmap):
        self.image = QPixmap(pixmap)  # Never downsample the source buffer.
        self.bboxes = []
        self.recorder = TraceRecorder()
        self.selected_bbox_index = -1
        self.operation = self.preview = self.last_pos = None
        self.mouse_in_canvas = self.hovering = self.has_changes = False
        self.read_only = False
        self.view_rect = self.image_rect
        self.update()
        self.viewChanged.emit()

    def clear_image(self, message="图片不可用，请选择原图目录或跳到下一题"):
        self.set_image(QPixmap())
        self.message = message
        self.update()

    def mapping(self):
        if self.image.isNull() or self.view_rect.isEmpty():
            return 1.0, QPointF()
        scale = min(self.width() / self.view_rect.width(), self.height() / self.view_rect.height())
        offset = QPointF((self.width() - self.view_rect.width() * scale) / 2,
                         (self.height() - self.view_rect.height() * scale) / 2)
        return scale, offset

    def to_image(self, pos, clamp=False):
        scale, offset = self.mapping()
        point = (QPointF(pos) - offset) / scale + self.view_rect.topLeft()
        if clamp:
            point.setX(max(0, min(self.image.width(), point.x())))
            point.setY(max(0, min(self.image.height(), point.y())))
        return point

    def to_widget(self, point):
        scale, offset = self.mapping()
        return (QPointF(point) - self.view_rect.topLeft()) * scale + offset

    def emit_event(self, kind, pos=None, **fields):
        event = self.recorder.record(kind, pos, **fields)
        if event:
            self.has_changes = True
            self.contentChanged.emit()
        return event

    def ensure_enter(self, pos):
        if not self.mouse_in_canvas or (self.recorder.enabled and not self.recorder.running):
            self.mouse_in_canvas = True
            self.emit_event("canvas_enter", pos)

    def leave_canvas(self):
        if not self.mouse_in_canvas:
            return
        # Qt can keep delivering mouse events while a pressed button grabs the
        # pointer outside the widget. End the unfinished gesture at its last
        # in-canvas position, then stop both sampling and the active-time clock.
        self.cancel_operation()
        self.end_hover(self.last_pos)
        self.mouse_in_canvas = False
        self.emit_event("canvas_leave", self.last_pos)
        self.recorder.stop_clock()
        self.viewChanged.emit()

    def end_hover(self, pos):
        if self.hovering:
            self.emit_event("hover_end", pos)
            self.hovering = False

    def enterEvent(self, event):
        if not self.image.isNull():
            point = self.to_image(self.mapFromGlobal(QCursor.pos()))
            self.ensure_enter(point)
            self.last_pos = point
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.leave_canvas()
        super().leaveEvent(event)

    def hit_test(self, widget_pos):
        # Test all handles before interiors so small or overlapping boxes work.
        for i in reversed(range(len(self.bboxes))):
            box = self.bboxes[i]
            for name, point in (("tl", box.topLeft()), ("tr", box.topRight()),
                                ("bl", box.bottomLeft()), ("br", box.bottomRight())):
                delta = self.to_widget(point) - QPointF(widget_pos)
                if abs(delta.x()) <= 7 and abs(delta.y()) <= 7:
                    return i, name
        point = self.to_image(widget_pos)
        for i in reversed(range(len(self.bboxes))):
            if self.bboxes[i].contains(point):
                return i, None
        return -1, None

    def mousePressEvent(self, event):
        if self.image.isNull() or self.operation or event.button() not in (Qt.LeftButton, Qt.RightButton):
            return
        if not self.rect().contains(event.pos()):
            self.leave_canvas()
            return
        if self.read_only and event.button() == Qt.LeftButton:
            return
        self.setFocus()
        raw = self.to_image(event.pos())
        if not self.view_rect.contains(raw):
            return
        pos = self.to_image(event.pos(), clamp=True)
        self.ensure_enter(raw)
        self.end_hover(raw)
        self.recorder.reset_motion()
        self.last_pos = raw
        self.anchor = pos
        self.anchor_widget = QPointF(event.pos())
        if event.button() == Qt.RightButton:
            self.operation = "zoom"
            self.preview = QRectF(pos, pos)
            self.emit_event("zoom_start", raw)
        else:
            index, handle = self.hit_test(event.pos()) if not event.modifiers() & Qt.ShiftModifier else (-1, None)
            self.selected_bbox_index = index
            if index >= 0:
                self.operation = "edit"
                self.before = QRectF(self.bboxes[index])
                self.handle = handle
                self.mode = "resize" if handle else "move"
                self.emit_event("select_bbox", raw, index=index, bbox=box_values(self.before))
                self.emit_event("edit_start", raw, **self.edit_fields())
            else:
                self.operation = "create"
                self.selected_bbox_index = len(self.bboxes)
                self.preview = QRectF(pos, pos)
                self.emit_event("down", raw)
                self.emit_event("create_start", raw, bbox={"index": self.selected_bbox_index})
        self.update()

    def edit_fields(self):
        return dict(index=self.selected_bbox_index, mode=self.mode, handle=self.handle,
                    bbox=box_values(self.bboxes[self.selected_bbox_index]))

    def update_operation(self, pos):
        if self.operation in ("create", "zoom"):
            self.preview = QRectF(self.anchor, pos).normalized()
        elif self.operation == "edit":
            box = QRectF(self.before)
            if self.mode == "move":
                delta = pos - self.anchor
                dx = max(-box.left(), min(self.image.width() - box.right(), delta.x()))
                dy = max(-box.top(), min(self.image.height() - box.bottom(), delta.y()))
                box.translate(dx, dy)
            else:
                opposite = {"tl": box.bottomRight(), "tr": box.bottomLeft(),
                            "bl": box.topRight(), "br": box.topLeft()}[self.handle]
                box = QRectF(pos, opposite).normalized().intersected(self.image_rect)
            self.bboxes[self.selected_bbox_index] = box

    def mouseMoveEvent(self, event):
        if self.image.isNull():
            return
        if not self.rect().contains(event.pos()):
            self.leave_canvas()
            return
        raw = self.to_image(event.pos())
        self.last_pos = raw
        if not self.read_only:
            self.ensure_enter(raw)
        if self.operation:
            self.update_operation(self.to_image(event.pos(), clamp=True))
            if self.operation == "zoom":
                self.emit_event("zoom_move", raw, bbox=box_values(self.preview))
            elif self.operation == "create":
                self.emit_event("drag_move", raw, bbox={"bbox": box_values(self.preview), "index": self.selected_bbox_index})
            else:
                self.emit_event("edit_move", raw, **self.edit_fields())
        elif not self.read_only:
            if not self.hovering and self.events and self.events[-1]["type"] == "up":
                self.emit_event("hover_start", raw)
            self.hovering = True
            self.emit_event("hover_move", raw)
            index, handle = self.hit_test(event.pos())
            self.setCursor(Qt.SizeFDiagCursor if handle in ("tl", "br") else
                           Qt.SizeBDiagCursor if handle else Qt.SizeAllCursor if index >= 0 else Qt.CrossCursor)
        self.update()

    def mouseReleaseEvent(self, event):
        if not self.rect().contains(event.pos()):
            self.leave_canvas()
            return
        if not self.operation:
            return
        if (self.operation == "zoom") != (event.button() == Qt.RightButton):
            return
        pos = self.to_image(event.pos(), clamp=True)
        self.update_operation(pos)  # Release position may differ from last move.
        if self.operation == "zoom":
            screen_delta = QPointF(event.pos()) - self.anchor_widget
            if abs(screen_delta.x()) >= 4 and abs(screen_delta.y()) >= 4 and self.preview.width() >= 1 and self.preview.height() >= 1:
                self.emit_event("zoom_end", pos, bbox=box_values(self.preview))
                self.view_rect = QRectF(self.preview)
                self.viewChanged.emit()
            else:
                self.emit_event("zoom_end", pos, canceled=True)
        elif self.operation == "create":
            box = box_values(self.preview)
            self.emit_event("create_end", pos, bbox=box, index=self.selected_bbox_index)
            if box[0] < box[2] and box[1] < box[3]:
                self.bboxes.append(rect_from_box(box))
            else:
                # Keep the attempted action in the trace, but not a zero-area final box.
                self.emit_event("delete_bbox", index=self.selected_bbox_index, bbox=box)
                self.selected_bbox_index = -1
            self.emit_event("up", pos)
        else:
            box = box_values(self.bboxes[self.selected_bbox_index])
            if box[0] >= box[2] or box[1] >= box[3]:
                self.bboxes[self.selected_bbox_index] = self.before
            else:
                self.bboxes[self.selected_bbox_index] = rect_from_box(box)
            self.emit_event("edit_end", pos, **self.edit_fields())
        self.operation = self.preview = None
        self.recorder.reset_motion()
        self.contentChanged.emit()
        self.update()

    def cancel_operation(self):
        if not self.operation:
            return
        if self.operation == "zoom":
            self.emit_event("zoom_end", self.last_pos, canceled=True)
        elif self.operation == "edit":
            self.bboxes[self.selected_bbox_index] = self.before
            self.emit_event("edit_end", self.last_pos, **self.edit_fields())
        else:
            box = box_values(self.preview)
            self.emit_event("create_end", self.last_pos, bbox=box, index=self.selected_bbox_index)
            self.emit_event("delete_bbox", index=self.selected_bbox_index, bbox=box)
            self.emit_event("up", self.last_pos)
            self.selected_bbox_index = -1
        self.operation = self.preview = None
        self.contentChanged.emit()
        self.update()

    def reset_view(self):
        if self.image.isNull():
            return
        self.cancel_operation()
        if self.view_rect != self.image_rect:
            self.emit_event("zoom_reset")  # Operation only; no button coordinates.
            self.view_rect = self.image_rect
            self.recorder.reset_motion()
            self.viewChanged.emit()
            self.update()

    def delete_selected_bbox(self):
        if self.read_only or self.operation:
            return
        if 0 <= self.selected_bbox_index < len(self.bboxes):
            index = self.selected_bbox_index
            self.emit_event("delete_bbox", index=index, bbox=box_values(self.bboxes[index]))
            del self.bboxes[index]
            self.selected_bbox_index = -1
            self.contentChanged.emit()
            self.update()

    def clear_canvas(self):
        """Delete boxes, preserving the entire search history and clock."""
        if self.read_only:
            return
        self.cancel_operation()
        while self.bboxes:
            self.selected_bbox_index = len(self.bboxes) - 1
            self.delete_selected_bbox()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected_bbox()
        elif event.key() == Qt.Key_R:
            self.reset_view()
        elif event.key() == Qt.Key_Escape:
            self.cancel_operation()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        # A window resize changes the screen-to-image map, not pointer motion.
        self.recorder.reset_motion()
        self.viewChanged.emit()
        super().resizeEvent(event)

    def freeze(self):
        self.cancel_operation()
        self.recorder.pause()
        self.viewChanged.emit()

    def unfreeze(self):
        self.recorder.resume(running=self.mouse_in_canvas)
        self.viewChanged.emit()

    def show_record(self, record):
        self.bboxes = [rect_from_box(box) for box in record["final_bboxes_pixels"]]
        self.recorder.restore(record["events"])
        self.recorder.enabled = False
        self.read_only = True
        self.has_changes = False
        self.viewChanged.emit()
        self.update()

    def snapshot(self):
        return dict(boxes=self.get_final_bboxes(), events=self.get_events(), view=box_values(self.view_rect),
                    image_size=[self.image.width(), self.image.height()])

    def restore(self, snapshot):
        if snapshot["image_size"] != [self.image.width(), self.image.height()]:
            raise ValueError("草稿的原图尺寸与当前图片不一致")
        self.bboxes = [rect_from_box(box) for box in snapshot["boxes"]]
        self.view_rect = rect_from_box(snapshot["view"]).intersected(self.image_rect)
        if self.view_rect.isEmpty():
            self.view_rect = self.image_rect
        self.recorder.restore(snapshot["events"])
        self.has_changes = bool(self.events or self.bboxes)
        self.update()

    def get_final_bboxes(self):
        return [box_values(box) for box in self.bboxes]

    def get_events(self):
        return copy.deepcopy(self.events)  # Preserve append order, including equal timestamps.

    def has_unsaved_changes(self):
        return self.has_changes

    def reset_changes(self):
        self.has_changes = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#202936"))
        if self.image.isNull():
            painter.setPen(QColor("#dae3ed"))
            painter.drawText(self.rect().adjusted(24, 24, -24, -24), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scale, offset = self.mapping()
        target = QRectF(offset, self.view_rect.size() * scale)
        painter.drawPixmap(target, self.image, self.view_rect)
        painter.setClipRect(target)
        for i, box in enumerate(self.bboxes):
            color = QColor("#ff5f63" if i == self.selected_bbox_index else "#44e39a")
            painter.setPen(QPen(color, 2))
            rect = QRectF(self.to_widget(box.topLeft()), self.to_widget(box.bottomRight()))
            painter.drawRect(rect)
            painter.drawText(rect.topLeft() + QPointF(3, -4), str(i + 1))
            if i == self.selected_bbox_index and not self.read_only:
                for p in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                    painter.fillRect(QRectF(p.x() - 3, p.y() - 3, 6, 6), color)
        if self.preview is not None:
            painter.setPen(QPen(QColor("#75c7ff" if self.operation == "zoom" else "#44e39a"), 2, Qt.DashLine))
            painter.drawRect(QRectF(self.to_widget(self.preview.topLeft()), self.to_widget(self.preview.bottomRight())))
