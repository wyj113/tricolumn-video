# Tricolumn Video · 三列视频合成工具

[English](README.md) | **中文**

把一个本地素材文件夹整理成三列独立播放的横屏视频。
流程为 **扫描 → 筛选 → 随机排片 → 合成 → 完整检查 → 清理缓存**。
默认 2560×1440、60fps、静音，原视频只读。无需云服务，也不上传素材。

这是从实际批量合成脚本整理的第一版命令行工具。当前已在 Windows、Python 3.14、FFmpeg 9.0.1 上验证；Linux/macOS 使用相同 Python 入口，但尚未完成实机验证。

## 功能

- 扫描分辨率、平均帧率、时长；考虑旋转标记和像素宽高比，排除封面流。
- 按横竖屏、最低短边像素和最低平均帧率筛选。至少需要 3 个匹配视频。
- 每个选中文件使用一次。三列按时长平衡，不同分辨率随机穿插，种子相同可复现。
- `cover`：等比例放大，居中裁切填满。`contain`：保留全画面，居中补黑边。
- 分段编码与续跑；每段核对帧数，完成后无重编码拼接。
- 全片解码、总帧数与参数核对、源文件大小/修改时间检查、成片 SHA-256 记录。
- 缓存清理默认预览，显式 `--yes` 才删除；保留源视频、正式成片及排片记录。

## 准备环境

1. 安装 Python 3.10 或更新版本。
2. 安装含 `ffmpeg`、`ffprobe`、`libx264` 的 FFmpeg。建议使用与验证环境一致的 FFmpeg 9；必须支持 `scale` 的 `reset_sar` 参数。
3. 将 FFmpeg 的 `bin` 加入 PATH，或在需要视频工具的命令后指定 `--ffmpeg-dir "D:\tools\ffmpeg\bin"`。也支持环境变量 `FFMPEG_DIR`。

本项目使用 Python 标准库，直接在解压后的项目目录运行即可：

```powershell
py -3 -m tricolumn doctor
py -3 -m tricolumn --help
```

macOS/Linux 将 `py -3` 换成 `python3`。
可选安装为命令：`python -m pip install -e .`，安装后可用 `tricolumn --help`。
FFmpeg 不包含在本项目中，也不会自动下载或安装。

## 最快用法

在项目目录运行，下列素材路径是示例，请换成你自己的文件夹：

```powershell
py -3 -m tricolumn run "D:\videos" --job "runs\first" --config "examples\default.json"
```

成片在 `runs/first/final.mp4`，完整检查结果在 `runs/first/verification.json`。
`run` 只建立新任务；任务目录已存在时不会覆盖。
**任务目录和素材目录不能互相包含**，避免把缓存当成素材。
PowerShell 也可用 `./run.ps1 doctor`，相对路径以项目目录为准。

## 先查看筛选与排片，再开始长时间编码

```powershell
py -3 -m tricolumn scan "D:\videos" --output "runs\library.inventory.json"
py -3 -m tricolumn plan --inventory "runs\library.inventory.json" --config "examples\high-quality.json" --job "runs\premium"
```

查看以下文件后再合成：

| 文件 | 内容 |
|---|---|
| `library.inventory.json` | 每个视频的参数与读取错误 |
| `library.inventory.summary.txt` | 分辨率/平均帧率数量汇总 |
| `premium/plan-summary.json` | 选中数量、各列时长、结束差、分辨率分布 |
| `premium/play-order.txt` | 各列开始时间和文件顺序 |
| `premium/plan.json` | 可复现的完整排片与配置 |

```powershell
py -3 -m tricolumn render --job "runs\premium" --progress-seconds 600
py -3 -m tricolumn verify --job "runs\premium"
```

进度默认每30秒输出一次；上例改为10分钟。`progress.json` 会在每段完成后更新。
`verify` 会完整解码一次成片，因此还需要一些时间。

## 配置示例

| 配置 | 效果 |
|---|---|
| `examples/default.json` | 所有匹配竖屏，1440p、60fps、三列填满 |
| `examples/high-quality.json` | 短边≥1440、平均帧率≥59，1440p、60fps、填满 |
| `examples/no-crop.json` | 1440p、60fps，保留完整画面并补黑边 |

复制一个 JSON 修改即可。未填写项使用默认值，未知配置项会报错，防止拼写错误被忽略。

