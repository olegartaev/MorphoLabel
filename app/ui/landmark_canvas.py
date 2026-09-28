"""Tokenized, cached landmark canvas extracted from proven ReadyEditor behaviour."""
from __future__ import annotations
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
from app.gui_crop_debug import log
from app.landmark_state import load_current_landmark_state
from app.editor_state import EditorState
from app.landmark_frames import LandmarkFrameError, crop_frame_record, restore_standardized_frame
from app.project_runtime import scoped_project
from app.ui.landmark_display import load_display_settings, draw_marker, move_marker, draw_label, move_label, label_text

class LandmarkCanvasController:
    """Main-workspace landmark operator.  Image decoding is tokenized; dragging is vector-only."""
    def __init__(self, parent, context, changed, selection_changed=None):
        self.parent, self.context = parent, context
        self.changed, self.selection_changed = changed, selection_changed
        self.canvas = tk.Canvas(parent, background="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._token = 0
        self._events = queue.Queue()
        self._poll = None
        self._poll_ids = set()
        self._loading_pulse_job = None
        self._loading_pulse_step = 0
        self._destroyed = False
        self._closing = threading.Event()
        self._workers = set()
        # Keep at most one decoded next batch image ready; Tk receives it only on the main thread.
        self._prefetch_lock = threading.Lock()
        self._prefetched = {}
        self._prefetching = set()
        self.on_image_ready = None
        self.image = self.photo = None
        self.image_id = self.image_path = None
        self.requested_image_id = self.displayed_image_id = None
        self.requested_generation = 0
        self.requested_request_epoch = 0
        self.zoom = 1.0
        self.pan = (0.0, 0.0)
        self._display_cache = None
        self._raster_key = None
        self._image_item = None
        self._point_items = {}
        self._points = {}
        self.review_landmark_ids = set()
        self.review_message = ""
        self.state = None
        self._state_fresh = False
        self.dragging = None
        self.pending = None
        self.pan_drag = None
        self.stats = {"state_reads": 0, "photo_creations": 0, "drag_motion": 0, "drag_saves": 0, "drag_max_ms": 0.0}
        self.display_settings = load_display_settings(context.project)
        schema = context.project.schema
        self.operator_state = EditorState(point_ids=tuple(int(item["id"]) for item in schema) or (1,))
        self.choice = tk.IntVar(value=self.operator_state.current_landmark)
        for event, handler in (
            ("<Button-1>", self.place), ("<B1-Motion>", self.drag),
            ("<ButtonRelease-1>", self.release), ("<Button-3>", self.pan_start),
            ("<B3-Motion>", self.pan_motion), ("<ButtonRelease-3>", lambda _e: setattr(self, "pan_drag", None)),
            ("<MouseWheel>", self.wheel), ("<Configure>", lambda _e: self.redraw_cached()),
        ):
            self.canvas.bind(event, handler)
        self.canvas.bind("<Destroy>", self.destroy, add="+")
        self.load_current()

    def destroy(self, event):
        if event.widget is not self.canvas:
            return
        self._destroyed = True
        self._closing.set()
        self._token += 1
        self.pending = None
        if self._loading_pulse_job:
            try:self.canvas.after_cancel(self._loading_pulse_job)
            except tk.TclError:pass
            self._loading_pulse_job=None
        for after_id in tuple(self._poll_ids):
            try:
                self.canvas.after_cancel(after_id)
            except tk.TclError:
                pass
        self._poll_ids.clear()
        self._poll = None
        self._poll_ids = set()
        # One-way shutdown: workers may finish a current decode, but never schedule UI work.
        for worker in tuple(self._workers):
            worker.join(timeout=0.25)

    def _paths(self, row):
        crop = crop_frame_record(self.context.project, row["image_id"])
        return None if crop is None else restore_standardized_frame(self.context.project, row["image_id"], crop)[0]

    def _load_prepared_image(self, row, project, progress=None):
        """Decode only the persisted canonical crop frame off the Tk thread."""
        if progress:progress("Checking saved crop frame")
        crop = crop_frame_record(project, row["image_id"])
        if crop is None:
            raise LandmarkFrameError("Crop required before landmarking")
        if progress:progress("Preparing saved crop frame")
        target, rebuilt = restore_standardized_frame(project, row["image_id"], crop)
        if progress:progress("Opening crop image" if not rebuilt else "Opening rebuilt crop image")
        with Image.open(target) as source:
            return target, source.convert("RGB")
    def ready_for(self, image_id):
        current=(self.context.current() or {}).get("image_id")
        return bool(image_id and self.requested_image_id == self.displayed_image_id == current == image_id and self.image_id == image_id and self.state)

    def _start_loading_pulse(self, text):
        self._loading_pulse_step = 0
        self._loading_text = str(text)
        def tick():
            if self._destroyed or self.displayed_image_id is not None:
                self._loading_pulse_job = None; return
            self._loading_pulse_step += 1
            dots = "." * (self._loading_pulse_step % 4)
            try:self.canvas.itemconfigure("landmark_loading", text=self._loading_text+dots)
            except tk.TclError:return
            self._loading_pulse_job = self.canvas.after(350, tick)
        tick()

    def _stop_loading_pulse(self):
        if self._loading_pulse_job:
            try:self.canvas.after_cancel(self._loading_pulse_job)
            except tk.TclError:pass
            self._loading_pulse_job=None

    def load_current(self, request_epoch=None):
        """Start background preparation for the current selected image; latest token wins."""
        row = self.context.current()
        self._token += 1
        token = self._token
        self.requested_generation = token
        if request_epoch is not None: self.requested_request_epoch = request_epoch
        self.requested_image_id = (row or {}).get("image_id")
        self._new_image = True
        # Never allow an old displayed state to be edited or accepted while a new image loads.
        self.displayed_image_id = self.image_id = self.image_path = None
        self.image = self.photo = self.state = None; self._points = {}; self.dragging = self.pending = None; self._state_fresh = False
        self.canvas.delete("landmark_loading")
        self.canvas.create_text(16, 16, anchor="nw", fill="white", text="Preparing landmark image", tags="landmark_loading")
        self._start_loading_pulse("Preparing landmark image")
        if not row:
            return
        row, project = dict(row), self.context.project
        with self._prefetch_lock:
            ready = self._prefetched.pop(row["image_id"], None)
        if ready is not None:
            target, image = ready
            self._events.put((token, "ok", row["image_id"], target, image, None))
            self._poll_events(token)
            return

        def worker():
            target = None
            started=time.perf_counter();stage_started=started;stage="worker start"
            log(row["image_id"],"production_landmark_load_worker","START",detail=f"token={token}")
            try:
                def progress(message):
                    nonlocal stage_started,stage
                    now=time.perf_counter()
                    log(row["image_id"],"production_landmark_load_stage","END",detail=f"stage={stage}; elapsed_s={now-stage_started:.3f}")
                    stage=str(message);stage_started=now
                    if not self._closing.is_set():self._events.put((token,"progress",row["image_id"],None,None,stage))
                target, image = self._load_prepared_image(row, project, progress=progress)
                now=time.perf_counter()
                log(row["image_id"],"production_landmark_load_stage","END",detail=f"stage={stage}; elapsed_s={now-stage_started:.3f}")
                log(row["image_id"],"production_landmark_load_worker","END",path=str(target),detail=f"elapsed_s={now-started:.3f}")
                if not self._closing.is_set(): self._events.put((token, "ok", row["image_id"], target, image, None))
            except Exception as exc:
                log(row["image_id"],"production_landmark_load_worker","ERROR",path=str(target),detail=f"stage={stage}; elapsed_s={time.perf_counter()-started:.3f}; error={exc}")
                if not self._closing.is_set(): self._events.put((token, "error", row["image_id"], target, None, str(exc)))
            finally:
                self._workers.discard(threading.current_thread())

        thread=threading.Thread(target=worker, daemon=True, name=f"production-landmark-load-{row['image_id']}");self._workers.add(thread);thread.start()
        self._poll_events(token)

    def prefetch(self, image_id):
        """Decode one next finite-batch image in the background without touching Tk."""
        row = next((dict(item) for item in self.context.rows if item.get("image_id") == image_id), None)
        if row is None or self._destroyed:
            return False
        with self._prefetch_lock:
            if image_id in self._prefetched or image_id in self._prefetching:
                return False
            self._prefetching.add(image_id)
        project = self.context.project

        def worker():
            try:
                target, image = self._load_prepared_image(row, project)
                with self._prefetch_lock:
                    # A single image is enough for one-ahead navigation and bounds memory use.
                    self._prefetched = {image_id: (target, image)}
            except Exception as exc:
                log(image_id, "production_landmark_prefetch", "ERROR", detail=str(exc))
            finally:
                with self._prefetch_lock:
                    self._prefetching.discard(image_id)

        thread=threading.Thread(target=worker, daemon=True, name=f"production-landmark-prefetch-{image_id}");self._workers.add(thread);thread.start()
        return True

    def _prefetch_next_batch_image(self, current_id):
        """Warm exactly the next persisted batch member while the operator annotates this one."""
        try:
            from app.landmark_ai_workflow import load_state
            state = load_state(self.context.project)
            stage = state.get("stage")
            key = "initial_image_ids" if stage == "INITIAL_TRAINING" else "improvement_image_ids" if stage == "MODEL_IMPROVEMENT" else None
            ids = list(state.get(key, ())) if key else []
            position = ids.index(current_id)
            if position + 1 < len(ids):
                self.prefetch(ids[position + 1])
        except (ValueError, OSError, KeyError):
            # Prefetch is only a responsiveness optimization and must never affect annotation.
            return

    def _poll_events(self, expected):
        if self._destroyed or self._closing.is_set():
            return
        try:
            while True:
                token, status, ident, path, image, error = self._events.get_nowait()
                current=(self.context.current() or {}).get("image_id")
                if token != self._token or ident != self.requested_image_id or ident != current:
                    log(ident, "production_landmark_stale_load", "END", path=str(path), detail=f"token={token} requested={self.requested_image_id} current={current}")
                    continue
                if status=="progress":
                    self._loading_text=str(error)
                    try:self.canvas.itemconfigure("landmark_loading",text=self._loading_text)
                    except tk.TclError:pass
                    continue
                self._stop_loading_pulse();self.canvas.delete("landmark_loading")
                if status != "ok":
                    self.canvas.delete("all")
                    text = "Crop required before landmarking" if error == "Crop required before landmarking" else f"Could not prepare landmark image:\n{error}"
                    self.canvas.create_text(16, 16, anchor="nw", fill="white", text=text, tags="landmark_loading")
                    log(ident, "production_landmark_load", "ERROR", path=str(path), detail=error)
                    return
                self.image_id, self.displayed_image_id, self.image_path, self.image = ident, ident, path, image
                self.zoom, self.pan = 1.0, (0.0, 0.0)
                self._display_cache = self._raster_key = None
                self._image_item = None
                self.refresh_authoritative(notify=True)
                lm1=self._points.get(1)
                if lm1:
                    log(ident,"production_landmark_lm1_loaded","END",path=str(path),detail=f"state={lm1.get('state')} provenance={lm1.get('provenance')} x={lm1.get('x_standardized')} y={lm1.get('y_standardized')} model_id={lm1.get('model_id')} prediction_run_id={lm1.get('prediction_run_id')} updated_at={lm1.get('updated_at')}")
                self._prefetch_next_batch_image(ident)
                if self.on_image_ready:
                    self.canvas.after_idle(lambda ident=ident: self.on_image_ready(ident, token, getattr(self, 'requested_request_epoch', 0)) if self.ready_for(ident) and token == self.requested_generation else None)
                return
        except queue.Empty:
            if expected == self._token and not self._destroyed:
                holder = {}
                def poll_again():
                    self._poll_ids.discard(holder.get("id"))
                    self._poll_events(expected)
                holder["id"] = self.canvas.after(25, poll_again)
                self._poll = holder["id"]
                self._poll_ids.add(self._poll)

    def _fit(self):
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        fit = min((width - 20) / self.image.width, (height - 20) / self.image.height)
        return max(0.001, fit * self.zoom), width, height

    def _position(self, x, y):
        scale, _, _ = self._fit()
        return self.pan[0] + float(x) * scale, self.pan[1] + float(y) * scale

    def _ensure_raster(self):
        scale, width, height = self._fit()
        dw, dh = max(1, round(self.image.width * scale)), max(1, round(self.image.height * scale))
        if self.pan == (0.0, 0.0):
            self.pan = ((width - dw) / 2, (height - dh) / 2)
        key = (id(self.image), dw, dh)
        if key != self._raster_key:
            shown = self.image.resize((dw, dh), Image.Resampling.BILINEAR)
            self.photo = ImageTk.PhotoImage(shown, master=self.canvas)
            self.stats["photo_creations"] += 1
            self._display_cache, self._raster_key = shown, key
            if self._image_item is None:
                self._image_item = self.canvas.create_image(*self.pan, anchor="nw", image=self.photo, tags="image")
            else:
                self.canvas.itemconfigure(self._image_item, image=self.photo)
        if self._image_item is not None:
            self.canvas.coords(self._image_item, *self.pan)

    def _draw_overlays(self):
        self.canvas.delete("landmark_overlay")
        self._point_items = {}
        settings = self.display_settings
        for ident, point in self._points.items():
            if point.get("state") == "missing" or point.get("x_standardized") is None:
                continue
            x, y = self._position(point["x_standardized"], point["y_standardized"])
            selected = int(ident) == self.choice.get()
            color = settings["selected_color"] if selected else settings["other_color"]
            marker = draw_marker(
                self.canvas, x, y,
                color=color, size=settings["size"], symbol=settings["symbol"], halo=settings["halo"],
                tags=("landmark_overlay", f"landmark:{ident}"),
            )
            offset = settings["size"] + 4
            label = draw_label(
                self.canvas, x + offset, y - offset,
                text=label_text(self.context.project.schema, ident, settings["label"]),
                color=color, font_size=settings["label_size"], halo=settings["halo"],
                tags=("landmark_overlay", f"landmark:{ident}"),
            )
            self._point_items[int(ident)] = (marker, label)
        if self.review_landmark_ids:
            for ident in sorted(self.review_landmark_ids):
                point=self._points.get(int(ident))
                if not point or point.get("state")=="missing" or point.get("x_standardized") is None:
                    continue
                x,y=self._position(point["x_standardized"],point["y_standardized"])
                radius=max(14,int(settings["size"])+9)
                self.canvas.create_oval(x-radius,y-radius,x+radius,y+radius,outline="#ffb000",width=3,tags=("landmark_overlay","landmark_review_ring"))
            if self.review_message:
                self.canvas.create_text(14,14,anchor="nw",text=self.review_message,fill="#ffdf80",font=("Segoe UI",10,"bold"),tags=("landmark_overlay","landmark_review_ring"))

    def set_review_landmarks(self, landmark_ids=(), message=""):
        self.review_landmark_ids={int(value) for value in landmark_ids if value is not None}
        self.review_message=str(message or "")
        if self.review_landmark_ids:
            first=next(iter(sorted(self.review_landmark_ids)))
            if first in self.operator_state.point_ids:self.set_choice(first)
        elif self.image:self._draw_overlays()
        return tuple(sorted(self.review_landmark_ids))

    def clear_review_landmarks(self):
        self.review_landmark_ids=set();self.review_message=""
        if self.image:self._draw_overlays()

    def apply_display_settings(self):
        self.display_settings = load_display_settings(self.context.project)
        self._draw_overlays()
        return dict(self.display_settings)

    def redraw_cached(self):
        if not self.image or self.context.current() is None or self.context.current()["image_id"] != self.image_id:
            return False
        self._ensure_raster()
        self._draw_overlays()
        return True

    render = redraw_cached

    def refresh_authoritative(self, notify=False):
        if not self.image_id:
            return None
        self.stats["state_reads"] += 1
        self.state = load_current_landmark_state(self.context.project, self.image_id)
        self._points = {ident: dict(point) for ident, point in self.state.points_by_id.items()}
        self._state_fresh = True
        selected = self.choice.get()
        is_new = getattr(self, '_new_image', False)
        self.operator_state.open_record({"points": {str(key): value for key, value in self._points.items()}})
        unresolved = sorted(self.state.unresolved_ids)
        current = (unresolved[0] if unresolved else self.operator_state.current_landmark) if is_new else (selected if selected in self.operator_state.point_ids else self.operator_state.current_landmark)
        self._new_image = False
        self.operator_state.select(current)
        self.choice.set(current)
        self.redraw_cached()
        if notify:
            self._sync_selection()
        return self.state

    def take_fresh_state(self):
        if not self._state_fresh:
            return None
        self._state_fresh = False
        return self.state
    def _point(self, event):
        scale, _, _ = self._fit()
        return (float(event.x - self.pan[0]) / scale, float(event.y - self.pan[1]) / scale)

    def _sync_selection(self):
        if self.selection_changed:
            self.selection_changed(self.choice.get())

    def set_choice(self, ident):
        self.operator_state.select(int(ident))
        self.choice.set(self.operator_state.current_landmark)
        if self.image:
            self._draw_overlays()
        self._sync_selection()

    def _next(self):
        if self.state and self.state.unresolved_ids:
            ident = self.operator_state.select(sorted(self.state.unresolved_ids)[0])
            self.choice.set(ident)

    def place(self, event):
        if not self.ready_for(self.image_id):
            return
        for ident, point in self._points.items():
            if point.get("state") == "missing" or point.get("x_standardized") is None:
                continue
            x, y = self._position(point["x_standardized"], point["y_standardized"])
            hit_radius = max(10, int(self.display_settings["size"]) + 5)
            if (event.x - x) ** 2 + (event.y - y) ** 2 <= hit_radius ** 2:
                self.set_choice(int(ident))
                self.dragging = int(ident)
                self.pending = (float(point["x_standardized"]), float(point["y_standardized"]))
                self.stats["drag_motion"] = 0
                self._draw_overlays()
                self._sync_selection()
                return
        x, y = self._point(event)
        if 0 <= x < self.image.width and 0 <= y < self.image.height:
            unresolved = sorted(self.state.unresolved_ids) if self.state else []
            if not unresolved:
                return
            selected = self.choice.get()
            if selected not in unresolved:
                selected = self.operator_state.current_landmark
            ident = self.operator_state.select(selected if selected in unresolved else unresolved[0])
            self.choice.set(ident)
            try:
                self.context.project.save_landmark(self.image_id, ident, x, y, "manual", "manual")
                log(self.image_id,"production_landmark_place","END",path=str(self.image_path or ""),detail=f"landmark_id={ident} x={x} y={y}")
            except Exception as exc:
                self._persistence_error("place landmark", exc)
                return
            self.refresh_authoritative(notify=False)
            self._next()
            self._draw_overlays()
            self._sync_selection()
            self.changed()

    def _persistence_error(self, action, exc):
        log(self.image_id or "GLOBAL", "production_landmark_persistence", "ERROR", path=str(self.image_path or ""), detail=f"action={action} error={exc!r}")
        messagebox.showerror("Landmark save failed", f"Could not {action}. No landmark data was changed.\n\n{exc}", parent=self.parent)
    def drag(self, event):
        """Motion is intentionally vector-only: no state read, resize, PhotoImage, or shell render."""
        if self.dragging is None or not self.ready_for(self.image_id):
            return
        x, y = self._point(event)
        if not (0 <= x < self.image.width and 0 <= y < self.image.height):
            return
        self.pending = (x, y)
        self.stats["drag_motion"] += 1
        point = self._points.get(self.dragging)
        items = self._point_items.get(self.dragging)
        if point is None or items is None:
            return
        point["x_standardized"], point["y_standardized"] = x, y
        sx, sy = self._position(x, y)
        marker, label = items
        move_marker(self.canvas, marker, sx, sy)
        offset = int(self.display_settings["size"]) + 4
        move_label(self.canvas, label, sx + offset, sy - offset)

    def release(self, _event):
        if self.dragging is None or not self.ready_for(self.image_id):
            self.dragging = self.pending = None
            return
        ident, pending = self.dragging, self.pending
        self.dragging = self.pending = None
        if pending:
            try:
                self.context.project.save_landmark(self.image_id, ident, *pending, "corrected", "corrected_by_human")
            except Exception as exc:
                self._persistence_error("save dragged landmark", exc)
                self.refresh_authoritative(notify=True)
                return
            self.stats["drag_saves"] += 1
        log(self.image_id, "production_landmark_drag_release", "END", path=str(self.image_path or ""), detail=f"landmark_id={ident} motions={self.stats['drag_motion']} saved={bool(pending)}")
        # The drag path already holds the saved coordinates locally. Defer the
        # authoritative recount/redraw until Tk is idle so mouse release stays instant.
        self._state_fresh=False
        self.canvas.after_idle(self.changed)

    def current_is_missing(self):
        point=self._points.get(self.operator_state.current_landmark) or {}
        return point.get("state")=="missing"

    def toggle_missing(self):
        if not self.ready_for(self.image_id):
            return
        ident=self.operator_state.current_landmark
        try:
            if self.current_is_missing():
                self.context.project.restore_landmark_before_missing(self.image_id,ident)
            else:
                self.context.project.save_landmark(self.image_id,ident,None,None,"missing","missing")
        except Exception as exc:
            self._persistence_error("toggle landmark missing state", exc)
            return
        self.refresh_authoritative(notify=False)
        if self._points.get(ident,{}).get("state")=="missing":
            self._next()
        else:
            self.operator_state.select(ident);self.choice.set(ident)
        self._draw_overlays();self._sync_selection();self.changed()

    def mark_missing(self):
        return self.toggle_missing()

    def delete_current(self):
        """Legacy remove(): delete only the current point and leave it unresolved."""
        if not self.image_id:
            return
        ident = self.operator_state.current_landmark
        try:
            self.context.project.delete_landmark(self.image_id, ident)
        except Exception as exc:
            self._persistence_error("delete landmark", exc)
            return
        self.refresh_authoritative(notify=False)
        self.operator_state.select(ident)
        self.choice.set(ident)
        self._draw_overlays()
        self._sync_selection()
        self.changed()

    clear_current = delete_current

    def clear_all(self):
        """Reset all editable current landmarks using the established manual-rebuild path."""
        if not self.image_id or not self._points:
            return
        if not messagebox.askyesno("Clear all landmarks", "Clear every landmark on this image? This can be annotated again.", parent=self.parent):
            return
        try:
            self.context.project.clear_landmark_finals_for_draft(self.image_id)
        except Exception as exc:
            self._persistence_error("clear all landmarks", exc)
            return
        self.refresh_authoritative(notify=False)
        schema=list(getattr(self.context.project,"schema",()) or ())
        if schema:
            first_id=int(schema[0]["id"])
            self.operator_state.select(first_id)
            self.choice.set(first_id)
        self._draw_overlays()
        self._sync_selection()
        self.changed()

    def mark_checked(self):
        if not self.ready_for(self.image_id):
            return
        if not self.state or not self.state.complete:
            messagebox.showwarning("Check landmarks", "Place or mark missing every landmark first.", parent=self.parent)
            return
        self.context.project.mark_checked(self.image_id)
        self.refresh_authoritative(notify=True)
        self.changed()

    def pan_start(self, event):
        self.pan_drag = (event.x, event.y, self.pan)

    def pan_motion(self, event):
        if self.pan_drag:
            x, y, origin = self.pan_drag
            self.pan = (origin[0] + event.x - x, origin[1] + event.y - y)
            self.redraw_cached()

    def wheel(self, event):
        if not self.image:
            return
        scale, _, _ = self._fit()
        before = ((event.x - self.pan[0]) / scale, (event.y - self.pan[1]) / scale)
        self.zoom = max(0.2, min(8.0, self.zoom * (1.15 if event.delta > 0 else 1 / 1.15)))
        new_scale, _, _ = self._fit()
        self.pan = (event.x - before[0] * new_scale, event.y - before[1] * new_scale)
        self.redraw_cached()
