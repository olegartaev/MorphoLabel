"""Unified scientific export identity remains traceable without filename guessing."""
import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.export_formats import export_landmark_csv_long, export_landmark_tps, export_landmark_wide, export_morphoj_text
from app.measurements import export_measurements
from app.project_storage import Project
from app.results_export import parse_tps
from app.xray_crop import crop_from_geometry
from app.xray_project import XRayProject
from app.xray_schema import bundled_scheme
from app.xray_trait_export import export_trait_rows
from app.export_identity import export_identity
from app.export_formats import _morphoj_identifier


IDENTITY = ["specimen_id", "image_id", "sample_id", "locality", "filename", "source_relative_path"]


class UnifiedLandmarkExportIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root / "source"
        for sample in ("Образец А", "Образец Б"):
            folder = self.source / sample; folder.mkdir(parents=True)
            Image.new("RGB", (40, 30), (10, 20, 30)).save(folder / "одинаковое.png")
        scheme = self.root / "scheme.csv"
        scheme.write_text("id,abbr,name,role\n1,A,Alpha,GM\n2,B,Beta,GM\n", encoding="utf-8")
        self.project = Project.create("identity", self.source, self.root, scheme, source_layout="direct")
        self.rows = self.project.catalog_rows()
        for row in self.rows:
            self.project.save_landmark(row["image_id"], 1, 1.234567, 2.345678, "manual", "manual")
            self.project.save_landmark(row["image_id"], 2, 3.456789, 4.567891, "manual", "manual")
        (self.project.root / "measurement_schema.csv").write_text(
            "Use,Abbr,Name,Point1,Point2,Point1Abbr,Point2Abbr\n1,Len,Length,1,2,A,B\n", encoding="utf-8")

    def read(self, path):
        with Path(path).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_missing_identity_is_never_inferred_from_filename(self):
        missing = export_identity({"image_id": "persisted-image", "original_name": "same.png"})
        self.assertEqual("", missing["specimen_id"])
        self.assertEqual("", missing["sample_id"])
        self.assertEqual("", missing["locality"])
        self.assertEqual("same.png", missing["filename"])
        self.assertEqual("", missing["source_relative_path"])
        self.assertEqual("", _morphoj_identifier({"original_name": "same.png"}))

    def test_wide_long_and_measurements_share_actual_identity(self):
        before = self.project.path.read_bytes()
        photo_hashes = {row["relative_path"]: (self.source / row["relative_path"]).read_bytes() for row in self.rows}
        wide = self.read(export_landmark_wide(self.project, target=self.root / "wide.csv"))
        long = self.read(export_landmark_csv_long(self.project, target=self.root / "long.csv"))
        measurements = self.read(export_measurements(self.project, target=self.root / "measurements.csv")["path"])
        self.assertEqual(self.project.path.read_bytes(), before)
        self.assertEqual(photo_hashes, {row["relative_path"]: (self.source / row["relative_path"]).read_bytes() for row in self.rows})
        for rows in (wide, measurements):
            self.assertEqual(IDENTITY, list(rows[0])[:6])
        self.assertEqual(IDENTITY, list(long[0])[:6])
        expected = {row["image_id"]: {key: row[key] for key in IDENTITY} for row in wide}
        self.assertEqual(2, len({row["specimen_id"] for row in wide}))
        self.assertEqual(2, len({row["image_id"] for row in wide}))
        self.assertEqual({"одинаковое.png"}, {row["filename"] for row in wide})
        self.assertEqual({"Образец А", "Образец Б"}, {row["sample_id"] for row in wide})
        for rows in (long, measurements):
            for row in rows:
                self.assertEqual(expected[row["image_id"]], {key: row[key] for key in IDENTITY})
        self.assertEqual("1.23457", wide[0]["x1"])
        self.assertEqual("1.23457", long[0]["x_standardized"])
        # No calibration/cache is stored in this synthetic source, so values
        # remain blank while the identity row is still exported.
        self.assertEqual(["", ""], [row["Len_mm"] for row in measurements])

    def test_standalone_tps_and_morphoj_have_exact_id_crosswalks_and_unchanged_matrix(self):
        tps = export_landmark_tps(self.project, target=self.root / "shape.tps")
        morphoj = export_morphoj_text(self.project, target=self.root / "shape.txt")
        for source, exported_ids, delimiter in (
            (tps, {row["image_id"] for row in self.rows}, None),
            (morphoj, {row["image_id"] for row in self.rows}, "\t"),
        ):
            sidecar = source.with_name(f"{source.stem}_specimens.csv")
            mapping = self.read(sidecar)
            self.assertEqual(len(exported_ids), len(mapping))
            self.assertEqual(exported_ids, {row["exported_id"] for row in mapping})
            self.assertEqual(len(mapping), len({row["exported_id"] for row in mapping}))
            self.assertEqual({row["image_id"] for row in mapping}, exported_ids)
        tps_text = tps.read_text(encoding="utf-8")
        self.assertEqual(2, tps_text.count("LM=2"))
        self.assertIn("IMAGE=одинаковое.png", tps_text)
        self.assertNotIn("specimen_id", tps_text)
        with morphoj.open(encoding="utf-8", newline="") as stream:
            matrix = list(csv.reader(stream, delimiter="\t"))
        self.assertEqual(["ID", "x1", "y1", "x2", "y2"], matrix[0])
        self.assertEqual(5, len(matrix[1]))
        self.assertEqual(2, len(matrix) - 1)

    def test_missing_metadata_stays_blank_and_bundle_keeps_single_crosswalk(self):
        row = self.rows[0]
        with self.project.transaction() as db:
            db.execute("UPDATE images SET sample_id=NULL,locality=NULL WHERE image_id=?", (row["image_id"],))
        wide = self.read(export_landmark_wide(self.project, target=self.root / "missing.csv"))[0]
        self.assertEqual("", wide["sample_id"])
        self.assertEqual("", wide["locality"])

    def test_analysis_bundle_reuses_crosswalk_without_tps_sidecars(self):
        from app.analysis_export import SCOPE_ALL, export_analysis_bundle

        destination = self.root / "bundle"
        before = self.project.path.read_bytes()
        export_analysis_bundle(self.project, destination, scope=SCOPE_ALL)
        self.assertEqual(before, self.project.path.read_bytes())
        specimens = self.read(destination / "specimens.csv")
        wide = self.read(destination / "landmarks_wide_ALL.csv")
        long = self.read(destination / "landmarks_long.csv")
        measured = self.read(destination / "measurements.csv")
        self.assertEqual(IDENTITY, list(specimens[0])[:6])
        crosswalk = {row["image_id"]: {key: row[key] for key in IDENTITY} for row in specimens}
        for rows in (wide, measured, long):
            for row in rows:
                self.assertEqual(crosswalk[row["image_id"]], {key: row[key] for key in IDENTITY})
        names = {path.name for path in destination.iterdir()}
        self.assertFalse(any(name.endswith("_specimens.csv") for name in names))
        tps_ids = {block["ID"] for block in parse_tps(destination / "landmarks_all.tps")}
        with (destination / "landmarks_MorphoJ_ALL.txt").open(encoding="utf-8", newline="") as stream:
            morphoj_ids = {row[0] for row in list(csv.reader(stream, delimiter="\t"))[1:]}
        image_ids = {row["image_id"] for row in specimens}
        self.assertEqual(image_ids, tps_ids)
        self.assertEqual(image_ids, morphoj_ids)
        self.assertTrue(all(sum(row["image_id"] == ident for row in specimens) == 1 for ident in tps_ids | morphoj_ids))


