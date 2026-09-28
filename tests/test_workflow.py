import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, '-m', 'tricolumn', *map(str, args)],
                                cwd=REPO, capture_output=True, text=True, encoding='utf-8')
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def test_help_describes_workflow_without_ffmpeg(self):
        result = self.cli('--help')
        for command in ('scan', 'plan', 'render', 'verify', 'clean', 'run'):
            self.assertIn(command, result.stdout)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_real_media_pipeline_resume_and_safe_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='tricolumn-') as temp:
            root = Path(temp)
            source = root/'source with spaces'
            source.mkdir()
            for i, (size, fps) in enumerate([('120x160',24), ('90x160',30), ('120x160',60), ('160x90',30)]):
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                                f'color=white:s={size}:r={fps}:d=0.5',
                                '-c:v','libx264','-pix_fmt','yuv420p',str(source/f'clip {i}.mp4')], check=True)
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            inventory = root/'inventory.json'
            self.cli('scan', source, '--output', inventory)
            data = json.loads(inventory.read_text(encoding='utf-8'))
            self.assertEqual(len(data['videos']),4)
            config = root/'config.json'
            config.write_text(json.dumps({'width':256,'height':144,'fps':60,'preset':'ultrafast',
                                          'min_short_edge':90,'min_fps':23.9}),encoding='utf-8')
            for mode in ('cover','contain'):
                settings = json.loads(config.read_text()); settings['fit'] = mode
                config.write_text(json.dumps(settings))
                job = root/mode
                self.cli('plan','--inventory',inventory,'--config',config,'--job',job)
                plan = json.loads((job/'plan.json').read_text(encoding='utf-8'))
                paths=[c['path'] for col in plan['columns'] for c in col]
                self.assertEqual(len(paths),3)
                self.assertEqual(len(set(paths)),3)
                self.cli('render','--job',job)
                self.cli('verify','--job',job)
                final = job/'final.mp4'
                raw = subprocess.check_output(['ffmpeg','-v','error','-i',str(final),'-frames:v','1',
                                               '-pix_fmt','gray','-f','rawvideo','-'])
                if mode=='cover':
                    for x in (0,42,85,86,128,169,170,213,255):
                        self.assertGreater(raw[x],235)
                else:
                    self.assertLess(min(raw[:256]),10)
                stamp = final.stat().st_mtime_ns
                self.cli('render','--job',job)
                self.assertEqual(final.stat().st_mtime_ns,stamp)
                cache=list((job/'cache').glob('segment_*.mp4'))
                self.assertTrue(cache)
                keep=job/'cache'/'unrelated.txt';keep.write_text('keep')
                changed=root/'modified.mp4'
                damaged=bytearray(final.read_bytes());damaged[-1]^=1;changed.write_bytes(damaged)
                self.cli('clean','--job',job,'--final',changed,'--yes',ok=False)
                self.assertTrue(all(p.exists() for p in cache))
                (job/'.lock').write_text('test lock')
                self.cli('clean','--job',job,'--yes',ok=False)
                (job/'.lock').unlink()
                self.cli('clean','--job',job)
                self.assertTrue(all(p.exists() for p in cache))
                exported=root/f'{mode} exported.mp4';final.rename(exported)
                self.cli('clean','--job',job,ok=False)
                self.cli('clean','--job',job,'--final',exported,'--yes')
                self.assertTrue(exported.exists())
                self.assertTrue(keep.exists())
                self.assertFalse(any(p.exists() for p in cache))
            run_job=root/'all-in-one'
            self.cli('run',source,'--config',config,'--job',run_job)
            self.assertTrue(json.loads((run_job/'verification.json').read_text())['passed'])
            self.assertEqual(before,{p.name:p.read_bytes() for p in source.iterdir()})

    def test_invalid_settings_rejected_before_creating_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=root/'bad.json';config.write_text('{"width":255}')
            inventory=root/'inventory.json';inventory.write_text('{"videos": []}')
            job=root/'job'
            self.cli('plan','--inventory',inventory,'--config',config,'--job',job,ok=False)
            self.assertFalse(job.exists())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_nested_run_rejects_without_writing_inside_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source';source.mkdir()
            self.cli('run',source,'--job',source/'output',ok=False)
            self.assertEqual(list(source.iterdir()),[])


if __name__ == '__main__':
    unittest.main()
