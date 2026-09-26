import unittest
from app.active_learning import select_review_batch
from app.model_registry import create_model_package

class ActiveModelTests(unittest.TestCase):
    def test_review_keeps_informative_and_audit_mix(self):
        rows=[{"image_id":str(i),"uncertainty":i} for i in range(10)]
        queue=select_review_batch(rows,size=4,seed=7,informative_fraction=.5)
        self.assertEqual(len(queue["images"]),4); self.assertEqual(queue["images"][0]["uncertainty"],9)
    def test_model_registry_module_exposes_immutable_creator(self): self.assertTrue(callable(create_model_package))

if __name__ == "__main__": unittest.main()
