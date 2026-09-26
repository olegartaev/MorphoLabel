import tkinter as tk
import unittest
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch

from app.ui.workflow import columns_for_width
from app.ui.tooltips import clamp_popup
from app.ui.landmark_display import normalize_display_settings


class WorkflowLayoutTests(unittest.TestCase):
    def _production_landmarks_harness(self, width, height):
        from app.ui import landmarks_section
        from app.ui.landmarks_section import LandmarksSection

        class Project:
            def active_model_readonly(self, _kind):
                return {}

            def get_ui_state(self, _key, default=None):
                return default

        class Tip:
            def bind(self, *_args, **_kwargs):
                return None

        class Shell(tk.Tk):
            def __init__(self):
                super().__init__()
                self.context = SimpleNamespace(project=Project())
                self.tip = Tip()

            def control_button(self, parent, text, command, _help, **kwargs):
                state = kwargs.pop("state", "normal")
                style = kwargs.pop("style", "TButton")
                kwargs.pop("primary", None)
                kwargs.pop("enabled", None)
                return ttk.Button(parent, text=text, command=command, state=state, style=style, **kwargs)

            def show_models(self, *_args):
                return None

        class Canvas:
            def __init__(self, parent, *_args, **_kwargs):
                self.widget = tk.Canvas(parent, width=2400, height=1800)
                self.widget.pack(fill="both", expand=True)
                self.on_image_ready = None
                self.state = None
                self.choice = tk.IntVar(master=parent, value=1)

            def redraw_cached(self):
                return None

            def toggle_missing(self):
                return None

            def delete_current(self):
                return None

            def clear_all(self):
                return None

            def mark_checked(self):
                return None

        shell = Shell()
        self.addCleanup(lambda: shell.destroy() if shell.winfo_exists() else None)
        shell.geometry(f"{width}x{height}+0+0")
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)
        outer = ttk.Frame(shell, padding=(8, 6))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)
        nav = ttk.Frame(outer, height=42)
        nav.grid(row=0, column=0, sticky="ew")
        nav.grid_propagate(False)
        workspace = ttk.Frame(outer)
        workspace.grid(row=1, column=0, sticky="nsew")
        workspace.rowconfigure(0, weight=1)
        workspace.columnconfigure(1, weight=1)
        sidebar = ttk.Frame(workspace, width=310)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        main = ttk.Frame(workspace)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=1)
        status = ttk.Frame(main, height=28)
        status.grid(row=0, column=0, sticky="ew")
        status.grid_propagate(False)
        section_host = ttk.Frame(main)
        section_host.grid(row=1, column=0, sticky="nsew")
        with (
            patch.object(landmarks_section, "LandmarkCanvasController", Canvas),
            patch.object(landmarks_section, "current_run", return_value=None),
            patch.object(landmarks_section, "previous_runs", return_value=[]),
            patch.object(landmarks_section, "available_control_image_ids", return_value=()),
            patch.object(landmarks_section, "stage_summary", return_value={"stage": None, "state": {"initial_image_ids": []}, "verified": 0, "total": 0}),
            patch.object(landmarks_section, "available_training_parents", return_value=[]),
            patch.object(LandmarksSection, "_refresh_landmark_sidebar", return_value=None),
            patch.object(LandmarksSection, "_refresh_action_buttons", return_value=None),
        ):
            view = LandmarksSection(shell, section_host)
            view.render()
        shell.update_idletasks()
        shell.update()
        panel = section_host.winfo_children()[0]
        dock = panel.grid_slaves(row=2, column=0)[0]
        return shell, section_host, panel, view.canvas_frame, dock

    def test_cards_use_full_row_when_real_requested_widths_fit(self):
        self.assertEqual(4, columns_for_width(1262, 4, [245, 255, 300, 410]))
        self.assertEqual(3, columns_for_width(1000, 3, [245, 255, 300]))

    def test_cards_wrap_to_two_columns_when_four_do_not_fit(self):
        widths=[245,255,300,410]
        self.assertEqual(2, columns_for_width(900, 4, widths))
        self.assertEqual(2, columns_for_width(700, 3, widths[:3]))

    def test_cards_stack_when_pair_does_not_fit(self):
        self.assertEqual(1, columns_for_width(500, 4, [260,260,300,410]))

    def test_production_landmarks_workflow_geometry_and_resize(self):
        shell, section_host, panel, canvas_frame, dock = self._production_landmarks_harness(1600, 900)
        cards = tuple(dock._cards)
        self.assertEqual(4, len(cards))
        self.assertTrue(all(card.winfo_ismapped() for card in cards))

        def assert_fits(label):
            shell.update_idletasks()
            shell.update()
            width = dock.winfo_width()
            bottoms = [card.winfo_rooty() + card.winfo_height() for card in cards]
            visible_bottom = section_host.winfo_rooty() + section_host.winfo_height()
            self.assertLessEqual(max(bottoms), visible_bottom, f"{label}: cards={bottoms}, visible_bottom={visible_bottom}, dock_width={width}")
            self.assertLessEqual(dock.winfo_rooty() + dock.winfo_height(), visible_bottom, f"{label}: dock extends below section host")
            self.assertLessEqual(canvas_frame.winfo_rooty() + canvas_frame.winfo_height(), dock.winfo_rooty(), f"{label}: canvas overlaps workflow")
            self.assertGreater(canvas_frame.winfo_height(), 0, f"{label}: canvas has no remaining space")
            cards_left=dock.cards_host.winfo_rootx();cards_right=cards_left+dock.cards_host.winfo_width()
            cards_top=dock.cards_host.winfo_rooty();cards_bottom=cards_top+dock.cards_host.winfo_height()
            for index, card in enumerate(cards):
                self.assertGreater(card.winfo_width(), 0, f"{label}: card {index + 1} has no width")
                self.assertGreater(card.winfo_height(), 0, f"{label}: card {index + 1} has no height")
                self.assertGreaterEqual(card.winfo_rootx(), cards_left, f"{label}: card {index + 1} spills left")
                self.assertLessEqual(card.winfo_rootx()+card.winfo_width(), cards_right, f"{label}: card {index + 1} spills right")
                self.assertGreaterEqual(card.winfo_rooty(), cards_top, f"{label}: card {index + 1} spills above card host")
                self.assertLessEqual(card.winfo_rooty()+card.winfo_height(), cards_bottom, f"{label}: card {index + 1} spills below card host")
                descendants=list(card.winfo_children())
                while descendants:
                    child=descendants.pop()
                    descendants.extend(child.winfo_children())
                    if child.winfo_ismapped() and child.winfo_width():
                        child_left=child.winfo_rootx();child_right=child_left+child.winfo_width()
                        card_left=card.winfo_rootx();card_right=card_left+card.winfo_width()
                        self.assertGreaterEqual(child_left,card_left,f"{label}: card {index + 1} child {child} spills left")
                        self.assertLessEqual(child_right,card_right,f"{label}: card {index + 1} child {child} is clipped horizontally")
            return width

        wide_width = assert_fits("1600x900")
        card_geometry = tuple((card.winfo_x(), card.winfo_y(), card.winfo_width(), card.winfo_height(), card.winfo_reqwidth(), card.winfo_reqheight()) for card in cards)
        geometry = (f"1600x900 created {dock._last_columns} columns at dock width {wide_width}; "
                    f"section_host={section_host.winfo_width()}x{section_host.winfo_height()} "
                    f"panel={panel.winfo_width()}x{panel.winfo_height()} "
                    f"canvas={canvas_frame.winfo_width()}x{canvas_frame.winfo_height()} req={canvas_frame.winfo_reqheight()} "
                    f"dock={dock.winfo_width()}x{dock.winfo_height()} req={dock.winfo_reqheight()} "
                    f"cards_host={dock.cards_host.winfo_width()}x{dock.cards_host.winfo_height()} req={dock.cards_host.winfo_reqheight()} "
                    f"cards={card_geometry}")
        self.assertEqual(4, dock._last_columns, geometry)

        shell.geometry("1200x900+0+0")
        medium_width = assert_fits("1200x900")
        self.assertEqual(2, dock._last_columns, f"1200x900 created {dock._last_columns} columns at dock width {medium_width}")

        shell.geometry("850x900+0+0")
        narrow_width = assert_fits("850x900")
        self.assertEqual(1, dock._last_columns, f"850x900 created {dock._last_columns} columns at dock width {narrow_width}")

        shell.geometry("1600x900+0+0")
        restored_width = assert_fits("resize back to 1600x900")
        self.assertEqual(4, dock._last_columns, f"restored layout created {dock._last_columns} columns at dock width {restored_width}")

    def test_popup_moves_above_bottom_work_area(self):
        x, y = clamp_popup(
            1700, 1020, 260, 120,
            (0, 0, 1920, 1040),
            above_y=1000,
        )
        self.assertLessEqual(x + 260, 1912)
        self.assertLessEqual(y + 120, 1032)
        self.assertEqual(880, y)

    def test_popup_clamps_to_left_and_top_edges(self):
        self.assertEqual(
            (8, 8),
            clamp_popup(-50, -20, 200, 80, (0, 0, 1920, 1040)),
        )

    def test_landmark_display_settings_are_bounded_and_valid(self):
        settings = normalize_display_settings({
            "selected_color": "#112233",
            "other_color": "bad",
            "size": 99,
            "symbol": "filled_circle",
            "label": "name",
            "label_size": 40,
            "halo": "white",
        })
        self.assertEqual("#112233", settings["selected_color"])
        self.assertEqual("#00e5ff", settings["other_color"])
        self.assertEqual(12, settings["size"])
        self.assertEqual("filled_circle", settings["symbol"])
        self.assertEqual("name", settings["label"])
        self.assertEqual(24, settings["label_size"])
        self.assertEqual("white", settings["halo"])


if __name__ == "__main__":
    unittest.main()
