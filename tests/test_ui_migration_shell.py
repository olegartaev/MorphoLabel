from app.ui.section_registry import visible_sections
def test_crop_visibility():
 assert [s.key for s in visible_sections(False)] == ["project","landmarks","measurements","export"]
 assert "crop" in [s.key for s in visible_sections(True)]