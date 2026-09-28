import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tricolumn.core import normalize, packet_duration, probe, scan, settings, tool_paths, video_stream
from tricolumn.render import render_segment


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class MediaTests(unittest.TestCase):
    def test_seek_keeps_repeat_cadence_for_integer_fractional_and_variable_fps(self):
        tools=tool_paths();cfg=dict(settings(),width=256,height=144,preset='ultrafast')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for rate in ('24','30','60','30000/1001','vfr'):
                with self.subTest(rate=rate):
                    source=root/(rate.replace('/','_')+'.mkv')
                    fps='60' if rate=='vfr' else rate
                    graph=f"nullsrc=s=120x160:r={fps}:d=5,geq=lum='16+mod(N,60)*3':cb=128:cr=128"
                    if rate=='vfr': graph+=",select='eq(n,0)+not(eq(mod(n,7),0))'"
                    subprocess.run([tools[0],'-v','error','-f','lavfi','-i',graph,
                                    '-fps_mode','vfr','-c:v','ffv1',str(source)],check=True)
                    def sampled(offset,count,label):
                        output=root/(source.stem+label+'.mp4')
                        active={'path':str(source),'stream_index':0,'offset':offset}
                        render_segment({'frames':count,'active':[active]*3},output,tools,cfg)
                        raw=subprocess.check_output([tools[0],'-v','error','-i',str(output),
                                                     '-pix_fmt','gray','-f','rawvideo','-'])
                        return raw[72*256+128::256*144]
                    full=sampled(0,300,'full');cut=sampled(193,90,'cut')
                    self.assertEqual(len(cut),90)
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(full[193:283],cut)),1)

    def test_mkv_scan_ignores_long_audio_and_packet_fallback_reads_video_only(self):
        tools=tool_paths()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'mixed.mkv'
            subprocess.run([tools[0],'-v','error','-f','lavfi','-i','color=white:s=120x160:r=30:d=0.5',
                            '-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','ffv1','-c:a','pcm_s16le',str(source)],check=True)
            metadata=probe(source,tools)
            self.assertGreater(float(metadata['format']['duration']),2.9)
            self.assertAlmostEqual(normalize(source,metadata)['duration'],.5,places=3)
            self.assertAlmostEqual(packet_duration(source,video_stream(metadata),tools),.5,places=2)
            result=scan(root,root/'inventory.json',tools)
            self.assertEqual(result['videos'],1)


if __name__=='__main__':
    unittest.main()
