import unittest
from app.ui.scrollbars import autohide_scroll_command


class FakeScrollbar:
    def __init__(self, mode):
        self.mode=mode
        self.actions=[]
        self.last=None
    def winfo_manager(self):
        return self.mode
    def grid_remove(self):
        self.actions.append("hide_grid")
        self.mode=""
    def grid(self):
        self.actions.append("show_grid")
        self.mode="grid"
    def pack_forget(self):
        self.actions.append("hide_pack")
        self.mode=""
    def pack(self, **kwargs):
        self.actions.append(("show_pack",kwargs))
        self.mode="pack"
    def set(self,a,b):
        self.last=(a,b)


class AutohideTests(unittest.TestCase):
    def test_grid_scrollbar_hides_when_fully_visible_and_returns(self):
        s=FakeScrollbar("grid")
        update=autohide_scroll_command(s)
        update("0.0","1.0")
        self.assertEqual(s.actions,["hide_grid"])
        update("0.0","0.8")
        self.assertEqual(s.actions,["hide_grid","show_grid"])
        update("0.3","1")
        self.assertEqual(s.actions,["hide_grid","show_grid"])
        update("0","1")
        self.assertEqual(s.actions[-1],"hide_grid")
    def test_pack_scrollbar_stays_hidden_until_needed(self):
        s=FakeScrollbar("pack")
        update=autohide_scroll_command(s,geometry="pack")
        update("0","1")
        update("0","1")
        self.assertEqual(s.actions,["hide_pack"])
        update("0","0.5")
        self.assertEqual(s.actions[-1],("show_pack",{"side":"right","fill":"y"}))
    def test_invalid_geometry_rejected(self):
        with self.assertRaises(ValueError):
            autohide_scroll_command(FakeScrollbar("grid"),geometry="place")


if __name__=="__main__":
    unittest.main()
