"""Current operator launch: sample image counts are visible in the browser."""
from collections import Counter
from pathlib import Path
from .operator_v6 import OperatorV6

class OperatorV7(OperatorV6):
    def _layout(self):
        super()._layout()
        counts=Counter(row["sample_id"] for row in self.images)
        self.listing.delete(0,"end")
        for row in self.images:
            self.listing.insert("end",f"{row['sample_id']} ({counts[row['sample_id']]} images) | {Path(row['source_relpath']).name}")

def run():
    app=OperatorV7(); app.calibration_clicks=None; app.mainloop()

if __name__ == "__main__": run()
