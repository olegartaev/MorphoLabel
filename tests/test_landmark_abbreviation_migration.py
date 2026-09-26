import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from app.measurements import load_measurements, save_measurements
from app.project_storage import Project


def write_schema(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("id", "abbr", "name", "role"))
        writer.writerows(rows)


class LandmarkAbbreviationMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "source" / "sample"
        self.source.mkdir(parents=True)
        Image.new("RGB", (40, 30), "white").save(self.source / "specimen.jpg")
        self.schema = root / "schema.csv"
        write_schema(self.schema, [(1, "A", "A", "BOTH"), (2, "B", "B", "BOTH"), (3, "C", "C", "BOTH"), (4, "D", "D", "BOTH"), (5, "E", "E", "BOTH")])
        self.project = Project.create("project", self.source.parent, root, self.schema, source_layout="direct")
        self.image_id = self.project.catalog_rows()[0]["image_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_new_project_can_start_without_a_landmark_scheme(self):
        root = Path(self.temp.name)
        project = Project.create("empty_scheme", self.source.parent, root, source_layout="direct")
        self.assertEqual([], project.schema)
        self.assertEqual([], Project.open(project.root).schema)
        self.assertIn("abbr,name", project.schema_path.read_text(encoding="utf-8"))
    def test_backup_migrate_delete_and_reorder_follow_abbreviations(self):
        for display, coordinate in enumerate((10, 20, 30, 40, 50), 1):
            self.project.save_landmark(self.image_id, display, coordinate, coordinate + 1, "manual", "manual")
        save_measurements(self.project, [{"use": True, "abbr": "AE", "name": "A to E", "point1": 1, "point2": 5}])
        connection = sqlite3.connect(self.project.path)
        connection.execute("DROP INDEX IF EXISTS idx_landmarks_image_abbr")
        connection.execute("ALTER TABLE landmarks DROP COLUMN landmark_abbr")
        connection.commit()
        connection.close()
        reopened = Project.open(self.project.root)
        backups = sorted((reopened.root / "backups").glob("schema_identity_*"))
        self.assertTrue(backups)
        manifest = (backups[-1] / "migration.json").read_text(encoding="utf-8")
        self.assertIn("project.sqlite", manifest)
        self.assertIn("landmark_schema.csv", manifest)
        with reopened.transaction() as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM landmarks WHERE landmark_abbr IS NULL").fetchone()[0])
        write_schema(reopened.schema_path, [("row-1", "A", "A", "BOTH"), ("row-3", "C", "C", "BOTH"), ("row-5", "E", "E", "BOTH")])
        reduced = Project.open(reopened.root)
        points = reduced.load_landmarks(self.image_id)
        self.assertEqual({1: 10.0, 2: 30.0, 3: 50.0}, {key: value["x_standardized"] for key, value in points.items()})
        with reduced.transaction() as connection:
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM landmarks WHERE landmark_abbr IN ('B','D')").fetchone()[0])
        write_schema(reduced.schema_path, [(99, "E", "E", "BOTH"), (8, "A", "A", "BOTH"), (1, "C", "C", "BOTH")])
        reordered = Project.open(reduced.root)
        points = reordered.load_landmarks(self.image_id)
        self.assertEqual({1: 50.0, 2: 10.0, 3: 30.0}, {key: value["x_standardized"] for key, value in points.items()})
        measurement = load_measurements(reordered)[0]
        self.assertEqual(("A", "E", 2, 1), (measurement["point1_abbr"], measurement["point2_abbr"], measurement["point1"], measurement["point2"]))


if __name__ == "__main__":
    unittest.main()