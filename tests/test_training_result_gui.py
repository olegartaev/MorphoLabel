import unittest

from app.editor_ready_v15 import format_internal_validation
from app.landmark_training_workflow import validation_metrics


class TrainingResultGuiTests(unittest.TestCase):
 def test_new_result_displays_percent_metrics_best_epoch_and_ema(self):
  metrics=validation_metrics({'result':{'engineering_validation':{'median_error_percent':1.234,'p90_error_percent':2.345,'p95_error_percent':3.456},'best_epoch':210,'ema_used':True}})
  text=format_internal_validation(metrics)
  self.assertIn('Median: 1.23% of reference span',text)
  self.assertIn('P90: 2.35%',text)
  self.assertIn('P95: 3.46%',text)
  self.assertIn('Best checkpoint: epoch 210',text)
  self.assertIn('EMA: Yes',text)
 def test_legacy_result_still_opens_safely(self):
  text=format_internal_validation(validation_metrics({'result':{}}))
  self.assertEqual('Internal validation:\nMedian: Unavailable of reference span\nP90: Unavailable\nP95: Unavailable\nBest checkpoint: Unavailable\nEMA: Unavailable',text)


if __name__=='__main__': unittest.main()