class UnifiedXrayExportIdentityTests(unittest.TestCase):
    def test_same_plate_multiple_specimens_keep_unique_ids_and_ui_sample_path(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); source = root / "source" / "Выборка А"; source.mkdir(parents=True)
        Image.new("L", (800, 400), 100).save(source / "plate.png")
        project = XRayProject.create("xray", root / "source", root, bundled_scheme("phoxinus_vertebral_counts"))
        plate = project.source_images()[0]["image_id"]
        one = project.add_manual_specimen(plate, crop_from_geometry(400, 100, 700, 100, 0, (800, 400), algorithm="manual"))
        two = project.add_manual_specimen(plate, crop_from_geometry(400, 300, 700, 100, 0, (800, 400), algorithm="manual"))
        project.confirm_plate(plate)
        target = root / "traits.csv"; export_trait_rows(project, target)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertTrue({"sample_id", "filename"} <= set(rows[0]))
        self.assertEqual({one, two}, {row["specimen_id"] for row in rows})
        self.assertEqual({project.specimen(one)["image_id"]}, {row["image_id"] for row in rows})
        self.assertEqual({"Выборка А"}, {row["sample_id"] for row in rows})
        self.assertEqual({"plate.png"}, {row["filename"] for row in rows})
        self.assertEqual(2, len({(row["specimen_id"], row["image_id"]) for row in rows}))


if __name__ == "__main__":
    unittest.main()
