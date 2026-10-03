            try:export_structure_model_package(self.project,target,model_id)
            except Exception as exc:messagebox.showerror("Export Structure AI",str(exc),parent=dialog);return
            messagebox.showinfo("Export Structure AI","Portable model package saved. It can be imported on another computer with the same X-ray structure scheme.",parent=dialog)
        def import_model():
            source=filedialog.askopenfilename(
                parent=dialog,title="Import Structure AI",filetypes=(("MorphoLabel Structure AI","*.zip"),("ZIP files","*.zip")),
            )
            if not source:return
            try:model_id=import_structure_model_package(self.project,source)
            except Exception as exc:messagebox.showerror("Import Structure AI",str(exc),parent=dialog);return
            reload(model_id);self._refresh_workflow()
            messagebox.showinfo("Import Structure AI",f"Imported {model_id}. Select it and choose Make active before prediction or continued training.",parent=dialog)
        def compare_human():
            model_id=selected()
            if not model_id:
                messagebox.showinfo("Compare with human","Select a model first.",parent=dialog);return
            if self._busy:return
            self._busy=True;events=queue.Queue()
            progress_dialog,progress_label,progress_bar=self._structure_ai_dialog(
                "Compare with human","Running the selected model on its validation holdout…",None
            )
            def progress(done,total,specimen_id):
                events.put(("progress",int(done),int(total),str(specimen_id)))
            def worker():
                try:events.put(("done",compare_structure_model_to_human(self.project,model_id,split="val",progress=progress)))
                except Exception as exc:events.put(("error",exc))
            threading.Thread(target=worker,daemon=True,name="xray-structure-human-comparison").start()
            def poll():
                try:
                    while True:
                        event=events.get_nowait()
                        if event[0]=="progress":
                            progress_label.configure(text=f"Validation holdout: {event[1]} / {event[2]} specimens")
                        elif event[0]=="error":
                            self._busy=False
                            try:progress_bar.stop();progress_dialog.destroy()
                            except tk.TclError:pass
                            messagebox.showerror("Compare with human",str(event[1]),parent=dialog);return
                        elif event[0]=="done":
                            self._busy=False
                            try:progress_bar.stop();progress_dialog.destroy()
                            except tk.TclError:pass
                            self._show_structure_model_comparison(event[1],parent=dialog);return
                except queue.Empty:pass
                if progress_dialog.winfo_exists():progress_dialog.after(120,poll)
            progress_dialog.after(120,poll)

        def delete():
            model_id=selected()
            if not model_id:return
            if not messagebox.askyesno(
                "Delete Structure AI",f"Delete {model_id} and its managed model files?\n\nModels used as a parent by later training are protected.",
                parent=dialog,default="no",
            ):return
            try:self.project.delete_structure_model(model_id)
            except Exception as exc:messagebox.showerror("Delete Structure AI",str(exc),parent=dialog);return
            reload();self._refresh_workflow()
        actions=ttk.Frame(frame);actions.grid(row=2,column=0,columnspan=2,sticky="ew",pady=(9,0))
        ttk.Button(actions,text="Make active",command=activate).pack(side="left")
        ttk.Button(actions,text="Compare with human…",command=compare_human).pack(side="left",padx=(5,0))
        ttk.Button(actions,text="Delete…",command=delete).pack(side="left",padx=(5,0))
        ttk.Button(actions,text="Close",command=dialog.destroy).pack(side="right")
        reload((self.project.active_structure_model() or {}).get("model_id"))

    def _show_structure_model_comparison(self,report,parent=None):
        summary=dict(report.get("summary") or {});traits=list(report.get("traits") or ());structures=list(report.get("structures") or ())
        dialog=tk.Toplevel(parent or self.root);dialog.title("Structure AI vs human");dialog.transient(parent or self.root);dialog.geometry("1120x650");dialog.minsize(900,520)
        outer=ttk.Frame(dialog,padding=12);outer.pack(fill="both",expand=True);outer.columnconfigure(0,weight=1);outer.rowconfigure(3,weight=1)
        ttk.Label(outer,text="Structure AI vs human",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(
            outer,text=f"{summary.get('model_id','')} · validation holdout only · {summary.get('specimens_compared',0)} current human-verified specimens compared. Project data are not changed.",
            style="PageSubtitle.TLabel",wraplength=1060,
        ).grid(row=1,column=0,sticky="w",pady=(2,8))
        def pct(value):
            return "—" if value is None else f"{100*float(value):.1f}%"
        def num(value,digits=3):
            return "—" if value is None else f"{float(value):.{digits}f}"
        exact=f"{int(summary.get('exact_traits') or 0)} / {int(summary.get('exact_traits_total') or 0)} ({pct(summary.get('exact_trait_accuracy'))})"
        all_correct=f"{int(summary.get('all_traits_correct_specimens') or 0)} / {int(summary.get('all_traits_evaluable_specimens') or 0)}"
        role=f"{int(summary.get('reference_role_exact') or 0)} / {int(summary.get('reference_role_total') or 0)} ({pct(summary.get('reference_role_accuracy'))})"
        summary_text=(
            f"Exact trait values: {exact}    ·    All evaluated traits correct: {all_correct}\n"
            f"Repeated count MAE: {num(summary.get('repeated_count_mae'))}    ·    Count bias: {num(summary.get('repeated_count_bias'))}    ·    "
            f"Reference role accuracy: {role}\n"
            f"Marker localization: median {pct(summary.get('localization_median_diag'))} of crop diagonal · p95 {pct(summary.get('localization_p95_diag'))}    ·    "
            f"Macro F1: {num(summary.get('macro_f1'))}"
        )
        ttk.Label(outer,text=summary_text,justify="left",wraplength=1060).grid(row=2,column=0,sticky="w",pady=(0,10))
        notebook=ttk.Notebook(outer);notebook.grid(row=3,column=0,sticky="nsew")
        trait_tab=ttk.Frame(notebook,padding=8);structure_tab=ttk.Frame(notebook,padding=8)
        notebook.add(trait_tab,text="Traits");notebook.add(structure_tab,text="Structures")
        trait_tab.columnconfigure(0,weight=1);trait_tab.rowconfigure(0,weight=1)
        trait_columns=("trait","method","n","accuracy","correct","mae","median","p95")
        trait_tree=ttk.Treeview(trait_tab,columns=trait_columns,show="headings")
        for key,title,width in (
            ("trait","Trait",230),("method","Method",105),("n","Compared",75),("accuracy","Accuracy",95),
            ("correct","Correct / evaluated",135),("mae","MAE",80),("median","Median |error|",105),("p95","P95 |error|",105),
        ):
            trait_tree.heading(key,text=title);trait_tree.column(key,width=width,anchor="w",stretch=key=="trait")
        trait_tree.grid(row=0,column=0,sticky="nsew")
        trait_scroll=ttk.Scrollbar(trait_tab,orient="vertical",command=trait_tree.yview);trait_tree.configure(yscrollcommand=trait_scroll.set);trait_scroll.grid(row=0,column=1,sticky="ns")
        for row in traits:
            accuracy=row.get("accuracy");correct=row.get("correct");evaluated=row.get("evaluated")
            correct_text="—" if correct is None else f"{int(correct)} / {int(evaluated or 0)}"
            trait_tree.insert("","end",values=(
                row.get("abbr") or row.get("name"),row.get("method"),row.get("n",0),pct(accuracy),correct_text,
                num(row.get("mae")),num(row.get("median_abs_error")),num(row.get("p95_abs_error")),
            ))
        structure_tab.columnconfigure(0,weight=1);structure_tab.rowconfigure(0,weight=1)
        structure_columns=("structure","n","prf","count","bias","role","localization")
        structure_tree=ttk.Treeview(structure_tab,columns=structure_columns,show="headings")
        for key,title,width in (
            ("structure","Structure",220),("n","N",55),("prf","Precision / Recall / F1",210),
            ("count","Exact count / MAE",165),("bias","Count bias",90),("role","Role accuracy / MAE",170),
            ("localization","Localization median / p95",180),
        ):
            structure_tree.heading(key,text=title);structure_tree.column(key,width=width,anchor="w",stretch=key=="structure")
        structure_tree.grid(row=0,column=0,sticky="nsew")
        structure_scroll=ttk.Scrollbar(structure_tab,orient="vertical",command=structure_tree.yview);structure_tree.configure(yscrollcommand=structure_scroll.set);structure_scroll.grid(row=0,column=1,sticky="ns")
        for row in structures:
            count_text="—" if row.get("exact_count_accuracy") is None else f"{pct(row.get('exact_count_accuracy'))} / {num(row.get('count_mae'))}"
            role_text="—" if row.get("role_accuracy") is None else f"{pct(row.get('role_accuracy'))} / {num(row.get('role_ordinal_mae'))}"
            loc_text="—" if row.get("localization_median_diag") is None else f"{pct(row.get('localization_median_diag'))} / {pct(row.get('localization_p95_diag'))}"
            structure_tree.insert("","end",values=(
                row.get("name"),row.get("n",0),
                f"{pct(row.get('precision'))} / {pct(row.get('recall'))} / {pct(row.get('f1'))}",
                count_text,num(row.get("count_bias")),role_text,loc_text,
            ))
        note=(
            "Accuracy is shown separately for every discrete or derived trait. For continuous traits it is the share within the scheme's explicit tolerance; without a tolerance, MAE/median/p95 are reported instead of inventing a pass/fail threshold. "
            "Count bias is AI count minus human count. Localization is normalized to the crop diagonal."
        )
        ttk.Label(outer,text=note,style="Muted.TLabel",wraplength=1060).grid(row=4,column=0,sticky="w",pady=(8,0))
        ttk.Button(outer,text="Close",command=dialog.destroy).grid(row=5,column=0,sticky="e",pady=(8,0))

    def _open_structure_review_batch(self,ids):
        ids=[str(value) for value in ids if str(value)]
        if not ids:return False
        self.pass_no.set(1);self.specimen_list.pass_no=1
        state={"pass_no":1,"ids":ids,"position":0}
        self.project.set_ui_state("xray_structure_active_batch",state)
        self._load_specimen(ids[0]);self._refresh_workflow()
        return True

    def _source_exclusion_changed(self,image_id):
        """Mirror Landmarks exclusion: reversible membership change, scientific data kept."""
        image_id=str(image_id);excluded=bool(self.project.source_image(image_id).get("excluded"))
        if excluded:
            remove_result_review_image(self.project,image_id)
            repeat=self.project.structure_repeatability()
            if repeat and str(repeat.get("status") or "")=="in_progress":
                member_ids={str(value) for value in repeat.get("ids") or ()}
                affected={row["specimen_id"] for row in self.project.specimens(image_id) if not row.get("excluded")}
                if member_ids & affected:
                    self.project.retire_structure_repeatability(repeat["run_id"])
                    self.pass_no.set(1);self.specimen_list.pass_no=1
        if excluded and self.selected_specimen_id:
            current=self.project.specimen(self.selected_specimen_id)
            if str(current["image_id"])==image_id:
                active=self.project.structure_specimens(self.pass_no.get())
                target=active[0]["specimen_id"] if active else None
                self.selected_specimen_id=str(target or "")
                self.preferred_image_id=self.project.specimen(target)["image_id"] if target else ""
        self.refresh()
        return True

    def predict_current_structure(self):
        if self._busy or not self.selected_specimen_id:return
        model=self.project.active_structure_model()
        if not model:
            messagebox.showinfo("Predict current","Train or import a Structure AI model first.",parent=self.root);return
        specimen_id=str(self.selected_specimen_id)
        pass_no=int(self.pass_no.get())
        run=self.project.annotation_run(specimen_id,pass_no,"human",False)
        replacing_verified=bool(run and str(run.get("status") or "")=="verified")
        if replacing_verified and not messagebox.askyesno(
            "Predict current",
            "This annotation is already verified.\n\n"
            "Replace its markers with new AI suggestions? The current verified annotation will be archived first. "
            "After correcting the AI suggestions, press Apply to verify the result again.",
            parent=self.root,default="no",
        ):return
        self._busy=True;events=queue.Queue()
        dialog,label,bar=self._structure_ai_dialog("Predict current","Placing AI marker suggestions on this specimen…",1)
        def worker():
            try:events.put(("done",predict_structures(
                self.project,[specimen_id],model=model,pass_no=pass_no,allow_verified=True
            )))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-structure-predict-current").start()
        def poll():
            try:
                event=events.get_nowait()
            except queue.Empty:
                if dialog.winfo_exists():dialog.after(100,poll)
                return
            self._busy=False
            try:dialog.destroy()
            except tk.TclError:pass
            if event[0]=="error":
                messagebox.showerror("Predict current",str(event[1]),parent=self.root);return
            result=event[1];success=list(result.get("success") or ())
            if not success:
                failures=list(result.get("failures") or ())
                detail=str(failures[0].get("reason")) if failures else "No prediction was produced."
                messagebox.showwarning("Predict current",detail,parent=self.root);return
            self._load_specimen(specimen_id);self._refresh_workflow()
        dialog.after(100,poll)

    def predict_structure_batch(self,count):
        if self._busy:return
        model=self.project.active_structure_model()
        if not model:
            messagebox.showinfo("Predict structures","Train or import a Structure AI model first.",parent=self.root);return
        candidates=self.project.structure_prediction_candidate_ids()
        ids=self.project.select_structure_prediction_ids(len(candidates) if count is None else max(1,int(count)))
        if not ids:
            messagebox.showinfo("Predict structures","No eligible unreviewed specimens remain.",parent=self.root);return
        self._busy=True;events=queue.Queue();cancel=threading.Event()
        dialog,label,bar=self._structure_ai_dialog("Predict structures",f"Preparing {len(ids)} specimen(s)…",len(ids))
        ttk.Button(dialog.winfo_children()[0],text="Cancel",command=cancel.set).pack(anchor="e",pady=(8,0))
        def progress(done,total,detail):
            events.put(("progress",int(done),int(total),str(detail)))
        def worker():
            try:events.put(("done",predict_structures(self.project,ids,cancel=cancel,progress=progress,model=model)))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-structure-predict").start()
        def poll():
            try:
                while True:
                    event=events.get_nowait()
                    if event[0]=="progress":
                        bar.configure(value=event[1],maximum=max(1,event[2]));label.configure(text=f"Predicting structures: {event[1]} / {event[2]}")
                    elif event[0]=="error":
                        self._busy=False;dialog.destroy();messagebox.showerror("Predict structures",str(event[1]),parent=self.root);return
                    elif event[0]=="done":
                        self._busy=False;dialog.destroy();result=event[1]
                        success=[row["specimen_id"] for row in result.get("success") or ()]
                        failures=list(result.get("failures") or ())
                        self._refresh_workflow()