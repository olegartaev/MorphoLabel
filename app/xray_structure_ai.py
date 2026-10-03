            good=specimen_all_ok==specimen_all_terms
            all_correct+=int(good);wrong_specimens+=int(not good)
    structure_rows=[];f1_values=[]
    for structure in structures:
        stat=structure_stats[str(structure["id"])];tp=stat["tp"];fp=stat["fp"];fn=stat["fn"]
        precision=tp/max(1,tp+fp);recall=tp/max(1,tp+fn);f1=2*precision*recall/max(1e-12,precision+recall)
        if stat["n"]:f1_values.append(f1)
        localization=stat.pop("localization");count_abs=stat.pop("count_abs");count_diff=stat.pop("count_diff");role_errors=stat.pop("role_abs_error")
        structure_rows.append({
            **stat,"precision":precision,"recall":recall,"f1":f1,
            "exact_count_accuracy":(stat["exact_count"]/stat["n"] if stat["repeated"] and stat["n"] else None),
            "count_mae":(sum(count_abs)/len(count_abs) if count_abs else None),
            "count_bias":(sum(count_diff)/len(count_diff) if count_diff else None),
            "localization_median_diag":(float(np.median(localization)) if localization else None),
            "localization_p95_diag":(float(np.percentile(localization,95)) if localization else None),
            "role_accuracy":(stat["role_exact"]/stat["role_total"] if stat["role_total"] else None),
            "role_ordinal_mae":(sum(role_errors)/len(role_errors) if role_errors else None),
        })
    trait_rows=[]
    perfect_traits=0;perfect_trait_total=0
    for trait in traits:
        stat=trait_stats[str(trait["id"])];errors=stat.pop("errors")
        exact_accuracy=(stat["exact"]/stat["n"] if stat["method"] in _EXACT_TRAIT_METHODS and stat["n"] else None)
        if exact_accuracy is not None:
            perfect_trait_total+=1;perfect_traits+=int(abs(exact_accuracy-1.0)<=1e-12)
        within_accuracy=(stat["within"]/stat["within_n"] if stat["within_n"] else None)
        accuracy=exact_accuracy if exact_accuracy is not None else within_accuracy
        accuracy_basis="exact" if exact_accuracy is not None else "within_tolerance" if within_accuracy is not None else "error_only"
        correct=(int(stat["exact"]) if exact_accuracy is not None else int(stat["within"]) if within_accuracy is not None else None)
        evaluated=(int(stat["n"]) if exact_accuracy is not None else int(stat["within_n"]) if within_accuracy is not None else int(stat["n"]))
        trait_rows.append({
            **stat,"exact_accuracy":exact_accuracy,"within_tolerance_accuracy":within_accuracy,
            "accuracy":accuracy,"accuracy_basis":accuracy_basis,"correct":correct,"evaluated":evaluated,
            "mae":(sum(errors)/len(errors) if errors else None),
            "median_abs_error":(float(np.median(errors)) if errors else None),
            "p95_abs_error":(float(np.percentile(errors,95)) if errors else None),
        })
    return {
        "summary":{
            "specimens_compared":compared,
            "exact_traits":exact_ok,"exact_traits_total":exact_total,
            "exact_trait_accuracy":(exact_ok/exact_total if exact_total else None),
            "perfect_traits":perfect_traits,"perfect_traits_total":perfect_trait_total,
            "all_traits_correct_specimens":all_correct,"all_traits_evaluable_specimens":all_evaluable,
            "mean_exact_traits_per_specimen":(sum(exact_counts_per_specimen)/len(exact_counts_per_specimen) if exact_counts_per_specimen else None),
            "specimens_with_wrong_trait":wrong_specimens,
            "repeated_count_mae":(sum(abs(value) for value in repeated_diffs)/len(repeated_diffs) if repeated_diffs else None),
            "repeated_count_bias":(sum(repeated_diffs)/len(repeated_diffs) if repeated_diffs else None),
            "reference_role_accuracy":(role_exact/role_total if role_total else None),
            "reference_role_exact":role_exact,"reference_role_total":role_total,
            "reference_role_ordinal_mae":(sum(role_abs)/len(role_abs) if role_abs else None),
            "localization_median_diag":(float(np.median(all_localization)) if all_localization else None),
            "localization_p95_diag":(float(np.percentile(all_localization,95)) if all_localization else None),
            "macro_f1":(sum(f1_values)/len(f1_values) if f1_values else None),
        },
        "traits":trait_rows,"structures":structure_rows,
    }


