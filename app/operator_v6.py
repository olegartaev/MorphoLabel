"""Operator launch with visibly reviewable calibration line."""
from .operator_v5 import OperatorV5
from .storage import load_calibration

class OperatorV6(OperatorV5):
    def render(self):
        super().render()
        calibration=load_calibration(self.current()["sample_id"]); points=calibration.get("points_standardized")
        if points and len(points)==2:
            (x1,y1),(x2,y2)=points; x1*=self.zoom; y1*=self.zoom; x2*=self.zoom; y2*=self.zoom
            self.canvas.create_line(x1,y1,x2,y2,fill="#55ff55",width=3)
            self.canvas.create_text((x1+x2)/2,(y1+y2)/2,text=f"{calibration.get('physical_length_mm')} mm",fill="#55ff55")

def run():
    app=OperatorV6(); app.calibration_clicks=None; app.mainloop()

if __name__ == "__main__": run()
