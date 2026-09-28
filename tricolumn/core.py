import hashlib
import json
import math
import os
import random
import shutil
import subprocess
from collections import Counter
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v', '.wmv', '.ts'}
DEFAULTS = dict(width=2560, height=1440, fps=60, fit='cover', orientation='portrait',
                min_short_edge=0, min_fps=0, seed=42, preset='veryfast', crf=20, threads=12)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def tool_paths(directory=None):
    directory = directory or os.environ.get('FFMPEG_DIR')
    result = []
    for name in ('ffmpeg', 'ffprobe'):
        path = str(Path(directory) / (name + ('.exe' if os.name == 'nt' else ''))) if directory else shutil.which(name)
        if not path or not Path(path).is_file():
            raise ValueError(f'{name} not found. Add FFmpeg to PATH or pass --ffmpeg-dir DIR.')
        result.append(path)
    return tuple(result)


def probe(path, tools):
    raw = subprocess.check_output([tools[1], '-v', 'error', '-show_streams', '-show_format',
                                   '-of', 'json', str(path)], encoding='utf-8', errors='replace')
    return json.loads(raw)


def video_stream(metadata):
    return next(s for s in metadata['streams'] if s['codec_type'] == 'video'
                and not s.get('disposition', {}).get('attached_pic'))


def rational(value, default=0):
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return default


def stream_duration(stream):
    duration = rational(stream.get('duration'))
    if duration > 0 and math.isfinite(duration):
        return duration
    tags = {key.upper(): value for key, value in stream.get('tags', {}).items()}
    try:
        hours, minutes, seconds = tags['DURATION'].split(':')
        end = int(hours)*3600 + int(minutes)*60 + float(seconds)
        return max(0, end - rational(stream.get('start_time')))
    except (KeyError, ValueError):
        return 0


def packet_duration(path, stream, tools):
    """Read video packet times only when the container has no video duration."""
    cmd = [tools[1], '-v', 'error', '-select_streams', str(stream['index']), '-show_packets',
           '-show_entries', 'packet=pts_time,duration_time', '-of', 'compact=p=0:nk=0', str(path)]
    first, last = float('inf'), -float('inf')
    fallback = 1 / (rational(stream.get('avg_frame_rate')) or rational(stream.get('r_frame_rate')) or 30)
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8') as process:
        for line in process.stdout:
            fields = dict(part.split('=', 1) for part in line.strip().split('|') if '=' in part)
            pts = rational(fields.get('pts_time'), float('nan'))
            if math.isfinite(pts):
                first = min(first, pts)
                last = max(last, pts + (rational(fields.get('duration_time')) or fallback))
        if process.wait():
            raise ValueError('Could not determine video packet duration')
    if not math.isfinite(last-first) or last <= first:
        raise ValueError('No usable video packet timestamps')
    return last-first


def normalize(path, metadata):
    stream = video_stream(metadata)
    width, height = int(stream['width']), int(stream['height'])
    sar = rational(stream.get('sample_aspect_ratio', '1:1').replace(':', '/'), 1) or 1
    rotation = float(stream.get('tags', {}).get('rotate', 0))
    for side in stream.get('side_data_list', []):
        rotation = float(side.get('rotation', rotation))
    if abs(rotation / 90 - round(rotation / 90)) > .001:
        raise ValueError('Non-right-angle rotation is not supported')
    dw, dh = width * sar, float(height)
    if round(rotation / 90) % 2:
        dw, dh = dh, dw
    duration = stream_duration(stream)
    fps = rational(stream.get('avg_frame_rate')) or rational(stream.get('r_frame_rate'))
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(fps) or fps <= 0:
        raise ValueError('Missing or invalid duration/frame rate')
    stat = path.stat()
    return dict(path=str(path), name=path.name, size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                duration=duration, fps=fps, width=width, height=height, display_width=dw,
                display_height=dh, rotation=rotation, stream_index=stream['index'],
                short_edge=min(dw, dh), long_edge=max(dw, dh),
                orientation='portrait' if dh > dw else 'landscape' if dw > dh else 'square',
                hdr=stream.get('color_transfer') in ('smpte2084', 'arib-std-b67'))


