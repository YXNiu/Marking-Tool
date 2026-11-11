# Marking-Tool · Human Search Traces

用于记录人类视觉搜索过程与最终证据框的 **PyQt5 桌面标注工具**。本次 v2.0.0 根据 [YXNiu/Human-Search-Traces](https://huggingface.co/datasets/YXNiu/Human-Search-Traces) 的全部 1,144 条发布记录，以及项目维护者对交互流程的确认重建。

这是兼容发布数据的重建版本；没有找回当年未上传的源码，也不声称每一个内部实现与历史版本完全相同。依据、例外与新增改进见 [数据分析与重建说明](docs/reconstruction.md)。

## 1. 核心流程

1. 加载问题与原图，**答案和已有证据框在新标注时隐藏**。
2. 初始无图像滚动条，按窗口显示整张原图；右键拖出矩形，查看该局部，可连续放大。
3. 左键拖动标注证据框，支持多框、移动、四角调整和删除。
4. 点击「提交并评价」，用两个 0–1 滑条选择难度与证据置信度，或选择歧义。
5. **成功保存后才显示参考答案**，当前记录锁定，停留本题。
6. 手动点击「下一题 / 跳过」继续；不要求每题必须提交。

全程保留原始图像像素，显示适配不会修改原图。轨迹只采集画布交互，按钮点击和评分滑条不采集。输出坐标统一为原图像素，详见 [数据契约](docs/data_contract.md)。

多数据集的统一目录、输入文件、切换、保存与备份流程见 [多数据集操作手册](docs/workflow.md)。工具会按任务文件自动分开建立输出文件夹，不需要为每个数据集手动改代码。

## 2. 安装与启动

推荐 Python 3.11。支持 Python 3.10+；本次已在 macOS Apple Silicon、Python 3.11、PyQt5 5.15.11 上验证。Linux 无显示环境只能跑测试，实际标注需要桌面会话。

```bash
git clone git@github.com:YXNiu/Marking-Tool.git
cd Marking-Tool
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Windows 激活命令为 `.venv\Scripts\activate`。macOS 创建好 `.venv` 后，也可双击仓库里的 `启动标注工具.command`。

如果用 Git 下载仓库中的旧 `data.rar`，需安装 Git LFS，再运行 `git lfs install --local && git lfs pull`。这个归档仅包含旧 VLM-R1 任务 JSON，不是新版运行必需的数据，也不包含 VisualProbe 原图。

### 先用练习题试操作

```bash
python tools/create_demo.py data/demo
python main.py --data data/demo/tasks.json --output output/practice
```

练习图为程序生成的红、蓝矩形，标记为 `synthetic_practice`，不能混入研究数据。输出目录与正式标注分开。

## 3. 准备正式任务和原图

[Human-Search-Traces](https://huggingface.co/datasets/YXNiu/Human-Search-Traces) 发布的是 1,144 条原始会话，**不含图片**。图片来自 [Mini-o3/VisualProbe_train](https://huggingface.co/datasets/Mini-o3/VisualProbe_train)。

可加载三类输入：

| 输入 | 用途 | 处理方式 |
| --- | --- | --- |
| VisualProbe 原始 `train.json` | 新标注任务 | `doc_id/problem/solution/images/data_source` 转为内部任务 |
| 发布的 `train_search_traces.jsonl` 或单条会话 JSON | 重新标注或只读检查 | 新标注默认隐藏源答案、框、轨迹和评分；检查请加 `--review` |
| 旧 `id/image/instruction` 或 VLM-R1 `messages/images` | 兼容旧任务 | 可重新采集；旧屏幕坐标不会被猜测转换成原图坐标 |

### 获取发布数据

```bash
git clone https://huggingface.co/datasets/YXNiu/Human-Search-Traces ../Human-Search-Traces
git -C ../Human-Search-Traces lfs install --local
git -C ../Human-Search-Traces lfs pull
```

### 只下载本次任务需要的图片

```bash
python -m pip install -r requirements-download.txt
python tools/download_images.py \
  ../Human-Search-Traces/data/train_search_traces.jsonl \
  ../VisualProbe_images
```

默认下载任务中引用的全部原图，体积可能达到数 GB；`--limit 2` 只取前两题，`--list-only` 仅列清单。下载可重复执行，使用 Hugging Face 的本地缓存。此脚本只适用于 VisualProbe，其他数据请自行指定图像目录。

启动：

```bash
python main.py \
  --data ../Human-Search-Traces/data/train_search_traces.jsonl \
  --images-root ../VisualProbe_images/data \
  --output output/annotations
```

若希望从全部原始问题开始，使用官方 `train.json`：

```bash
hf download Mini-o3/VisualProbe_train train.json \
  --repo-type dataset --local-dir ../VisualProbe_train
python tools/download_images.py ../VisualProbe_train/train.json ../VisualProbe_images
python main.py --data ../VisualProbe_train/train.json \
  --images-root ../VisualProbe_images/data --output output/annotations
```

下载工具调用官方 `snapshot_download`，方法参考 [Hugging Face 下载文档](https://huggingface.co/docs/huggingface_hub/guides/download)。如果命令行无法连接 Hugging Face，而系统已有代理，可给当前命令设置 `HTTPS_PROXY` / `HTTP_PROXY`，不要把个人代理配置或令牌写进仓库。

## 4. 逐步标注

### 阅读与搜索

打开任务后先读左侧问题，参考答案显示为「提交后显示」。已有发布记录作为任务输入时，不会预填答案、框或评分。整张图初始适配右侧区域，没有图像滚动条；小目标请用**鼠标右键拖出一个局部矩形**，松开后放大。可在放大的视图里再次右键框选。

「恢复全图」按钮或 `R` 回到整图。这里改变的是显示视图，原始图像缓冲区保持原分辨率；不用预先把原图缩小或手工改坐标。

### 画框与修正

| 操作 | 方法 |
| --- | --- |
| 新建证据框 | 左键按住并拖动，可从任意角开始 |
| 多个分散证据 | 在其他区域继续画框 |
| 在已有框内部新建框 | `Shift` + 左键拖动 |
| 选中 / 移动 | 左键点框内部并拖动，选中框为红色 |
| 调整大小 | 拖动四个角的手柄 |
| 删除 | 选中框后点「删除选中框」，或 Delete / Backspace |
| 清空 | 「清空证据框」会逐个删除框，**不会抹除此前轨迹** |
| 取消未完成拖动 | Esc；已开始的动作仍保留结束/删除记录 |

新框限制在图像边界内，零面积误点击不会留在最终框里。框的上限不固定为一个或两个：发布数据出现过双框，但这不是最大允许数量。

建议圈出回答问题所需的完整视觉证据。分散证据可分别框选，例如两侧春联计字需要两个框。这是样例支持的操作建议；数据本身不能证明某种固定扫描路线、鼠标停留阈值或“绝不允许修正”等规则。不要为了产生整齐的轨迹而伪造或补画搜索过程。

### 提交与评分

点击「提交并评价」或 `Ctrl+S`（macOS 为 `⌘+S`）。两个滑条支持 0.00–1.00，精度 0.01，也可在右侧数值框精确输入：

- 搜索 / 定位难度：越大越难；新版本默认 0.50。
- 证据正确性置信度：越大越有把握；新版本默认 1.00。
- 勾选歧义：`difficulty_level="ambiguous"`，两项分数均为 `null`。

当前等级映射为 `≤0.30 easy`、`(0.30, 0.60] medium`、`>0.60 hard`，覆盖所有已发布样例。历史边界值及默认值不能从数据唯一恢复，这些是明确记录的新版本选择。

评分期间不追加画布事件，不记录滑条或按钮的鼠标坐标。取消评分后返回标注，参考答案继续隐藏；取消对话框中花费的时间从后续画布时钟排除。提交失败时保持本题和答案隐藏，可修复磁盘 / 权限问题后再次提交。

成功提交后显示参考答案，记录转为只读，避免看过答案后的动作混入原搜索过程。**不会自动进入下一题**，请手动继续。重复点击提交不会产生额外版本。

### 跳过、返回与退出

「下一题 / 跳过」始终可用于导航到下一题，无须先提交。未提交内容每 5 秒及切题 / 关闭时写入当前数据集文件夹的 `.drafts`，返回该题或重启后可恢复。正在拖动时不做中间草稿，切题会先结束 / 取消该拖动。

切到其他题及程序关闭期间不计入恢复后的轨迹时钟；本地 `.metadata` 会注明恢复段数。它不属于发布 JSON 的 11 个字段。需要严格单次、不中断研究会话时，请统一安排连续完成，不混用恢复草稿与连续会话。

「跳转到序号 / ID」中的题号从 **1** 开始；命令行 `--start-index` 从 **0** 开始。还可指定 `--start-id visual_probe_train_1001`。快捷导航为 `Alt+→` / `Alt+←`。

缺图时会清空旧画布并禁用提交，仍可继续导航，不会把上一题的图或框保存到本题。界面可随时选择原图目录；默认相对路径相对于任务文件目录解析，显式指定的原图目录优先。

## 5. 输出与检查

每个成功提交会生成一个 JSON：

```text
output/annotations/                         # 选择的输出根目录
└── visualprobe_train--0123456789/           # 自动名称 + 任务文件标识（示意）
    ├── workspace.json                     # 本地目录配置与来源校验
    ├── sessions/
    │   └── visual_probe_train_1001_idx950_v1.json
    ├── .drafts/                           # 未提交草稿，不参与导出
    ├── .metadata/                         # 工具版本、原图尺寸、恢复段数
    └── exports/                           # 界面导出 JSONL 的推荐位置
```

`id` 与文件名一致，`sample_id` 保留源任务 ID。原始任务的 `idx` 是源文件中的零基索引；载入已发布会话重新标注时保留其原 `idx`，从高于源版本的版本号开始。已有文件不会覆盖，重启及并发保存都会递增版本号。

优先点击界面「导出当前数据集 JSONL」。也可把所有已提交版本合并为 JSONL（将下列数据集目录替换为实际目录）：

```bash
python tools/export_jsonl.py "output/annotations/<数据集目录>/sessions" output/export_all.jsonl
```

默认保留每个独立会话。若明确只需同一任务的最高版本，可加 `--latest-only`。导出目标已存在时会拒绝覆盖；草稿和元数据不会导出。

验证发布或导出的数据：

```bash
python tools/audit_traces.py output/export_all.jsonl --output output/audit.json
```

只读检查历史证据框与答案：

```bash
python main.py --review \
  --data ../Human-Search-Traces/data/train_search_traces.jsonl \
  --images-root ../VisualProbe_images/data
```

只读模式允许局部放大和恢复全图，但不会采集新事件，也不能提交。它显示最终证据框与会话统计，不是历史视图的逐帧录像播放器；原发布数据也不包含完整的屏幕尺寸 / 显示缩放元数据。

## 6. 详细依据与开发验证

- [字段、事件、坐标与时间契约](docs/data_contract.md)
- [多数据集目录、任务文件、切换、备份和统一操作流程](docs/workflow.md)
- [1,144 条记录的反推分析、七个样例及已知异常](docs/reconstruction.md)
- [可复算的全量数据审计](docs/data_audit.json)
- [变更说明](CHANGELOG.md)
- [本次验证范围与结果](docs/validation.md)

```bash
python -m pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest -q
python tools/audit_traces.py ../Human-Search-Traces/data/train_search_traces.jsonl
```

测试覆盖原图坐标、多级缩放、任意方向绘框、编辑删除、轨迹保留、隐藏答案、取消 / 失败提交、草稿恢复、缺图保护、版本冲突和导出。若旁边没有下载发布数据，全量数据回归测试会跳过，其他测试使用独立的合成图和临时目录。

原数据的授权范围与图像授权仍以 [Human-Search-Traces 数据说明](https://huggingface.co/datasets/YXNiu/Human-Search-Traces) 和上游 VisualProbe 为准；工具不会上传任何标注、图像或操作记录。
