"""Consistent analysis export bundles created from one SQLite snapshot."""
from __future__ import annotations
import csv, hashlib, json, math, os, re, shutil, sqlite3, tempfile, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from .export_formats import (_selected_complete_coordinates, _selected_tps_coordinates, available_groups,
    export_landmark_csv_long, export_landmark_tps, export_landmark_wide, export_morphoj_text, group_label)
from .landmark_state import load_current_landmark_state
from .measurements import active_measurements, export_measurements, measurement_definitions_csv, values_for_image
from .project_storage import Project
from .version import __version__

SCOPE_VERIFIED = "verified_only"
SCOPE_ALL = "all"

def _sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def _project_definition_files(project, destination_root=None):
    destination_root = Path(destination_root) if destination_root is not None else Path(project.root)
    return {
        Path(project.config_path): destination_root / "project.yaml",
        Path(project.schema_path): destination_root / "landmark_schema.csv",
        Path(project.root) / "measurement_schema.csv": destination_root / "measurement_schema.csv",
    }

def _definition_fingerprints(files):
    return {source: (_sha256(source) if source.is_file() else None) for source in files}

def _copy_consistent_project_definitions(project, root, before):
    files = _project_definition_files(project, root)
    for source, target in files.items():
        if source.is_file():
            shutil.copy2(source, target)
        elif source.name == "measurement_schema.csv":
            target.write_text("Use,Abbr,Name,Point1,Point2,Point1Abbr,Point2Abbr\n", encoding="utf-8")
    after = _definition_fingerprints(files)
    copied = {source: (_sha256(target) if target.is_file() else None)
              for source, target in files.items() if before[source] is not None}
    copied_expected = {source: digest for source, digest in before.items() if digest is not None}
    if after != before or copied != copied_expected:
        raise RuntimeError(
            "Project schema, configuration, or measurement definitions changed while preparing the export snapshot; retry the export."
        )

def _csv(path, fields, rows):
    with Path(path).open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(rows)

class _ScopedProject:
    def __init__(self, project, rows): self._project=project; self._rows=list(rows)
    def catalog_rows(self): return [dict(r) for r in self._rows]
    def crop_record(self,image_id):
        crop=self._project.crop_record(image_id)
        if crop and crop.get("transform_json"):
            return crop
        # The production measurement exporter normally opens a developed cache
        # only to infer image dimensions for this no-op identity transform.
        # The disposable snapshot intentionally contains no caches or photos;
        # this exact identity mapping keeps its numerical output unchanged.
        from .transforms import Transform
        width=height=1
        for row in self._rows:
            if row["image_id"]==image_id:
                width=max(1,int(row.get("width") or 1)); height=max(1,int(row.get("height") or 1)); break
        transform=Transform(width,height,0.0,width/2,height/2,0,0,width,height)
        return {"transform_json":transform.__dict__}
    def __getattr__(self,name): return getattr(self._project,name)

def _verified(project, image_id):
    return bool(load_current_landmark_state(project,image_id).human_verified)

def _safe_path(root, relative):
    path=(root/str(relative)).resolve()
    try: path.relative_to(root.resolve())
    except ValueError: return None
    return path

def _hash_status(row, root, requested):
    stored=str(row.get("source_sha256") or "").strip().lower()
    if not requested: return ("stored_hash_available_not_reverified" if stored else "not_verified",stored)
    path=_safe_path(root,row.get("relative_path") or "")
    if path is None: return "invalid_relative_path",stored
    if not path.is_file(): return "source_unavailable",stored
    digest=_sha256(path)
    if stored: return ("verified_match" if digest==stored else "verified_mismatch"),digest
    return "verified_at_export_time",digest

def _point_reason(state,ident):
    if ident in state.explicitly_missing_ids:return "explicitly_missing"
    if ident in state.unresolved_ids:return "unresolved"
    point=state.points_by_id.get(ident)
    if not point:return "absent"
    try:x=float(point.get("x_standardized"));y=float(point.get("y_standardized"))
    except (TypeError,ValueError):return "coordinate_missing"
    return "" if math.isfinite(x) and math.isfinite(y) else "non_finite_coordinate"

