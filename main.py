"""Human Search Traces annotation desktop application."""
import argparse
import json
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence, QPixmap
from PyQt5.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QShortcut, QSlider,
    QVBoxLayout, QWidget)

from bbox_canvas import BBoxCanvas
from data_processor import DataProcessor
from session_store import DatasetWorkspace, SessionStore, atomic_json
from tools.export_jsonl import export_sessions
from trace_schema import evaluation, validate_record

ROOT = Path(__file__).resolve().parent


class EvaluationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("提交前评价")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请评价本次搜索与证据。提交成功后显示参考答案。"))
        form = QFormLayout()
        self.difficulty = self.add_score(form, "搜索 / 定位难度", 0.5)
        self.confidence = self.add_score(form, "证据正确性置信度", 1.0)
        layout.addLayout(form)
        self.ambiguous = QCheckBox("问题存在歧义（两项分数记为 null）")
        self.ambiguous.toggled.connect(self.update_enabled)
        layout.addWidget(self.ambiguous)
        self.level = QLabel()
        self.difficulty.valueChanged.connect(self.update_level)
        self.update_level()
        layout.addWidget(self.level)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确认提交并显示答案")
        buttons.button(QDialogButtonBox.Cancel).setText("返回标注")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_score(self, form, title, default):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(round(default * 100))
        spin = QDoubleSpinBox()
        spin.setRange(0, 1)
        spin.setSingleStep(0.01)
        spin.setDecimals(2)
        spin.setValue(default)
        slider.valueChanged.connect(lambda value: spin.setValue(value / 100))
        spin.valueChanged.connect(lambda value: slider.setValue(round(value * 100)))
        spin.slider_widget = slider
        row.addWidget(slider, 1)
        row.addWidget(spin)
        form.addRow(title, widget)
        return spin

    def update_enabled(self, checked):
        for spin in (self.difficulty, self.confidence):
            spin.setEnabled(not checked)
            spin.slider_widget.setEnabled(not checked)
        self.update_level()

    def update_level(self):
        grade = self.get_evaluation()
        self.level.setText(f"难度等级：{grade['difficulty_level']}　（0.00–1.00，步长 0.01）")

    def get_evaluation(self):
        return evaluation(self.difficulty.value(), self.confidence.value(), self.ambiguous.isChecked())


