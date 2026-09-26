from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ORIGINALS=ROOT/"orig_photos";WORK=ROOT/"work";REPORTS=ROOT/"reports";PROFILES=ROOT/"profiles"
def require_relative(path:Path)->str:
 path=Path(path).resolve()
 try:return path.relative_to(ROOT.resolve()).as_posix()
 except ValueError:
  from .project_runtime import active_project
  project=active_project()
  if project:
   try:return (Path("orig_photos")/path.relative_to(project.source_root.resolve())).as_posix()
   except ValueError:return path.relative_to(project.root.resolve()).as_posix()
  raise
def sample_work(sample_id:str)->Path:
 from .project_runtime import active_project
 project=active_project()
 return project.cache_root/sample_id if project else WORK/sample_id