| 参数 | 默认值 | 含义 |
|---|---|---|
| `width` / `height` | 2560 / 1440 | 输出像素尺寸，必须为偶数；宽至少6 |
| `fps` | 60 | 整数输出帧率，1–240 |
| `fit` | `cover` | `cover` 裁切填满；`contain` 补边保留完整画面 |
| `orientation` | `portrait` | `portrait`、`landscape`、`all`；`all` 包含方形视频 |
| `min_short_edge` | 0 | 最低短边像素，基于旋转校正后的显示尺寸 |
| `min_fps` | 0 | 最低文件平均帧率；59可纳入59.94及轻微变帧率素材 |
| `seed` | 42 | 随机种子；换一个整数可重新打乱 |
| `preset` | `veryfast` | x264 速度设置，越慢通常压缩效率越好 |
| `crf` | 20 | 1–51；越低文件通常越大，质量越高；本版不支持CRF 0无损模式 |
| `threads` | 12 | 编码线程数；按机器性能调整 |

输出4K可设 `width=3840,height=2160`，但处理时间和磁盘需求会增加。
素材筛选分辨率与输出分辨率是两个独立设置，放大不能恢复原本没有的细节。

## 中断、错误和续跑

再次运行相同 `render --job` 命令，会核对源文件并复用帧数正确的已完成片段。
任何片段失败都不会输出正式成片，原因记录在 `failures.json` 和 `cache/*.log`。
修复源文件访问或环境问题后再运行同一命令；源视频变更、排片变更或升级编码代码，应建立新任务。

不要手工修改已建立任务的 `plan.json`。每个任务使用锁文件阻止并发写入。
如果程序异常退出遗留 `.lock`，先确认该任务的 Python/FFmpeg 进程均已停止，再删除这个锁文件后续跑。
如果成片已移走，不要再次执行 `render`；它会重新生成成片。

## 清理缓存

先完成 `verify`。默认只显示将清理的数量和大小：

```powershell
py -3 -m tricolumn clean --job "runs\premium"
py -3 -m tricolumn clean --job "runs\premium" --yes
```

如果成片已搬到别处：

```powershell
py -3 -m tricolumn clean --job "runs\premium" --final "D:\exports\premium.mp4" --yes
```

工具会比对最终文件 SHA-256 与验证记录。最终文件缺失或不匹配时拒绝清理。
只删除这个任务已知编号的分段视频和分段日志，不递归删除目录，不删除成片、源文件、计划和其他文件。
任务目录不支持符号链接或 Windows 联接目录。

## 范围与限制

- 仅输出静音视频。音轨保留、混音、字幕、转场、人物跟踪裁切、图形界面不在本版范围。
- 降帧按时间采样，低帧率通过重复帧补齐；不使用光流或AI插帧。文件平均60fps不代表每帧都是独立拍摄帧。
- 随机排片会平衡不同分辨率的时间占比，但不识别相同相册，也不进行内容去重。不同文件名的重复内容可能都入选。
- 三列结束差尽量减小，不承诺严格相等；较早结束的列在最后的差值时间内为黑色。不会为对齐而删掉素材尾部。
- 2560像素不能平均分成3个偶数宽度，列宽为854、852、854，差异仅2像素。
- 只处理 SDR。带 PQ/HLG 标记的 HDR 素材会排除，未知颜色标记仍按 SDR 处理。
- 不支持任意角度旋转或文件名包含换行符。损坏/参数缺失视频记录在扫描错误中。
- 分段拼接极短片段可能出现 DTS 修正提示；以最终全片解码、帧数和参数验证为准。容器时长可能有毫秒级取整差。
- 编码缓存与成片会同时占用空间，需预留约两份输出体积以及日志空间。

## 测试与开发

```powershell
py -3 -m unittest discover -s tests -v
```

集成测试使用临时目录和程序生成的小视频，不读取私人素材；FFmpeg缺失时会跳过媒体测试。
GitHub Actions 运行纯 Python 单元测试；完整媒体测试需本地安装符合要求的 FFmpeg 后运行。
更多说明见 [开发与发布说明](docs/DEVELOPMENT.md)。

## 关于这个项目

这个工具是从我自己的批量合成脚本整理而来的。需求、参数设计和测试验证由我负责，**大部分代码是在 AI 编程助手的协助下完成的**。

项目不包含 FFmpeg 二进制、任何视频素材或成片；FFmpeg 需自行安装，其许可证取决于具体构建。

## 许可证

[MIT](LICENSE)