class AnnotationTool(QMainWindow):
    def __init__(self, start_id=None, start_index=0, output_dir=None, images_root=None, review=False, dataset_name=None):
        super().__init__()
        self.setWindowTitle("Human Search Traces · 原图证据标注" + (" · 只读检查" if review else ""))
        self.resize(1320, 880)
        self.start_id, self.start_index = start_id, start_index
        self.images_root = images_root
        self.review = review
        self.output_root = Path(output_dir or ROOT / "output").expanduser().resolve()
        self.workspace = None
        self.dataset_name = dataset_name
        self.data_processor = None
        self.current_image_path = None
        self.store = SessionStore(self.output_root)
        self.completed = {}
        self.draft_dirty = False
        self.resumed_segments = 0
        self.init_ui()
        self.draft_timer = QTimer(self)
        self.draft_timer.timeout.connect(self.autosave_draft)
        self.draft_timer.start(5000)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        sidebar = QWidget()
        controls = QVBoxLayout(sidebar)
        heading = QLabel("只读检查历史记录" if self.review else "原图证据标注")
        heading.setStyleSheet("font-size: 22px; font-weight: 600; padding: 6px 0;")
        controls.addWidget(heading)
        self.dataset_name_input = QLineEdit(self.dataset_name or "")
        self.dataset_name_input.setPlaceholderText("数据集名称（留空自动识别，加载前填写）")
        self.dataset_name_input.setToolTip("用于输出文件夹名称；无 source_dataset 的任务也会使用此名称。")
        controls.addWidget(self.dataset_name_input)
        for title, callback in (("加载 JSON / JSONL", self.load_data_file),
                                ("选择原图目录", self.choose_images),
                                ("选择输出根目录", self.choose_output),
                                ("导出当前数据集 JSONL", self.export_current)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            controls.addWidget(button)
        self.image_info_label = self.label("请加载数据文件")
        controls.addWidget(self.image_info_label)
        controls.addWidget(QLabel("问题"))
        self.instruction_label = self.label("尚未加载", "#eaf2fb")
        self.instruction_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        controls.addWidget(self.instruction_label)
        self.answer_label = self.label("参考答案：提交后显示", "#eef4ee")
        controls.addWidget(self.answer_label)
        nav = QHBoxLayout()
        self.prev_btn = QPushButton("上一题")
        self.prev_btn.clicked.connect(lambda: self.navigate(-1))
        self.next_btn = QPushButton("下一题 / 跳过")
        self.next_btn.clicked.connect(lambda: self.navigate(1))
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        controls.addLayout(nav)
        jump = QPushButton("跳转到序号 / ID")
        jump.clicked.connect(self.jump_to)
        controls.addWidget(jump)
        self.save_btn = QPushButton("提交并评价（Ctrl / ⌘ + S）")
        self.save_btn.setStyleSheet("QPushButton {background: #245e8a; color: white; padding: 12px; font-weight: 600;}"
                                   "QPushButton:disabled {background: #d8dfe6; color: #667687;}")
        self.save_btn.clicked.connect(self.save_annotation)
        controls.addWidget(self.save_btn)
        self.reset_btn = QPushButton("恢复全图（R）")
        self.reset_btn.clicked.connect(lambda: self.canvas.reset_view())
        controls.addWidget(self.reset_btn)
        self.delete_btn = QPushButton("删除选中框（Delete）")
        self.delete_btn.clicked.connect(lambda: self.canvas.delete_selected_bbox())
        controls.addWidget(self.delete_btn)
        self.clear_btn = QPushButton("清空证据框（保留轨迹）")
        self.clear_btn.clicked.connect(self.clear_annotation)
        controls.addWidget(self.clear_btn)
        controls.addWidget(self.label("左键拖动：标证据；右键拖动：放大区域\n"
            "左键选框后拖动 / 拖角点：移动 / 调整\n"
            "Shift + 左键：在已有框内新建框\n"
            "Esc：取消当前拖动；R：恢复全图\n"
            "提交后停留当前题；下一题随时可跳过\n"
            "按钮点击与评分操作不采集鼠标轨迹。", "#fff6df"))
        controls.addStretch()
        self.status_label = self.label("就绪")
        controls.addWidget(self.status_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(sidebar)
        scroll.setMinimumWidth(330)
        scroll.setMaximumWidth(390)
        layout.addWidget(scroll)
        right = QVBoxLayout()
        self.view_label = QLabel("原始图像像素坐标")
        right.addWidget(self.view_label)
        self.canvas = BBoxCanvas()
        self.canvas.contentChanged.connect(self.on_content_changed)
        self.canvas.viewChanged.connect(self.update_view_info)
        right.addWidget(self.canvas, 1)
        layout.addLayout(right, 1)
        QShortcut(QKeySequence.Save, self, activated=self.save_annotation)
        QShortcut(QKeySequence("Alt+Right"), self, activated=lambda: self.navigate(1))
        QShortcut(QKeySequence("Alt+Left"), self, activated=lambda: self.navigate(-1))
        self.update_ui_state()

    @staticmethod
    def label(text, background="#f0f3f7"):
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setStyleSheet(f"background: {background}; color: #1e3042; padding: 10px;")
        return label

    def load_data_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择任务或记录文件", "", "JSON / JSONL (*.json *.jsonl)")
        if path:
            self.load_path(path)

    def load_path(self, path):
        # A different dataset must never silently inherit the previous image folder.
        candidate = DataProcessor(path, self.images_root if self.data_processor is None else None)
        if not candidate.load_data():
            QMessageBox.critical(self, "数据加载失败", candidate.error)
            return False
        try:
            workspace = DatasetWorkspace(self.output_root, candidate, self.dataset_name_input.text().strip() or None)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "数据集输出目录无法建立", str(exc))
            return False
        if not self.persist_current():
            return False
        self.data_processor = candidate
        self.workspace = workspace
        self.store = workspace.store
        self.completed = self.store.completed_records(candidate.data)
        index = candidate.find_index_by_id(self.start_id) if self.start_id else self.start_index
        if not 0 <= index < len(candidate.data):
            QMessageBox.warning(self, "起点无效", "未找到指定 ID 或序号，已回到第 1 题。")
            index = 0
        candidate.current_index = index
        self.load_current_image()
        return True

    def load_current_image(self):
        self.current_image_path = None
        self.canvas.clear_image()
        self.draft_dirty = False
        self.resumed_segments = 0
        item = self.data_processor.get_current_item()
        index = self.data_processor.current_index
        self.instruction_label.setText(item["question"].replace("<image>", "").strip())
        self.answer_label.setText("参考答案：提交后显示")
        self.image_info_label.setText(f"第 {index + 1} / {len(self.data_processor.data)} 题（索引 {index}）\n"
            f"{item['sample_id']}\n来源：{item['source_dataset']}\n输出：{self.workspace.path.name}/sessions")
        self.image_info_label.setToolTip(str(self.store.output_dir))
        path = self.data_processor.resolve_image()
        pixmap = QPixmap(str(path)) if path else QPixmap()
        if pixmap.isNull():
            self.canvas.clear_image(f"找不到或无法解码原图：{item['image']}\n请选择原图目录，或点击下一题跳过。")
            self.status_label.setText("当前题缺图，无法提交。上一题图像已清除。")
            self.update_ui_state()
            return
        self.current_image_path = path
        self.canvas.set_image(pixmap)
        record = item if self.review else self.completed.get(index)
        if record is not None:
            errors, warnings = validate_record(record)
            if errors:
                self.canvas.read_only = True
                self.canvas.recorder.enabled = False
                self.status_label.setText("历史记录无法检查：" + "；".join(errors[:3]))
            else:
                self.canvas.show_record(record)
                self.answer_label.setText("参考答案：" + record["answer"])
                self.status_label.setText(f"只读 · {len(record['events'])} 个事件 · {record['annotation_time']} 秒\n"
                    f"评价：{record['task_evaluation']}" + ("\n提示：" + "；".join(warnings) if warnings else ""))
        else:
            draft_path = self.store.draft_path(self.data_processor.data_path, index)
            self.status_label.setText("请阅读问题，然后在原图中搜索证据。答案将在提交后显示。")
            if draft_path.exists():
                try:
                    draft = json.loads(draft_path.read_text(encoding="utf-8"))
                    if draft["identity"] != self.identity():
                        raise ValueError("任务内容已变化，未载入旧草稿")
                    self.canvas.restore(draft["canvas"])
                    self.resumed_segments = draft.get("resumed_segments", 0) + 1
                    self.status_label.setText("已恢复未提交草稿；切题 / 关闭期间不计时。参考答案仍隐藏。")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.canvas.read_only = True
                    self.canvas.recorder.enabled = False
                    self.status_label.setText(f"草稿需要检查，已禁止覆盖：{exc}\n{draft_path}")
        self.update_view_info()
        self.update_ui_state()

    def identity(self):
        item = self.data_processor.get_current_item()
        return {key: item[key] for key in ("sample_id", "question", "image")}

    def autosave_draft(self):
        if not self.draft_dirty or self.canvas.operation or self.canvas.read_only or not self.current_image_path:
            return True
        try:
            path = self.store.draft_path(self.data_processor.data_path, self.data_processor.current_index)
            atomic_json(path, dict(identity=self.identity(), canvas=self.canvas.snapshot(),
                                   resumed_segments=self.resumed_segments))
            self.draft_dirty = False
            return True
        except (OSError, ValueError) as exc:
            self.status_label.setText(f"草稿保存失败：{exc}")
            return False

    def persist_current(self):
        if not self.data_processor or not self.current_image_path or self.canvas.read_only:
            return True
        self.canvas.freeze()
        if not self.autosave_draft():
            QMessageBox.warning(self, "草稿未保存", "草稿写入失败，当前题保持打开。请检查输出目录权限或磁盘空间。")
            self.canvas.unfreeze()
            return False
        return True

    def navigate(self, delta):
        if not self.data_processor:
            return
        target = self.data_processor.current_index + delta
        if 0 <= target < len(self.data_processor.data) and self.persist_current():
            self.data_processor.current_index = target
            self.load_current_image()

    def jump_to(self):
        if not self.data_processor:
            return
        value, ok = QInputDialog.getText(self, "跳转", "输入从 1 开始的题号，或 sample_id / session id：")
        if not ok:
            return
        target = int(value) - 1 if value.isdigit() else self.data_processor.find_index_by_id(value.strip())
        if 0 <= target < len(self.data_processor.data):
            self.navigate(target - self.data_processor.current_index)
        else:
            QMessageBox.warning(self, "无法跳转", "序号超出范围或 ID 不存在。")

    def choose_images(self):
        path = QFileDialog.getExistingDirectory(self, "选择包含原图的目录")
        if path and self.persist_current():
            if self.data_processor:
                self.data_processor.images_root = Path(path)
                try:
                    self.workspace.write_manifest(self.data_processor)
                except OSError as exc:
                    QMessageBox.warning(self, "原图目录未持久保存", str(exc))
                self.load_current_image()
            else:
                self.images_root = path

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择标注输出根目录（各数据集自动分文件夹）", str(self.output_root))
        if path and self.persist_current():
            try:
                if self.data_processor:
                    workspace = DatasetWorkspace(path, self.data_processor, self.workspace.name)
                    self.workspace = workspace
                    self.store = workspace.store
                    self.completed = self.store.completed_records(self.data_processor.data)
                    self.load_current_image()
                else:
                    self.store = SessionStore(path)
                self.output_root = Path(path).resolve()
            except (OSError, ValueError, TypeError) as exc:
                QMessageBox.critical(self, "输出目录不可用", str(exc))
                self.canvas.unfreeze()

    def export_current(self):
        if not self.workspace:
            return
        folder = self.workspace.path / "exports"
        path, _ = QFileDialog.getSaveFileName(self, "导出所有已提交会话（不含草稿）", str(folder / "sessions.jsonl"), "JSONL (*.jsonl)")
        if path:
            try:
                count = export_sessions(self.store.output_dir, path)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "导出未完成", str(exc))
                return
            QMessageBox.information(self, "导出完成", f"已导出 {count} 个独立会话。\n{path}")

    def save_annotation(self):
        if not self.data_processor or not self.current_image_path or self.canvas.read_only or self.canvas.operation:
            return False
        self.canvas.freeze()
        if not self.canvas.bboxes:
            reply = QMessageBox.question(self, "提交空框记录", "当前没有证据框。仍然提交本次搜索记录？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                self.canvas.unfreeze()
                return False
        dialog = EvaluationDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            self.canvas.unfreeze()
            return False
        return self.commit_submission(dialog.get_evaluation())

    def commit_submission(self, grade):
        """Called only after the user confirms their evaluation."""
        if not self.current_image_path or self.canvas.read_only or self.canvas.operation:
            return False
        try:
            index = self.data_processor.current_index
            path, record = self.store.save(self.data_processor.get_current_item(), index,
                self.canvas.get_final_bboxes(), self.canvas.get_events(), grade)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "提交失败", f"答案仍隐藏，当前题未切换。\n{exc}")
            self.canvas.unfreeze()
            return False
        self.completed[index] = record
        self.canvas.show_record(record)
        self.draft_dirty = False
        self.answer_label.setText("参考答案：" + record["answer"])
        self.status_label.setText(f"已提交：{path.name}\n{record['annotation_time']} 秒 · {len(record['events'])} 个事件\n"
                                  "当前记录已锁定；点击下一题继续。")
        try:
            self.store.draft_path(self.data_processor.data_path, index).unlink(missing_ok=True)
            atomic_json(self.store.state_dir / ".metadata" / path.name,
                        dict(tool_version="2.0.0", resumed_segments=self.resumed_segments,
                             image_size=[self.canvas.image.width(), self.canvas.image.height()]))
        except OSError as exc:
            self.status_label.setText(self.status_label.text() + f"\n已保存，但本地辅助信息未更新：{exc}")
        self.update_ui_state()
        return True

    def clear_annotation(self):
        if not self.canvas.bboxes or self.canvas.read_only:
            return
        if QMessageBox.question(self, "清空证据框", "删除全部证据框？已记录的搜索和操作轨迹会保留。",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.canvas.clear_canvas()

    def on_content_changed(self):
        if not self.canvas.read_only:
            self.draft_dirty = True
        self.update_view_info()

    def update_view_info(self):
        if self.canvas.image.isNull():
            self.view_label.setText("等待原图")
        else:
            scale, _ = self.canvas.mapping()
            self.view_label.setText(f"原图 {self.canvas.image.width()} × {self.canvas.image.height()} px　"
                f"显示比例 {scale:.1%}　证据框 {len(self.canvas.bboxes)}　事件 {len(self.canvas.events)}")

    def update_ui_state(self):
        loaded = self.data_processor is not None
        valid = bool(loaded and self.current_image_path)
        editable = valid and not self.canvas.read_only
        self.prev_btn.setEnabled(loaded and self.data_processor.current_index > 0)
        self.next_btn.setEnabled(loaded and self.data_processor.current_index + 1 < len(self.data_processor.data))
        for button in (self.save_btn, self.clear_btn, self.delete_btn):
            button.setEnabled(editable)
        self.reset_btn.setEnabled(valid)

    def closeEvent(self, event):
        if self.persist_current():
            event.accept()
        else:
            event.ignore()


def main():
    parser = argparse.ArgumentParser(description="Human Search Traces 原图证据标注工具")
    parser.add_argument("--data", type=Path, help="JSON / JSONL 任务文件")
    parser.add_argument("--images-root", type=Path, help="原图目录")
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--start-index", type=int, default=0, help="从 0 开始的任务索引")
    parser.add_argument("--start-id", help="起始 sample_id / session id")
    parser.add_argument("--review", action="store_true", help="只读检查已有记录；显示答案与最终框，不采集新轨迹")
    parser.add_argument("--dataset-name", help="数据集输出文件夹的可读名称；留空从来源或任务文件自动识别")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    window = AnnotationTool(args.start_id, args.start_index, args.output, args.images_root, args.review, args.dataset_name)
    window.show()
    if args.data:
        window.load_path(args.data)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
