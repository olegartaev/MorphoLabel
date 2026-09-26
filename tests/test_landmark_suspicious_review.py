import shutil
import tempfile
import unittest
from pathlib import Path

from app.project_storage import Project
from app.landmark_suspicious_review import start, active, current, summary, move, complete_current, remove_image


class SuspiciousLandmarkReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=Path(tempfile.mkdtemp());source=self.tmp/'source';source.mkdir()
        (source/'a.jpg').write_bytes(b'a');(source/'b.jpg').write_bytes(b'b')
        schema=self.tmp/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n',encoding='utf8')
        self.project=Project.create('p',source,self.tmp,schema,source_layout='direct')
        self.ids=[row['image_id'] for row in self.project.catalog_rows()]

    def tearDown(self):
        shutil.rmtree(self.tmp,ignore_errors=True)

    def test_legacy_complex_qc_queue_without_generation_metadata_is_not_resumed(self):
        issue={'image_id':self.ids[0],'kind':'complex_qc','message':'Old QC'}
        self.project.set_ui_state('landmark_suspicious_review',{'active':True,'source':'Complex QC','issues':[issue],'position':0,'completed':[]})
        self.assertIsNone(active(self.project))
        fresh=start(self.project,[issue],source='Complex QC')
        self.assertEqual(2,fresh['format_version'])
        self.assertTrue(fresh['generation_id']);self.assertTrue(fresh['created_at'])
        self.assertIsNotNone(active(self.project))

    def test_excluding_current_review_image_removes_all_its_issues_and_advances(self):
        issues=[
            {'image_id':self.ids[0],'kind':'spatial_outlier','landmark_id':1,'message':'one'},
            {'image_id':self.ids[0],'kind':'swap_suggestion','landmark_ids':[1,2],'message':'two'},
            {'image_id':self.ids[1],'kind':'bounds','landmark_id':2,'message':'next'},
        ]
        start(self.project,issues,source='Complex QC')
        state,target=remove_image(self.project,self.ids[0])
        self.assertEqual(self.ids[1],target)
        self.assertEqual([self.ids[1]],[item['image_id'] for item in state['issues']])
        self.assertEqual(self.ids[1],current(self.project)['image_id'])
        self.assertEqual([],state['completed'])

    def test_excluding_last_review_image_finishes_queue_without_accepting_it(self):
        start(self.project,[{'image_id':self.ids[0],'kind':'complex_qc','message':'bad photo'}],source='Complex QC')
        state,target=remove_image(self.project,self.ids[0])
        self.assertIsNone(target);self.assertFalse(state['active']);self.assertEqual([],state['issues'])
        self.assertIsNone(active(self.project))

    def test_review_cycles_issues_persistently_and_finishes(self):
        issues=[
            {'image_id':self.ids[0],'kind':'spatial_outlier','landmark_id':1,'message':'Check LM1'},
            {'image_id':self.ids[0],'kind':'swap_suggestion','first_landmark_id':1,'second_landmark_id':2,'message':'Possible swap'},
            {'image_id':self.ids[1],'kind':'bounds','landmark_id':2,'message':'Outside image'},
        ]
        start(self.project,issues,source='test batch')
        self.assertTrue(active(self.project));self.assertEqual([1],current(self.project)['landmark_ids'])
        self.assertEqual((1,3),(summary(self.project)['position'],summary(self.project)['total']))
        state,finished=complete_current(self.project);self.assertFalse(finished);self.assertEqual([1,2],current(self.project)['landmark_ids'])
        state,finished=move(self.project,-1);self.assertFalse(finished);self.assertEqual([1],current(self.project)['landmark_ids'])
        complete_current(self.project);complete_current(self.project)
        state,finished=complete_current(self.project);self.assertTrue(finished);self.assertIsNone(active(self.project))


if __name__=='__main__':
    unittest.main()
