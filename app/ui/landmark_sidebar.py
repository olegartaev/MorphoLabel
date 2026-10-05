"""Legacy landmark table beneath the shared PhotoListCanvas."""
from tkinter import ttk
from app.landmark_state import load_current_landmark_state
from .photo_list_panel import PhotoListPanel

class LandmarkSidebar(ttk.Frame):
    def __init__(self, parent, context, on_image, tooltip, on_landmark, on_exclusion=None):
        super().__init__(parent)
        self.context, self.on_landmark = context, on_landmark
        self._syncing = False
        self._synced_choice = None
        self._table_image_id = None
        self._row_state = {}
        self.pane = ttk.Panedwindow(self, orient="vertical")
        self.pane.pack(fill="both", expand=True)
        top = ttk.Frame(self.pane)
        bottom = ttk.Labelframe(self.pane, text="Landmarks", padding=3)
        self.pane.add(top, weight=1)
        self.pane.add(bottom, weight=0)
        self.photos = PhotoListPanel(top, context, on_image, tooltip, on_exclusion=on_exclusion)
        self.photos.pack(fill="both", expand=True)
        self.canvas = self.photos.canvas
        self.image_query = self.photos.image_query
        self.locality_query = self.photos.locality_query
        self.show_excluded = self.photos.show_excluded
        visible_rows = max(1, min(12, len(self.context.project.schema)))
        self.table = ttk.Treeview(bottom, columns=("status", "id", "use", "abbr", "name"), show="headings", selectmode="browse", height=visible_rows)
        for key, label, width, stretch in (
            ("status", "", 28, False), ("id", "#", 34, False), ("use", "Use", 42, False),
            ("abbr", "Abbr", 58, False), ("name", "Landmark", 180, True),
        ):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=width, stretch=stretch, anchor="w")
        self.table.tag_configure("present", foreground="#188038")
        self.table.tag_configure("missing", foreground="#c88700")
        self.table.tag_configure("unresolved", foreground="#d93025")
        self.table.tag_configure("review_warning", background="#fde8e8")
        scroll = ttk.Scrollbar(bottom, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", self.pick)
        self.pane.bind("<ButtonRelease-1>", self.save_sash, add="+")
        self.pane.bind("<Configure>", self.restore_sash, add="+")

    def refresh(self, *args, **kwargs):
        return self.photos.refresh(*args, **kwargs)

    def refresh_image(self, image_id):
        return self.photos.refresh_image(image_id)

    def navigate(self, step):
        return self.photos.navigate(step)

    def restore_sash(self, attempt=0):
        try:
            height = self.pane.winfo_height()
            if height < 360 and attempt < 8:
                return
            minimum_photo = 180
            # New layout key intentionally ignores the older oversized default.
            stored = self.context.project.get_ui_state("photo_landmark_sash_v2", None)
            if stored is None:
                self.update_idletasks()
                desired_bottom = max(86, min(self.table.winfo_reqheight() + 34, int(height * 0.45)))
                value = height - desired_bottom
            else:
                value = int(stored)
            maximum = max(minimum_photo, height - 84)
            self.pane.sashpos(0, max(minimum_photo, min(maximum, value)))
        except Exception:
            return

    def save_sash(self, _event=None):
        try:
            self.context.project.set_ui_state("photo_landmark_sash_v2", int(self.pane.sashpos(0)))
        except Exception:
            return

    def refresh_landmarks(self, current=None, state=None):
        """Populate once per image; simple selection/edit updates only changed rows."""
        self._syncing = True
        try:
            row = self.context.current()
            if not row:return
            state = state or load_current_landmark_state(self.context.project, row["image_id"])
            rebuild = self._table_image_id != row["image_id"] or len(self.table.get_children()) != len(self.context.project.schema)
            if rebuild:
                self.table.delete(*self.table.get_children());self._table_image_id=row["image_id"];self._row_state={}
            points=state.points_by_id; review=bool(row.get("review_warning"))
            for item in self.context.project.schema:
                ident=int(item["id"]);point=points.get(ident,{})
                tag="missing" if point.get("state")=="missing" else "present" if ident in state.present_ids else "unresolved";marker={"present":"✓","missing":"●","unresolved":"○"}[tag]
                role={"CLASSICAL":"CL","GM":"GM","BOTH":"BT"}.get(str(item.get("role","BOTH")).upper(),"BT");values=(marker,ident,role,item.get("abbr",""),item.get("name",""));tags=(tag,"review_warning") if review else (tag,)
                signature=(values,tags)
                if rebuild:self.table.insert("","end",iid=str(ident),values=values,tags=tags)
                elif self._row_state.get(ident)!=signature:self.table.item(str(ident),values=values,tags=tags)
                self._row_state[ident]=signature
            choice=int(current or 0);self._synced_choice=choice
            if choice and self.table.exists(str(choice)):
                self.table.selection_set(str(choice));self.table.see(str(choice))
        finally:self._syncing=False
    def pick(self, _event=None):
        if self._syncing:
            return
        selected = self.table.selection()
        if selected and int(selected[0]) != self._synced_choice:
            self.on_landmark(int(selected[0]))
