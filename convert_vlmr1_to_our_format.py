import json
import os
import re


def convert_vlmr1_to_our_format(vlmr1_file, output_file, images_base_path=""):
    """
    将VLM-R1标注格式转换为我们的UI工具格式

    Args:
        vlmr1_file: VLM-R1的标注文件路径
        output_file: 输出文件路径
        images_base_path: 图片基础路径（如果图片路径需要调整）
    """

    # 读取VLM-R1标注文件
    with open(vlmr1_file, 'r', encoding='utf-8') as f:
        vlmr1_data = json.load(f)

    converted_data = []

    for i, item in enumerate(vlmr1_data):
        # 提取用户消息作为instruction
        user_message = ""
        for msg in item.get("messages", []):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                # 移除开头的<image>标签
                user_message = user_message.replace("<image>", "").strip()
                break

        # 提取图片路径
        image_path = ""
        if item.get("images") and len(item.get("images", [])) > 0:
            image_path = item["images"][0]
            # 如果指定了基础路径，则调整图片路径
            if images_base_path:
                # 只保留文件名，然后拼接到基础路径
                filename = os.path.basename(image_path)
                image_path = os.path.join(images_base_path, filename)

        # 提取原有的bbox信息（作为参考，但我们会重新标注）
        original_bboxes = []
        assistant_message = ""
        for msg in item.get("messages", []):
            if msg.get("role") == "assistant":
                assistant_message = msg.get("content", "")
                # 尝试从assistant消息中提取bbox信息
                try:
                    # 使用正则表达式提取JSON数组
                    bbox_match = re.search(r'\[.*\]', assistant_message, re.DOTALL)
                    if bbox_match:
                        bbox_json = bbox_match.group()
                        bbox_data = json.loads(bbox_json)
                        if isinstance(bbox_data, list) and len(bbox_data) > 0:
                            original_bboxes = bbox_data[0].get("bbox_2d", [])
                except:
                    pass
                break

        # 创建转换后的数据项
        converted_item = {
            "id": f"vlmr1_{i:06d}",
            "image": image_path,
            "instruction": user_message,
            "original_bbox": original_bboxes,  # 保存原始bbox作为参考
            "original_response": assistant_message,  # 保存原始响应
            "type": "vlmr1_bbox"  # 标记为VLM-R1的边界框标注任务
        }

        converted_data.append(converted_item)

    # 保存转换后的数据
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(converted_data, f, indent=2, ensure_ascii=False)

    print(f"转换完成！共转换 {len(converted_data)} 条数据")
    print(f"输出文件: {output_file}")

    return converted_data


def check_image_availability(converted_data):
    """检查图片文件是否可用"""
    missing_images = []
    available_images = []

    for item in converted_data:
        image_path = item["image"]
        if os.path.exists(image_path):
            available_images.append(image_path)
        else:
            missing_images.append(image_path)

    print(f"\n图片可用性检查:")
    print(f"可用的图片: {len(available_images)}")
    print(f"缺失的图片: {len(missing_images)}")

    if missing_images:
        print("\n缺失的图片列表:")
        for img in missing_images[:10]:  # 只显示前10个缺失的图片
            print(f"  - {img}")
        if len(missing_images) > 10:
            print(f"  ... 还有 {len(missing_images) - 10} 个缺失图片")

    return available_images, missing_images


# 修改 convert_vlmr1_to_our_format.py 中的配置部分
if __name__ == "__main__":
    # 配置参数
    VLM_R1_FILE = "./data/mllm_rec_json.json"  # VLM-R1标注文件
    OUTPUT_FILE = "data/vlmr1_converted.json"  # 输出文件
    IMAGES_BASE_PATH = "./data/train2014"  # 修改这里！图片在当前目录的train2014文件夹中

    # 确保输出目录存在
    os.makedirs(os.path.dirname(OUTPUT_FILE) if os.path.dirname(OUTPUT_FILE) else ".", exist_ok=True)

    # 执行转换
    converted_data = convert_vlmr1_to_our_format(VLM_R1_FILE, OUTPUT_FILE, IMAGES_BASE_PATH)

    # 检查图片可用性
    available, missing = check_image_availability(converted_data)

    if missing:
        print("\n警告: 部分图片文件缺失，标注工具可能无法正常加载这些图片")
        print("请确保图片文件存在于指定路径，或调整 IMAGES_BASE_PATH 参数")