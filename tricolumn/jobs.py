import json
import subprocess
import time
from pathlib import Path

from .core import (check_sources, digest, file_hash, job_lock, load_job, probe,
                   read_json, reject_links, video_stream, write_json)
from .render import build_timeline, frame_count, join_segments, render_segment


def clips(plan):
    return [c for col in plan['columns'] for c in col]


def encoder_signature(plan):
    modules = {p.name: file_hash(p) for p in Path(__file__).parent.glob('*.py')}
    return digest(dict(plan=plan, code=modules))


def validate_final(path, tools, plan):
    metadata = probe(path, tools)
    video, cfg = video_stream(metadata), plan['settings']
    actual = (video['width'], video['height'], video['codec_name'], video['pix_fmt'], int(video['nb_frames']))
    expected = (cfg['width'], cfg['height'], 'h264', 'yuv420p', max(plan['column_frames']))
    if actual != expected or len(metadata['streams']) != 1 or video['r_frame_rate'] != f"{cfg['fps']}/1":
        raise ValueError('Final video does not match the job plan')
    return metadata


def render(job, tools, progress_seconds=30):
    job, plan = load_job(job)
    cfg = plan['settings']
    with job_lock(job):
        check_sources(clips(plan))
        final = job/'final.mp4'
        reject_links(final)
        if final.exists():
            validate_final(final, tools, plan)
            return dict(output=str(final), resumed=True)
        help_text = subprocess.check_output([tools[0], '-hide_banner', '-h', 'filter=scale'],
                                            encoding='utf-8', errors='replace', stderr=subprocess.STDOUT)
        if 'reset_sar' not in help_text:
            raise ValueError('FFmpeg scale reset_sar is required; use FFmpeg 9 or newer')
        cache = job/'cache'
        cache.mkdir(exist_ok=True)
        signature = encoder_signature(plan)
        manifest = cache/'manifest.json'
        if manifest.exists() and read_json(manifest).get('signature') != signature:
            raise ValueError('Encoder changed; create a new job instead of reusing old cache')
        if not manifest.exists() and any(cache.iterdir()):
            raise ValueError('Refusing to use an unowned cache directory')
        write_json(manifest, dict(signature=signature))
        segments, totals = build_timeline(plan['columns'], cfg['fps'])
        if totals != plan['column_frames']:
            raise ValueError('Timeline does not match saved plan')
        outputs, failures = [], []
        started, last_notice = time.monotonic(), -float('inf')
        for i, segment in enumerate(segments):
            output = cache/f'segment_{i:06d}.mp4'
            partial = cache/f'segment_{i:06d}.partial.mp4'
            try:
                reject_links(output)
                reject_links(partial)
                check_sources([c for c in segment['active'] if c])
                if output.exists():
                    if frame_count(output, tools) != segment['frames']:
                        raise ValueError('Cached segment has wrong frame count; remove this damaged cache file and retry')
                else:
                    render_segment(segment, partial, tools, cfg)
                    partial.rename(output)
                outputs.append(output)
            except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
                failures.append(dict(segment=i, error=str(exc)))
            elapsed = time.monotonic()-started
            status = dict(done=i+1, total=len(segments), failed=len(failures), elapsed_seconds=round(elapsed, 1),
                          timeline_seconds=(segment['start']+segment['frames'])/cfg['fps'])
            write_json(job/'progress.json', status)
            if elapsed-last_notice >= progress_seconds or i == len(segments)-1:
                print(json.dumps(status), flush=True)
                last_notice = elapsed
        write_json(job/'failures.json', failures)
        if failures:
            raise ValueError(f'{len(failures)} segments failed; see failures.json and cache/*.log, then rerun render')
        reject_links(job/'final.partial.mp4')
        join_segments(outputs, final, tools, cfg['fps'], max(totals))
        metadata = validate_final(final, tools, plan)
        return dict(output=str(final), bytes=final.stat().st_size, duration=metadata['format']['duration'])


def verify(job, tools):
    job, plan = load_job(job)
    with job_lock(job):
        final = job/'final.mp4'
        reject_links(final)
        metadata = validate_final(final, tools, plan)
        check_sources(clips(plan))
        report = dict(passed=False, plan_sha256=digest(plan))
        write_json(job/'verification.json', report)
        with (job/'decode-errors.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([tools[0], '-hide_banner', '-nostdin', '-v', 'error', '-xerror',
                                     '-stats_period', '10', '-progress', str(job/'decode-progress.txt'),
                                     '-i', str(final), '-map', '0:v:0', '-fps_mode', 'passthrough', '-f', 'null', '-'],
                                    stdout=subprocess.DEVNULL, stderr=log)
        progress = dict(line.split('=', 1) for line in (job/'decode-progress.txt').read_text().splitlines() if '=' in line)
        if result.returncode or progress.get('progress') != 'end' or int(progress.get('frame', 0)) != max(plan['column_frames']):
            raise ValueError('Full decode failed; see decode-errors.log')
        if (job/'decode-errors.log').stat().st_size or int(progress.get('drop_frames', 0)) or int(progress.get('dup_frames', 0)):
            raise ValueError('Decode reported errors or frame changes')
        check_sources(clips(plan))
        report.update(passed=True, final_sha256=file_hash(final), final_bytes=final.stat().st_size,
                      metadata=metadata, decoded_frames=int(progress['frame']), sources_unchanged=True)
        write_json(job/'verification.json', report)
        return dict(passed=True, frames=report['decoded_frames'], output=str(final))


def clean(job, final=None, yes=False):
    job, plan = load_job(job)
    with job_lock(job):
        report = read_json(job/'verification.json')
        final = Path(final).resolve() if final else job/'final.mp4'
        if not report.get('passed') or report.get('plan_sha256') != digest(plan):
            raise ValueError('A successful verification for this plan is required before cleanup')
        if not final.is_file() or final.stat().st_size != report['final_bytes'] or file_hash(final) != report['final_sha256']:
            raise ValueError('Verified final is missing or changed; use --final PATH if you moved it')
        cache = job/'cache'
        if final == cache or cache in final.parents:
            raise ValueError('Final must not be inside the cache directory')
        if not cache.exists():
            return dict(deleted=0, bytes=0, dry_run=not yes)
        read_json(cache/'manifest.json')
        segments, _ = build_timeline(plan['columns'], plan['settings']['fps'])
        targets = []
        for i in range(len(segments)):
            for suffix in ('.mp4', '.partial.mp4', '.partial.log'):
                target = cache/f'segment_{i:06d}{suffix}'
                reject_links(target)
                if target.is_file():
                    targets.append(target)
        total = sum(p.stat().st_size for p in targets)
        if yes:
            for target in targets:
                target.unlink()
        summary = dict(files=len(targets), bytes=total, dry_run=not yes, preserved_final=str(final))
        if yes:
            write_json(job/'cleanup.json', summary)
        return summary
