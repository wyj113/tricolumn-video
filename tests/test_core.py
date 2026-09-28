import json
import tempfile
import unittest
from pathlib import Path

from tricolumn.core import arrange, normalize, settings
from tricolumn.render import build_timeline


class CoreTests(unittest.TestCase):
    def test_rotation_and_sample_aspect_ratio_define_orientation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.mp4';path.write_bytes(b'fixture')
            stream=dict(index=0, codec_type='video', width=720, height=576,
                        sample_aspect_ratio='16:15', duration='1.5', avg_frame_rate='30000/1001',
                        side_data_list=[{'rotation':-90}])
            item=normalize(path, {'streams':[stream]})
            self.assertEqual((item['display_width'],item['display_height']),(576,768))
            self.assertEqual(item['orientation'],'portrait')
            self.assertAlmostEqual(item['fps'],29.97002997)

    def test_video_duration_tag_wins_over_longer_container_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'short-video.mkv';path.write_bytes(b'fixture')
            stream=dict(index=0,codec_type='video',width=120,height=160,
                        avg_frame_rate='30/1',tags={'DURATION':'00:00:00.500000000'})
            item=normalize(path,{'streams':[stream], 'format':{'duration':'3.021'}})
            self.assertEqual(item['duration'],.5)

    def test_lossless_crf_is_rejected_for_high_profile_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'config.json';config.write_text('{"crf":0}')
            with self.assertRaisesRegex(ValueError,'CRF'):
                settings(config)

    def test_schedule_uses_every_clip_once_with_reproducible_balancing(self):
        source=[dict(path=f'{band}-{i}',duration=(i%3)+1,short_edge=band)
                for band in (720,1080,1440,2160) for i in range(18)]
        cfg=settings();columns,totals=arrange(source,cfg)
        self.assertEqual(len({v['path'] for col in columns for v in col}),72)
        self.assertEqual(sum(map(len,columns)),72)
        self.assertEqual(max(totals)-min(totals),0)
        self.assertEqual((columns,totals),arrange(source,cfg))
        self.assertNotEqual(columns,arrange(source,dict(cfg,seed=43))[0])
        for band in (720,1080,1440,2160):
            self.assertEqual([sum(v['short_edge']==band for v in col) for col in columns],[6,6,6])

    def test_timeline_preserves_all_frames_when_columns_end_unequally(self):
        columns=[[{'path':'a','duration':1.5}], [{'path':'b','duration':1}],
                 [{'path':'c','duration':.5},{'path':'d','duration':1.5}]]
        segments,totals=build_timeline(columns,60)
        self.assertEqual(totals,[90,60,120])
        coverage={}
        for segment in segments:
            for clip in segment['active']:
                if clip:
                    coverage.setdefault(clip['path'],[]).extend(range(clip['offset'],clip['offset']+segment['frames']))
        self.assertEqual(coverage,{'a':list(range(90)),'b':list(range(60)),
                                   'c':list(range(30)),'d':list(range(90))})
        self.assertEqual(segments[-1]['active'][:2],[None,None])


if __name__=='__main__':
    unittest.main()
