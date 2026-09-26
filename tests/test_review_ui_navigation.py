import unittest
from unittest.mock import patch
from pathlib import Path

from app.editor_ready_v15 import ReadyEditorV15, review_item_landmark_ids, review_warning_image_ids, review_warning_label_layout


class _State:
 def __init__(self): self.selected=[]; self.present_ids={18,19,20}; self.points={}
 def select(self, landmark_id): self.selected.append(landmark_id)


class _Status:
 def __init__(self): self.text=""
 def config(self, **kwargs): self.text=kwargs.get("text",self.text)


class _Canvas:
 def __init__(self): self.deleted=[]; self.ovals=[]; self.text=[]
 def delete(self, tag): self.deleted.append(tag)
 def create_oval(self, *coords, **kwargs): self.ovals.append((coords,kwargs))
 def create_text(self, *coords, **kwargs): self.text.append((coords,kwargs))
 def winfo_width(self): return 300
 def winfo_height(self): return 200


class ReviewUiNavigationTests(unittest.TestCase):
 def setUp(self):
  self.queue=[
   {"image_id":"first","landmark_ids":[18,19,20],"message":"LM18–LM20 may be misassigned"},
   {"image_id":"second","landmark_ids":[7,8],"message":"LM7 and LM8 may be swapped"},
   {"image_id":"second","landmark_ids":[9],"message":"LM9 needs review"},
  ]

 def test_warning_ids_cover_exact_group_and_unrelated_rows_are_excluded(self):
  self.assertEqual(review_item_landmark_ids(self.queue[0]),(18,19,20))
  self.assertNotIn(17,review_item_landmark_ids(self.queue[0]))

 def test_photo_warning_layer_tracks_only_unreviewed_queue_items(self):
  self.assertEqual(review_warning_image_ids(self.queue),{"first","second"})
  self.assertEqual(review_warning_image_ids(self.queue,{0}),{"second"})
  self.assertEqual(review_warning_image_ids(self.queue,{0,1,2}),set())

 def test_opening_item_selects_target_photo_and_sets_issue_line(self):
  class Editor:
   pass
  editor=Editor();editor._review_queue=self.queue;editor._review_queue_index=0;editor._review_active_ids=set();editor.images=[{"image_id":"first","source_relpath":"L/first.nef"},{"image_id":"second","source_relpath":"L/second.nef"}];editor.index=1;editor.state=_State();editor.review_status=_Status();editor._render_signature=None;editor.opened=[];editor.refreshed=0;editor.rendered=0
  editor.open_image=lambda **kwargs:editor.opened.append(kwargs)
  editor.sync=lambda:None
  editor._refresh_visible_photo_rows=lambda:setattr(editor,"refreshed",editor.refreshed+1)
  editor.render=lambda:setattr(editor,"rendered",editor.rendered+1)
  editor.current=lambda:editor.images[editor.index];editor._review_issue_label=lambda item:ReadyEditorV15._review_issue_label(editor,item)
  ReadyEditorV15._open_review_queue_item(editor,0)
  self.assertEqual(editor.index,0);self.assertEqual(len(editor.opened),1)
  self.assertEqual(editor.state.selected,[]);self.assertEqual(editor._review_active_ids,{18,19,20});self.assertEqual(editor._review_pending_image_id,"first")
  self.assertIn("Issue 1 of 3 | first.nef",editor.review_status.text)
  self.assertGreater(editor.refreshed,0)

 def test_consecutive_same_image_issue_does_not_reload_image(self):
  class Editor:
   pass
  editor=Editor();editor._review_queue=self.queue;editor._review_queue_index=1;editor._review_active_ids=set();editor.images=[{"image_id":"first","source_relpath":"L/first.nef"},{"image_id":"second","source_relpath":"L/second.nef"}];editor.index=1;editor.state=_State();editor.review_status=_Status();editor._render_signature=None;editor._display_image_id="second";editor.opened=[]
  editor.open_image=lambda **kwargs:editor.opened.append(kwargs);editor.sync=lambda:None;editor._refresh_visible_photo_rows=lambda:None;editor.render=lambda:None;editor.current=lambda:editor.images[editor.index];editor._review_issue_label=lambda item:ReadyEditorV15._review_issue_label(editor,item);editor._apply_review_issue_if_loaded=lambda:True
  ReadyEditorV15._open_review_queue_item(editor,2)
  self.assertEqual(editor.opened,[]);self.assertEqual(editor._review_active_ids,{9})

 def test_warning_helper_label_is_top_left_by_default(self):
  self.assertEqual(review_warning_label_layout(100,100,300,200),(91,91,"se"))

 def test_warning_helper_label_uses_nearest_readable_edge_fallback(self):
  self.assertEqual(review_warning_label_layout(5,5,300,200),(14,14,"nw"))
  self.assertEqual(review_warning_label_layout(5,100,300,200),(14,91,"sw"))

 def test_warning_helper_label_has_black_text_and_one_pixel_white_outline(self):
  class Editor:
   pass
  editor=Editor();editor.canvas=_Canvas();editor._draw_landmark_number_label=lambda ident,x,y,warning=False:ReadyEditorV15._draw_landmark_number_label(editor,ident,x,y,warning)
  ReadyEditorV15._draw_review_warning_label(editor,18,100,100)
  white=[entry for entry in editor.canvas.text if entry[1]["fill"]=="white"]
  black=[entry for entry in editor.canvas.text if entry[1]["fill"]=="black"]
  self.assertEqual(len(white),8);self.assertEqual(len(black),1);self.assertEqual(black[0][0],(91,91))
  for coords,_kwargs in white:self.assertLessEqual(abs(coords[0]-91),1);self.assertLessEqual(abs(coords[1]-91),1)
  self.assertEqual(black[0][1]["anchor"],"se")
 def test_normal_annotation_mode_keeps_parent_landmark_label_style(self):
  class Editor:
   pass
  editor=Editor();editor.source_mode=False;editor.project=object();editor.canvas=_Canvas();editor.pan=(0,0);editor.zoom=1;editor.review_mode=False;editor._review_active_ids=set()
  points={1:{"x_standardized":50,"y_standardized":50}}
  editor._load_current_landmark_state=lambda:type("State",(),{"present_ids":set(points),"points_by_id":points})()
  # The ordinary ReadyEditorV11 renderer has already drawn its normal label.
  editor.canvas.create_text(58,42,text="1",anchor="sw",fill="#00e5ff",tags=("landmark_label",))
  ReadyEditorV15._draw_universal_landmark_number_labels(editor)
  self.assertEqual(editor.canvas.deleted,[])
  self.assertEqual(len(editor.canvas.text),1)
  self.assertEqual(editor.canvas.text[0][1]["fill"],"#00e5ff")
  self.assertEqual(editor.canvas.text[0][1]["anchor"],"sw")

 def test_review_mode_every_present_landmark_uses_black_top_left_label(self):
  class Editor:
   pass
  editor=Editor();editor.source_mode=False;editor.project=object();editor.canvas=_Canvas();editor.pan=(0,0);editor.zoom=1;editor.review_mode=True;editor._review_active_ids=set()
  points={1:{"x_standardized":50,"y_standardized":50},2:{"x_standardized":100,"y_standardized":100}}
  editor._load_current_landmark_state=lambda:type("State",(),{"present_ids":set(points),"points_by_id":points})()
  editor._draw_landmark_number_label=lambda ident,x,y,warning=False:ReadyEditorV15._draw_landmark_number_label(editor,ident,x,y,warning)
  ReadyEditorV15._draw_universal_landmark_number_labels(editor)
  black=[entry for entry in editor.canvas.text if entry[1]["fill"]=="black"]
  white=[entry for entry in editor.canvas.text if entry[1]["fill"]=="white"]
  self.assertEqual(len(black),2);self.assertEqual(len(white),16);self.assertTrue(all(entry[1]["anchor"]=="se" for entry in black))

 def test_exit_review_returns_label_rendering_to_normal_owner(self):
  class Editor:
   pass
  editor=Editor();editor.source_mode=False;editor.project=object();editor.canvas=_Canvas();editor.pan=(0,0);editor.zoom=1;editor.review_mode=True;editor._review_active_ids=set()
  points={1:{"x_standardized":50,"y_standardized":50}}
  editor._load_current_landmark_state=lambda:type("State",(),{"present_ids":set(points),"points_by_id":points})()
  editor._draw_landmark_number_label=lambda ident,x,y,warning=False:ReadyEditorV15._draw_landmark_number_label(editor,ident,x,y,warning)
  ReadyEditorV15._draw_universal_landmark_number_labels(editor)
  self.assertTrue(any(item[1]["fill"]=="black" for item in editor.canvas.text))
  editor.review_mode=False;editor.canvas.deleted.clear();editor.canvas.text.clear()
  # The actual render calls ReadyEditorV11 first; V15 must not replace that
  # restored normal label after Exit Review.
  editor.canvas.create_text(58,42,text="1",anchor="sw",fill="#00e5ff",tags=("landmark_label",))
  ReadyEditorV15._draw_universal_landmark_number_labels(editor)
  self.assertEqual(editor.canvas.deleted,[])
  self.assertEqual([(entry[1]["fill"],entry[1]["anchor"]) for entry in editor.canvas.text],[("#00e5ff","sw")])

 def test_canvas_overlay_tags_exact_warning_landmarks(self):
  class Editor:
   pass
  editor=Editor();editor.review_mode=True;editor.project=object();editor.canvas=_Canvas();editor._review_active_ids={18,19,20};editor.pan=(0,0);editor.zoom=1;editor.state=type("S",(),{"current_landmark":18})()
  points={18:{"x_standardized":10,"y_standardized":10},19:{"x_standardized":20,"y_standardized":20},20:{"x_standardized":30,"y_standardized":30}}
  editor._load_current_landmark_state=lambda:type("State",(),{"present_ids":set(points),"points_by_id":points})();editor._draw_landmark_number_label=lambda ident,x,y,warning=False:ReadyEditorV15._draw_landmark_number_label(editor,ident,x,y,warning)
  ReadyEditorV15._draw_review_overlays(editor)
  tags={tag for _coords,kwargs in editor.canvas.ovals for tag in kwargs["tags"]}
  self.assertEqual({tag for tag in tags if tag.startswith("review_warning_landmark_")},{"review_warning_landmark_18","review_warning_landmark_19","review_warning_landmark_20"})

 def test_async_navigation_defers_issue_sync_until_loaded(self):
  class Editor:
   pass
  editor=Editor();editor._review_queue=self.queue;editor._review_queue_index=0;editor._review_active_ids=set();editor._review_pending_image_id=None;editor.images=[{"image_id":"first","source_relpath":"L/first.nef"},{"image_id":"second","source_relpath":"L/second.nef"}];editor.index=1;editor._display_image_id="second";editor.review_status=_Status();editor.opened=[];editor.refreshed=0
  editor._refresh_visible_photo_rows=lambda:setattr(editor,"refreshed",editor.refreshed+1);editor.current=lambda:editor.images[editor.index];editor._review_issue_label=lambda item:ReadyEditorV15._review_issue_label(editor,item);editor.open_image=lambda **kwargs:editor.opened.append(kwargs)
  ReadyEditorV15._open_review_queue_item(editor,0)
  self.assertEqual(editor.index,0);self.assertEqual(editor._review_pending_image_id,"first")
  self.assertEqual(len(editor.opened),1);self.assertIn("Issue 1 of 3 | first.nef",editor.review_status.text)

 def test_post_load_reapplies_issue_highlights_after_normal_sync(self):
  class Editor:
   pass
  editor=Editor();editor.review_mode=True;editor._review_queue=self.queue;editor._review_queue_index=0;editor._review_pending_image_id="first";editor._review_active_ids=set();editor.images=[{"image_id":"first","source_relpath":"L/first.nef"}];editor.index=0;editor._display_image_id="first";editor.state=_State();editor.review_status=_Status();editor._render_signature=None;called=[]
  editor.current=lambda:editor.images[editor.index];editor._review_issue_label=lambda item:ReadyEditorV15._review_issue_label(editor,item);editor.sync=lambda:called.append("sync");editor._refresh_visible_photo_rows=lambda:called.append("photos")
  self.assertTrue(ReadyEditorV15._apply_review_issue_if_loaded(editor))
  self.assertEqual(editor._review_active_ids,{18,19,20});self.assertIsNone(editor._review_pending_image_id)
  self.assertEqual(called,["sync","photos"]);self.assertIn("LM18–LM20",editor.review_status.text)
 def test_accept_as_correct_persists_current_issue_without_coordinate_write(self):
  class Project:
   def __init__(self):self.accepted=[]
   def accept_review_warning(self,image_id,item):self.accepted.append((image_id,dict(item)))
  class Editor:
   pass
  project=Project();editor=Editor();editor._review_queue=self.queue;editor._review_queue_index=0;editor._review_completed_indices=set();editor._review_active_ids={18,19,20};editor.project=project;editor.images=[{"image_id":"first","source_relpath":"L/first.nef"}];editor.index=0;editor.current=lambda:editor.images[editor.index];editor._refresh_visible_photo_rows=lambda:None;editor._refresh_landmark_list=lambda _state:None;editor._load_current_landmark_state=lambda:object();opened=[];editor._open_review_queue_item=lambda index:opened.append(index);editor.review_status=_Status()
  ReadyEditorV15.accept_review_warning(editor)
  self.assertEqual(project.accepted,[("first",self.queue[0])]);self.assertEqual(editor._review_completed_indices,{0});self.assertEqual(editor._review_active_ids,set());self.assertEqual(opened,[1])
 def test_done_marks_session_item_and_advances_without_data_write(self):
  class Editor:
   pass
  editor=Editor();editor._review_queue=self.queue;editor._review_queue_index=0;editor._review_completed_indices=set();editor._review_active_ids={18,19,20};editor._review_swap_first=None;editor._review_undo=None;editor.review_mode=True;editor.review_status=_Status();editor._render_signature=None
  editor._load_current_landmark_state=lambda:type("State",(),{"complete":True,"unresolved_ids":set()})()
  editor.mark_checked=lambda:None;editor._refresh_visible_photo_rows=lambda:None;opened=[];editor._open_review_queue_item=lambda index:opened.append(index)
  ReadyEditorV15.finish_review(editor)
  self.assertEqual(editor._review_completed_indices,{0});self.assertEqual(opened,[1])

 def test_successful_scan_atomically_replaces_stale_warning_images(self):
  class Button:
   def config(self, **_kwargs): pass
  class Editor:
   pass
  editor=Editor();editor._review_scan_worker=True;editor.check_landmarks_button=Button();editor._review_queue=[{"image_id":"old"}];editor._review_queue_index=4;editor._review_completed_indices={0};editor._review_active_ids={18};editor._review_pending_image_id="old";editor.review_mode=True;editor.review_status=_Status();editor._render_signature=None;calls=[]
  editor._refresh_visible_photo_rows=lambda:calls.append("photos");editor._refresh_landmark_list=lambda _state:calls.append("table");editor._load_current_landmark_state=lambda:object();editor.render=lambda:calls.append("render");editor._set_review_controls=lambda:calls.append("controls");editor._open_review_queue_item=lambda index:calls.append(("open",index))
  result={"cancelled":False,"queue":({"image_id":"new","landmark_ids":[18],"message":"warning"},),"manual_annotations_available":2,"trusted_reference_identity":False,"early_cross_image":True,"early_annotated_images":2,"statistical_reference":False,"scanned":2,"images_needing_review":1}
  with patch("app.editor_ready_v15.messagebox.showinfo"):
   ReadyEditorV15._commit_review_scan_result(editor,result)
  self.assertEqual(review_warning_image_ids(editor._review_queue,editor._review_completed_indices),{"new"});self.assertTrue(editor.review_mode);self.assertEqual(editor._review_active_ids,set());self.assertIn(("open",0),calls)

 def test_zero_warning_scan_clears_temporary_review_state(self):
  class Button:
   def config(self, **_kwargs): pass
  class Editor:
   pass
  editor=Editor();editor._review_scan_worker=True;editor.check_landmarks_button=Button();editor._review_queue=[{"image_id":"old"}];editor._review_queue_index=0;editor._review_completed_indices=set();editor._review_active_ids={18};editor._review_pending_image_id="old";editor.review_mode=True;editor.review_status=_Status();editor._render_signature=None
  editor._refresh_visible_photo_rows=lambda:None;editor._refresh_landmark_list=lambda _state:None;editor._load_current_landmark_state=lambda:object();editor.render=lambda:None;editor._set_review_controls=lambda:None;editor._open_review_queue_item=lambda _index:None
  result={"cancelled":False,"queue":(),"manual_annotations_available":0,"trusted_reference_identity":False,"early_cross_image":False,"early_annotated_images":0,"statistical_reference":False,"scanned":2,"images_needing_review":0}
  with patch("app.editor_ready_v15.messagebox.showinfo"):
   ReadyEditorV15._commit_review_scan_result(editor,result)
  self.assertEqual(editor._review_queue,[]);self.assertFalse(editor.review_mode);self.assertEqual(editor._review_active_ids,set());self.assertIsNone(editor._review_pending_image_id)

 def test_review_background_layer_does_not_change_qc_status_dot_data(self):
  class Editor:
   pass
  editor=Editor();editor.review_mode=True;editor._review_queue=[{"image_id":"warning"}];editor._review_completed_indices=set()
  row={"image_id":"warning","sample_id":"L","source_relpath":"L/fish.nef","status_color":"green"}
  rendered=ReadyEditorV15._row_data(editor,0,row)
  self.assertEqual(rendered["status"],"green");self.assertTrue(rendered["review_warning"])
 def test_cancelled_scan_keeps_last_successful_warning_set(self):
  class Button:
   def config(self, **_kwargs): pass
  class Editor:
   pass
  editor=Editor();editor._review_scan_worker=True;editor.check_landmarks_button=Button();editor._review_queue=[{"image_id":"old"}];editor._review_active_ids={18};editor.review_status=_Status()
  ReadyEditorV15._commit_review_scan_result(editor,{"cancelled":True})
  self.assertEqual(editor._review_queue,[{"image_id":"old"}]);self.assertEqual(editor._review_active_ids,{18})
 def test_photo_renderer_has_distinct_warning_and_selection_layers(self):
  source=(Path(__file__).parents[1]/"app"/"photo_list.py").read_text(encoding="utf8")
  self.assertIn('fill="#fde8e8"',source);self.assertIn('outline="#2563eb"',source)
  self.assertIn('row.get("review_warning")',source)

 def test_controls_use_issue_words_and_table_has_warning_tag(self):
  source=(Path(__file__).parents[1]/"app"/"editor_ready_v15.py").read_text(encoding="utf8")
  self.assertIn('text="Previous Issue"',source);self.assertIn('text="Next Issue"',source)
  self.assertIn('tag_configure("review_warning",background="#fde8e8")',source)
  self.assertIn('self.images_box.selection_set(visible);self.images_box.see(visible)',source)

if __name__=="__main__":
 unittest.main()