def scan(source, output, tools):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir():
        raise ValueError('Source must be a directory')
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}')
    videos, errors = [], []
    for path in sorted(source.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        try:
            path = path.resolve()
            if any(c in str(path) for c in '\r\n'):
                raise ValueError('Line breaks in media paths are not supported')
            metadata = probe(path, tools)
            stream = video_stream(metadata)
            if not stream_duration(stream):
                stream['duration'] = str(packet_duration(path, stream, tools))
            videos.append(normalize(path, metadata))
        except (ValueError, KeyError, StopIteration, OSError, subprocess.CalledProcessError) as exc:
            errors.append(dict(path=str(path), error=str(exc)))
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, dict(schema=1, source=str(source), videos=videos, errors=errors))
    counts = Counter((f"{v['display_width']:g}x{v['display_height']:g}", round(v['fps'], 3)) for v in videos)
    summary = [f'Videos: {len(videos)}; errors: {len(errors)}', 'Display resolution\tAverage fps\tCount']
    summary += [f'{res}\t{fps}\t{count}' for (res, fps), count in sorted(counts.items())]
    output.with_suffix('.summary.txt').write_text('\n'.join(summary), encoding='utf-8')
    return dict(videos=len(videos), errors=len(errors), inventory=str(output))


def settings(path=None):
    custom = read_json(path) if path else {}
    if not isinstance(custom, dict) or set(custom) - set(DEFAULTS):
        raise ValueError('Unknown configuration keys (see examples/default.json)')
    cfg = dict(DEFAULTS, **custom)
    for key in ('width', 'height', 'fps', 'seed', 'threads', 'crf'):
        if type(cfg[key]) is not int:
            raise ValueError(f'{key} must be an integer')
    if cfg['width'] < 6 or cfg['height'] < 2 or cfg['width'] % 2 or cfg['height'] % 2:
        raise ValueError('Width/height must be positive even dimensions; width >= 6')
    if not 1 <= cfg['fps'] <= 240 or not 1 <= cfg['threads'] <= 128 or not 1 <= cfg['crf'] <= 51:
        raise ValueError('Invalid fps, threads or CRF')
    if cfg['fit'] not in ('cover', 'contain') or cfg['orientation'] not in ('portrait', 'landscape', 'all'):
        raise ValueError('Invalid fit or orientation')
    if cfg['preset'] not in ('ultrafast','superfast','veryfast','faster','fast','medium','slow','slower','veryslow'):
        raise ValueError('Invalid x264 preset')
    for key in ('min_short_edge', 'min_fps'):
        if type(cfg[key]) not in (float, int) or not math.isfinite(cfg[key]) or cfg[key] < 0:
            raise ValueError(f'{key} must be a finite nonnegative number')
    return cfg


def band(clip):
    return next((n for n in (1080, 1440, 2160) if clip['short_edge'] < n), 99999)


def arrange(clips, cfg):
    rng = random.Random(cfg['seed'])
    columns, totals = [[], [], []], [0, 0, 0]
    for category in sorted({band(c) for c in clips}):
        pool = [dict(c, frames=max(1, round(c['duration'] * cfg['fps']))) for c in clips if band(c) == category]
        rng.shuffle(pool)
        pool.sort(key=lambda c: c['frames'], reverse=True)
        group_totals = [0, 0, 0]
        for clip in pool:
            col = min(range(3), key=lambda i: (group_totals[i], totals[i]))
            columns[col].append(clip)
            totals[col] += clip['frames']
            group_totals[col] += clip['frames']
    for _ in range(50):
        score, best = max(totals) - min(totals), None
        if score <= 1:
            break
        for a in range(3):
            for b in range(a + 1, 3):
                for i, left in enumerate(columns[a]):
                    for j, right in enumerate(columns[b]):
                        if band(left) != band(right):
                            continue
                        delta = right['frames'] - left['frames']
                        trial = totals.copy()
                        trial[a] += delta
                        trial[b] -= delta
                        gap = max(trial) - min(trial)
                        if gap < score:
                            score, best = gap, (a, b, i, j, trial)
        if best is None:
            break
        a, b, i, j, totals = best
        columns[a][i], columns[b][j] = columns[b][j], columns[a][i]
    for col, clips in enumerate(columns):
        keyed = []
        for category in sorted({band(c) for c in clips}):
            pool = [c for c in clips if band(c) == category]
            rng.shuffle(pool)
            total, cursor = sum(c['frames'] for c in pool), 0
            for clip in pool:
                keyed.append(((cursor + clip['frames'] / 2) / total + rng.uniform(-.035, .035), clip))
                cursor += clip['frames']
        columns[col] = [c for _, c in sorted(keyed, key=lambda pair: pair[0])]
    return columns, totals


