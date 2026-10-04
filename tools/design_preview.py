"""Run the real UI against isolated, explicitly synthetic review projects."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
PREVIEW_ROOT = REPO_ROOT / ".design-preview"


def build_preview_projects(root: Path):
    """Create fixtures through existing project APIs; never copy user projects."""
    from PIL import Image, ImageDraw
    from app.project_storage import Project
    from app.crop_workflow import apply_reviewed_crop
    from app.xray_project import XRayProject
    from app.xray_schema import bundled_scheme
    from app.xray_crop import crop_from_geometry

    source=root/"synthetic-source";source.mkdir(parents=True,exist_ok=True)
    destination=root/"projects";destination.mkdir(exist_ok=True)
    image=Image.new("L",(1200,600),25);draw=ImageDraw.Draw(image)
    for y in (175,415):
        draw.ellipse((90,y-50,200,y+50),fill=200)
        for x in range(200,1040,35):
            draw.rounded_rectangle((x,y-10,x+25,y+10),radius=4,fill=200)
            draw.line((x+10,y-10,x+30,y-65),fill=140,width=4)
            draw.line((x+10,y+10,x+25,y+60),fill=140,width=4)
        draw.line((1040,y,1110,y-60),fill=150,width=5)
        draw.line((1040,y,1110,y+60),fill=150,width=5)
    draw.text((12,12),"SYNTHETIC DESIGN PREVIEW - NOT SCIENTIFIC DATA",fill=200)
    for i in range(1,5):
        path=source/f"Plate_{i:02d}.png"
        if not path.exists():image.save(path)

    xray_path=destination/"Design-preview-Xray"
    if xray_path.exists():xray=XRayProject(xray_path)
    else:
        xray=XRayProject.create(xray_path.name,source,destination,bundled_scheme("phoxinus_vertebral_counts"))
        for row in xray.source_images():
            for y in (175,415):
                xray.add_manual_specimen(row["image_id"],crop_from_geometry(600,y,1120,175,0,image.size,algorithm="manual"))
            xray.confirm_plate(row["image_id"])
        # This seeds a recorded draft through the usual API. No model is trained
        # or downloaded; the name explicitly identifies the synthetic fixture.
        xray.seed_structure_predictions(xray.specimens()[0]["specimen_id"],[
            {"structure_id":"vertebra","x":x/25,"y":.5,"score":.9} for x in range(3,23)
        ]+[
            {"structure_id":"first_caudal","x":.55,"y":.5},
            {"structure_id":"last_predorsal","x":.35,"y":.5},
            {"structure_id":"preanal_pterygiophore","x":.6,"y":.65},
        ],"Synthetic-preview-v001")

    schema=root/"schema.csv"
    if not schema.exists():schema.write_text("id,abbr,name,role\n1,A,Anterior,BOTH\n2,B,Middle,BOTH\n3,C,Posterior,BOTH\n",encoding="utf-8")
    core_path=destination/"Design-preview-Landmarks"
    if core_path.exists():core=Project.open(core_path)
    else:
        core=Project.create(core_path.name,source,destination,schema,source_layout="direct")
        for row in core.catalog_rows():
            apply_reviewed_crop(core,row["image_id"],image.convert("RGB"),(0,0,1200,600),0,
                core.cache_root/"standardized"/f"{row['image_id']}.png",core.image_path(row["image_id"]))
            for landmark_id,x in ((1,140),(2,600),(3,1050)):
                core.save_landmark(row["image_id"],landmark_id,x,175,"present")
    return core,xray


def choose_module():
    import tkinter as tk
    from tkinter import ttk
    from app.ui.design import apply_styles
    root=tk.Tk();root.title("MorphoLabel — design preview");root.resizable(False,False)
    apply_styles(root,ttk.Style(root));frame=ttk.Frame(root,padding=24);frame.pack()
    ttk.Label(frame,text="Choose a preview module",style="PageTitle.TLabel").pack(anchor="w")
    ttk.Label(frame,text="Artificial images and isolated projects. Your research projects are not opened.",wraplength=440).pack(anchor="w",pady=(8,16))
    selection=[]
    def select(module):selection.append(module);root.destroy()
    actions=ttk.Frame(frame);actions.pack(fill="x")
    ttk.Button(actions,text="Landmarks",command=lambda:select("landmarks"),style="Primary.TButton").pack(side="left",padx=(0,8))
    ttk.Button(actions,text="X-ray traits",command=lambda:select("xray"),style="Primary.TButton").pack(side="left")
    root.mainloop()
    return selection[0] if selection else None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module",choices=("landmarks","xray"))
    args=parser.parse_args(argv)
    sys.path.insert(0,str(REPO_ROOT))
    from tools.source_launcher import resolve_source_python, _clean_environment
    python=resolve_source_python()
    if python.resolve()!=Path(sys.executable).resolve():
        return subprocess.call([str(python),"-E","-B",str(Path(__file__).resolve()),*sys.argv[1:]],cwd=REPO_ROOT,env=_clean_environment())
    # Isolate last-project preferences, diagnostics and display settings too.
    # Profile variables are changed only in this preview process.
    state=PREVIEW_ROOT/"state";state.mkdir(parents=True,exist_ok=True)
    os.environ["LOCALAPPDATA"]=str(state);os.environ["APPDATA"]=str(state)
    from tools.canonical_exec import print_provenance
    print_provenance()
    module=args.module or choose_module()
    if module is None:return 0
    core,xray=build_preview_projects(PREVIEW_ROOT)
    from app.ui.shell import ProductionShell
    shell=ProductionShell()
    if module=="landmarks":
        from app.ui.context import UIContext
        shell.module_key="landmarks";shell.context=UIContext(core,section="landmarks")
        shell.context.refresh(force=True);shell.render()
    else:
        from app.modules.xray_counts import XRayCountsRuntime
        runtime=XRayCountsRuntime();runtime.project=xray;runtime.stage="structures"
        shell.module_key="xray_counts";shell._active_module_runtime=runtime
        shell._clear();runtime.render(shell._module_host())
    shell.title("MorphoLabel — DESIGN PREVIEW · synthetic data")
    shell.mainloop()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
