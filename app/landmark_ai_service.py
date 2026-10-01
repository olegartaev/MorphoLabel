"""Project-to-backend landmark inference orchestration; deliberately Tk-free."""
from __future__ import annotations
import math
import hashlib, uuid
from datetime import datetime, timezone
from .io import atomic_json_write
from dataclasses import dataclass, field
from pathlib import Path
from PIL import Image
from .ai import ImagePrediction, InferenceRequest, LandmarkBackend, LandmarkPrediction
from .landmark_frames import restore_standardized_frame
from .landmark_preparation import standardized_metadata, prepare_inference_metadata
from .project_storage import Project, load_schema, schema_hash, landmark_model_schema_compatible, landmark_is_protected_human
from .ai_hardware import auto_performance_config, record_inference_batch, is_cuda_oom, cuda_batch_candidates, get_hardware_profile

class PredictionValidationError(ValueError): pass
class SchemaMismatchError(PredictionValidationError): pass
def _is_rank_process_failure(error): return 'rtmpose rank failed (return code' in str(error).lower()


@dataclass(frozen=True)
class PredictionWriteResult:
    image_id: str
    standardized_image_path: Path
    saved_landmarks: int
    skipped_human_landmarks: int
    prediction_run_id: str
    manifest_path: Path

@dataclass
class BatchPredictionSummary:
    attempted: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    written_landmarks: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    results: dict[str, PredictionWriteResult] = field(default_factory=dict)

