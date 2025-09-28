import json
import os


class DataProcessor:
    def __init__(self, data_path):
        self.data_path = data_path
        self.data = []
        self.current_index = 0

    def load_data(self):
        """加载数据文件，支持多种格式"""
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)

            # 判断数据格式并标准化
            self.data = self._standardize_data_format(raw_data)
            return True
        except Exception as e:
            print(f"Error loading data: {e}")
            return False

    def _standardize_data_format(self, raw_data):
        """将不同格式的数据标准化为统一格式"""
        standardized_data = []

        # 检查数据格式类型
        if self._is_vlmr1_format(raw_data):
            print("检测到VLM-R1格式数据")
            standardized_data = self._convert_vlmr1_format(raw_data)
        elif self._is_our_format(raw_data):
            print("检测到标准格式数据")
            standardized_data = raw_data
        else:
            print("未知数据格式，尝试直接使用")
            standardized_data = raw_data

        return standardized_data

    def _is_vlmr1_format(self, data):
        """判断是否为VLM-R1原始格式"""
        if isinstance(data, list) and len(data) > 0:
            first_item = data[0]
            if 'messages' in first_item and 'images' in first_item:
                return True
        return False

    def _is_our_format(self, data):
        """判断是否为我们工具的标准格式"""
        if isinstance(data, list) and len(data) > 0:
            first_item = data[0]
            if all(key in first_item for key in ['id', 'image', 'instruction']):
                return True
        return False

    def _convert_vlmr1_format(self, vlmr1_data):
        """转换VLM-R1格式为标准格式（备用转换，如果外部转换脚本失败）"""
        converted_data = []

        for i, item in enumerate(vlmr1_data):
            # 提取用户消息
            user_message = ""
            for msg in item.get("messages", []):
                if msg.get("role") == "user":
                    user_message = msg.get("content", "").replace("<image>", "").strip()
                    break

            # 提取图片路径
            image_path = item.get("images", [""])[0] if item.get("images") else ""

            converted_item = {
                "id": f"vlmr1_{i:06d}",
                "image": image_path,
                "instruction": user_message,
                "type": "vlmr1_bbox",
                "original_format": "vlmr1"  # 标记原始格式
            }

            converted_data.append(converted_item)

        return converted_data

    def get_current_item(self):
        """获取当前数据项"""
        if 0 <= self.current_index < len(self.data):
            return self.data[self.current_index]
        return None

    def next_item(self):
        """移动到下一个数据项"""
        if self.current_index < len(self.data) - 1:
            self.current_index += 1
            return self.get_current_item()
        return None

    def prev_item(self):
        """移动到上一个数据项"""
        if self.current_index > 0:
            self.current_index -= 1
            return self.get_current_item()
        return None

    def get_all_ids(self):
        """获取所有唯一的ID列表"""
        ids = []
        for item in self.data:
            item_id = item.get("id")
            if item_id and item_id not in ids:
                ids.append(item_id)
        return ids

    def find_index_by_id(self, target_id):
        """根据ID查找对应的索引位置"""
        for i, item in enumerate(self.data):
            if item.get("id") == target_id:
                return i
        return -1