def _reason(project,row,schema):
    state=load_current_landmark_state(project,row["image_id"])
    groups={name:[] for name in ("explicitly_missing","unresolved","absent","coordinate_missing","non_finite_coordinate")}
    for item in schema:
        ident=int(item["id"]);why=_point_reason(state,ident)
        if why:groups[why].append(ident)
    return ";".join(f"{key}_landmark_ids="+",".join(map(str,ids)) for key,ids in groups.items() if ids)

def _group_specs(project):
    schema=list(project.schema);specs=[{"key":"ALL","label":"ALL","schema":schema,"token":"ALL"}]
    keys={"all"};tokens={"all"}
    for label in available_groups(project):
        key=label
        if key.casefold() in keys:key=f"group:{label}"
        base=key;suffix=2
        while key.casefold() in keys:key=f"{base}:{suffix}";suffix+=1
        keys.add(key.casefold())
        if label in {"GM","CLASSICAL"}:token=label
        else:
            normalized=unicodedata.normalize("NFKD",str(label)).encode("ascii","ignore").decode("ascii")
            token=re.sub(r"[^A-Za-z0-9_-]+","_",normalized).strip("_-.") or "group"
        base=token;suffix=2
        while token.casefold() in tokens:token=f"{base}__{suffix}";suffix+=1
        tokens.add(token.casefold())
        specs.append({"key":key,"label":label,"schema":[item for item in schema if group_label(item)==label],"token":token})
    return specs

def _group_filenames(spec):
    if spec["key"]=="ALL":return {"TPS":"landmarks_all.tps","wide_csv":"landmarks_wide_ALL.csv","MorphoJ":"landmarks_MorphoJ_ALL.txt"}
    token=spec["token"]
    return {"TPS":f"landmarks_{token}.tps","wide_csv":f"landmarks_wide_{token}.csv","MorphoJ":f"landmarks_MorphoJ_{token}.txt"}

def _omissions(project,all_rows,selected,group_specs):
    selected_ids={r["image_id"] for r in selected};out=[];missing=[];definitions=active_measurements(project)
    def omission(row,fmt,group,reason,record_type="specimen",landmark_id="",measurement=""):
        out.append(dict(image_id=row["image_id"],specimen_id=row.get("specimen_id") or row["image_id"],output_format=fmt,group=group,record_type=record_type,landmark_id=landmark_id,measurement=measurement,reason=reason))
    def missing_value(row,fmt,group,ident,abbr,reason,record_type="landmark",measurement=""):
        missing.append(dict(image_id=row["image_id"],specimen_id=row.get("specimen_id") or row["image_id"],output_format=fmt,group=group,record_type=record_type,landmark_id=ident,landmark_abbreviation=abbr,measurement=measurement,reason=reason))
    for row in all_rows:
        iid=row["image_id"]
        if row.get("excluded"):
            omission(row,"*","ALL","excluded");continue
        if iid not in selected_ids:
            omission(row,"*","ALL","not_human_verified");continue
        state=load_current_landmark_state(project,iid);saved=project.load_landmarks(iid)
        for spec in group_specs:
            group=spec["key"];schema=spec["schema"]
            tps_included=_selected_tps_coordinates(project,iid,schema) is not None
            if not tps_included:omission(row,"TPS",group,_reason(project,row,schema) or "invalid_or_nonfinite_coordinates")
            if _selected_complete_coordinates(project,iid,schema) is None:
                omission(row,"MorphoJ",group,_reason(project,row,schema) or "invalid_or_nonfinite_coordinates")
            for item in schema:
                ident=int(item["id"]);abbr=str(item.get("abbr") or "");why=_point_reason(state,ident)
                if not why:continue
                if tps_included:missing_value(row,"TPS",group,ident,abbr,why)
                if spec["key"]=="ALL":
                    if ident not in saved:omission(row,"long_csv","ALL",why,"landmark",ident)
                    else:missing_value(row,"long_csv","ALL",ident,abbr,why)
                missing_value(row,"wide_csv",group,ident,abbr,why)
        values,_=values_for_image(project,row,definitions)
        for item in definitions:
            if values.get(item["abbr"])=="NA":
                endpoints=[int(ident) for ident in (item["point1"],item["point2"]) if _point_reason(state,int(ident))]
                if endpoints:
                    statuses=sorted({_point_reason(state,ident) for ident in endpoints})
                    reason="missing_endpoint_landmark_ids="+",".join(map(str,endpoints))+";states="+",".join(statuses)
                else:reason="calibration_unavailable"
                missing_value(row,"measurements","ALL","","",reason,"measurement",item["abbr"])
    return out,missing

