import sys
import os
import json
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QPushButton, QLabel, QScrollArea, QMessageBox,
                             QFileDialog, QSizePolicy, QInputDialog, QDialog, QListWidget)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QFont
from data_processor import DataProcessor
from bbox_canvas import BBoxCanvas


class StartDialog(QDialog):
    """启动选择对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择标注起点")
        self.setGeometry(200, 200, 400, 300)

        self.selected_id = None
        self.start_index = 0
        self.init_ui()

    def init_ui(self):

        layout = QVBoxLayout(self)

        # 说明文字
        info_label = QLabel("请选择标注起点（用于继续之前的标注工作）")
        layout.addWidget(info_label)

        # 选项按钮
        start_from_beginning_btn = QPushButton("从开始处标注")
        start_from_beginning_btn.clicked.connect(self.start_from_beginning)
        layout.addWidget(start_from_beginning_btn)

        start_from_id_btn = QPushButton("从指定ID开始标注")
        start_from_id_btn.clicked.connect(self.start_from_id)
        layout.addWidget(start_from_id_btn)

        start_from_index_btn = QPushButton("从指定序号开始标注")
        start_from_index_btn.clicked.connect(self.start_from_index)
        layout.addWidget(start_from_index_btn)

        # 状态显示
        self.status_label = QLabel("选择: 从开始处标注")
        layout.addWidget(self.status_label)

        # 确定按钮
        confirm_btn = QPushButton("确定")
        confirm_btn.clicked.connect(self.accept)
        layout.addWidget(confirm_btn)

    def start_from_beginning(self):
        self.selected_id = None
        self.start_index = 0
        self.status_label.setText("选择: 从开始处标注")

    def start_from_id(self):
        id, ok = QInputDialog.getText(self, "输入ID", "请输入要开始的ID:")
        if ok and id:
            self.selected_id = id.strip()
            self.start_index = 0  # 将在加载数据后查找
            self.status_label.setText(f"选择: 从ID '{self.selected_id}' 开始")

    def start_from_index(self):
        index, ok = QInputDialog.getInt(self, "输入序号", "请输入要开始的序号(从0开始):", 0, 0, 100000, 1)
        if ok:
            self.start_index = index
            self.selected_id = None
            self.status_label.setText(f"选择: 从序号 {self.start_index} 开始")


class AnnotationTool(QMainWindow):
    def __init__(self, start_id=None, start_index=0):
        super().__init__()
        self.setWindowTitle("RLHF 数据标注工具")
        self.setGeometry(100, 100, 1200, 800)

        # 启动参数
        self.start_id = start_id
        self.start_index = start_index

        # 数据处理器
        self.data_processor = None
        self.current_image_path = None

        # 输出目录
        self.output_dir = "output"
        os.makedirs(self.output_dir, exist_ok=True)

        # 标注计数器 - 记录每张图片的标注次数
        self.annotation_count = {}

        # 已保存的标注记录
        self.saved_annotations = set()

        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QHBoxLayout(central_widget)

        # 左侧控制面板
        left_panel = QWidget()
        left_panel.setFixedWidth(300)
        left_layout = QVBoxLayout(left_panel)

        # 文件加载按钮
        load_btn = QPushButton("加载数据文件")
        load_btn.clicked.connect(self.load_data_file)
        left_layout.addWidget(load_btn)

        # 图片信息显示
        self.image_info_label = QLabel("请先加载数据文件")
        self.image_info_label.setWordWrap(True)
        self.image_info_label.setStyleSheet("background-color: #f0f0f0; padding: 10px; margin: 5px 0;")
        left_layout.addWidget(self.image_info_label)

        # 指令显示
        instruction_label = QLabel("指令:")
        instruction_label.setFont(QFont("Arial", 10, QFont.Bold))
        left_layout.addWidget(instruction_label)

        self.instruction_label = QLabel("无指令")
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setStyleSheet("background-color: #e8f4fd; padding: 10px; margin: 5px 0;")
        left_layout.addWidget(self.instruction_label)

        # 导航按钮
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("上一张")
        self.prev_btn.clicked.connect(self.prev_image)
        self.prev_btn.setEnabled(False)

        self.next_btn = QPushButton("下一张")
        self.next_btn.clicked.connect(self.next_image)
        self.next_btn.setEnabled(False)

        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.next_btn)
        left_layout.addLayout(nav_layout)

        # 标注控制按钮
        self.save_btn = QPushButton("保存标注")
        self.save_btn.clicked.connect(self.save_annotation)
        self.save_btn.setEnabled(False)

        self.clear_btn = QPushButton("清空标注")
        self.clear_btn.clicked.connect(self.clear_annotation)
        self.clear_btn.setEnabled(False)

        self.delete_btn = QPushButton("删除选中框 (Del)")
        self.delete_btn.clicked.connect(self.delete_selected_bbox)
        self.delete_btn.setEnabled(False)

        left_layout.addWidget(self.save_btn)
        left_layout.addWidget(self.clear_btn)
        left_layout.addWidget(self.delete_btn)

        # 帮助信息
        help_label = QLabel("""
