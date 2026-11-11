# 数据契约与采集口径

依据是发布文件 `data/train_search_traces.jsonl`，不是旧 README 中的 `final_bboxes/instruction/type` 示例。全量审计见 [data_audit.json](data_audit.json)，历史问题见 [reconstruction.md](reconstruction.md)。

## 顶层对象

每个 JSON 文件 / JSONL 行是一次会话。新版提交只输出以下 11 个字段：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string | 会话 ID，也是文件名去掉 `.json`，如 `visual_probe_train_1001_idx950_v1` |
| `sample_id` | string | 原始任务 ID，如 `visual_probe_train_1001` |
| `image` | string | 原图文件名，不含本机目录前缀 |
| `question` | string | 原始问题；保留输入文本及 `<image>` 标记，界面单独移除标记 |
| `answer` | string | 来源任务的参考答案，提交前不显示，不是让标注员另填的回答 |
| `final_bboxes_pixels` | list[list[int]] | 最终原图像素框 `[x1,y1,x2,y2]`；可多个，也可空 |
| `events` | list[object] | 按采集顺序排列的原始交互事件，同一时刻可以多个事件 |
| `annotation_time` | number | 秒，`round(events[-1].t / 1000, 2)`；无事件时为 0 |
| `task_evaluation` | object | 难度、歧义、置信度，见下文 |
| `source_format` | string | 此发布集全部为 `standard`，兼容 VLM-R1 任务时为 `vlmr1` |
| `source_dataset` | string | 此发布集全部为 `visualprobe_train` |

VisualProbe 原始任务用 `doc_id/problem/solution/images[0]/data_source`，其中原始来源拼写为 `visual_probe_train`，新版输出统一为发布集中的 `visualprobe_train`。输入 `image` 可为绝对路径或相对任务文件的路径；输出只保存文件名，实际查图由 `--images-root` 或界面选择目录完成。

`idx` 不是图片数字 ID，也不是 Hugging Face 查看器的当前行号。对本次发布文件逐条核对上游 `train.json`，全部 1,144 条的 `idx` 等于源任务索引。发布 JSONL 已按会话 ID 排序，所以它的第 0 行是 `...1001_idx950_v1`。

加载原始任务时用该文件的零基索引；加载已发布会话作为重新标注任务时保留原 `idx`，并从高于源 `v` 的版本号开始。新提交不复用旧会话事件或框。版本号按磁盘文件分配，原子发布，已经存在的文件永远不覆盖。

## 坐标系统

- 图像左上角为原点，x 向右、y 向下，单位为原图像素。
- 原始图像以完整分辨率加载；窗口显示整图或放大的局部，不改变原图缓冲区。
- 窗口鼠标坐标必须扣除留白，再除以显示比例，再加上当前局部在原图中的起点。否则多次放大后会把局部坐标误记为整图坐标。
- 新版保留原始浮点位置用于计算，在保存事件坐标和框时统一 `round` 为整数；同一最终动作框与最终输出框使用同一个值。
- 新证据框限制在 `[0,width] × [0,height]` 内且必须具有正面积；这是边界坐标定义，允许右 / 下边界等于宽 / 高。
- **指针坐标不裁剪**：它可以落在画布的图像留白区域，因此 x / y 允许为负或超出图像尺寸。不能把所有指针点硬裁剪到图片上。
- 中间拖动框 / 缩放框可暂时为线或点；取消缩放以 `canceled: true` 结束。误点击不保留为新的最终零面积证据框。

已发布框中的负坐标和零面积不会被导入工具偷偷修复；只读检查与审计会提示。也不能因为事件框与最终框相差 1 像素就改写历史事件。

## 时间和速度

- 首次实际画布事件为 `t=0`，`t` 单位为毫秒，通常保留一位小数。不是 Unix 时间，也不含年月日。
- 使用单调时钟累计画布内的有效时间，不依赖系统时间调整。按追加顺序保存，相同 `t` 保留原顺序。
- **离开画布时停止采集鼠标事件并暂停时钟，重新进入时从暂停值恢复。** 离开期间不计入 `t` 或 `annotation_time`，不清空已经记录的事件。
- 新版移动事件最多约每 100 ms 采样一次；不是每 100 ms 无条件补点。鼠标静止不会制造额外轨迹。
- `v` 单位为原图像素 / 秒，是相邻已采样位置的距离除以间隔；`a` 是标量速度变化率，单位为像素 / 秒²。
- 速度与加速度保留两位小数。非移动事件输出 `v=a=0`。新运动段第一点为零速度，得到两个有效速度后才计算加速度。
- 视图变化、离开画布和动作类别切换会重置新版的运动基线，避免把视图切换解释为鼠标高速运动。历史数据存在跨缩放速度尖峰，未做修复。
- `annotation_time` 是最后一个事件的相对时间除以 1000，**不是点击提交 / 评分完成的时间**。

不采集按钮和评分滑条的鼠标操作。画布进入 / 离开本身仍是画布事件，点击「恢复全图」或「删除选中框」产生的语义结果仍分别记录为 `zoom_reset` / `delete_bbox`，但没有按钮位置坐标。鼠标在画布外触发这些结果时，事件使用暂停时刻，时钟不会为了记录结果而重新启动。没有 `submit_click`、`next_click`、`rating_move` 等事件。