def _output_counts(directory):
    result={}
    for p in Path(directory).iterdir():
        if p.suffix.lower()==".tps": result[p.name]=sum(x.startswith("LM=") for x in p.read_text(encoding="utf-8-sig").splitlines())
        elif p.name.startswith("landmarks_MorphoJ_"):
            with p.open(encoding="utf-8-sig",newline="") as f: result[p.name]=max(0,sum(1 for _ in csv.reader(f,delimiter="\t"))-1)
        elif p.suffix.lower()==".csv":
            with p.open(encoding="utf-8-sig",newline="") as f: result[p.name]=sum(1 for _ in csv.DictReader(f))
    return result

def _validate_manifest(path):
    data=json.loads(Path(path).read_text(encoding="utf-8")); root=Path(path).parent
    for name,meta in data["files"].items():
        p=root/name
        if not p.is_file() or p.stat().st_size!=meta["size_bytes"] or _sha256(p)!=meta["sha256"]:
            raise ValueError(f"manifest validation failed for {name}")

def _validate_output_identities(directory, project, selected, group_specs):
    selected_ids=[row["image_id"] for row in selected]
    specimen_ids=[row.get("specimen_id") or row["image_id"] for row in selected]
    for spec in group_specs:
        filename=_group_filenames(spec)["wide_csv"]
        with (directory/filename).open(encoding="utf-8-sig",newline="") as stream:
            ids=[row["specimen_id"] for row in csv.DictReader(stream)]
        if ids!=specimen_ids: raise ValueError(f"{filename} specimen crosswalk does not match scope")
    with (directory/"measurements.csv").open(encoding="utf-8-sig",newline="") as stream:
        measurement_ids=[row["image_id"] for row in csv.DictReader(stream)]
    if measurement_ids!=selected_ids: raise ValueError("measurements.csv image identities do not match scope")
    with (directory/"landmarks_long.csv").open(encoding="utf-8-sig",newline="") as stream:
        long_rows=list(csv.DictReader(stream))
    allowed={int(item["id"]) for item in project.schema}
    expected={(row["image_id"],int(ident)) for row in selected
              for ident in project.load_landmarks(row["image_id"]) if int(ident) in allowed}
    actual=[(row["image_id"],int(row["landmark_id"])) for row in long_rows]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:
        raise ValueError("long CSV point identities do not match saved snapshot landmarks")
    def tps_ids(path):
        lines=path.read_text(encoding="utf-8-sig").splitlines(); result=[]; index=0
        while index<len(lines):
            if not lines[index].startswith("LM="): index+=1; continue
            count=int(lines[index].split("=",1)[1]); index+=1+count; tags={}
            while index<len(lines) and lines[index]:
                key,_,value=lines[index].partition("="); tags[key]=value; index+=1
            if "ID" not in tags: raise ValueError(f"TPS ID missing in {path.name}")
            result.append(tags["ID"]); index+=1
        return result
    from .export_formats import _selected_tps_coordinates, _selected_complete_coordinates
    for spec in group_specs:
        group,schema=spec["key"],spec["schema"]
        expected_tps=[row["image_id"] for row in selected if _selected_tps_coordinates(project,row["image_id"],schema) is not None]
        got=tps_ids(directory/_group_filenames(spec)["TPS"])
        if got!=expected_tps: raise ValueError(f"TPS {group} identities do not match inclusion rules")
        file=directory/_group_filenames(spec)["MorphoJ"]
        with file.open(encoding="utf-8-sig",newline="") as stream: rows=list(csv.reader(stream,delimiter="\t"))
        header=rows[0] if rows else []
        expected_header=["ID"]+[axis+str(item["id"]) for item in schema for axis in ("x","y")]
        if header!=expected_header: raise ValueError(f"MorphoJ {group} coordinate order is invalid")
        expected_morpho=[row["image_id"] for row in selected if _selected_complete_coordinates(project,row["image_id"],schema) is not None]
        actual_morpho=[row[0] for row in rows[1:]]
        if actual_morpho!=expected_morpho: raise ValueError(f"MorphoJ {group} row set does not match omission rules")

