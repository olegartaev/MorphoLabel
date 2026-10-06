import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.ai_component import AIComponentError, active_record_path, component_runtime_candidates, install_component_archive

ROOT=Path(__file__).resolve().parents[1]

class AIComponentContractTests(unittest.TestCase):
    def test_build_spec_is_pinned_to_verified_upstream_compatibility_family(self):
        spec=json.loads((ROOT/"ai_runtime"/"windows-cu121-component.json").read_text(encoding="utf-8"))
        self.assertEqual("1.0.0-rc.1",spec["component_version"])
        self.assertEqual("3.11.9",spec["python"]["version"])
        self.assertEqual("2.1.0",spec["packages"]["torch"])
        self.assertEqual("0.16.0",spec["packages"]["torchvision"])
        self.assertEqual("2.1.0",spec["packages"]["mmcv"])
        self.assertEqual("1.3.2",spec["packages"]["mmpose"])
        self.assertEqual("3.2.0",spec["packages"]["mmdet"])
        self.assertEqual("1.26.4",spec["packages"]["numpy"])
        self.assertEqual("4.10.0.84",spec["packages"]["opencv_python"])
        self.assertEqual("5408bc76f5b848cf925a0d1857899011d8c5b497",spec["mmpose_source"]["commit"])
        self.assertEqual("https://github.com/open-mmlab/mmpose.git",spec["mmpose_source"]["repo_url"])
        self.assertIn("rtmpose-m_simcc-ap10k",spec["bootstrap"]["checkpoint_url"])
        self.assertEqual("896e3665d849ef7eb9b6ec0995955796cc9810f024fa0aa0bdc18acb0d68bf52",spec["bootstrap"]["checkpoint_sha256"])

    def test_workflow_builds_real_component_and_uploads_zip(self):
        text=(ROOT/".github"/"workflows"/"ai-component.yml").read_text(encoding="utf-8")
        self.assertIn("build_ai_component.py",text)
        self.assertIn("MorphoLabel-AI-Windows-x64-",text)
        self.assertIn("AI_BUILD_INFO.json",text)
        self.assertIn("MorphoLabel-AI-Windows-x64.json",text)
        self.assertIn("build_ai_release_assets.py",text)
        self.assertIn("release-assets",text)
        self.assertIn("2147483648",text)
        self.assertIn("Reclaim smoke space and build split public delivery assets",text)
        self.assertIn("Remove-Item -Recurse -Force build\\ai-component\\runtime",text)
        self.assertIn("MorphoLabel-AI-Windows-x64-*.zip | Remove-Item -Force",text)
        self.assertIn("Attach managed AI assets for tags",text)
        self.assertNotIn("gh release upload \"$env:GITHUB_REF_NAME\" $zip.FullName",text)
        self.assertIn("build_ai_notices.py", (ROOT/"tools"/"build_ai_component.py").read_text(encoding="utf-8"))
        self.assertIn("Managed install and bootstrap smoke",text)
        self.assertIn("MANAGED_AI_INSTALL_PASS",text)
        self.assertIn('$managedPython = Join-Path "$env:LOCALAPPDATA\\MorphoLabel\\components\\ai\\$($active.version)" "python.exe"',text)
        self.assertIn("& $managedPython -m app --ai-self-test",text)
        self.assertNotIn("$hostPython",text)
        smoke=text[text.index("- name: End-to-end managed inference and training smoke"):text.index("- name: Reclaim smoke space",text.index("- name: End-to-end managed inference and training smoke"))]
        self.assertNotIn("pip install -r requirements.txt",smoke)
        builder=(ROOT/"tools"/"build_ai_component.py").read_text(encoding="utf-8")
        self.assertIn("--no-deps",builder)
        self.assertIn("constraints.txt",builder)
        self.assertIn("BOOTSTRAP_CONFIG_PASS",builder)
        self.assertIn('"fetch", "--depth", "1"',builder)
        self.assertIn('"checkout", "--detach", "FETCH_HEAD"',builder)
        self.assertIn('shutil.copytree(source_tmp / "configs"',builder)
        self.assertIn('(vendor / "tools").mkdir(parents=True)',builder)
        self.assertIn('shutil.copy2(source_tmp / "tools" / "train.py"',builder)
        self.assertNotIn('"ls-files", "-z"',builder)
        self.assertNotIn("shutil.rmtree(git_dir)",builder)
        self.assertIn("mmdet.__version__",builder)
        self.assertIn("THIRD_PARTY_NOTICES.txt",builder)
        self.assertIn("MODEL_PROVENANCE.txt",builder)
        self.assertIn("checkpoint_sha256 = sha256(checkpoint)",builder)
        self.assertNotIn("checkpoint_sha256 = checkpoint_sha256",builder)
        self.assertIn("checkpoint.unlink()",builder)
        self.assertIn('"bootstrap_checkpoint_url"',builder)
        self.assertIn('"installed_bytes": runtime_bytes',builder)
        self.assertIn('"installed_file_count": len(runtime_files)',builder)
        self.assertIn("BOOTSTRAP_INFERENCE_PASS",builder)
        self.assertIn('"device": "cpu"',builder)
        self.assertIn('list(range(1, 18))',builder)
        self.assertIn('run(["tar", "-a", "-c", "-f", archive',builder)
        self.assertNotIn("shutil.make_archive",builder)

    def test_archive_install_is_atomic_and_active_runtime_is_first_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);component=root/"payload"
            (component/"vendor"/"mmpose"/"tools").mkdir(parents=True)
            (component/"vendor"/"mmpose"/"tools"/"train.py").write_text("",encoding="utf-8")
            (component/"vendor"/"mmpose"/"configs").mkdir(parents=True)
            (component/"vendor"/"mmpose"/"configs"/"bootstrap.py").write_text("",encoding="utf-8")
            (component/"assets").mkdir()
            (component/"assets"/"bootstrap.pth").write_bytes(b"weights")
            (component/"python.exe").write_bytes(b"python")
            import hashlib
            manifest={"component_format":1,"component_version":"1.0.0-test","platform":"windows-x64",
                "python_relative_path":"python.exe","bootstrap_config":"vendor/mmpose/configs/bootstrap.py",
                "bootstrap_checkpoint":"assets/bootstrap.pth",
                "bootstrap_checkpoint_sha256":hashlib.sha256(b"weights").hexdigest(),
                "bootstrap_checkpoint_url":"https://download.openmmlab.com/test/bootstrap.pth",
                "mmpose_source":"vendor/mmpose"}
            (component/"component.json").write_text(json.dumps(manifest),encoding="utf-8")
            archive=root/"component.zip"
            with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
                for path in component.rglob("*"):
                    if path.is_file():z.write(path,path.relative_to(component).as_posix())
            with patch.dict("os.environ",{"LOCALAPPDATA":str(root/"local")},clear=False):
                runtime=install_component_archive(archive,run_runtime_check=False)
                self.assertTrue(runtime.is_file())
                self.assertEqual(runtime,component_runtime_candidates()[0])
                self.assertEqual("1.0.0-test",json.loads(active_record_path().read_text(encoding="utf-8"))["version"])


    def test_managed_component_root_is_manifest_based_not_scripts_layout(self):
        from app.ai_component import component_root_for_runtime
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"component"
            root.mkdir()
            runtime=root/"python.exe"
            runtime.write_bytes(b"python")
            (root/"component.json").write_text(json.dumps({
                "component_format":1,
                "component_version":"1.0.0-test",
                "platform":"windows-x64",
                "python_relative_path":"python.exe",
            }),encoding="utf-8")
            self.assertEqual(root.resolve(),component_root_for_runtime(runtime))

    def test_runner_uses_component_manifest_to_find_runtime_root(self):
        runner=(ROOT/"ai_runtime"/"rtmpose_runner.py").read_text(encoding="utf-8")
        self.assertIn('candidate/"component.json"',runner)
        self.assertIn('runtime_root=_managed_component_root() or executable.parent.parent',runner)

    def test_windows_root_directory_entry_is_ignored_during_safe_extract(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);component=root/"payload"
            (component/"vendor"/"mmpose"/"tools").mkdir(parents=True)
            (component/"vendor"/"mmpose"/"tools"/"train.py").write_text("",encoding="utf-8")
            (component/"vendor"/"mmpose"/"configs").mkdir(parents=True)
            (component/"vendor"/"mmpose"/"configs"/"bootstrap.py").write_text("",encoding="utf-8")
            (component/"python.exe").write_bytes(b"python")
            import hashlib
            manifest={"component_format":1,"component_version":"1.0.0-root-entry","platform":"windows-x64",
                "python_relative_path":"python.exe","bootstrap_config":"vendor/mmpose/configs/bootstrap.py",
                "bootstrap_checkpoint":"assets/bootstrap.pth",
                "bootstrap_checkpoint_sha256":hashlib.sha256(b"weights").hexdigest(),
                "bootstrap_checkpoint_url":"https://download.openmmlab.com/test/bootstrap.pth",
                "mmpose_source":"vendor/mmpose"}
            (component/"assets").mkdir()
            (component/"assets"/"bootstrap.pth").write_bytes(b"weights")
            (component/"component.json").write_text(json.dumps(manifest),encoding="utf-8")
            archive=root/"component.zip"
            with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
                z.writestr("./",b"")
                for path in component.rglob("*"):
                    if path.is_file():
                        z.write(path,"./"+path.relative_to(component).as_posix())
            with patch.dict("os.environ",{"LOCALAPPDATA":str(root/"local")},clear=False):
                runtime=install_component_archive(archive,run_runtime_check=False)
                self.assertTrue(runtime.is_file())
                self.assertEqual("1.0.0-root-entry",json.loads(active_record_path().read_text(encoding="utf-8"))["version"])

    def test_unsafe_archive_is_rejected_without_component(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);archive=root/"bad.zip"
            with zipfile.ZipFile(archive,"w") as z:z.writestr("../outside.txt","bad")
            with patch.dict("os.environ",{"LOCALAPPDATA":str(root/"local")},clear=False):
                with self.assertRaises(AIComponentError):install_component_archive(archive,run_runtime_check=False)
                self.assertFalse((root/"outside.txt").exists())

if __name__=="__main__":
    unittest.main()