例如，在画布内操作 5 秒，离开 20 秒，再返回操作 3 秒，累计有效标注时长为 8 秒。`canvas_leave` 与其后的 `canvas_enter` 可以具有相同 `t`。仅凭历史事件中两个相对时间值的差，不能推导鼠标在画布外的实际墙钟停留时间。

评分对话框、切题、关闭后的草稿等待同样暂停计时；取消评分时若鼠标仍在画布外，时钟保持暂停。草稿恢复后，等待鼠标进入画布才开始下一段。已经提交的会话锁定，不再增加事件。

画布范围指右侧图像交互控件，包括图像周围的留白；因此留白内的指针可以映射成负原图坐标。拖动时即使 Qt 继续向控件派发画布外鼠标事件，也不采集这些事件；未完成的拖动在离开边界时取消，按最后的画布内状态结束。

## 19 类事件

所有事件至少含 `type/t/v/a/category`。除 `zoom_reset`、`delete_bbox` 外，已发布事件都含 `x/y`。下表的字段是公共字段以外的内容。

| `type` | `category` | 特有字段 / 语义 |
| --- | --- | --- |
| `canvas_enter` | canvas | `x,y`：进入画布 |
| `canvas_leave` | canvas | `x,y`：离开画布，采用最后已知指针位置 |
| `hover_start` | hover | `x,y`：悬停段开始 |
| `hover_move` | hover | `x,y`：搜索中的指针移动 |
| `hover_end` | hover | `x,y`：悬停段结束 |
| `zoom_start` | zoom | `x,y`：右键区域放大开始 |
| `zoom_move` | zoom | `x,y,bbox:[x1,y1,x2,y2]`：正在选择的放大区域 |
| `zoom_end` | zoom | 正常结束含 `x,y,bbox`；取消含 `x,y,canceled:true` |
| `zoom_reset` | zoom | 恢复全图，没有 `x/y/bbox` |
| `down` | drag | `x,y`：新建证据框按下 |
| `create_start` | drag | `x,y,bbox:{index}` |
| `drag_move` | drag | `x,y,bbox:{bbox:[x1,y1,x2,y2],index}` |
| `create_end` | drag | `x,y,bbox:[x1,y1,x2,y2],index` |
| `up` | drag | `x,y`：新建证据框释放 |
| `select_bbox` | edit | `x,y,index,bbox:[x1,y1,x2,y2]` |
| `edit_start` | edit | `x,y,index,mode,handle,bbox` |
| `edit_move` | edit | `x,y,index,mode,handle,bbox` |
| `edit_end` | edit | `x,y,index,mode,handle,bbox` |
| `delete_bbox` | edit | `index,bbox:[x1,y1,x2,y2]`，没有指针位置 |

编辑事件的 `mode` 为 `move` 或 `resize`，`handle` 为 `tl/tr/bl/br` 或 `null`。`index` 是动作当时的框列表零基索引，删除框会改变后续索引，不是永久对象 ID。

**`bbox` 的形状随事件类型变化**，不能给所有事件统一当成四元素数组：`create_start` 和 `drag_move` 是对象，完成 / 编辑 / 缩放时通常是数组。旧 README 中 `bbox.before/bbox.after`、`move_start/resize_end/delete` 的旧约定不适用于最终发布集。

事件类型不代表固定操作模板：没有要求每条轨迹含每一种事件，也没有要求成对事件的计数在所有历史记录中都完美对应。尤其有一个最终点框无法由事件重放完整解释，不能反向“补造”其过程。

## 任务评价

```json
{
  "difficulty_score": 0.5,
  "difficulty_level": "medium",
  "is_ambiguous": false,
  "confidence_score": 1.0
}
```

歧义样例的实际约定是：

```json
{
  "difficulty_score": null,
  "difficulty_level": "ambiguous",
  "is_ambiguous": true,
  "confidence_score": null
}
```

难度和置信度支持 0–1、小数值，不只是 easy / medium / hard 三档按钮。历史存在 `0.26/0.67/0.88` 难度值以及 `0.09/0.28/0.32` 置信度值，说明不能只提供 0.1 步长。

观察到的 easy 为 0.20、0.26、0.30；medium 为 0.40、0.50、0.60；hard 最小为 0.67。0.31–0.39 和 0.61–0.66 没有观测，因此历史精确阈值不可唯一反推。新版选用 0.30 / 0.60 为边界，默认值 0.50 / 1.00。这些选择在代码 `trace_schema.evaluation` 和提交对话框中集中定义。

## 发布结构与本地状态分离

草稿位于 `.drafts`；本地 `.metadata` 保存工具版本、图片尺寸及草稿恢复段数。它们不冒充发布数据，也不会被 JSONL 导出工具纳入。若需判断不同采集版本或会话是否中断，保留本地元数据一并备份。

此格式是鼠标交互记录，不是眼动测量，也没有自然语言推理过程。单纯拥有数据文件不能逐帧重建当年的屏幕 UI，因为缺少完整视窗尺寸、DPI 与控件布局；本工具只读模式展示原图、最终框和统计，并支持主动查看局部。