def export_analysis_bundle(project,destination,*,scope=SCOPE_VERIFIED,verify_sources=False):
    """Export to a new directory; existing directories are never overwritten."""
    if scope not in {SCOPE_VERIFIED,SCOPE_ALL}: raise ValueError("scope must be verified_only or all")
    destination=Path(destination).resolve()
    if destination.exists(): raise FileExistsError(f"destination exists: {destination}")
    destination.parent.mkdir(parents=True,exist_ok=True)
    source_root=Path(project.source_root)
    stage=Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-",dir=destination.parent))
    scratch=Path(tempfile.mkdtemp(prefix="morpholabel-snapshot-")); published=False
    try:
        definition_files = _project_definition_files(project)
        definition_fingerprints = _definition_fingerprints(definition_files)
        snapdb=scratch/"snapshot.sqlite"
        src=sqlite3.connect(project.path.resolve().as_uri()+"?mode=ro",uri=True,timeout=10)
        src.execute("PRAGMA query_only=ON"); dst=sqlite3.connect(snapdb)
        try: src.backup(dst); dst.commit()
        finally: dst.close(); src.close()
        source_snapshot_hash=_sha256(snapdb)
        root=scratch/"project"; (root/"project_data").mkdir(parents=True)
        _copy_consistent_project_definitions(project, root, definition_fingerprints)
        shutil.copy2(snapdb,root/"project_data"/"project.sqlite")
        cfg=json.loads((root/"project.yaml").read_text(encoding="utf-8")); cfg["source_root"]=str(scratch/"no_source_files")
        (root/"project.yaml").write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        snap=Project.open(root)
        # Project.open may apply schema migrations to this disposable clone.
        # Record the exact post-open SQLite state consumed by all exporters.
        snapshot_hash=_sha256(snap.path)
        all_rows=snap.catalog_rows()
        ids=[r["image_id"] for r in all_rows]; specimen_ids=[r.get("specimen_id") or r["image_id"] for r in all_rows]
        if len(ids)!=len(set(ids)): raise ValueError("duplicate image_id in project snapshot")
        if len(specimen_ids)!=len(set(specimen_ids)): raise ValueError("duplicate specimen_id in project snapshot")
        selected=[r for r in all_rows if not r.get("excluded") and (scope==SCOPE_ALL or _verified(snap,r["image_id"]))]
        view=_ScopedProject(snap,selected)
        group_specs=_group_specs(snap)
        exports=[]
        for spec in group_specs:
            selected_group=() if spec["key"]=="ALL" else (spec["label"],)
            names=_group_filenames(spec)
            exports.extend([
            (names["TPS"],lambda p,g=selected_group:export_landmark_tps(view,groups=g,target=p)),
            (names["wide_csv"],lambda p,g=selected_group:export_landmark_wide(view,groups=g,target=p)),
            (names["MorphoJ"],lambda p,g=selected_group:export_morphoj_text(view,groups=g,target=p)),
            ])
        exports.extend([
            ("landmarks_long.csv",lambda p:export_landmark_csv_long(view,target=p)),
            ("measurements.csv",lambda p:export_measurements(view,target=p)),
        ])
        for name,fn in exports: fn(stage/name)
        _validate_output_identities(stage,view,selected,group_specs)
        omissions,missing_values=_omissions(view,all_rows,selected,group_specs)
        _csv(stage/"omissions.csv",["image_id","specimen_id","output_format","group","record_type","landmark_id","measurement","reason"],omissions)
        _csv(stage/"missing_values.csv",["image_id","specimen_id","output_format","group","record_type","landmark_id","landmark_abbreviation","measurement","reason"],missing_values)
        selected_ids={r["image_id"] for r in selected}; specimens=[]
        for row in all_rows:
            st=load_current_landmark_state(snap,row["image_id"]); draft=snap.annotation_draft(row["image_id"])
            hs,digest=_hash_status(row,source_root,verify_sources)
            specimens.append({
                "specimen_id":row.get("specimen_id") or row["image_id"],"image_id":row["image_id"],
                "locality":row.get("locality") or row.get("sample_id") or "",
                "sample_id":row.get("sample_id") or "","filename":row.get("original_name") or "","source_relative_path":row.get("relative_path") or "",
                "source_hash_status":hs,"source_sha256":digest,
                "excluded":str(bool(row.get("excluded"))).lower(),"human_verified":str(st.human_verified).lower(),
                "draft_status":"draft" if draft else "none","review_status":"verified" if st.human_verified else ("draft" if draft else "pending_review"),
                "selected_for_export":str(row["image_id"] in selected_ids).lower(),"scope":scope,
                "qc_status":"excluded" if row.get("excluded") else st.color,
                "resolved_landmarks":st.resolved_count,"expected_landmarks":st.expected_count,
                "explicit_missing_landmark_ids":";".join(map(str,sorted(st.explicitly_missing_ids))),
                "unresolved_landmark_ids":";".join(map(str,sorted(st.unresolved_ids))),
                "coordinate_system":"standardized_crop_pixels"})
        specimen_fields=list(specimens[0]) if specimens else ["specimen_id","image_id","locality","sample_id","filename","source_relative_path","source_hash_status","source_sha256","excluded","human_verified","draft_status","review_status","selected_for_export","scope","qc_status","resolved_landmarks","expected_landmarks","explicit_missing_landmark_ids","unresolved_landmark_ids","coordinate_system"]
        _csv(stage/"specimens.csv",specimen_fields,specimens)
        transform_fields=["image_id","transform_status","version","original_width","original_height","rotation_degrees","center_x","center_y","crop_left","crop_top","output_width","output_height"]
        transform_rows=[]
        for row in all_rows:
            crop=snap.crop_record(row["image_id"]); t=(crop or {}).get("transform_json")
            transform_rows.append({"image_id":row["image_id"],"transform_status":"stored" if t else "identity_no_crop",
                "version":(t or {}).get("version","identity_v1" if not t else ""),
                **{key:(t or {}).get(key,"") for key in ("original_width","original_height","rotation_degrees","center_x","center_y","crop_left","crop_top","output_width","output_height")}})
        _csv(stage/"transforms.csv",transform_fields,transform_rows)
        _csv(stage/"landmark_definitions.csv",
            ["landmark_id","abbreviation","name","role","category","order","coordinate_frame","coordinate_units"],
            [dict(landmark_id=int(x["id"]),abbreviation=x.get("abbr",""),name=x.get("name",""),role=x.get("role",""),category=x.get("category",""),order=i+1,coordinate_frame="standardized_crop_pixels",coordinate_units="pixel") for i,x in enumerate(snap.schema)])
        (stage/"measurement_definitions.csv").write_text(measurement_definitions_csv(snap),encoding="utf-8",newline="")
        morpho_omitted={spec["key"]:sum(x["output_format"]=="MorphoJ" and x["group"]==spec["key"] for x in omissions) for spec in group_specs}
        summary=(
            "# MorphoLabel analysis export\n\n"
            f"- Scope: {scope}\n- Active specimens: {len(all_rows)}\n- Selected for scope: {len(selected)}\n"
            f"- Verified: {sum(_verified(snap,r['image_id']) for r in selected)}\n"
            f"- Unverified in project: {sum(not _verified(snap,r['image_id']) and not r.get('excluded') for r in all_rows)}\n"
            f"- Drafts: {sum(bool(snap.annotation_draft(r['image_id'])) for r in all_rows)}\n"
            f"- Excluded: {sum(bool(r.get('excluded')) for r in all_rows)}\n"
            f"- MorphoJ omitted by group: {json.dumps(morpho_omitted,sort_keys=True)}\n"
            f"- Omission records: {len(omissions)}\n- Missing-value records: {len(missing_values)}\n\n"
            "The all scope is opt-in and may include unchecked or unfinished records. See omissions.csv and missing_values.csv for per-format completeness details.\n")
        (stage/"SUMMARY.md").write_text(summary,encoding="utf-8",newline="")
        expected={"specimens.csv","landmarks_long.csv","measurements.csv","omissions.csv","missing_values.csv","landmark_definitions.csv","measurement_definitions.csv","transforms.csv","SUMMARY.md"}
        for spec in group_specs:expected.update(_group_filenames(spec).values())
        if {p.name for p in stage.iterdir() if p.is_file()}!=expected: raise ValueError("analysis bundle file set validation failed")
        with (stage/"specimens.csv").open(encoding="utf-8",newline="") as f: cross=list(csv.DictReader(f))
        if [r["image_id"] for r in cross]!=ids: raise ValueError("specimen crosswalk IDs do not match snapshot")
        files={n:{"sha256":_sha256(stage/n),"size_bytes":(stage/n).stat().st_size} for n in sorted(expected)}
        manifest={"format":"morpholabel_analysis_bundle_v1","app_version":__version__,
            "exported_at_utc":datetime.now(timezone.utc).isoformat(),"scope":scope,
            "warning":"All scope may include unchecked or unfinished records." if scope==SCOPE_ALL else None,
            "dataset_snapshot":{"sha256":snapshot_hash,"source_backup_sha256":source_snapshot_hash,
                "source":"SQLite online backup; reopened by current project code before export",
                "shared_by_all_exports":True},
            "schema_identity_and_order":{spec["key"]:[{"id":int(x["id"]),"abbreviation":x.get("abbr",""),"order":i+1} for i,x in enumerate(spec["schema"])] for spec in group_specs},
            "group_files":{spec["key"]:{"label":spec["label"],**_group_filenames(spec)} for spec in group_specs},
            "scientific_units":{"coordinates":"pixel","measurements":"mm"},
            "coordinate_frames":{"TPS":"original_image_pixels","wide_csv":"standardized_crop_pixels","long_csv":"standardized_crop_pixels","MorphoJ":"standardized_crop_pixels","measurements":"original_image_pixels distance converted to mm"},
            "source_hash_policy":{"verification_requested":bool(verify_sources),"new_hashes_written_to_project":False,"new_hash_semantics":"verified at export time only","when_not_requested":"not_verified"},
            "counts":{"active_specimens":len(all_rows),"excluded":sum(bool(r.get("excluded")) for r in all_rows),"selected_for_scope":len(selected),
                "drafts":sum(bool(snap.annotation_draft(r["image_id"])) for r in all_rows),"export_rows":_output_counts(stage),
                "MorphoJ_omitted":morpho_omitted,"omission_records":len(omissions),"missing_value_records":len(missing_values)} ,"files":files}
        (stage/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        _validate_manifest(stage/"manifest.json")
        if destination.exists(): raise FileExistsError(f"destination created concurrently: {destination}")
        os.rename(stage,destination); published=True
        return {"path":destination,"manifest":destination/"manifest.json","counts":manifest["counts"],"snapshot_sha256":snapshot_hash}
    finally:
        if not published and stage.exists(): shutil.rmtree(stage)
        shutil.rmtree(scratch,ignore_errors=True)