class LandmarkAIService:
    """Applies a compatible backend without changing manual/editor code."""
    def __init__(self, project: Project, backend: LandmarkBackend):
        self.project = project
        self.backend = backend
        self._request_hashes = {}
    def _standardized_image(self, image_id: str) -> Path:
        # A landmark prediction is only meaningful in an already persisted
        # canonical crop frame. Missing PNG caches are derived, never inferred.
        path, _ = restore_standardized_frame(self.project, image_id)
        return path
    def _architecture_tuning_identity(self, landmark_count):
        import hashlib, re
        config=Path(getattr(getattr(self.backend,"spec",None),"config_path", "rtmpose"))
        try:
            text=config.read_text(encoding="utf-8")
            fields=re.findall(r"(?:type|arch|deepen_factor|widen_factor|in_channels|out_channels|simcc_split_ratio)\s*=\s*([^,\n]+)",text)
            digest=hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()[:16]
        except OSError: digest=config.name
        return f"rtmpose_inference_arch_v2:{config.name}:{digest}:landmarks={int(landmark_count)}"
    def _request(self, image_id: str, *, metadata=None, schema=None, digest=None) -> InferenceRequest:
        schema = tuple(dict(row) for row in (schema or load_schema(self.project.schema_path)))
        digest = digest or schema_hash(self.project.schema_path)
        if self.backend.schema_sha256 != digest:
            raise SchemaMismatchError("landmark backend schema hash does not match current landmark_schema.csv")
        if metadata is None:
            path, metadata = standardized_metadata(self.project, image_id)
        else:
            path = Path(metadata["path"])
        width, height = int(metadata["standardized_width"]), int(metadata["standardized_height"])
        self._request_hashes[str(image_id)] = metadata.get("standardized_sha256")
        return InferenceRequest(str(image_id), path, schema, digest, width, height)
    @staticmethod
    def _validated_prediction(prediction: ImagePrediction, request: InferenceRequest):
        """Validate output and normalize only sub-pixel edge overflow.

        RTMPose/MMPose may decode a point exactly on, or fractionally beyond,
        the full-image bbox edge. Pixel storage is half-open [0, width) x
        [0, height), so an overflow smaller than one pixel is clipped inward.
        Larger excursions remain a real validation error and require review.
        """
        if prediction.image_id != request.image_id: raise PredictionValidationError("prediction image_id does not match request")
        if prediction.schema_sha256 != request.schema_sha256: raise SchemaMismatchError("prediction schema hash does not match current landmark_schema.csv")
        valid_ids={int(row["id"]) for row in request.schema};seen=set();normalized=[];adjustments=[]
        width=float(request.width);height=float(request.height)
        max_x=math.nextafter(width,-math.inf);max_y=math.nextafter(height,-math.inf)
        for point in prediction.landmarks:
            if point.landmark_id not in valid_ids: raise PredictionValidationError(f"prediction landmark ID is not in schema: {point.landmark_id}")
            if point.landmark_id in seen: raise PredictionValidationError(f"duplicate prediction landmark ID: {point.landmark_id}")
            seen.add(point.landmark_id)
            x=float(point.x);y=float(point.y)
            if not (math.isfinite(x) and math.isfinite(y)): raise PredictionValidationError(f"prediction coordinates must be finite for landmark {point.landmark_id}")
            if not (-1.0 < x <= width and -1.0 < y <= height):
                raise PredictionValidationError(f"prediction coordinates outside standardized image for landmark {point.landmark_id}")
            nx=min(max(x,0.0),max_x);ny=min(max(y,0.0),max_y)
            if nx!=x or ny!=y:
                adjustments.append({"landmark_id":int(point.landmark_id),"raw_x":x,"raw_y":y,"stored_x":nx,"stored_y":ny,"reason":"subpixel_edge_clip"})
            normalized.append(LandmarkPrediction(int(point.landmark_id),nx,ny,point.confidence))
        return ImagePrediction(prediction.image_id,prediction.model_id,prediction.schema_sha256,tuple(normalized)),tuple(adjustments)
    @staticmethod
    def _validate(prediction: ImagePrediction, request: InferenceRequest) -> None:
        LandmarkAIService._validated_prediction(prediction,request)
    def _write_run_manifest(self, request, raw_prediction, stored_prediction, skipped_ids, adjustments=()):
        run_id=str(uuid.uuid4());path=self.project.data_root/"ai"/"predictions"/run_id/"manifest.json"
        returned=[{"landmark_id":point.landmark_id,"x":point.x,"y":point.y,"confidence":point.confidence} for point in raw_prediction.landmarks]
        stored=[{"landmark_id":point.landmark_id,"x":point.x,"y":point.y,"confidence":point.confidence} for point in stored_prediction.landmarks]
        returned_ids={point["landmark_id"] for point in stored};required=[int(row["id"]) for row in request.schema]
        digest=self._request_hashes.get(str(request.image_id)) or hashlib.sha256(request.standardized_image_path.read_bytes()).hexdigest()
        manifest={"format_version":1,"prediction_run_id":run_id,"created_at":datetime.now(timezone.utc).isoformat(),"status":"success","image_id":request.image_id,"model_id":raw_prediction.model_id,"schema_sha256":request.schema_sha256,"standardized_width":request.width,"standardized_height":request.height,"standardized_sha256":digest,"required_landmark_ids":required,"returned_predictions":returned,"omitted_landmark_ids":sorted(set(required)-returned_ids),"written_landmark_ids":sorted(returned_ids-set(skipped_ids)),"skipped_existing_human_ids":sorted(skipped_ids),"backend":self.backend.model_info()}
        if adjustments:
            manifest["stored_predictions"]=stored
            manifest["coordinate_adjustments"]=list(adjustments)
        path.parent.mkdir(parents=True,exist_ok=False);atomic_json_write(path,manifest);return run_id,path
    def _persist_prediction(self, request, prediction):
        if prediction.model_id != self.backend.model_id: raise PredictionValidationError("prediction model_id does not match backend")
        stored_prediction,adjustments=self._validated_prediction(prediction,request)
        existing=self.project.load_landmarks(request.image_id)
        cutoff_reader=getattr(self.project,"landmark_human_protection_cutoff",None)
        frame_cutoff=cutoff_reader(request.image_id) if callable(cutoff_reader) else None
        skipped_ids={point.landmark_id for point in stored_prediction.landmarks if landmark_is_protected_human(existing.get(point.landmark_id),frame_cutoff)}
        run_id,manifest_path=self._write_run_manifest(request,prediction,stored_prediction,skipped_ids,adjustments);saved=skipped=0
        try:
            if hasattr(self.project, "save_machine_landmarks"):
                payload=[{"landmark_id":point.landmark_id,"x":point.x,"y":point.y,"confidence":point.confidence} for point in stored_prediction.landmarks]
                saved,skipped=self.project.save_machine_landmarks(request.image_id,payload,model_id=prediction.model_id,prediction_run_id=run_id)
            else:
                for point in stored_prediction.landmarks:
                    old=existing.get(point.landmark_id)
                    if landmark_is_protected_human(old,frame_cutoff):
                        skipped+=1;continue
                    self.project.save_landmark(request.image_id,point.landmark_id,point.x,point.y,"auto",provenance="machine",model_id=prediction.model_id,predicted_x=point.x,predicted_y=point.y,confidence=point.confidence,prediction_run_id=run_id,reviewed=False)
                    saved+=1
        except Exception:
            manifest_path.unlink(missing_ok=True);raise
        return PredictionWriteResult(request.image_id,request.standardized_image_path,saved,skipped,run_id,manifest_path)

    def predict_one(self, image_id: str) -> PredictionWriteResult:
        request = self._request(image_id)
        registered = self.project.model_metadata(self.backend.model_id)
        if registered is None:
            self.project.register_model(self.backend.model_id, "landmark", metrics=self.backend.model_info(), schema_digest=request.schema_sha256)
        elif registered["kind"] != "landmark" or not landmark_model_schema_compatible(self.project, registered):
            raise SchemaMismatchError("registered landmark model landmark identities/order do not match current landmark schema")
        return self._persist_prediction(request, self.backend.predict(request))
    def predict_many(self, image_ids, progress=None, status=None) -> BatchPredictionSummary:
        summary = BatchPredictionSummary()
        ids=tuple(image_ids)
        if not hasattr(self.backend, "predict_readonly_many"):
            for image_id in ids:
                summary.attempted += 1
                try: result = self.predict_one(image_id)
                except Exception as exc:
                    summary.failed += 1;summary.errors[str(image_id)] = str(exc);continue
                summary.succeeded += 1;summary.results[str(image_id)] = result;summary.written_landmarks += result.saved_landmarks
                if progress: progress(str(image_id), result, None)
                if result.saved_landmarks == 0: summary.skipped += 1
            return summary
        requests=[]
        if status:status("Preparing landmark images for AI…")
        metadata_by_id = None
        prepared_hardware = None
        # The real service prepares canonical frames and image metadata in
        # bounded file-only workers.  Test/backward-compatible callers that
        # replace _request retain their supplied requests unchanged.
        if getattr(self._request, "__func__", None) is LandmarkAIService._request:
            try:
                # Use the setup-qualified machine profile. Hardware discovery is
                # a setup/diagnostic concern, not a landmark-prediction stage.
                prepared_hardware = get_hardware_profile()
                metadata_by_id = prepare_inference_metadata(self.project, ids, hardware=prepared_hardware)
                prepared_schema = tuple(dict(row) for row in load_schema(self.project.schema_path))
                prepared_digest = schema_hash(self.project.schema_path)
            except Exception:
                metadata_by_id = None
        for image_id in ids:
            summary.attempted += 1
            try: requests.append(self._request(image_id, metadata=metadata_by_id[str(image_id)], schema=prepared_schema, digest=prepared_digest) if metadata_by_id is not None else self._request(image_id))
            except Exception as exc: summary.failed += 1;summary.errors[str(image_id)] = str(exc)
        if not requests:return summary
        registered=self.project.model_metadata(self.backend.model_id)
        if registered is None:self.project.register_model(self.backend.model_id,"landmark",metrics=self.backend.model_info(),schema_digest=requests[0].schema_sha256)
        elif registered["kind"] != "landmark" or not landmark_model_schema_compatible(self.project, registered): raise SchemaMismatchError("registered landmark model landmark identities/order do not match current landmark schema")
        architecture=self._architecture_tuning_identity(len(requests[0].schema));variant="landmark_inference_architecture_v5:"+architecture
        tuning_input_size=tuple(getattr(getattr(self.backend,'spec',None),'input_size',(requests[0].width,requests[0].height)))
        performance=auto_performance_config(self.project,workload="landmark_inference",model=architecture,input_size=tuning_input_size,training=False,hardware=prepared_hardware,tuning_variant=variant)
        # A new hardware/model/input tuple is calibrated once with the runner
        # holding one loaded model; startup therefore cannot bias batch choice.
        requested_batch=max(1,int(performance['batch_size']))
        selected_prefetch_workers=performance.get('prefetch_workers')
        selected_prefetch_depth=performance.get('prefetch_depth')
        if status and performance.get('tuning_source') == 'cache':status("Using cached inference settings…")
        if performance.get('tuning_source') == 'heuristic' and hasattr(self.backend, 'benchmark_readonly_many'):
            try:
                import time
                calibration_started=time.perf_counter()
                if status:status("Calibrating inference — first run only…")
                hardware=prepared_hardware or get_hardware_profile()
                if hardware.cuda_available:
                    # Calibrate capacity even when the first real job is tiny:
                    # cycle read-only requests so a 2-4 image first run cannot
                    # permanently cache an artificially small batch.
                    heuristic_batch=max(1,int(performance.get("batch_size",1)))
                    calibration_max=min(64,max(8,heuristic_batch*4))
                    sample_count=calibration_max
                    sample=tuple(requests[index % len(requests)] for index in range(sample_count))
                    batch_values=cuda_batch_candidates(hardware,maximum=calibration_max)
                else:
                    sample_count=16
                    sample=tuple(requests[index % len(requests)] for index in range(sample_count))
                    batch_values=tuple(value for value in (1,2,4,8,16) if value<=sample_count) or (1,)
                physical=max(1,int(hardware.physical_cores or hardware.logical_cores or 1))
                workers=tuple(dict.fromkeys((0,min(2,physical),min(4,physical))))
                try:
                    tuning=self.backend.benchmark_readonly_many(
                        sample,batch_sizes=batch_values,
                        prefetch_worker_candidates=workers,
                        prefetch_depth_candidates=(1,2),
                        progress_callback=(lambda done,total: status(f"Testing inference images {done}/{total}…")) if status else None,
                    )
                except TypeError:
                    tuning=self.backend.benchmark_readonly_many(sample,batch_sizes=batch_values)
                selected=dict(tuning.get('selected_config') or {'batch_size':tuning.get('selected_batch_size',requested_batch)})
                measured=record_inference_batch(self.project,workload='landmark_inference',model=architecture,input_size=tuning_input_size,batch_size=max(1,int(selected['batch_size'])),validated=True,configuration=selected,tuning_variant=variant,hardware=hardware,benchmark_rows=tuning.get('benchmarks'),calibration_elapsed_seconds=time.perf_counter()-calibration_started)
                requested_batch=max(1,int(measured['batch_size']))
                selected_prefetch_workers=measured.get('prefetch_workers')
                selected_prefetch_depth=measured.get('prefetch_depth')
                if status:
                    saved="Cache saved." if measured.get('cache_saved') else "Cache could not be saved; calibration may repeat next time."
                    status(f"Selected inference batch {requested_batch}, preprocess workers {selected_prefetch_workers if selected_prefetch_workers is not None else 'automatic'}, depth {selected_prefetch_depth if selected_prefetch_depth is not None else 'automatic'}. {saved}")
            except Exception as exc:
                # The production rank path retains its existing fresh-process
                # fallback.  Do not let optional tuning prevent prediction.
                if not (is_cuda_oom(exc) or _is_rank_process_failure(exc)):
                    raise
                requested_batch=1
        if status:status(f"Running AI: batch {requested_batch}" + (f", preprocess workers {selected_prefetch_workers}" if selected_prefetch_workers is not None else ""))
        # One rank request keeps the isolated runtime and loaded model alive for
        # the whole mass job. The runner owns its internal progress heartbeat.
        def rank_many_with_compatibility(batch):
            nonlocal requested_batch
            try:
                return tuple(self.backend.predict_readonly_many(requests,batch_size=batch,prefetch_workers=selected_prefetch_workers,prefetch_depth=selected_prefetch_depth))
            except TypeError as exc:
                if not any(name in str(exc) for name in ("batch_size", "prefetch_workers", "prefetch_depth")):
                    raise
                try:
                    # Most third-party-compatible backends support batch_size
                    # but predate SIMM's optional prefetch controls.
                    return tuple(self.backend.predict_readonly_many(requests,batch_size=batch))
                except TypeError as legacy_exc:
                    if "batch_size" not in str(legacy_exc):
                        raise
                # Older compatible backends expose bulk ranking without the
                # optional batch keyword. Preserve bounded retry semantics.
                if batch == 1:
                    requested_batch=len(requests)
                    return tuple(self.backend.predict_readonly_many(requests))
                if batch >= len(requests):
                    return tuple(self.backend.predict_readonly_many(requests))
                return tuple(prediction for start in range(0,len(requests),batch) for prediction in self.backend.predict_readonly_many(requests[start:start+batch]))
        attempted_batch=requested_batch
        while True:
            try:
                predictions=rank_many_with_compatibility(requested_batch)
                break
            except Exception as exc:
                if requested_batch>1 and (is_cuda_oom(exc) or _is_rank_process_failure(exc)):
                    requested_batch=max(1,requested_batch//2)
                    continue
                for request in requests:
                    summary.failed+=1;summary.errors[str(request.image_id)]=str(exc)
                    if progress: progress(str(request.image_id),None,exc)
                return summary
        actual_batch=getattr(self.backend,'last_rank_batch_size',requested_batch)
        runtime_setting=record_inference_batch(self.project,workload='landmark_inference',model=architecture,input_size=tuning_input_size,batch_size=actual_batch,hardware=prepared_hardware,tuning_variant=variant,attempted_batch=attempted_batch)
        if status and actual_batch<attempted_batch:
            saved="Cache saved." if runtime_setting.get('cache_saved') else "Cache could not be saved."
            status(f"CUDA memory limit reached; batch {actual_batch} succeeded. {saved}")
        returned={prediction.image_id:prediction for prediction in predictions}
        for request in requests:
            try:
                result=self._persist_prediction(request,returned[request.image_id])
            except Exception as exc:
                summary.failed+=1;summary.errors[str(request.image_id)]=str(exc)
                if progress: progress(str(request.image_id),None,exc)
                continue
            summary.succeeded+=1;summary.results[str(request.image_id)]=result;summary.written_landmarks+=result.saved_landmarks
            if progress: progress(str(request.image_id),result,None)
            if result.saved_landmarks==0:summary.skipped+=1
        return summary

