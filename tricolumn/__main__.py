import argparse
import json
import subprocess
from pathlib import Path

from .core import make_plan, new_job_location, scan, settings, tool_paths
from .jobs import clean, render, verify


def main(argv=None):
    parser = argparse.ArgumentParser(description='Scan, filter and compose local videos into three columns.')
    commands = parser.add_subparsers(dest='command', required=True)
    doctor = commands.add_parser('doctor', help='Check Python/FFmpeg availability')
    doctor.add_argument('--ffmpeg-dir')
    scanning = commands.add_parser('scan', help='Save source metadata and a resolution/fps summary')
    scanning.add_argument('source', type=Path)
    scanning.add_argument('--output', type=Path, required=True)
    scanning.add_argument('--ffmpeg-dir')
    planning = commands.add_parser('plan', help='Filter and balance three randomized columns')
    planning.add_argument('--inventory', type=Path, required=True)
    planning.add_argument('--config', type=Path)
    planning.add_argument('--job', type=Path, required=True)
    for name in ('render', 'verify'):
        sub = commands.add_parser(name, help='Encode/resume segments' if name == 'render' else 'Decode entire final and check sources')
        sub.add_argument('--job', type=Path, required=True)
        sub.add_argument('--ffmpeg-dir')
        if name == 'render':
            sub.add_argument('--progress-seconds', type=int, default=30)
    cleanup = commands.add_parser('clean', help='Preview cache cleanup; --yes deletes generated segments only')
    cleanup.add_argument('--job', type=Path, required=True)
    cleanup.add_argument('--final', type=Path, help='Verified final video if moved out of the job directory')
    cleanup.add_argument('--yes', action='store_true')
    run = commands.add_parser('run', help='New scan -> plan -> render -> full verification')
    run.add_argument('source', type=Path)
    run.add_argument('--job', type=Path, required=True)
    run.add_argument('--config', type=Path)
    run.add_argument('--ffmpeg-dir')
    args = parser.parse_args(argv)
    try:
        if args.command == 'clean':
            result = clean(args.job, args.final, args.yes)
        elif args.command == 'plan':
            result = make_plan(args.inventory, args.config, args.job)
        else:
            tools = tool_paths(args.ffmpeg_dir)
            if args.command == 'doctor':
                result = dict(ffmpeg=tools[0], ffprobe=tools[1], version=subprocess.check_output(
                    [tools[0], '-version'], encoding='utf-8').splitlines()[0])
            elif args.command == 'scan':
                result = scan(args.source, args.output, tools)
            elif args.command == 'render':
                if args.progress_seconds < 1:
                    raise ValueError('Progress interval must be >= 1 second')
                result = render(args.job, tools, args.progress_seconds)
            elif args.command == 'verify':
                result = verify(args.job, tools)
            else:
                settings(args.config)
                new_job_location(args.source, args.job)
                inventory = args.job.absolute().with_name(args.job.name + '.inventory.json')
                scan(args.source, inventory, tools)
                make_plan(inventory, args.config, args.job)
                render(args.job, tools)
                result = verify(args.job, tools)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Error: {exc}\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Interrupted. Completed segments are retained; use render --job to resume.\n')


if __name__ == '__main__':
    raise SystemExit(main())