def compare_structure_model_to_human(project,model_id=None,split="val",progress=None):
    """Run read-only model inference on its recorded membership and compare with current human truth."""
    model=next((item for item in project.structure_models() if item["model_id"]==str(model_id)),None) if model_id else project.active_structure_model()
    if not model:raise XRayStructureAIError("Select an X-ray Structure AI model first.")
    if str(model.get("schema_digest") or "")!=structure_schema_digest(project.scheme):
        raise XRayStructureAIError("This model uses a different X-ray structure scheme.")
    membership=[item for item in project.structure_model_membership(model["model_id"]) if str(item.get("split") or "")==str(split)]
    if not membership:
        raise XRayStructureAIError("This model has no recorded validation membership to compare with human annotations.")
    ids=[str(item["specimen_id"]) for item in membership]
    checkpoint=project.root/str(model["path"]);metadata=project.root/str(model["metadata_path"])
    if not checkpoint.is_file() or not metadata.is_file():
        raise XRayStructureAIError("The selected Structure AI model artifact is incomplete.")
    verified=[];skipped=[]
    for specimen_id in ids:
        run=project.annotation_run(specimen_id,1,"human",False)
        if not run or str(run.get("status") or "")!="verified":
            skipped.append(specimen_id);continue
        verified.append(specimen_id)
    if not verified:
        raise XRayStructureAIError("None of this model's recorded validation specimens currently has human-verified annotations.")
    runtime,_=ensure_ai_runtime(project=project)
    settings=structure_performance_settings()["inference"];predictions={};failures=[]
    with tempfile.TemporaryDirectory(prefix="morpholabel_xray_structure_compare_") as scratch_name:
        scratch=Path(scratch_name);prepared=[]
        for index,specimen_id in enumerate(verified,1):
            try:prepared.append((specimen_id,_prediction_image(project,specimen_id,scratch/f"{index:06d}.png")))
            except Exception as exc:failures.append({"specimen_id":specimen_id,"reason":str(exc)})
        batch_size=max(1,int(settings.get("batch_size") or 1));index=0
        while index<len(prepared):
            chunk=prepared[index:index+batch_size]
            payload={"metadata":str(metadata),"checkpoint":str(checkpoint),"images":[str(path) for _sid,path in chunk],"device":settings["device"]}
            try:result=_run(runtime,"predict_many",payload,max(900,180*len(chunk)))
            except Exception as exc:
                if is_cuda_oom(exc) and batch_size>1:
                    batch_size=max(1,batch_size//2);continue
                for specimen_id,_path in chunk:failures.append({"specimen_id":specimen_id,"reason":str(exc)})
                index+=len(chunk);continue
            returned=list(result.get("results") or ())
            for offset,(specimen_id,_path) in enumerate(chunk):
                if offset>=len(returned):
                    failures.append({"specimen_id":specimen_id,"reason":"Incomplete prediction batch."});continue
                predictions[specimen_id]=_comparison_prediction_rows(returned[offset].get("structures") or ())
                if progress:progress(index+offset+1,len(prepared),specimen_id)
            index+=len(chunk)
    rows=[]
    for specimen_id in verified:
        if specimen_id not in predictions:continue
        rows.append({
            "specimen_id":specimen_id,
            "human":project.effective_annotations(specimen_id,1,"human"),
            "predicted":predictions[specimen_id],
            "visibility":project.structure_visibility_states(specimen_id,1,"human"),
        })
    report=summarize_structure_ai_human_comparison(project.scheme,rows)
    report["summary"].update({
        "model_id":str(model["model_id"]),"split":str(split),"membership_specimens":len(ids),
        "skipped_not_verified":len(skipped),"prediction_failures":len(failures),
        "comparison_note":"Validation holdout only; current human-verified annotations are read without modifying project data.",
    })
    report["failures"]=failures
    return report


def _safe_model_json(path):
    try:
        source = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XRayStructurePackageError("Structure model metadata is invalid.") from exc
    allowed = {
        "format_version", "backend", "training_objective", "target_encoding", "input_size", "output_stride", "structures", "preprocessing",
        "thresholds", "validation", "epochs_completed", "model_id", "schema_digest",
        "dataset_hash", "parent_model_id", "training_specimens", "validation_specimens",
        "training_plates", "validation_plates",
    }
    return {key: source[key] for key in allowed if key in source}


def export_structure_model_package(project, target, model_id=None):
    model = next(
        (item for item in project.structure_models() if item["model_id"] == str(model_id)),
        None,
    ) if model_id else project.active_structure_model()
    if not model:
        raise XRayStructurePackageError("No X-ray structure model is selected.")
    checkpoint = project.root / str(model["path"])
    metadata = project.root / str(model["metadata_path"])
    if not checkpoint.is_file() or not metadata.is_file():
        raise XRayStructurePackageError("Structure model artifact is incomplete.")
    safe_meta = _safe_model_json(metadata)
    safe_meta["model_id"] = str(model["model_id"])
    safe_meta["schema_digest"] = str(model["schema_digest"])
    meta_bytes = json.dumps(safe_meta, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    checkpoint_bytes = checkpoint.read_bytes()
    files = {
        "artifacts/model.pth": checkpoint_bytes,
        "artifacts/model.json": meta_bytes,
    }
    metrics = dict(model.get("metrics") or {})
    safe_metrics = {
        key: value for key, value in metrics.items()
        if key not in {"training_membership", "validation_membership"} and not str(key).endswith("_path")
    }
    manifest = {
        "package_format": MODEL_PACKAGE_FORMAT,
        "model_id": str(model["model_id"]),
        "backend": str(model.get("backend") or STRUCTURE_BACKEND),
        "schema_digest": str(model["schema_digest"]),
        "training_statistics": {
            "training_specimen_count": int(model.get("training_specimen_count") or 0),
            "validation_specimen_count": int(model.get("validation_specimen_count") or 0),
            "metrics": safe_metrics,
        },
        "files": {name: _sha256_bytes(data) for name, data in files.items()},
    }
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return target


def import_structure_model_package(project, source):
    source = Path(source)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise XRayStructurePackageError("The selected structure model package is not a valid ZIP file.") from exc
    with archive:
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise XRayStructurePackageError("Structure model package manifest is invalid.") from exc
        if manifest.get("package_format") != MODEL_PACKAGE_FORMAT:
            raise XRayStructurePackageError("Unsupported X-ray structure model package format.")
        if str(manifest.get("backend") or "") != STRUCTURE_BACKEND:
            raise XRayStructurePackageError("This package uses an unsupported X-ray structure backend.")
        current_digest = structure_schema_digest(project.scheme)
        if str(manifest.get("schema_digest") or "") != current_digest:
            raise XRayStructurePackageError(
                "This structure model was trained for a different X-ray structure scheme."
            )
        expected = dict(manifest.get("files") or {})
        if set(expected) != {"artifacts/model.pth", "artifacts/model.json"}:
            raise XRayStructurePackageError("Structure model package has an unexpected artifact set.")
        payload = {}
        for name, digest in expected.items():
            if ".." in Path(name).parts or not name.startswith("artifacts/"):
                raise XRayStructurePackageError(f"Unsafe package path: {name}")
            try:
                data = archive.read(name)
            except KeyError as exc:
                raise XRayStructurePackageError(f"Missing package artifact: {name}") from exc
            if _sha256_bytes(data) != str(digest):
                raise XRayStructurePackageError(f"Checksum mismatch: {name}")
            payload[name] = data
        try:
            metadata = json.loads(payload["artifacts/model.json"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise XRayStructurePackageError("Imported structure model metadata is invalid.") from exc
        if str(metadata.get("schema_digest") or "") != current_digest:
            raise XRayStructurePackageError("Imported model metadata does not match the current structure scheme.")
        original = str(manifest.get("model_id") or "imported_structure_model")
        if not _SAFE_ID.fullmatch(original):
            raise XRayStructurePackageError("Imported structure model ID is unsafe.")
        existing = {item["model_id"] for item in project.structure_models()}
        local = original
        counter = 2
        while local in existing or (project.models_root / local).exists():
            local = f"imported_{original}_{counter}"
            counter += 1
        destination = project.models_root / local
        staging = destination.with_name(destination.name + ".importing")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            (staging / "model.pth").write_bytes(payload["artifacts/model.pth"])
            metadata["model_id"] = local
            metadata["imported_from_model_id"] = original
            (staging / "model.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            staging.replace(destination)
            stats = dict(manifest.get("training_statistics") or {})
            metrics = dict(stats.get("metrics") or {})
            metrics.update({
                "origin": "imported",
                "original_model_id": original,
                "portable_package_format": MODEL_PACKAGE_FORMAT,
            })
            project.register_structure_model(
                local,
                str((destination / "model.pth").relative_to(project.root)),
                str((destination / "model.json").relative_to(project.root)),
                None,
                current_digest,
                STRUCTURE_BACKEND,
                metrics,
                (),
                training_specimen_count=int(stats.get("training_specimen_count") or 0),
                validation_specimen_count=int(stats.get("validation_specimen_count") or 0),
                activate=False,
            )