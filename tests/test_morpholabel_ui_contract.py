import base64
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.identity import (
    APP_NAME, APP_VERSION, APP_STATUS, CONTACT_EMAIL, PUBLIC_REPOSITORY,
    LICENSE_NAME, ICON_PNG_BASE64, ICON_SOURCE_SHA256,
)
from app import __version__ as PACKAGE_VERSION
from app.project_storage import Project
from app.ui.context import UIContext
from app.ui.measurements_section import MeasurementsSection
from app.ui.shell import ProductionShell
from app.landmark_suspicious_review import start as start_suspicious_review, current as current_suspicious
from app.landmark_ai_review import create_review_session_for_ids, activate_review_session, active_review_session


class _Choice:
    def __init__(self): self.value=""
    def set(self,value): self.value=value
    def get(self): return self.value


class _Preview:
    def __init__(self): self.loads=0
    def load_current(self): self.loads+=1


class _RowsProject:
    def __init__(self,rows): self.rows=list(rows)
    def catalog_rows(self): return [dict(row) for row in self.rows]
    def permanent_test_image_ids(self): return frozenset()


class MorphoLabelUIContractTests(unittest.TestCase):
    def test_package_and_identity_versions_are_consistent(self):
        self.assertEqual("0.5.0-beta.1", PACKAGE_VERSION)
        self.assertEqual(PACKAGE_VERSION, APP_VERSION)
        root=Path(__file__).parents[1]
        self.assertIn(f"Development beta · {PACKAGE_VERSION}",(root/"README.md").read_text(encoding="utf-8"))
        self.assertIn(f'version: "{PACKAGE_VERSION}"',(root/"CITATION.cff").read_text(encoding="utf-8"))

    def test_identity_is_development_morpholabel_with_supplied_png(self):
        self.assertEqual("MorphoLabel",APP_NAME)
        self.assertEqual("0.5.0-beta.1",APP_VERSION)
        self.assertEqual("Development beta",APP_STATUS)
        self.assertEqual("morpholabel@olegartaev.com",CONTACT_EMAIL)
        self.assertEqual("https://github.com/olegartaev/MorphoLabel",PUBLIC_REPOSITORY)
        self.assertEqual("Apache-2.0",LICENSE_NAME)
        icon=base64.b64decode(ICON_PNG_BASE64)
        self.assertTrue(icon.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(ICON_SOURCE_SHA256,hashlib.sha256(icon).hexdigest())
        self.assertEqual("08a59d18aa7a4198a4731040a4a6a778528762af485cea3acb8f5ec93e5a9c7b",ICON_SOURCE_SHA256)

    def test_repository_contains_open_source_license_notice_and_citation(self):
        root=Path(__file__).parents[1]
        license_text=(root/"LICENSE").read_text(encoding="utf-8")
        notice=(root/"NOTICE").read_text(encoding="utf-8")
        citation=(root/"CITATION.cff").read_text(encoding="utf-8")
        self.assertIn("Apache License",license_text)
        self.assertIn("Version 2.0",license_text)
        self.assertIn("Copyright 2026 Oleg Artaev",notice)
        self.assertIn("morpholabel@olegartaev.com",notice)
        self.assertIn('title: "MorphoLabel"',citation)
        self.assertIn('license: "Apache-2.0"',citation)

    def test_context_refresh_preserves_selected_image_id_when_row_order_changes(self):
        first={"image_id":"first"};second={"image_id":"second"}
        project=_RowsProject([first,second])
        context=UIContext(project=project,selected=1,rows=[dict(first),dict(second)],_catalog_valid=True)
        project.rows=[second,first]
        context.refresh(force=True)
        self.assertEqual("second",context.current()["image_id"])
        self.assertEqual(0,context.selected)

    def test_measurements_preview_sync_does_not_replace_shared_specimen(self):
        first={"image_id":"first","sample_id":"S","original_name":"one.jpg"}
        second={"image_id":"second","sample_id":"S","original_name":"two.jpg"}
        current=[second]
        section=MeasurementsSection.__new__(MeasurementsSection)
        section.context=SimpleNamespace(current=lambda:current[0])
        section.preview_images=[first,second]
        section.preview_choice=_Choice()
        section.preview=_Preview()
        MeasurementsSection._sync_preview_to_current(section)
        self.assertIn("two.jpg",section.preview_choice.value)
        self.assertEqual(1,section.preview.loads)
        self.assertEqual("second",current[0]["image_id"])

    def test_excluding_current_complex_qc_image_advances_to_next_queue_member(self):
        root=Path(tempfile.mkdtemp())
        try:
            source=root/"source";source.mkdir()
            (source/"a.jpg").write_bytes(b"a");(source/"b.jpg").write_bytes(b"b")
            schema=root/"schema.csv";schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n",encoding="utf-8")
            project=Project.create("p",source,root,schema,source_layout="direct")
            ids=[row["image_id"] for row in project.catalog_rows()]
            start_suspicious_review(project,[
                {"image_id":ids[0],"kind":"complex_qc","message":"first"},
                {"image_id":ids[1],"kind":"complex_qc","message":"second"},
            ],source="Complex QC")
            context=UIContext(project=project,section="landmarks")
            context.refresh(force=True);context.select_image(ids[0])
            project.exclude_image(ids[0],"User excluded")
            shell=SimpleNamespace(context=context,current_view=None,photo_panel=None,render=lambda:None)
            ProductionShell._photo_exclusion_changed(shell,ids[0])
            self.assertTrue(project.image_exclusion(ids[0])["excluded"])
            self.assertEqual(ids[1],context.current()["image_id"])
            self.assertEqual(ids[1],current_suspicious(project)["image_id"])
        finally:
            shutil.rmtree(root,ignore_errors=True)

    def test_excluding_current_ai_review_image_removes_it_from_session(self):
        root=Path(tempfile.mkdtemp())
        try:
            source=root/"source";source.mkdir()
            for name in ("a.jpg","b.jpg","c.jpg"):(source/name).write_bytes(name.encode())
            schema=root/"schema.csv";schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n",encoding="utf-8")
            project=Project.create("p",source,root,schema,source_layout="direct")
            ids=[row["image_id"] for row in project.catalog_rows()]
            session=create_review_session_for_ids(project,"review-test",ids,kind="review_worst")
            activate_review_session(project,session["batch_id"])
            context=UIContext(project=project,section="landmarks");context.refresh(force=True);context.select_image(ids[0])
            project.exclude_image(ids[0],"User excluded")
            shell=SimpleNamespace(context=context,current_view=None,photo_panel=None,render=lambda:None)
            ProductionShell._photo_exclusion_changed(shell,ids[0])
            active=active_review_session(project)
            self.assertNotIn(ids[0],active["image_ids"])
            self.assertEqual(ids[1],context.current()["image_id"])
        finally:
            shutil.rmtree(root,ignore_errors=True)

    def test_section_change_contract_preserves_current_image_id(self):
        source=Path(__file__).parents[1]/"app"/"ui"/"shell.py"
        text=source.read_text(encoding="utf-8")
        self.assertIn('image_id=(self.context.current() or {}).get("image_id")',text)
        self.assertIn('if image_id:self.context.select_image(image_id)',text)

    def test_launcher_isolated_and_targets_current_morpholabel_shell(self):
        root=Path(__file__).parents[1]
        start=(root/"START_APP.cmd").read_text(encoding="utf-8")
        canonical=(root/"RUN_CANONICAL.cmd").read_text(encoding="utf-8")
        self.assertIn('RUN_CANONICAL.cmd" shell',start)
        self.assertIn('python -E -B',canonical)
        self.assertNotIn('python -I',canonical)
        self.assertIn('set "PYTHONPATH="',canonical)
        self.assertIn('set "PYTHONHOME="',canonical)
        self.assertIn('tools\\canonical_exec.py',canonical)
        self.assertNotIn('app\\gui.py',canonical)

    def test_provenance_checks_current_sources_without_isolating_site_packages(self):
        from tools.canonical_exec import verify_provenance
        root=Path(__file__).parents[1].resolve()
        provenance=verify_provenance()
        self.assertEqual(root,Path(provenance["CANONICAL_REPO"]).resolve())
        for key in ("APP_SOURCE","SHELL_SOURCE","TRAINING_WORKFLOW_SOURCE","BOOTSTRAP_SOURCE"):
            Path(provenance[key]).resolve().relative_to(root)
        self.assertEqual(Path(__import__("sys").executable).resolve(),Path(provenance["HOST_PYTHON"]).resolve())

    def test_icons_are_never_upscaled_and_about_has_only_close_action(self):
        root=Path(__file__).parents[1]
        identity=(root/"app"/"identity.py").read_text(encoding="utf-8")
        hub=(root/"app"/"ui"/"module_hub.py").read_text(encoding="utf-8")
        shell=(root/"app"/"ui"/"shell.py").read_text(encoding="utf-8")
        self.assertNotIn('.zoom(',identity)
        self.assertNotIn('zoom=',hub)
        self.assertNotIn('zoom=',shell)
        start=shell.index('def show_about(self):')
        end=shell.index('def show_hardware(self):',start)
        about=shell[start:end]
        self.assertIn('"Close"',about)
        self.assertNotIn('control_button(actions,"GitHub"',about)
        self.assertNotIn('control_button(actions,"Email"',about)

    def test_package_entrypoint_uses_same_morpholabel_shell(self):
        root=Path(__file__).parents[1]
        entry=(root/"app"/"__main__.py").read_text(encoding="utf-8")
        canonical=(root/"tools"/"canonical_exec.py").read_text(encoding="utf-8")
        self.assertIn("from .ui.shell import run",entry)
        self.assertNotIn("from .gui import run",entry)
        self.assertIn("MorphoLabel",canonical)

    def test_current_public_ui_has_one_supported_root_and_no_legacy_gui_imports(self):
        root = Path(__file__).parents[1]
        shell = (root / "app" / "ui" / "shell.py").read_text(encoding="utf-8")
        hub = (root / "app" / "ui" / "module_hub.py").read_text(encoding="utf-8")
        self.assertIn("class ProductionShell", shell)
        self.assertIn("ModuleHub", shell)
        self.assertIn("ModuleHub(self,", shell)
        self.assertIn("class ModuleHub", hub)
        from app.extensions.builtins import module_registry
        self.assertEqual("Landmarks & measurements", module_registry().get("landmarks").display_name)
        self.assertIn("spec.display_name", hub)
        legacy = ("app.gui", "app.gui_full", "app.project_gui", "app.editor_ready", "app.operator_v")
        for path in (root / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name in legacy:
                self.assertNotIn(f"from {name} import", text, path.name)
                self.assertNotIn(f"import {name}", text, path.name)

    def test_user_facing_core_files_no_longer_brand_the_app_as_simm(self):
        root=Path(__file__).parents[1]
        for relative in (
            "app/identity.py",
            "app/ui/module_hub.py",
            "app/ui/project_section.py",
        ):
            text=(root/relative).read_text(encoding="utf-8")
            self.assertNotIn("Simple Intelligent Morpho Mapper",text)
            self.assertNotIn("About SIMM",text)

    def test_source_contract_starts_on_module_hub_and_labels_landmark_actions(self):
        root=Path(__file__).parents[1]
        shell=(root/"app"/"ui"/"shell.py").read_text(encoding="utf-8")
        hub=(root/"app"/"ui"/"module_hub.py").read_text(encoding="utf-8")
        landmarks=(root/"app"/"ui"/"landmarks_section.py").read_text(encoding="utf-8")
        self.assertIn('self.module_key="landmarks" if project is not None else None',shell)
        self.assertNotIn('elif remembered_path:',shell)
        from app.extensions.builtins import module_registry
        self.assertEqual("Landmarks & measurements",module_registry().get("landmarks").display_name)
        self.assertIn("spec.display_name",hub)
        self.assertIn('"Open module"',hub)
        self.assertIn("Landmark actions:",landmarks)


if __name__=="__main__":
    unittest.main()
