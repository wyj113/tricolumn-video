"""Frame-aligned segment encoder adapted from the validated local workflow."""
import json
import subprocess
from pathlib import Path

from .core import video_stream, probe


def build_timeline(columns, fps):
    timelines, totals, boundaries = [], [], {0}
    for column in columns:
        cursor, clips = 0, []
        for clip in column:
            frames = max(1, round(clip['duration'] * fps))
            clips.append(dict(clip, start=cursor, end=cursor + frames))
            cursor += frames
            boundaries.add(cursor)
        timelines.append(clips)
        totals.append(cursor)
    segments = []
    boundaries = sorted(boundaries)
    for start, end in zip(boundaries, boundaries[1:]):
        active = []
        for column in timelines:
            clip = next((c for c in column if c['start'] <= start < c['end']), None)
            active.append(dict(clip, offset=start-clip['start']) if clip else None)
        segments.append(dict(start=start, frames=end-start, active=active))
    return segments, totals


def frame_count(path, tools):
    return int(video_stream(probe(path, tools))['nb_frames'])


def render_segment(segment, output, tools, cfg):
    width, height, fps = cfg['width'], cfg['height'], cfg['fps']
    base = width // 6 * 2
    remainder = width - base * 3
    slots = [base + min(2, remainder), base, base + max(0, remainder-2)]
    count = segment['frames']
    cmd = [tools[0], '-hide_banner', '-nostdin', '-v', 'warning', '-y', '-filter_complex_threads', '4']
    filters, input_index = [], 0
    for col, active in enumerate(segment['active']):
        slot = slots[col]
        if active is None:
            filters.append(f'color=c=black:s={slot}x{height}:r={fps},trim=end_frame={count},setpts=PTS-STARTPTS[c{col}]')
            continue
        offset = active['offset']
        # Seek one integer second early to preserve the original repeat-frame cadence.
        seek_frames = max(0, (offset // fps - 1) * fps)
        skip_frames = offset - seek_frames
        cmd += ['-threads', '2', '-ss', f'{seek_frames/fps:.9f}', '-t', f'{(skip_frames+count)/fps+1:.9f}', '-i', active['path']]
        mode = 'increase' if cfg['fit'] == 'cover' else 'decrease'
        geometry = (f'crop={slot}:{height}:(iw-ow)/2:(ih-oh)/2' if cfg['fit'] == 'cover' else
                    f'format=yuv444p,pad={slot}:{height}:(ow-iw)/2:(oh-ih)/2:black')
        filters.append(
            f'[{input_index}:{active["stream_index"]}]'
            f'scale={slot}:{height}:force_original_aspect_ratio={mode}:force_divisible_by=2:reset_sar=1:flags=lanczos:out_range=tv,'
            f'{geometry},format=yuv420p,fps={fps}:start_time=0,'
            f'tpad=stop_mode=clone:stop_duration=1,'
            f'trim=start_frame={skip_frames}:end_frame={skip_frames+count},setpts=PTS-STARTPTS[c{col}]')
        input_index += 1
    filters.append('[c0][c1][c2]hstack=inputs=3:shortest=1,setsar=1,format=yuv420p[out]')
    cmd += ['-filter_complex', ';'.join(filters), '-map', '[out]', '-an', '-frames:v', str(count),
            '-r', str(fps), '-fps_mode', 'cfr', '-c:v', 'libx264', '-preset', cfg['preset'],
            '-crf', str(cfg['crf']), '-threads', str(cfg['threads']), '-profile:v', 'high',
            '-g', str(fps*2), '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-colorspace', 'bt709',
            '-color_primaries', 'bt709', '-color_trc', 'bt709', '-video_track_timescale', str(fps*1000), str(output)]
    with output.with_suffix('.log').open('w', encoding='utf-8') as log:
        log.write(json.dumps(cmd, ensure_ascii=False) + '\n')
        log.flush()
        subprocess.run(cmd, stdout=log, stderr=log, check=True)
    if frame_count(output, tools) != count:
        raise ValueError(f'Unexpected segment frame count: {output.name}')


def join_segments(paths, output, tools, fps, expected):
    partial = output.with_name('final.partial.mp4')
    listing = output.with_name('concat.txt')
    # Relative generated filenames avoid quoting users' source paths in concat syntax.
    listing.write_text(''.join(f"file 'cache/{p.name}'\n" for p in paths), encoding='utf-8')
    with output.with_name('join.log').open('w', encoding='utf-8') as log:
        subprocess.run([tools[0], '-hide_banner', '-nostdin', '-v', 'warning', '-y', '-f', 'concat',
                        '-safe', '1', '-i', str(listing), '-map', '0:v:0', '-c', 'copy', '-an',
                        '-movflags', '+faststart', str(partial)], stdout=log, stderr=log, check=True)
    if frame_count(partial, tools) != expected:
        raise ValueError('Joined frame count mismatch')
    partial.rename(output)
