import json
import time
import numpy as np
from PyQt5.QtWidgets import QWidget, QLabel
from PyQt5.QtCore import Qt, QPoint, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QPixmap


class BBoxCanvas(QLabel):
    # 信号：当有框变换时发出
    boxTransformed = pyqtSignal(dict)
    contentChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignTop)

        # 状态变量
        self.bboxes = []
        self.current_bbox = None
        self.drawing = False
        self.resizing = False
        self.moving = False
        self.selected_bbox_index = -1
        self.resize_corner = None

        # 事件记录
        self.events = []
        self.last_mouse_pos = None
        self.start_time = None
        self.last_event_time = None
        self.last_velocity = 0

        # 移动相关的变量
        self.move_start_pos = None
        self.move_start_bbox = None

        # 样式
        self.bbox_color = QColor(0, 255, 0)
        self.selected_bbox_color = QColor(255, 0, 0)
        self.pen_width = 2

        # 内容变化标记
        self.has_changes = False

        # 时间间隔控制
        self.last_record_time = 0
        self.record_interval = 0.1

        # 悬停记录相关变量
        self.last_hover_pos = None
        self.hover_start_time = None
        self.hover_record_interval = 0.2
        self.last_hover_record_time = 0
        self.is_hovering = False

        # 新增：画布状态跟踪
        self.mouse_in_canvas = False  # 鼠标是否在画布内
        self.last_canvas_enter_time = None  # 上次进入画布时间

    def set_image(self, pixmap):
        """设置图片"""
        self.setPixmap(pixmap)
        self.clear_canvas()

    def clear_canvas(self):
        """清空画布"""
        self.bboxes = []
        self.events = []
        self.current_bbox = None
        self.selected_bbox_index = -1
        self.drawing = False
        self.resizing = False
        self.moving = False
        self.resize_corner = None
        self.last_mouse_pos = None
        self.start_time = None
        self.last_event_time = None
        self.last_velocity = 0
        self.move_start_pos = None
        self.move_start_bbox = None
        self.last_record_time = 0
        self.has_changes = False

        # 清空悬停状态
        self.last_hover_pos = None
        self.hover_start_time = None
        self.last_hover_record_time = 0
        self.is_hovering = False

        # 新增：重置画布状态
        self.mouse_in_canvas = False
        self.last_canvas_enter_time = None

    def mark_content_changed(self):
        """标记内容已变化"""
        if not self.has_changes:
            self.has_changes = True
            self.contentChanged.emit()

    def reset_changes(self):
        """重置变化标记"""
        self.has_changes = False

    def record_event(self, event_type, pos=None, bbox_data=None, category="drag"):
        """记录鼠标事件"""
        current_time = time.time()

        # 初始化开始时间
        if self.start_time is None:
            self.start_time = current_time

        # 使用相对时间戳（毫秒）
        relative_time = (current_time - self.start_time) * 1000

        # 计算速度和加速度（仅对移动事件）
        velocity = 0
        acceleration = 0

        if pos and self.last_event_time is not None:
            time_diff = current_time - self.last_event_time
            if time_diff > 0.01:  # 至少10ms间隔才记录
                if self.last_mouse_pos:
                    dx = pos.x() - self.last_mouse_pos.x()
                    dy = pos.y() - self.last_mouse_pos.y()
                    distance = np.sqrt(dx ** 2 + dy ** 2)
                    current_velocity = distance / time_diff

                    # 计算加速度
                    acceleration = (current_velocity - self.last_velocity) / time_diff
                    velocity = current_velocity
                    self.last_velocity = current_velocity

        event = {
            "type": event_type,
            "t": round(relative_time, 1),
            "v": round(velocity, 2),
            "a": round(acceleration, 2),
            "category": category
        }

        # 添加位置信息（如果有）
        if pos:
            event["x"] = pos.x()
            event["y"] = pos.y()

        if bbox_data:
            event["bbox"] = bbox_data

        self.events.append(event)

        # 更新最后位置和时间（仅对移动事件）
        if pos:
            self.last_mouse_pos = QPoint(pos.x(), pos.y())
            self.last_event_time = current_time

        return event

    def record_hover_event(self, event_type, pos):
        """专门记录悬停事件"""
        if self.drawing or self.moving or self.resizing:
            return

        current_time = time.time()

        if self.start_time is None:
            self.start_time = current_time

        relative_time = (current_time - self.start_time) * 1000

        # 计算速度
        velocity = 0
        if self.last_hover_pos:
            dx = pos.x() - self.last_hover_pos.x()
            dy = pos.y() - self.last_hover_pos.y()
            distance = np.sqrt(dx ** 2 + dy ** 2)
            time_diff = current_time - self.last_hover_record_time
            if time_diff > 0.01:
                velocity = distance / time_diff

        event = {
            "type": event_type,
            "x": pos.x(),
            "y": pos.y(),
            "t": round(relative_time, 1),
            "v": round(velocity, 2),
            "a": 0,
            "category": "hover"
        }

        self.events.append(event)
        self.last_hover_pos = QPoint(pos.x(), pos.y())
        self.last_hover_record_time = current_time

    # 新增：画布进入/离开事件
    def enterEvent(self, event):
        """鼠标进入画布事件"""
        pos = event.pos()
        current_time = time.time()

        # 记录进入事件
        self.record_event("canvas_enter", pos, category="canvas")

        # 更新状态
        self.mouse_in_canvas = True
        self.last_canvas_enter_time = current_time

        # 如果之前有悬停未结束，记录一个虚拟的结束（容错处理）
        if self.is_hovering and not (self.drawing or self.moving or self.resizing):
            self.record_hover_event("hover_end", pos)
            self.is_hovering = False

        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开画布事件"""
        # 获取离开时的位置（近似值）
        pos = self.last_mouse_pos if self.last_mouse_pos else QPoint(0, 0)

        # 记录离开事件
        self.record_event("canvas_leave", pos, category="canvas")

        # 计算在画布内停留的时间
        stay_duration = 0
        if self.last_canvas_enter_time:
            stay_duration = round((time.time() - self.last_canvas_enter_time) * 1000, 1)  # 毫秒

        # 添加停留时间信息到离开事件
        if self.events and self.events[-1]["type"] == "canvas_leave":
            self.events[-1]["stay_duration"] = stay_duration

        # 更新状态
        self.mouse_in_canvas = False
        self.last_canvas_enter_time = None

        # 结束当前的悬停状态
        if self.is_hovering:
            self.record_hover_event("hover_end", pos)
            self.is_hovering = False

        super().leaveEvent(event)

    def get_nearby_corner(self, pos, bbox):
        """检查鼠标是否靠近bbox的角点"""
        corners = [
            (bbox.left(), bbox.top(), "top_left"),
            (bbox.right(), bbox.top(), "top_right"),
            (bbox.left(), bbox.bottom(), "bottom_left"),
            (bbox.right(), bbox.bottom(), "bottom_right")
        ]

        threshold = 8

        for x, y, corner_type in corners:
            if abs(pos.x() - x) < threshold and abs(pos.y() - y) < threshold:
                return corner_type

        return None

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            pos = event.pos()

            # 确保鼠标在画布内（安全检查）
            if not self.mouse_in_canvas:
                self.mouse_in_canvas = True
                # 记录一个进入事件（补救措施）
                self.record_event("canvas_enter", pos, category="canvas")

            # 记录悬停结束
            if self.is_hovering:
                self.record_hover_event("hover_end", pos)
                self.is_hovering = False

            self.record_event("down", pos)

            # 检查是否选中了现有的bbox
            self.selected_bbox_index = -1
            for i, bbox in enumerate(self.bboxes):
                if bbox.contains(pos):
                    self.selected_bbox_index = i
                    self.current_bbox = bbox

                    # 检查是否靠近角点（调整大小）
                    self.resize_corner = self.get_nearby_corner(pos, bbox)
                    if self.resize_corner:
                        self.resizing = True
                        self.record_event("resize_start", pos, {
                            "index": i,
                            "corner": self.resize_corner,
                            "before": [bbox.left(), bbox.top(), bbox.right(), bbox.bottom()]
                        })
                    else:
                        self.moving = True
                        self.move_start_pos = pos
                        self.move_start_bbox = QRect(bbox)
                        self.record_event("move_start", pos, {
                            "index": i,
                            "before": [bbox.left(), bbox.top(), bbox.right(), bbox.bottom()]
                        })
                    break

            # 如果没有选中任何bbox，开始绘制新bbox
            if self.selected_bbox_index == -1:
                self.drawing = True
                self.current_bbox = QRect(pos, pos)
                self.bboxes.append(self.current_bbox)
                self.selected_bbox_index = len(self.bboxes) - 1

                self.record_event("create_start", pos, {
                    "index": self.selected_bbox_index,
                    "before": None
                })

            self.mark_content_changed()
            self.update()

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        pos = event.pos()
        current_time = time.time()

        # 更新光标形状
        cursor_shape = Qt.ArrowCursor
        if not (self.drawing or self.moving or self.resizing):
            for i, bbox in enumerate(self.bboxes):
                corner = self.get_nearby_corner(pos, bbox)
                if corner:
                    if corner in ["top_left", "bottom_right"]:
                        cursor_shape = Qt.SizeFDiagCursor
                    elif corner in ["top_right", "bottom_left"]:
                        cursor_shape = Qt.SizeBDiagCursor
                    break

                if bbox.contains(pos):
                    cursor_shape = Qt.SizeAllCursor
                    break

        self.setCursor(cursor_shape)

        # 记录悬停移动事件
        if not (self.drawing or self.moving or self.resizing):
            if not self.is_hovering:
                self.record_hover_event("hover_start", pos)
                self.is_hovering = True
                self.hover_start_time = current_time

            if current_time - self.last_hover_record_time >= self.hover_record_interval:
                self.record_hover_event("hover_move", pos)
                self.last_hover_record_time = current_time

        # 处理绘制、移动或调整大小
        if self.drawing and self.current_bbox:
            self.current_bbox.setBottomRight(pos)

        elif self.moving and self.current_bbox and self.move_start_pos:
            dx = pos.x() - self.move_start_pos.x()
            dy = pos.y() - self.move_start_pos.y()
            new_bbox = QRect(self.move_start_bbox)
            new_bbox.translate(dx, dy)
            self.current_bbox.setRect(new_bbox.x(), new_bbox.y(), new_bbox.width(), new_bbox.height())

        elif self.resizing and self.current_bbox:
            if self.resize_corner == "top_left":
                self.current_bbox.setTopLeft(pos)
            elif self.resize_corner == "top_right":
                self.current_bbox.setTopRight(pos)
            elif self.resize_corner == "bottom_left":
                self.current_bbox.setBottomLeft(pos)
            elif self.resize_corner == "bottom_right":
                self.current_bbox.setBottomRight(pos)

        # 每100ms记录一次移动事件
        if (self.drawing or self.moving or self.resizing) and self.current_bbox:
            if current_time - self.last_record_time >= self.record_interval:
                self.record_event("drag_move", pos, category="drag")
                self.last_record_time = current_time

        self.update()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton:
            pos = event.pos()

            if self.drawing:
                if (abs(self.current_bbox.width()) < 5 or
                        abs(self.current_bbox.height()) < 5):
                    if self.current_bbox in self.bboxes:
                        self.bboxes.remove(self.current_bbox)
                    self.selected_bbox_index = -1
                else:
                    self.record_event("create_end", pos, {
                        "index": self.selected_bbox_index,
                        "after": [
                            self.current_bbox.left(),
                            self.current_bbox.top(),
                            self.current_bbox.right(),
                            self.current_bbox.bottom()
                        ]
                    })

            elif self.moving:
                self.record_event("move_end", pos, {
                    "index": self.selected_bbox_index,
                    "after": [
                        self.current_bbox.left(),
                        self.current_bbox.top(),
                        self.current_bbox.right(),
                        self.current_bbox.bottom()
                    ]
                })

            elif self.resizing:
                self.record_event("resize_end", pos, {
                    "index": self.selected_bbox_index,
                    "corner": self.resize_corner,
                    "after": [
                        self.current_bbox.left(),
                        self.current_bbox.top(),
                        self.current_bbox.right(),
                        self.current_bbox.bottom()
                    ]
                })

            self.record_event("up", pos)

            # 鼠标释放后重新开始悬停记录
            self.is_hovering = False

            # 重置状态
            self.drawing = False
            self.moving = False
            self.resizing = False
            self.resize_corner = None
            self.move_start_pos = None
            self.move_start_bbox = None

    def keyPressEvent(self, event):
        """键盘事件"""
        if event.key() == Qt.Key_Delete:
            self.delete_selected_bbox()

    def delete_selected_bbox(self):
        """删除选中的bbox"""
        if 0 <= self.selected_bbox_index < len(self.bboxes):
            bbox = self.bboxes[self.selected_bbox_index]
            self.record_event("delete", QPoint(0, 0), {
                "index": self.selected_bbox_index,
                "bbox": [bbox.left(), bbox.top(), bbox.right(), bbox.bottom()]
            })
            del self.bboxes[self.selected_bbox_index]
            self.selected_bbox_index = -1
            self.mark_content_changed()
            self.update()

    def paintEvent(self, event):
        """绘制事件"""
        super().paintEvent(event)

        if not self.pixmap():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制所有bbox
        for i, bbox in enumerate(self.bboxes):
            if i == self.selected_bbox_index:
                pen = QPen(self.selected_bbox_color, self.pen_width)
            else:
                pen = QPen(self.bbox_color, self.pen_width)

            painter.setPen(pen)
            painter.drawRect(bbox)

            # 如果是选中的bbox，绘制调整手柄
            if i == self.selected_bbox_index:
                self.draw_resize_handles(painter, bbox)

    def draw_resize_handles(self, painter, bbox):
        """绘制调整手柄"""
        handle_size = 6
        painter.setBrush(self.selected_bbox_color)

        corners = [
            QPoint(bbox.left(), bbox.top()),
            QPoint(bbox.right(), bbox.top()),
            QPoint(bbox.left(), bbox.bottom()),
            QPoint(bbox.right(), bbox.bottom())
        ]

        for corner in corners:
            handle_rect = QRect(corner.x() - handle_size // 2,
                                corner.y() - handle_size // 2,
                                handle_size, handle_size)
            painter.fillRect(handle_rect, self.selected_bbox_color)

    def get_final_bboxes(self):
        """获取最终的bbox坐标列表"""
        result = []
        for bbox in self.bboxes:
            left = min(bbox.left(), bbox.right())
            top = min(bbox.top(), bbox.bottom())
            right = max(bbox.left(), bbox.right())
            bottom = max(bbox.top(), bbox.bottom())
            result.append([left, top, right, bottom])
        return result

    def get_events(self):
        """获取所有事件记录"""
        sorted_events = sorted(self.events, key=lambda x: x["t"])
        return sorted_events

    def has_unsaved_changes(self):
        """检查是否有未保存的更改"""
        return self.has_changes