def reject_links(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink() or (parent.exists() and getattr(parent.lstat(), 'st_file_attributes', 0) & 1024):
            raise ValueError(f'Symlinks/junctions are not allowed in job paths: {parent}')


def new_job_location(source, job):
    source, job = Path(source).resolve(), Path(job).absolute()
    reject_links(job)
    job = job.resolve()
    if source == job or source in job.parents or job in source.parents:
        raise ValueError('Source and job directories must be separate, not nested')
    if job.exists():
        raise FileExistsError('Use a new job directory; resume existing jobs with render')
    return job


def make_plan(inventory, config, job):
    cfg, data = settings(config), read_json(inventory)
    source = Path(data['source']).resolve()
    job = new_job_location(source, job)
    selected, seen = [], set()
    for c in data['videos']:
        if c.get('hdr') or (cfg['orientation'] != 'all' and c['orientation'] != cfg['orientation']):
            continue
        if c['short_edge'] < cfg['min_short_edge'] or c['fps'] < cfg['min_fps']:
            continue
        key = str(Path(c['path']).resolve())
        if key not in seen:
            selected.append(c)
            seen.add(key)
    if len(selected) < 3:
        raise ValueError('At least three matching SDR videos are needed')
    check_sources(selected)
    columns, totals = arrange(selected, cfg)
    plan = dict(schema=1, source=str(source), settings=cfg, columns=columns,
                column_frames=totals, selected_count=len(selected),
                excluded_count=len(data['videos']) - len(selected), scan_errors=data.get('errors', []))
    job.mkdir(parents=True)
    write_json(job/'plan.json', plan)
    write_json(job/'.tricolumn-job.json', dict(schema=1, plan_sha256=digest(plan)))
    report = dict(selected=len(selected), column_seconds=[n/cfg['fps'] for n in totals],
                  end_difference_seconds=(max(totals)-min(totals))/cfg['fps'],
                  resolution_counts=dict(Counter(f"{c['display_width']:g}x{c['display_height']:g}" for c in selected)))
    write_json(job/'plan-summary.json', report)
    lines = []
    for col, clips in enumerate(columns):
        cursor = 0
        lines.append(f'Column {col+1}')
        for clip in clips:
            lines.append(f"{cursor/cfg['fps']:.3f}s\t{clip['path']}")
            cursor += clip['frames']
    (job/'play-order.txt').write_text('\n'.join(lines), encoding='utf-8')
    return report


def load_job(job):
    job = Path(job).absolute()
    reject_links(job)
    job = job.resolve()
    marker, plan = read_json(job/'.tricolumn-job.json'), read_json(job/'plan.json')
    if marker.get('schema') != 1 or marker.get('plan_sha256') != digest(plan):
        raise ValueError('Job plan was modified; create a new job instead')
    reject_links(job/'cache')
    return job, plan


@contextmanager
def job_lock(job):
    lock = job/'.lock'
    try:
        with lock.open('x', encoding='utf-8') as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        raise ValueError(f'Job is locked: {lock}. Check running processes before removing a stale lock.')
    try:
        yield
    finally:
        lock.unlink()


def check_sources(clips):
    for clip in clips:
        stat = Path(clip['path']).stat()
        if (stat.st_size, stat.st_mtime_ns) != (clip['size'], clip['mtime_ns']):
            raise ValueError(f"Source changed: {clip['path']}")
