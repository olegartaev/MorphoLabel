"""Corrected launch entry point for the Block 1 editor."""
from .gui_full import Editor

class Operator(Editor):
    def __init__(self):
        super().__init__()
        self.calibration_clicks = None

def run():
    Operator().mainloop()

if __name__ == "__main__": run()
