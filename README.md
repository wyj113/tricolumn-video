# Tricolumn Video

A command-line tool that turns a local folder of video clips into one landscape video with **three independently playing columns**.

Workflow: **scan → filter → random scheduling → render → full verification → cache cleanup**. The default output is 2560×1440, 60 fps, silent. Source videos are opened read-only, and nothing is uploaded; everything runs locally.

**English** | [中文](README.zh-CN.md)

> Version 0.1.0 is a preview release. The full media pipeline has been verified on Windows (Python 3.14, FFmpeg 9.0.1). Linux and macOS use the same Python entry point; the core unit tests pass on macOS, but the full media pipeline has not been verified there yet.

## Features

- **Scanning:** reads resolution, average frame rate and duration. It accounts for rotation metadata and pixel aspect ratio, and ignores cover-art streams.
- **Filtering:** by orientation, minimum short edge and minimum average frame rate. At least 3 matching clips are required.
- **Scheduling:** each selected clip is used exactly once. The three columns are balanced by duration, and different resolutions are interleaved at random. The same seed always gives the same schedule.
- **Fit modes:** `cover` scales and center-crops to fill the column; `contain` keeps the whole frame and pads it with black.
- **Segmented, resumable rendering:** the frame count of every segment is checked, and the final file is concatenated without re-encoding.
- **Verification:** full decode of the output, a check of the total frame count and parameters, a check of each source file's size and modification time, and a SHA-256 of the final video.
- **Safe cleanup:** cache cleanup only shows a preview by default; nothing is deleted unless you pass `--yes`. Sources, the final video and the scheduling records are always kept.

## Requirements

- Python 3.10 or later. There are no third-party Python dependencies.
- FFmpeg with `ffmpeg`, `ffprobe` and `libx264`. FFmpeg 9 is recommended, and the `scale` filter must support `reset_sar`. Put FFmpeg's `bin` folder on your PATH, or pass `--ffmpeg-dir`, or set the `FFMPEG_DIR` environment variable.

FFmpeg is not bundled with this project and is never downloaded automatically.

## Quick start

Run these from the project folder. On macOS or Linux, replace `py -3` with `python3`.

```powershell
py -3 -m tricolumn doctor
py -3 -m tricolumn run "D:\videos" --job "runs\first" --config "examples\default.json"
```

The output is written to `runs/first/final.mp4`, and the verification report to `runs/first/verification.json`. The job folder and the source folder must not contain each other.

You can also install it as a command with `python -m pip install -e .` and then use `tricolumn --help`.

### Review the selection before a long render

```powershell
py -3 -m tricolumn scan "D:\videos" --output "runs\library.inventory.json"
py -3 -m tricolumn plan --inventory "runs\library.inventory.json" --config "examples\high-quality.json" --job "runs\premium"
py -3 -m tricolumn render --job "runs\premium"
py -3 -m tricolumn verify --job "runs\premium"
py -3 -m tricolumn clean --job "runs\premium"          # preview only
py -3 -m tricolumn clean --job "runs\premium" --yes    # actually delete the cache
```

If a render is interrupted, run the same `render` command again. Segments whose frame counts are correct are reused.

## Configuration

Start from one of the presets in `examples/` (`default.json`, `high-quality.json`, `no-crop.json`). Unknown keys are rejected, so a typo cannot be silently ignored.

| Key | Default | Meaning |
|---|---|---|
| `width` / `height` | 2560 / 1440 | Output size in pixels (even numbers) |
| `fps` | 60 | Integer output frame rate, 1–240 |
| `fit` | `cover` | `cover` (crop to fill) or `contain` (pad) |
| `orientation` | `portrait` | `portrait`, `landscape` or `all` |
| `min_short_edge` | 0 | Minimum short edge after rotation correction |
| `min_fps` | 0 | Minimum average frame rate of the source file |
| `seed` | 42 | Random seed for scheduling |
| `preset` / `crf` | `veryfast` / 20 | x264 settings |
| `threads` | 12 | Encoder threads |

## Limitations

The output is silent and SDR only; HDR sources (PQ/HLG) are excluded. There are no transitions and no GUI. The columns end close together but not exactly at the same time. See the Chinese README for the full list and more detailed notes.

## Tests

```powershell
py -3 -m unittest discover -s tests -v
```

The integration tests use small, generated videos in temporary folders; media tests are skipped if FFmpeg is missing. GitHub Actions runs the pure-Python unit tests on Ubuntu and Windows. See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) and [`docs/VALIDATION.md`](docs/VALIDATION.md) (both in Chinese).

## About this project

I built this from my own batch-composition script. I designed the requirements and parameters and verified the results. **Most of the code was written with the help of AI coding assistants.**

This repository contains no FFmpeg binaries, videos or rendered outputs. FFmpeg's license depends on the build you install.

## License

[MIT](LICENSE)
