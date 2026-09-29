import csv, tempfile, unittest
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.export_formats import export_landmark_csv_long, export_landmark_wide, export_landmark_tps, export_morphoj_text
from app.results_export import parse_tps
from app.ui.export_section import ExportSection
class ExportCategoryTests(unittest.TestCase):
 def test_category_filtered_long_csv_uses_canonical_rows(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);src=root/'source';src.mkdir();Image.new('RGB',(20,10)).save(src/'fish.jpg');schema=root/'schema.csv';schema.write_text('id,abbr,name,role,category\n1,A,Anterior,BOTH,Head\n2,T,Tail,BOTH,Tail\n',encoding='utf-8');project=Project.create('p',src,root,schema,source_layout='direct');image_id=project.catalog_rows()[0]['image_id'];project.save_landmark(image_id,1,3,4,'manual','manual');project.save_landmark(image_id,2,8,4,'manual','manual');path=export_landmark_csv_long(project,['Head']);rows=list(csv.DictReader(path.open(encoding='utf-8')));self.assertEqual([(r['landmark_id'],r['category']) for r in rows],[('1','Head')])
 def test_tps_wide_and_morphoj_have_format_specific_missing_behavior(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);src=root/'source';src.mkdir();Image.new('RGB',(20,10)).save(src/'a.jpg');Image.new('RGB',(20,10)).save(src/'b.jpg')
   schema=root/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,Anterior,BOTH\n2,T,Tail,BOTH\n',encoding='utf-8')
   project=Project.create('p',src,root,schema,source_layout='direct');rows=project.catalog_rows();a,b=rows[0]['image_id'],rows[1]['image_id']
   project.save_landmark(a,1,3,4,'manual','manual');project.save_landmark(a,2,8,4,'manual','manual')
   project.save_landmark(b,1,2,3,'manual','manual');project.save_landmark(b,2,None,None,'missing','manual')
   tps=export_landmark_tps(project,target=root/'chosen.tps');blocks=parse_tps(tps)
   self.assertEqual(2,len(blocks));self.assertEqual([(3.0,4.0),(8.0,4.0)],blocks[0]['coordinates']);self.assertEqual((-1.0,-1.0),blocks[1]['coordinates'][1])
   wide=export_landmark_wide(project,target=root/'wide.csv');wide_rows=list(csv.DictReader(wide.open(encoding='utf-8')))
   self.assertEqual('',wide_rows[1]['x2']);self.assertEqual('',wide_rows[1]['y2'])
   morphoj_target=root/'chosen_morphoj.txt';morphoj=export_morphoj_text(project,target=morphoj_target)
   self.assertEqual(morphoj_target,morphoj)
   lines=morphoj.read_text(encoding='utf-8').splitlines();self.assertEqual('ID\tx1\ty1\tx2\ty2',lines[0]);self.assertEqual(2,len(lines))
   fields=lines[1].split('\t');self.assertEqual(a,fields[0]);self.assertEqual(['3.00000','4.00000','8.00000','4.00000'],fields[1:])
 def test_group_filtered_tps_keeps_schema_order(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);src=root/'source';src.mkdir();Image.new('RGB',(20,10)).save(src/'fish.jpg')
   schema=root/'schema.csv';schema.write_text('id,abbr,name,role,category\n1,A,Anterior,BOTH,Head\n2,T,Tail,BOTH,Tail\n3,E,Eye,BOTH,Head\n',encoding='utf-8')
   project=Project.create('p',src,root,schema,source_layout='direct');image_id=project.catalog_rows()[0]['image_id']
   project.save_landmark(image_id,1,1,2,'manual','manual');project.save_landmark(image_id,3,3,4,'manual','manual')
   block=parse_tps(export_landmark_tps(project,['Head']))[0]
   self.assertEqual([(1.0,2.0),(3.0,4.0)],block['coordinates'])

 def test_tps_uses_original_image_coordinates_and_scale(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);src=root/'source'/'L';src.mkdir(parents=True);Image.new('RGB',(20,10)).save(src/'fish.jpg')
   schema=root/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,Anterior,BOTH\n2,T,Tail,BOTH\n',encoding='utf-8')
   project=Project.create('p',src.parent,root,schema,source_layout='direct');row=project.catalog_rows()[0];image_id=row['image_id']
   transform={'original_width':20,'original_height':10,'rotation_degrees':0.0,'center_x':10.0,'center_y':5.0,'crop_left':2.0,'crop_top':1.0,'output_width':18,'output_height':9}
   project.save_crop(image_id,{'crop_bounds':[2,1,20,10],'transform':transform,'rotation_degrees':0.0},'manual')
   project.save_landmark(image_id,1,3,4,'manual','manual');project.save_landmark(image_id,2,8,4,'manual','manual')
   project.set_locality_calibration('L',image_id,2.0,'mm',{'mm_per_pixel':0.5})
   block=parse_tps(export_landmark_tps(project,target=root/'coords.tps'))[0]
   self.assertEqual([(5.0,5.0),(10.0,5.0)],block['coordinates']);self.assertEqual('0.500000',block['SCALE']);self.assertEqual('fish.jpg',block['IMAGE'])
 def test_export_dialog_extension_tracks_selected_format(self):
  section=ExportSection.__new__(ExportSection)
  self.assertTrue(section._format_target('landmarks.tps','CSV wide (*.csv)').endswith('.csv'))
  self.assertTrue(section._format_target('landmarks.csv','*.tps').endswith('.tps'))
  self.assertTrue(section._format_target('landmarks.tps','MorphoJ row/column text (*.txt)').endswith('.txt'))

if __name__=='__main__':unittest.main()