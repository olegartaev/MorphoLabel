"""CPU-only regression checks for schema-defined, per-family X-ray model selection."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.xray_component_selection import (
    choose_routed_components, choose_saved_components, combine_marker_rows, structure_families, validated_routes,
)
from app.xray_auto_selection import choose_better_model
from app.xray_schema import bundled_scheme
from app.xray_structure_ai import predict_structures, summarize_structure_ai_human_comparison


class ComponentRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scheme = bundled_scheme("phoxinus_vertebral_counts")

    @staticmethod
    def sample_points(ptery=2, vertebra=3):
        rows = [
            {"structure_id": "vertebra", "x": .1 + .1*i, "y": .5, "sort_order": i}
            for i in range(vertebra)
        ]
        rows.extend([
            {"structure_id": "first_caudal", "x": .3, "y": .5, "sort_order": 0},
            {"structure_id": "last_predorsal", "x": .2, "y": .5, "sort_order": 0},
        ])
        rows.extend([
            {"structure_id": "preanal_pterygiophore", "x": .4 + .1*i, "y": .7, "sort_order": i}
            for i in range(ptery)
        ])
        return rows

    def test_reference_roles_stay_with_their_ordered_series(self):
        groups = [set(group) for group in structure_families(self.scheme)]
        self.assertIn({"vertebra", "first_caudal", "last_predorsal"}, groups)
        self.assertIn({"preanal_pterygiophore"}, groups)
        with self.assertRaisesRegex(ValueError, "same model"):
            validated_routes(
                self.scheme, "old",
                {"vertebra": "new", "first_caudal": "old"}, {"old", "new"},
            )

    def test_component_combiner_never_fabricates_points(self):
        scheme = self.scheme
        assigned = validated_routes(
            scheme, "old",
            {"preanal_pterygiophore": "new"}, {"old", "new"},
        )
        selected = combine_marker_rows(scheme, {
            "old": self.sample_points(ptery=4),
            "new": self.sample_points(ptery=2, vertebra=1),
        }, assigned)
        self.assertEqual(3, sum(x["structure_id"] == "vertebra" for x in selected))
        self.assertEqual(2, sum(x["structure_id"] == "preanal_pterygiophore" for x in selected))
        with self.assertRaises(ValueError):
            combine_marker_rows(scheme, {"old": []}, assigned)

    def test_automatic_search_selects_ptery_source_without_harming_vertebrae(self):
        cases = []
        predictions = {"old": {}, "new": {}}
        for i in range(24):
            sid = f"synthetic-{i}"
            truth = self.sample_points(ptery=2)
            old = self.sample_points(ptery=3 if i < 5 else 2)
            new = self.sample_points(ptery=2, vertebra=2)
            cases.append({"specimen_id": sid, "human": truth,
                          "visibility": {}, "crop_size": (900, 300)})
            predictions["old"][sid] = old
            predictions["new"][sid] = new
        selection = choose_routed_components(
            self.scheme, "old", "new", cases, predictions,
            summarize_structure_ai_human_comparison,
            check=choose_better_model,
        )
        self.assertTrue(selection["accepted"], selection["reason"])
        self.assertEqual("new", selection["routes"]["preanal_pterygiophore"])
        for name in ("vertebra", "first_caudal", "last_predorsal"):
            self.assertEqual("old", selection["routes"][name])
        self.assertEqual(24, selection["report"]["summary"]["all_traits_correct_specimens"])

    def test_no_evidence_keeps_previous_routes(self):
        cases = [{"specimen_id": "synthetic-0", "human": self.sample_points(),
                  "visibility": {}, "crop_size": (900, 300)}]
        predictions = {"old": {"synthetic-0": self.sample_points()},
                       "new": {"synthetic-0": self.sample_points()}}
        selected = choose_routed_components(
            self.scheme, "old", "new", cases, predictions,
            summarize_structure_ai_human_comparison,
            check=choose_better_model,
        )
        self.assertFalse(selected["accepted"])
        self.assertEqual({"old"}, set(selected["routes"].values()))

    def test_saved_sources_search_considers_three_models_on_same_cohort(self):
        cases = []
        predictions = {key: {} for key in ("old", "second", "third")}
        for i in range(24):
            sid = f"case-{i}"
            cases.append({"specimen_id": sid, "human": self.sample_points(), "visibility": {}, "crop_size": (900, 300)})
            predictions["old"][sid] = self.sample_points(ptery=3 if i < 5 else 2)
            predictions["second"][sid] = self.sample_points(ptery=3, vertebra=2)
            predictions["third"][sid] = self.sample_points(ptery=2, vertebra=2)
        result = choose_saved_components(self.scheme, "old", cases, predictions,
                                         summarize_structure_ai_human_comparison, check=choose_better_model)
        self.assertTrue(result["accepted"])
        self.assertEqual("third", result["routes"]["preanal_pterygiophore"])
        self.assertEqual("old", result["routes"]["vertebra"])
        del predictions["second"]["case-0"]
        with self.assertRaisesRegex(ValueError, "same verified"):
            choose_saved_components(self.scheme, "old", cases, predictions,
                                    summarize_structure_ai_human_comparison, check=choose_better_model)

    def test_train_reuses_verified_saved_selection_without_training(self):
        from app.xray_structure_ai import train_structure_model, XRayStructureAIError
        class Project:
            def active_structure_model(self):
                return {"model_id": "active", "metrics": {}, "training_specimen_count": 1,
                        "validation_specimen_count": 1}
            def structure_model_membership(self, ident):
                return [{"specimen_id": "train", "split": "train"},
                        {"specimen_id": "val", "split": "val"}]
            def specimen(self, ident): return {"image_id": ident}
        with patch("app.xray_structure_ai._auto_select_saved_structure_models",
                   return_value={"decision": "selected", "checked_specimens": 12}) as select, \
             patch("app.xray_structure_ai._structure_backend", side_effect=AssertionError("training started")):
            result = train_structure_model(Project(), parent_model_id="active")
        self.assertFalse(result["trained"])
        self.assertEqual("active", result["model_id"])
        self.assertEqual(1, select.call_count)
        with patch("app.xray_structure_ai._auto_select_saved_structure_models", side_effect=ValueError("bad evidence")), \
             patch("app.xray_structure_ai._structure_backend", side_effect=AssertionError("training started")):
            with self.assertRaisesRegex(XRayStructureAIError, "training was not started"):
                train_structure_model(Project(), parent_model_id="active")

    def test_routed_predict_saves_one_combined_model_id(self):
        scheme = self.scheme
        class Project:
            def __init__(self):
                self.scheme = scheme
                self.saved = []
                self.model = {
                    "model_id": "combined", "metrics": {
                        "component_routes": {
                            "vertebra": "old", "first_caudal": "old",
                            "last_predorsal": "old", "preanal_pterygiophore": "new",
                        }
                    },
                }
            def active_structure_model(self):
                return self.model
            def structure_models(self):
                return [self.model, {"model_id": "old"}, {"model_id": "new"}]
            def structure_prediction_candidate_ids(self, *args):
                return ["fish"]
            def structure_specimens(self, *args):
                return [{"specimen_id": "fish"}]
            def seed_structure_predictions(self, specimen_id, points, model_id, **kwargs):
                self.saved.append((specimen_id, points, model_id))
                return {"protected": False}
        project = Project()
        prepared = {
            "old": {"fish": self.sample_points(ptery=4)},
            "new": {"fish": self.sample_points(ptery=2, vertebra=1)},
        }
        with (
            patch("app.xray_structure_ai._scheme_matches_model", return_value=True),
            patch("app.xray_structure_ai._prediction_image", return_value="image.png"),
            patch("app.xray_structure_ai.structure_performance_settings",
                  return_value={"inference": {"device": "cpu", "batch_size": 1}}),
            patch("app.xray_structure_ai._predict_prepared_sources", return_value=(prepared, [], 1))
                  as runner,
        ):
            outcome = predict_structures(project, ["fish"], allow_verified=True)
        self.assertEqual([], outcome["failures"])
        self.assertEqual(1, len(project.saved))
        self.assertEqual("combined", project.saved[0][2])
        self.assertEqual(2, sum(row["structure_id"] == "preanal_pterygiophore"
                                for row in project.saved[0][1]))
        self.assertEqual({"old", "new"}, set(runner.call_args.args[1]))


    def test_training_selection_publishes_immutable_combined_model(self):
        import json
        import tempfile
        from pathlib import Path
        from app.xray_structure_ai import _auto_select_trained_structure_model, _auto_select_saved_structure_models

        scheme = self.scheme
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            class Project:
                def __init__(self):
                    self.root = root
                    self.models_root = root/"models"
                    self.models_root.mkdir()
                    self.scheme = scheme
                    self.models = []
                    self.active_id = "old"
                    self.membership = {}
                    for ident in ("old", "new"):
                        folder = self.models_root/ident
                        folder.mkdir()
                        (folder/"model.pth").write_bytes(b"test checkpoint")
                        (folder/"model.json").write_text(
                            json.dumps({"backend":"resnet18_heatmap_v1","schema_digest":"same"}),
                            encoding="utf-8",
                        )
                        self.models.append({
                            "model_id":ident,"parent_model_id":None,"schema_digest":"same",
                            "backend":"resnet18_heatmap_v1","path":str((folder/"model.pth").relative_to(root)),
                            "metadata_path":str((folder/"model.json").relative_to(root)),
                        })
                        self.membership[ident] = [
                            {"specimen_id":"train","split":"train"},
                            *[{"specimen_id":f"synthetic-{j}","split":"val"} for j in range(24)],
                        ]
                def structure_models(self):
                    return self.models
                def structure_model_membership(self, ident):
                    return self.membership[ident]
                def specimen(self, ident):
                    return {"image_id":"train-plate" if ident=="train" else
                            f"validation-{int(ident.split('-')[1])//8}"}
                def annotation_run(self, ident, *args):
                    return {"status":"verified"}
                def effective_annotations(self, ident, *args):
                    return ComponentRoutingTests.sample_points()
                def structure_visibility_states(self, ident, *args):
                    return {}
                def specimen_crop_size(self, ident):
                    return (900, 300)
                def next_structure_model_id(self):
                    return "combined-v001"
                def register_structure_model(self, ident, path, metadata_path, parent,
                                             digest, backend, metrics, membership,
                                             **kwargs):
                    self.models.append({
                        "model_id": ident, "path": path, "metadata_path": metadata_path,
                        "parent_model_id": parent, "schema_digest":digest,
                        "backend": backend, "metrics":metrics,
                    })
                    self.membership[ident] = list(membership)
                    if kwargs.get("activate"):
                        self.active_id = ident
                def activate_structure_model(self, ident):
                    self.active_id = ident

            project = Project()
            old_points = {
                f"synthetic-{j}":self.sample_points(ptery=3 if j < 5 else 2)
                for j in range(24)
            }
            new_points = {
                f"synthetic-{j}":self.sample_points(ptery=2, vertebra=2)
                for j in range(24)
            }
            def model_report(_project, model_id, **_kwargs):
                return {
                    "summary":{"skipped_not_verified":0,"prediction_failures":0},
                    "failures":[],
                    "prediction_rows":old_points if model_id=="old" else new_points,
                }
            with (
                patch("app.xray_structure_ai._scheme_matches_model",return_value=True),
                patch("app.xray_structure_ai.compare_structure_model_to_human",
                      side_effect=model_report),
            ):
                decision = _auto_select_trained_structure_model(project, project.models[0], "new")
            self.assertEqual("combined",decision["decision"])
            # The Models dialog must display the selected combination's score,
            # not the superseded baseline's score.
            self.assertEqual(24, decision["candidate_complete"])
            self.assertEqual(24, decision["evaluated_specimens"])
            self.assertEqual("combined-v001",project.active_id)
            combined = project.models[-1]
            self.assertEqual("new",combined["metrics"]["component_routes"]["preanal_pterygiophore"])
            self.assertEqual("old",combined["metrics"]["component_routes"]["vertebra"])
            self.assertTrue((root/combined["path"]).is_file())
            self.assertEqual("old",json.loads((root/combined["metadata_path"]).read_text())["parent_model_id"])
            self.assertEqual(24,sum(x["split"]=="val" for x in project.membership["combined-v001"]))
            self.assertEqual("old",project.models[0]["model_id"])
            self.assertEqual("new",project.models[1]["model_id"])
            # The saved-model path uses the same real publication and cohort checks.
            project.models.pop()
            project.membership.pop("combined-v001")
            import shutil
            shutil.rmtree(root / "models" / "combined-v001")
            project.active_id = "old"
            with (
                patch("app.xray_structure_ai._scheme_matches_model", return_value=True),
                patch("app.xray_structure_ai.compare_structure_model_to_human", side_effect=model_report),
            ):
                saved = _auto_select_saved_structure_models(project, project.models[0])
            self.assertEqual("combined", saved["decision"])
            self.assertEqual("new", project.models[-1]["metrics"]["component_routes"]["preanal_pterygiophore"])


    def test_combined_provenance_excludes_unselected_candidate_training(self):
        import json
        import tempfile
        from pathlib import Path
        from app.xray_structure_ai import _publish_routed_structure_model
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models_root = root/"models"
            models_root.mkdir()
            models = {}
            for ident in ("baseline", "unused_candidate", "chosen"):
                directory = models_root/ident
                directory.mkdir()
                (directory/"model.pth").write_bytes(b"sample weights")
                (directory/"model.json").write_text(
                    json.dumps({"backend":"resnet18_heatmap_v1","schema_digest":"digest"}),
                    encoding="utf-8",
                )
                models[ident] = {
                    "model_id": ident,
                    "path": str((directory/"model.pth").relative_to(root)),
                    "metadata_path": str((directory/"model.json").relative_to(root)),
                    "schema_digest": "digest", "backend": "resnet18_heatmap_v1",
                }
            memberships = {
                ident: [{"specimen_id":f"train_{ident}","split":"train"}]
                for ident in models
            }
            class Project:
                def __init__(self):
                    self.root = root
                    self.models_root = models_root
                    self.published = None
                def structure_models(self):
                    return list(models.values())
                def structure_model_membership(self, ident):
                    return memberships[ident]
                def next_structure_model_id(self):
                    return "combined"
                def register_structure_model(self, *args, **kwargs):
                    self.published = (args,kwargs)
            project = Project()
            routes = {
                "vertebra":"baseline", "first_caudal":"baseline",
                "last_predorsal":"baseline", "preanal_pterygiophore":"chosen",
            }
            _publish_routed_structure_model(
                project, models["baseline"], models["unused_candidate"],
                routes, ["validation_1"], {"decision":"selected"},
            )
            members = {row["specimen_id"]:row["split"] for row in project.published[7]}
            self.assertEqual({
                "train_baseline":"train", "train_chosen":"train",
                "validation_1":"val",
            }, members)
            self.assertTrue((models_root/"combined"/"model.pth").is_file())


    def test_scalar_count_cannot_masquerade_as_zero_point_markers(self):
        import tempfile
        from pathlib import Path
        from app.xray_structure_ai import _predict_prepared_sources
        class CountOnly:
            def predict_many(self, payload, timeout):
                return {"results":[{"structures":[{
                    "structure_id":"preanal_pterygiophore",
                    "count":4, "points":[],
                }]}]}
        with tempfile.TemporaryDirectory() as directory:
            project=type("Project",(),{"root":Path(directory)})()
            models={"count":{"model_id":"count","path":"count.pth","metadata_path":"count.json"}}
            with patch("app.xray_structure_ai.backend_for_structure_model",return_value=CountOnly()):
                outputs,failures,_batch=_predict_prepared_sources(
                    project,models,[("fish",Path(directory)/"fish.png")],
                    {"device":"cpu","batch_size":1},
                )
            self.assertEqual({},outputs["count"])
            self.assertEqual(1,len(failures))
            self.assertIn("Scalar-only",failures[0]["reason"])


if __name__ == "__main__":
    unittest.main()