使用说明:
• 鼠标左键拖拽绘制边界框
• 点击边界框选中，拖拽移动
• 拖拽边界框角点调整大小
• Delete键删除选中的边界框
• 红色框表示当前选中的边界框
        """)
        help_label.setStyleSheet("background-color: #fff3cd; padding: 10px; margin: 10px 0;")
        help_label.setWordWrap(True)
        left_layout.addWidget(help_label)

        left_layout.addStretch()

        # 状态显示
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("background-color: #d1ecf1; padding: 5px;")
        left_layout.addWidget(self.status_label)

        # 右侧图像显示区域
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setAlignment(Qt.AlignCenter)

        # 画布
        self.canvas = BBoxCanvas()
        self.canvas.contentChanged.connect(self.on_content_changed)
        scroll_area.setWidget(self.canvas)

        right_layout.addWidget(scroll_area)

        # 添加到主布局
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)

    def load_data_file(self):
        """加载数据文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择数据文件", "", "JSON files (*.json)"
        )

        if file_path:
            self.data_processor = DataProcessor(file_path)
            if self.data_processor.load_data():
                # 根据启动参数跳转到指定位置
                self.jump_to_start_position()
                self.update_ui_state()
                self.load_current_image()
                self.status_label.setText(f"已加载 {len(self.data_processor.data)} 条数据")
            else:
                QMessageBox.critical(self, "错误", "数据文件加载失败")

    def jump_to_start_position(self):
        """跳转到指定的起始位置"""
        if self.start_id:
            # 查找指定ID的位置
            found = False
            for i, item in enumerate(self.data_processor.data):
                if item.get("id") == self.start_id:
                    self.data_processor.current_index = i
                    found = True
                    self.status_label.setText(f"已跳转到ID: {self.start_id} (位置: {i})")
                    break

            if not found:
                QMessageBox.warning(self, "警告", f"未找到ID: {self.start_id}，将从开始处标注")
                self.data_processor.current_index = 0

        elif self.start_index > 0:
            # 跳转到指定索引
            if self.start_index < len(self.data_processor.data):
                self.data_processor.current_index = self.start_index
                self.status_label.setText(f"已跳转到序号: {self.start_index}")
            else:
                QMessageBox.warning(self, "警告", f"序号 {self.start_index} 超出范围，将从最后一条数据开始")
                self.data_processor.current_index = len(self.data_processor.data) - 1

    def update_ui_state(self):
        """更新UI状态"""
        has_data = self.data_processor and len(self.data_processor.data) > 0

        self.prev_btn.setEnabled(has_data and self.data_processor.current_index > 0)
        self.next_btn.setEnabled(has_data and self.data_processor.current_index < len(self.data_processor.data) - 1)
        self.save_btn.setEnabled(has_data)
        self.clear_btn.setEnabled(has_data)
        self.delete_btn.setEnabled(has_data)

    def load_current_image(self):
        """加载当前图片"""
        if not self.data_processor:
            return

        item = self.data_processor.get_current_item()
        if not item:
            return

        image_path = item.get("image", "")
        instruction = item.get("instruction", "")

        # 构建信息显示文本
        info_text = f"图片 {self.data_processor.current_index + 1}/{len(self.data_processor.data)}\n"
        info_text += f"ID: {item.get('id', 'N/A')}\n"
        info_text += f"类型: {item.get('type', 'N/A')}\n"

        # 如果是VLM-R1数据，显示额外信息
        if item.get('original_format') == 'vlmr1' or item.get('type', '').startswith('vlmr1'):
            info_text += "来源: VLM-R1数据集\n"
            if item.get('original_bbox'):
                info_text += f"原标注: {item['original_bbox']}\n"

        self.image_info_label.setText(info_text)
        self.instruction_label.setText(instruction)

        # 其余代码保持不变...
        # 加载图片部分...

        # 加载图片
        if os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                # 缩放图片以适应显示
                max_size = 800
                if pixmap.width() > max_size or pixmap.height() > max_size:
                    pixmap = pixmap.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

                self.canvas.set_image(pixmap)
                self.current_image_path = image_path
                self.status_label.setText(f"已加载图片: {os.path.basename(image_path)}")
            else:
                QMessageBox.warning(self, "警告", f"无法加载图片: {image_path}")
        else:
            QMessageBox.warning(self, "警告", f"图片文件不存在: {image_path}")

        self.update_ui_state()

    def check_unsaved_changes(self):
        """检查未保存的更改"""
        if self.canvas.has_unsaved_changes():
            reply = QMessageBox.question(
                self, "未保存的更改",
                "当前标注有未保存的更改，是否保存？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )

            if reply == QMessageBox.Yes:
                self.save_annotation()
                return True
            elif reply == QMessageBox.No:
                return True
            else:  # Cancel
                return False
        return True

    def prev_image(self):
        """上一张图片"""
        if not self.check_unsaved_changes():
            return

        if self.data_processor and self.data_processor.prev_item():
            self.load_current_image()

    def next_image(self):
        """下一张图片"""
        if not self.check_unsaved_changes():
            return

        if self.data_processor and self.data_processor.next_item():
            self.load_current_image()

    def save_annotation(self):
        """保存标注结果"""
        if not self.data_processor or not self.current_image_path:
            return

        item = self.data_processor.get_current_item()
        if not item:
            return

        # 如果没有边界框，询问是否保存空标注
        if len(self.canvas.bboxes) == 0:
            reply = QMessageBox.question(
                self, "空标注", "没有标注内容，是否保存空标注？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        # 获取事件列表
        events = self.canvas.get_events()

        # 正确计算标注时间（基于实际时间戳）
        annotation_time = 0
        if events:
            # 使用最后一个事件的时间戳（毫秒）转换为秒
            annotation_time = events[-1]["t"] / 1000.0

        # 准备输出数据
        output_data = {
            "id": item.get("id", ""),
            "image": item.get("image", ""),
            "instruction": item.get("instruction", ""),
            "type": item.get("type", ""),
            "final_bboxes": self.canvas.get_final_bboxes(),
            "events": events,
            "annotation_time": round(annotation_time, 2),  # 保留2位小数
            "source_format": "vlmr1" if item.get('original_format') == 'vlmr1' or item.get('type', '').startswith(
                'vlmr1') else "standard"
        }

        # 如果是VLM-R1数据，保存原始信息
        if item.get('original_format') == 'vlmr1' or item.get('type', '').startswith('vlmr1'):
            output_data.update({
                "original_bbox": item.get('original_bbox', []),
                "original_response": item.get('original_response', '')
            })

        # 获取图片ID和当前索引
        image_id = item.get("id", "unknown")
        current_index = self.data_processor.current_index

        # 生成唯一的标注标识
        annotation_key = f"{image_id}_{current_index}"

        # 更新标注计数器
        if annotation_key not in self.annotation_count:
            self.annotation_count[annotation_key] = 1
        else:
            self.annotation_count[annotation_key] += 1

        # 使用唯一标识符生成文件名
        output_filename = f"{image_id}_idx{current_index}_v{self.annotation_count[annotation_key]}.json"
        output_path = os.path.join(self.output_dir, output_filename)

        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            # 记录保存状态
            self.saved_annotations.add(annotation_key)
            self.canvas.reset_changes()

            self.status_label.setText(f"标注已保存: {output_filename}")
            QMessageBox.information(self, "成功", f"标注已保存到: {output_filename}")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
            self.status_label.setText("保存失败")

    def clear_annotation(self):
        """清空标注"""
        reply = QMessageBox.question(
            self, "确认清空", "确定要清空所有标注吗？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.canvas.clear_canvas()
            self.status_label.setText("标注已清空")

    def delete_selected_bbox(self):
        """删除选中的边界框"""
        self.canvas.delete_selected_bbox()

    def on_content_changed(self):
        """内容变化时的处理"""
        # 可以在这里添加自动保存或其他逻辑
        pass


def main():
    app = QApplication(sys.argv)

    # 显示启动选择对话框
    start_dialog = StartDialog()
    if start_dialog.exec_() == QDialog.Accepted:
        # 创建主窗口并传递启动参数
        window = AnnotationTool(
            start_id=start_dialog.selected_id,
            start_index=start_dialog.start_index
        )
        window.show()
        sys.exit(app.exec_())
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()