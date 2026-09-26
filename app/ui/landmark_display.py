"""Shared, project-persistent landmark display preferences."""
from __future__ import annotations

DEFAULT_SELECTED = "#ffb000"
DEFAULT_OTHER = "#00e5ff"
DEFAULT_SIZE = 5
DEFAULT_SYMBOL = "circle"
DEFAULT_LABEL = "number"
DEFAULT_LABEL_SIZE = 10
DEFAULT_HALO = "none"

SYMBOL_LABELS = {
    "Circle": "circle",
    "Filled circle": "filled_circle",
    "Cross": "cross",
    "Target": "target",
}
SYMBOL_NAMES = {value: key for key, value in SYMBOL_LABELS.items()}
LABEL_LABELS = {"Number": "number", "Name": "name", "No label": "none"}
LABEL_NAMES = {value: key for key, value in LABEL_LABELS.items()}
HALO_LABELS = {"None": "none", "White": "white", "Black": "black"}
HALO_NAMES = {value: key for key, value in HALO_LABELS.items()}


def _color(value, fallback):
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text.lower()
        except ValueError:
            pass
    return fallback


def normalize_display_settings(value=None):
    value = value if isinstance(value, dict) else {}
    try:
        size = int(value.get("size", DEFAULT_SIZE))
    except (TypeError, ValueError):
        size = DEFAULT_SIZE
    try:
        label_size = int(value.get("label_size", DEFAULT_LABEL_SIZE))
    except (TypeError, ValueError):
        label_size = DEFAULT_LABEL_SIZE
    symbol = str(value.get("symbol", DEFAULT_SYMBOL))
    label = str(value.get("label", DEFAULT_LABEL))
    halo = str(value.get("halo", DEFAULT_HALO))
    if symbol not in SYMBOL_NAMES:
        symbol = DEFAULT_SYMBOL
    if label not in LABEL_NAMES:
        label = DEFAULT_LABEL
    if halo not in HALO_NAMES:
        halo = DEFAULT_HALO
    return {
        "selected_color": _color(value.get("selected_color"), DEFAULT_SELECTED),
        "other_color": _color(value.get("other_color"), DEFAULT_OTHER),
        "size": max(3, min(12, size)),
        "symbol": symbol,
        "label": label,
        "label_size": max(8, min(24, label_size)),
        "halo": halo,
    }


def load_display_settings(project):
    return normalize_display_settings(project.get_ui_state("landmark_display", {}))


def save_display_settings(project, value):
    settings = normalize_display_settings(value)
    project.set_ui_state("landmark_display", settings)
    return settings


def label_text(schema, ident, mode):
    """Return the configured short label for one landmark."""
    if mode == "none":
        return ""
    ident = int(ident)
    if mode == "name":
        row = next((item for item in schema if int(item.get("id", item.get("landmark_id", -1))) == ident), None)
        if row:
            return str(row.get("name") or row.get("abbr") or ident)
    return str(ident)


def _halo_color(mode):
    return "#ffffff" if mode == "white" else "#000000" if mode == "black" else None


def _oval(canvas, x, y, radius, **kwargs):
    return canvas.create_oval(x-radius, y-radius, x+radius, y+radius, **kwargs)


def draw_marker(canvas, x, y, *, color, size, symbol, halo="none", tags=()):
    """Draw one marker; descriptor supports fast vector-only dragging."""
    r = max(3, int(size))
    tags = tuple(tags) if isinstance(tags, (tuple, list)) else (tags,)
    halo_color = _halo_color(halo)
    parts = []

    def add(kind, item, radius):
        parts.append((kind, item, radius))

    if symbol == "cross":
        if halo_color:
            add("diag1", canvas.create_line(x-r, y-r, x+r, y+r, fill=halo_color, width=5, tags=tags), r)
            add("diag2", canvas.create_line(x-r, y+r, x+r, y-r, fill=halo_color, width=5, tags=tags), r)
        add("diag1", canvas.create_line(x-r, y-r, x+r, y+r, fill=color, width=2, tags=tags), r)
        add("diag2", canvas.create_line(x-r, y+r, x+r, y-r, fill=color, width=2, tags=tags), r)
    elif symbol == "filled_circle":
        if halo_color:
            hr = r + 2
            add("oval", _oval(canvas, x, y, hr, fill=halo_color, outline=halo_color, tags=tags), hr)
        add("oval", _oval(canvas, x, y, r, fill=color, outline=color, tags=tags), r)
    elif symbol == "target":
        if halo_color:
            hr = r + 2
            add("oval", _oval(canvas, x, y, hr, outline=halo_color, width=5, tags=tags), hr)
        add("oval", _oval(canvas, x, y, r, outline=color, width=2, tags=tags), r)
        inner = max(2, r // 2)
        add("oval", _oval(canvas, x, y, inner, outline=color, width=2, tags=tags), inner)
    else:
        if halo_color:
            hr = r + 2
            add("oval", _oval(canvas, x, y, hr, outline=halo_color, width=5, tags=tags), hr)
        add("oval", _oval(canvas, x, y, r, outline=color, width=2, tags=tags), r)
    return {"parts": tuple(parts), "size": r}


def move_marker(canvas, marker, x, y):
    for kind, item, radius in marker["parts"]:
        r = int(radius)
        if kind == "diag1":
            canvas.coords(item, x-r, y-r, x+r, y+r)
        elif kind == "diag2":
            canvas.coords(item, x-r, y+r, x+r, y-r)
        else:
            canvas.coords(item, x-r, y-r, x+r, y+r)


def draw_label(canvas, x, y, *, text, color, font_size, halo="none", tags=()):
    """Draw readable landmark text with an optional one-pixel contrast halo."""
    if not text:
        return {"parts": ()}
    tags = tuple(tags) if isinstance(tags, (tuple, list)) else (tags,)
    font = ("Segoe UI", int(font_size), "bold")
    parts = []
    halo_color = _halo_color(halo)
    if halo_color:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)):
            item = canvas.create_text(x+dx, y+dy, text=text, anchor="sw", fill=halo_color, font=font, tags=tags)
            parts.append((item, dx, dy))
    item = canvas.create_text(x, y, text=text, anchor="sw", fill=color, font=font, tags=tags)
    parts.append((item, 0, 0))
    return {"parts": tuple(parts)}


def move_label(canvas, label, x, y):
    for item, dx, dy in label.get("parts", ()):
        canvas.coords(item, x+dx, y+dy)
