from tkinter import messagebox
from .operator_v4 import OperatorV4
from .dataset_v2 import export_training_dataset

class OperatorV5(OperatorV4):
    def export_training(self):
        result=export_training_dataset(self.profile.profile_id)
        messagebox.showinfo("Training export",f"Eligible fully final images: {len(result['images'])}\nExcluded incomplete/nonhuman-final: {len(result['excluded'])}")

def run():
    app=OperatorV5(); app.calibration_clicks=None; app.mainloop()

if __name__ == "__main__": run()
