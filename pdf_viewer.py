"""
PDF Viewer with Labeling

Features:
- Display a PDF in a GUI (tkinter + PyMuPDF)
- Zoom and pan support
- Page navigation (buttons or configurable keyboard shortcuts)
- Label shortcuts: configurable (default 1 = unwichtig, 2 = wichtig, 3 = sehr wichtig)
- Auto-advance to next page after labeling
- Auto-save labels in the background after every N labels (configurable, default 3)
- Save / load label progress (JSON)
- Extract pages labeled "wichtig" or "sehr wichtig" to a new PDF
- Page statistics panel (unlabeled / unwichtig / wichtig / sehr wichtig counts)
- Configurable keyboard shortcuts dialog
- Configurable settings dialog (auto-save threshold)
- Dracula Theme color scheme, JetBrains Mono font
"""

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
from PIL import Image, ImageTk

# ── Constants ───────────────────────────────────────────────────────────────

# ── Dracula Theme Official palette ──────────────────────────────────────────
DR_BG        = "#282A36"   # Background
DR_SURFACE   = "#44475A"   # Current Line / panels
DR_FG        = "#F8F8F2"   # Foreground
DR_COMMENT   = "#6272A4"   # Comments / muted text
DR_CYAN      = "#8BE9FD"
DR_GREEN     = "#50FA7B"
DR_ORANGE    = "#FFB86C"
DR_PINK      = "#FF79C6"
DR_PURPLE    = "#BD93F9"
DR_RED       = "#FF5555"
DR_YELLOW    = "#F1FA8C"

# Font
FONT_FAMILY = "JetBrains Mono"

# Auto-save
DEFAULT_AUTO_SAVE_THRESHOLD = 3   # save after every N labels

LABELS = {
    0: "",           # unlabeled
    1: "unwichtig",
    2: "wichtig",
    3: "sehr wichtig",
}

LABEL_COLORS = {
    0: DR_COMMENT,   # unlabeled  → muted purple-grey
    1: DR_RED,       # unwichtig  → red
    2: DR_ORANGE,    # wichtig    → orange
    3: DR_GREEN,     # sehr wichtig → green
}

ZOOM_STEP = 0.25
ZOOM_MIN = 0.25
ZOOM_MAX = 5.0
DEFAULT_ZOOM = 1.5   # start zoomed in so text is readable

DEFAULT_SHORTCUTS: dict[str, str] = {
    "prev_page":  "<Left>",
    "next_page":  "<Right>",
    "page_up":    "<Prior>",
    "page_down":  "<Next>",
    "label_1":    "1",
    "label_2":    "2",
    "label_3":    "3",
    "zoom_in":    "<plus>",
    "zoom_out":   "<minus>",
}

SHORTCUT_LABELS: dict[str, str] = {
    "prev_page":  "Vorherige Seite",
    "next_page":  "Nächste Seite",
    "page_up":    "Seite hoch (Page Up)",
    "page_down":  "Seite runter (Page Down)",
    "label_1":    "Label: unwichtig",
    "label_2":    "Label: wichtig",
    "label_3":    "Label: sehr wichtig",
    "zoom_in":    "Zoom +",
    "zoom_out":   "Zoom −",
}


# ── Application ─────────────────────────────────────────────────────────────

class PDFViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Viewer mit Labels")
        self.geometry("1200x800")
        self.configure(bg=DR_BG)

        # State
        self.pdf_path: str = ""
        self.doc: fitz.Document | None = None
        self.current_page: int = 0
        self.zoom: float = DEFAULT_ZOOM
        self.labels: dict[int, int] = {}   # page_index → label key (0–3)
        self.shortcuts: dict[str, str] = dict(DEFAULT_SHORTCUTS)
        self._bound_key_sequences: list[str] = []
        self._resize_job = None   # debounce handle for canvas resize
        self._is_fullscreen: bool = False
        # Auto-save
        self.auto_save_threshold: int = DEFAULT_AUTO_SAVE_THRESHOLD
        self._labels_since_last_save: int = 0

        self._build_ui()
        self._bind_keys()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top toolbar ──────────────────────────────────────────────────────
        toolbar = tk.Frame(self, bg=DR_SURFACE, pady=4)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        btn_cfg = {"bg": DR_COMMENT, "fg": DR_FG, "relief": tk.FLAT,
                   "padx": 8, "pady": 4, "cursor": "hand2",
                   "font": (FONT_FAMILY, 9)}

        tk.Button(toolbar, text="📂 PDF öffnen", command=self._open_pdf,
                  **btn_cfg).pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text="💾 Labels speichern", command=self._save_labels,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="📥 Labels laden", command=self._load_labels,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="📤 Wichtige Seiten exportieren",
                  command=self._export_important, **btn_cfg).pack(side=tk.LEFT, padx=2)

        # Separator
        tk.Label(toolbar, text="  ", bg=DR_SURFACE).pack(side=tk.LEFT)

        # Zoom controls
        tk.Button(toolbar, text="🔍 +", command=self._zoom_in,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="🔎 −", command=self._zoom_out,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="⟳ Reset Zoom", command=self._zoom_reset,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        self.zoom_label = tk.Label(toolbar, text=f"{int(DEFAULT_ZOOM*100)} %",
                                   bg=DR_SURFACE, fg=DR_COMMENT,
                                   font=(FONT_FAMILY, 9), width=6)
        self.zoom_label.pack(side=tk.LEFT, padx=4)

        # Separator
        tk.Label(toolbar, text="|", bg=DR_SURFACE, fg=DR_COMMENT).pack(side=tk.LEFT, padx=4)

        # Editable page navigation
        tk.Label(toolbar, text="Seite:", bg=DR_SURFACE, fg=DR_COMMENT,
                 font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=(2, 1))
        self.page_entry = tk.Entry(
            toolbar, width=4, justify="center", bg=DR_COMMENT, fg=DR_FG,
            insertbackground=DR_FG, relief=tk.FLAT, font=(FONT_FAMILY, 9)
        )
        self.page_entry.pack(side=tk.LEFT, padx=1)
        self.page_entry.bind("<Return>", self._on_page_entry)
        self.page_total_label = tk.Label(toolbar, text="/ --", bg=DR_SURFACE,
                                         fg=DR_COMMENT, font=(FONT_FAMILY, 9))
        self.page_total_label.pack(side=tk.LEFT, padx=(1, 8))

        # Shortcuts config button
        tk.Button(toolbar, text="⌨ Shortcuts", command=self._open_shortcuts_dialog,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)

        # Settings button (auto-save threshold etc.)
        tk.Button(toolbar, text="⚙ Einstellungen", command=self._open_settings_dialog,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)

        # Auto-save indicator
        self.autosave_label = tk.Label(
            toolbar, text="", bg=DR_SURFACE, fg=DR_GREEN,
            font=(FONT_FAMILY, 9)
        )
        self.autosave_label.pack(side=tk.LEFT, padx=4)

        # Fullscreen toggle button
        self.fullscreen_btn = tk.Button(
            toolbar, text="⛶ Vollbild (F11)", command=self._toggle_fullscreen,
            **btn_cfg
        )
        self.fullscreen_btn.pack(side=tk.LEFT, padx=2)

        # ── Status bar (bottom) ──────────────────────────────────────────────
        status_bar = tk.Frame(self, bg=DR_SURFACE, pady=3)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.label_badge = tk.Label(status_bar, text="", bg=DR_SURFACE,
                                    fg=DR_FG, font=(FONT_FAMILY, 11, "bold"),
                                    width=14, anchor="center")
        self.label_badge.pack(side=tk.LEFT, padx=8)

        # Shortcut hint
        hint = (
            "Shortcuts konfigurierbar (⌨ Shortcuts)  |  "
            "Mausrad = Scrollen  |  Strg+Mausrad = Zoom  |  "
            "Mitteltaste/Rechtstaste + Ziehen = Verschieben  |  "
            "F11 = Vollbild"
        )
        tk.Label(status_bar, text=hint, bg=DR_SURFACE, fg=DR_COMMENT,
                 font=(FONT_FAMILY, 9)).pack(side=tk.RIGHT, padx=8)

        # ── Main area: canvas + sidebar ──────────────────────────────────────
        main = tk.Frame(self, bg=DR_BG)
        main.pack(fill=tk.BOTH, expand=True)

        # Sidebar (page list + statistics + navigation)
        sidebar = tk.Frame(main, bg=DR_SURFACE, width=220)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Seiten", bg=DR_SURFACE, fg=DR_COMMENT,
                 font=(FONT_FAMILY, 11, "bold")).pack(pady=(8, 4))

        # Page list box
        list_frame = tk.Frame(sidebar, bg=DR_SURFACE)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4)

        sb_scroll = tk.Scrollbar(list_frame)
        sb_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.page_listbox = tk.Listbox(
            list_frame, bg=DR_BG, fg=DR_FG, selectbackground=DR_PURPLE,
            activestyle="none", font=(FONT_FAMILY, 9), yscrollcommand=sb_scroll.set
        )
        self.page_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_scroll.config(command=self.page_listbox.yview)
        self.page_listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        # Statistics panel
        tk.Frame(sidebar, bg=DR_COMMENT, height=1).pack(fill=tk.X, padx=4, pady=(4, 0))
        stats_outer = tk.Frame(sidebar, bg=DR_SURFACE)
        stats_outer.pack(fill=tk.X, padx=6, pady=4)
        tk.Label(stats_outer, text="Statistik", bg=DR_SURFACE, fg=DR_COMMENT,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(2, 4))
        self._stat_count_labels: dict[int, tk.Label] = {}
        for key, name, color in [
            (0, "Nicht gelabelt", LABEL_COLORS[0]),
            (1, "Unwichtig",      LABEL_COLORS[1]),
            (2, "Wichtig",        LABEL_COLORS[2]),
            (3, "Sehr wichtig",   LABEL_COLORS[3]),
        ]:
            row = tk.Frame(stats_outer, bg=DR_SURFACE)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text="●", fg=color, bg=DR_SURFACE,
                     font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)
            tk.Label(row, text=f" {name}:", bg=DR_SURFACE, fg=DR_COMMENT,
                     font=(FONT_FAMILY, 9), anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
            count_lbl = tk.Label(row, text="–", bg=DR_SURFACE, fg=DR_FG,
                                 font=(FONT_FAMILY, 9, "bold"), width=4, anchor="e")
            count_lbl.pack(side=tk.RIGHT)
            self._stat_count_labels[key] = count_lbl
        tk.Frame(sidebar, bg=DR_COMMENT, height=1).pack(fill=tk.X, padx=4, pady=(0, 4))

        # Navigation buttons
        nav = tk.Frame(sidebar, bg=DR_SURFACE)
        nav.pack(pady=6)
        tk.Button(nav, text="◀ Zurück", command=self._prev_page,
                  bg=DR_COMMENT, fg=DR_FG, relief=tk.FLAT,
                  padx=6, cursor="hand2",
                  font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=4)
        tk.Button(nav, text="Weiter ▶", command=self._next_page,
                  bg=DR_COMMENT, fg=DR_FG, relief=tk.FLAT,
                  padx=6, cursor="hand2",
                  font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=4)

        # ── PDF canvas with scrollbars ───────────────────────────────────────
        canvas_frame = tk.Frame(main, bg=DR_BG)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        h_scroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        v_scroll = tk.Scrollbar(canvas_frame)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(
            canvas_frame,
            bg=DR_SURFACE,
            xscrollcommand=h_scroll.set,
            yscrollcommand=v_scroll.set,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)

        # Pan bindings
        self.canvas.bind("<ButtonPress-2>", self._pan_start)
        self.canvas.bind("<B2-Motion>", self._pan_move)
        self.canvas.bind("<ButtonPress-3>", self._pan_start)
        self.canvas.bind("<B3-Motion>", self._pan_move)

        # Mouse wheel zoom / scroll
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)         # Windows
        self.canvas.bind("<Button-4>", self._on_mousewheel)           # Linux up
        self.canvas.bind("<Button-5>", self._on_mousewheel)           # Linux down
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_wheel) # Windows zoom
        self.canvas.bind("<Control-Button-4>", self._on_ctrl_wheel)   # Linux zoom up
        self.canvas.bind("<Control-Button-5>", self._on_ctrl_wheel)   # Linux zoom down

        # Re-center the page whenever the canvas is resized (debounced)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

    def _bind_keys(self):
        # Unbind previously registered shortcuts
        for seq in self._bound_key_sequences:
            try:
                self.unbind(seq)
            except Exception:
                pass
        self._bound_key_sequences.clear()

        def guard(func):
            """Ignore key event when an Entry widget has focus.

            This prevents label/navigation shortcuts from firing while the user
            is typing in the page-number Entry in the toolbar.
            """
            def wrapped(_event):
                if not isinstance(self.focus_get(), tk.Entry):
                    func()
            return wrapped

        def bind(seq: str, func) -> None:
            self.bind(seq, guard(func))
            self._bound_key_sequences.append(seq)

        bind(self.shortcuts["prev_page"],  self._prev_page)
        bind(self.shortcuts["next_page"],  self._next_page)
        bind(self.shortcuts["page_up"],    self._prev_page)
        bind(self.shortcuts["page_down"],  self._next_page)
        bind(self.shortcuts["label_1"],    lambda: self._set_label(1))
        bind(self.shortcuts["label_2"],    lambda: self._set_label(2))
        bind(self.shortcuts["label_3"],    lambda: self._set_label(3))
        bind(self.shortcuts["zoom_in"],    self._zoom_in)
        bind(self.shortcuts["zoom_out"],   self._zoom_out)
        # Numpad keys are fixed (not configurable)
        self.bind("<KP_Add>",      guard(self._zoom_in))
        self.bind("<KP_Subtract>", guard(self._zoom_out))
        # Fullscreen – always fixed, not affected by configurable shortcuts
        self.bind("<F11>",   self._toggle_fullscreen)
        self.bind("<Escape>", self._exit_fullscreen)

    # ── Fullscreen ───────────────────────────────────────────────────────────

    def _toggle_fullscreen(self, _event=None):
        """Toggle fullscreen mode on/off (F11)."""
        self._is_fullscreen = not self._is_fullscreen
        self.attributes("-fullscreen", self._is_fullscreen)
        label = "✕ Vollbild beenden (F11)" if self._is_fullscreen else "⛶ Vollbild (F11)"
        self.fullscreen_btn.config(text=label)

    def _exit_fullscreen(self, _event=None):
        """Exit fullscreen mode (Escape)."""
        if self._is_fullscreen:
            self._toggle_fullscreen()

    def _on_page_entry(self, _event=None):
        """Navigate to the page number typed in the toolbar entry.

        On invalid input or out-of-range values the entry is reset to the
        current page number by the _update_status() call at the end.
        """
        if not self.doc:
            return
        try:
            page_num = int(self.page_entry.get()) - 1
            if 0 <= page_num < len(self.doc):
                self.current_page = page_num
                self._show_page()
        except ValueError:
            pass
        # Always restore entry to the actual current page (resets invalid input)
        self._update_status()
        self.focus_set()  # return focus to main window

    # ── File operations ──────────────────────────────────────────────────────

    def _open_pdf(self):
        path = filedialog.askopenfilename(
            title="PDF öffnen",
            filetypes=[("PDF-Dateien", "*.pdf"), ("Alle Dateien", "*.*")]
        )
        if not path:
            return
        if self.doc:
            self.doc.close()
        self.pdf_path = path
        self.doc = fitz.open(path)
        self.current_page = 0
        self.labels = {}
        self.zoom = DEFAULT_ZOOM
        self.title(f"PDF Viewer – {os.path.basename(path)}")
        self._rebuild_sidebar()
        self._show_page()

    def _save_labels(self):
        if not self.pdf_path:
            messagebox.showwarning("Kein PDF", "Bitte zuerst eine PDF öffnen.")
            return
        default_name = os.path.splitext(self.pdf_path)[0] + "_labels.json"
        path = filedialog.asksaveasfilename(
            title="Labels speichern",
            initialfile=os.path.basename(default_name),
            defaultextension=".json",
            filetypes=[("JSON-Dateien", "*.json"), ("Alle Dateien", "*.*")]
        )
        if not path:
            return
        data = {
            "pdf": os.path.basename(self.pdf_path),
            "labels": {str(k): v for k, v in self.labels.items()},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("Gespeichert", f"Labels wurden gespeichert:\n{path}")

    def _load_labels(self):
        if not self.pdf_path:
            messagebox.showwarning("Kein PDF", "Bitte zuerst eine PDF öffnen.")
            return
        path = filedialog.askopenfilename(
            title="Labels laden",
            filetypes=[("JSON-Dateien", "*.json"), ("Alle Dateien", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.labels = {int(k): int(v) for k, v in data.get("labels", {}).items()}
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            messagebox.showerror("Fehler", f"Labels konnten nicht geladen werden:\n{exc}")
            return
        self._rebuild_sidebar()
        self._show_page()
        messagebox.showinfo("Geladen", f"Labels wurden geladen:\n{path}")

    def _export_important(self):
        if not self.doc:
            messagebox.showwarning("Kein PDF", "Bitte zuerst eine PDF öffnen.")
            return

        important_pages = sorted(
            page for page, lbl in self.labels.items()
            if lbl in (2, 3)   # wichtig or sehr wichtig
        )
        if not important_pages:
            messagebox.showinfo(
                "Keine wichtigen Seiten",
                "Es wurden noch keine Seiten als 'wichtig' oder 'sehr wichtig' markiert."
            )
            return

        default_name = os.path.splitext(self.pdf_path)[0] + "_wichtig.pdf"
        path = filedialog.asksaveasfilename(
            title="Wichtige Seiten exportieren",
            initialfile=os.path.basename(default_name),
            defaultextension=".pdf",
            filetypes=[("PDF-Dateien", "*.pdf"), ("Alle Dateien", "*.*")]
        )
        if not path:
            return

        new_doc = fitz.open()
        for page_idx in important_pages:
            new_doc.insert_pdf(self.doc, from_page=page_idx, to_page=page_idx)
        new_doc.save(path)
        new_doc.close()

        label_summary = "\n".join(
            f"  Seite {p + 1}: {LABELS[self.labels[p]]}" for p in important_pages
        )
        messagebox.showinfo(
            "Export erfolgreich",
            f"Exportierte {len(important_pages)} Seite(n) nach:\n{path}\n\n{label_summary}"
        )

    # ── Page rendering ────────────────────────────────────────────────────────

    def _show_page(self):
        if not self.doc:
            return
        page = self.doc[self.current_page]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self._tk_img = ImageTk.PhotoImage(img)

        self.canvas.delete("all")

        # Ensure layout is up-to-date before reading canvas dimensions
        self.canvas.update_idletasks()
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        # Center the image; add small margin (10 px) around it
        margin = 10
        x = max(canvas_w // 2, pix.width // 2 + margin)
        y = max(canvas_h // 2, pix.height // 2 + margin)
        scroll_w = max(canvas_w, pix.width + 2 * margin)
        scroll_h = max(canvas_h, pix.height + 2 * margin)

        self.canvas.config(scrollregion=(0, 0, scroll_w, scroll_h))
        self.canvas.create_image(x, y, anchor=tk.CENTER, image=self._tk_img)

        # Scroll so that the image center aligns with the viewport center
        x_frac = max(0.0, (x - canvas_w / 2) / scroll_w) if scroll_w else 0.0
        y_frac = max(0.0, (y - canvas_h / 2) / scroll_h) if scroll_h else 0.0
        self.canvas.xview_moveto(x_frac)
        self.canvas.yview_moveto(y_frac)

        self._update_status()
        self._update_sidebar_selection()

    def _update_status(self):
        n = len(self.doc) if self.doc else 0
        # Update toolbar page entry
        self.page_entry.delete(0, tk.END)
        if self.doc:
            self.page_entry.insert(0, str(self.current_page + 1))
        self.page_total_label.config(text=f"/ {n}" if self.doc else "/ --")
        # Update label badge
        lbl_key = self.labels.get(self.current_page, 0)
        lbl_text = LABELS[lbl_key]
        color = LABEL_COLORS[lbl_key]
        if lbl_key == 0:
            self.label_badge.config(text="[kein Label]", bg=DR_SURFACE, fg=DR_COMMENT)
        else:
            self.label_badge.config(text=f"[{lbl_text}]", bg=color, fg=DR_BG)
        self.zoom_label.config(text=f"{int(self.zoom * 100)} %")

    # ── Sidebar helpers ──────────────────────────────────────────────────────

    def _update_stats(self):
        """Refresh the statistics panel in the sidebar."""
        if not self.doc:
            for lbl in self._stat_count_labels.values():
                lbl.config(text="–")
            return
        total = len(self.doc)
        counts: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        for i in range(total):
            counts[self.labels.get(i, 0)] += 1
        for key, lbl in self._stat_count_labels.items():
            lbl.config(text=str(counts[key]))

    def _rebuild_sidebar(self):
        self.page_listbox.delete(0, tk.END)
        if not self.doc:
            self._update_stats()
            return
        for i in range(len(self.doc)):
            lbl_key = self.labels.get(i, 0)
            prefix = {0: "  ", 1: "✗ ", 2: "★ ", 3: "★★"}[lbl_key]
            color = LABEL_COLORS[lbl_key]
            entry = f"{prefix}Seite {i + 1}"
            self.page_listbox.insert(tk.END, entry)
            self.page_listbox.itemconfig(i, fg=color if lbl_key else DR_COMMENT)
        self._update_stats()

    def _update_sidebar_selection(self):
        self.page_listbox.selection_clear(0, tk.END)
        self.page_listbox.selection_set(self.current_page)
        self.page_listbox.see(self.current_page)

    def _on_listbox_select(self, _event):
        sel = self.page_listbox.curselection()
        if sel:
            self.current_page = sel[0]
            self._show_page()

    # ── Navigation ───────────────────────────────────────────────────────────

    def _prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self._show_page()

    def _next_page(self):
        if self.doc and self.current_page < len(self.doc) - 1:
            self.current_page += 1
            self._show_page()

    # ── Labeling ─────────────────────────────────────────────────────────────

    def _set_label(self, key: int):
        if not self.doc:
            return
        current = self.labels.get(self.current_page, 0)
        # Toggle: pressing the same key again removes the label
        if current == key:
            self.labels[self.current_page] = 0
        else:
            self.labels[self.current_page] = key
        self._update_status()
        # Update sidebar entry color/prefix
        lbl_key = self.labels.get(self.current_page, 0)
        prefix = {0: "  ", 1: "✗ ", 2: "★ ", 3: "★★"}[lbl_key]
        self.page_listbox.delete(self.current_page)
        self.page_listbox.insert(self.current_page, f"{prefix}Seite {self.current_page + 1}")
        color = LABEL_COLORS[lbl_key]
        self.page_listbox.itemconfig(self.current_page, fg=color if lbl_key else DR_COMMENT)
        self._update_sidebar_selection()
        self._update_stats()
        # Auto-save counter: only count actual label assignments (not removals)
        if lbl_key != 0:
            self._labels_since_last_save += 1
            if self._labels_since_last_save >= self.auto_save_threshold:
                self._auto_save()
        # Auto-advance to next page after labeling
        self._next_page()

    # ── Auto-save ─────────────────────────────────────────────────────────────

    def _auto_save(self):
        """Silently save labels to the default path next to the PDF file."""
        if not self.pdf_path or not self.labels:
            return
        path = os.path.splitext(self.pdf_path)[0] + "_labels.json"
        data = {
            "pdf": os.path.basename(self.pdf_path),
            "labels": {str(k): v for k, v in self.labels.items()},
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._labels_since_last_save = 0
            # Brief indicator in the toolbar
            self.autosave_label.config(text="✔ Automatisch gespeichert")
            self.after(3000, lambda: self.autosave_label.config(text=""))
        except OSError:
            # Show a brief error hint without interrupting the workflow
            self.autosave_label.config(
                text="⚠ Auto-Speichern fehlgeschlagen", fg=DR_ORANGE
            )
            self.after(4000, lambda: self.autosave_label.config(text="", fg=DR_GREEN))

    # ── Zoom ─────────────────────────────────────────────────────────────────

    def _zoom_in(self):
        self.zoom = min(self.zoom + ZOOM_STEP, ZOOM_MAX)
        self._show_page()

    def _zoom_out(self):
        self.zoom = max(self.zoom - ZOOM_STEP, ZOOM_MIN)
        self._show_page()

    def _zoom_reset(self):
        self.zoom = DEFAULT_ZOOM
        self._show_page()

    def _on_canvas_resize(self, _event=None):
        """Re-render the current page after a short debounce delay."""
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(50, self._show_page)

    def _on_mousewheel(self, event):
        if not self.doc:
            return
        if event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-3, "units")
        else:
            self.canvas.yview_scroll(3, "units")

    def _on_ctrl_wheel(self, event):
        if not self.doc:
            return
        if event.num == 4 or event.delta > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    # ── Pan ──────────────────────────────────────────────────────────────────

    def _pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    # ── Shortcuts configuration ──────────────────────────────────────────────

    def _open_shortcuts_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Shortcuts konfigurieren")
        dlg.configure(bg=DR_BG)
        dlg.geometry("420x370")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        temp: dict[str, str] = dict(self.shortcuts)
        key_buttons: dict[str, tk.Button] = {}
        waiting: list[str | None] = [None]

        tk.Label(dlg, text="Shortcuts konfigurieren", bg=DR_BG, fg=DR_FG,
                 font=(FONT_FAMILY, 12, "bold")).pack(pady=(12, 8))

        frame = tk.Frame(dlg, bg=DR_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=16)

        btn_cfg_dlg = dict(bg=DR_COMMENT, fg=DR_FG, relief=tk.FLAT,
                           padx=6, pady=2, cursor="hand2", width=14,
                           font=(FONT_FAMILY, 9))

        def start_capture(action: str) -> None:
            # Cancel any ongoing capture
            if waiting[0]:
                key_buttons[waiting[0]].config(text=temp[waiting[0]], bg=DR_COMMENT)
            waiting[0] = action
            key_buttons[action].config(text="[Taste drücken…]", bg=DR_PURPLE)
            dlg.bind("<Key>", capture_key)

        def capture_key(event: tk.Event) -> None:
            action = waiting[0]
            if action is None:
                return
            key = event.keysym
            binding = key if len(key) == 1 else f"<{key}>"
            temp[action] = binding
            key_buttons[action].config(text=binding, bg=DR_COMMENT)
            waiting[0] = None
            dlg.unbind("<Key>")

        for action, label in SHORTCUT_LABELS.items():
            row = tk.Frame(frame, bg=DR_BG)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, bg=DR_BG, fg=DR_COMMENT,
                     font=(FONT_FAMILY, 10), width=24, anchor="w").pack(side=tk.LEFT)
            btn = tk.Button(row, text=temp[action],
                            command=lambda a=action: start_capture(a),
                            **btn_cfg_dlg)
            btn.pack(side=tk.LEFT, padx=4)
            key_buttons[action] = btn

        def on_save() -> None:
            self.shortcuts = dict(temp)
            self._bind_keys()
            dlg.destroy()

        def on_reset() -> None:
            for action in DEFAULT_SHORTCUTS:
                temp[action] = DEFAULT_SHORTCUTS[action]
                key_buttons[action].config(text=DEFAULT_SHORTCUTS[action])

        btn_row = tk.Frame(dlg, bg=DR_BG)
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="Speichern", command=on_save,
                  bg=DR_GREEN, fg=DR_BG, relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2", font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Standard", command=on_reset,
                  bg=DR_COMMENT, fg=DR_FG, relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2", font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Abbrechen", command=dlg.destroy,
                  bg=DR_RED, fg=DR_BG, relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2", font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=6)

    # ── Settings dialog ──────────────────────────────────────────────────────

    def _open_settings_dialog(self):
        """Dialog for configuring application settings (e.g. auto-save threshold)."""
        dlg = tk.Toplevel(self)
        dlg.title("Einstellungen")
        dlg.configure(bg=DR_BG)
        dlg.geometry("340x180")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Einstellungen", bg=DR_BG, fg=DR_FG,
                 font=(FONT_FAMILY, 12, "bold")).pack(pady=(12, 8))

        frame = tk.Frame(dlg, bg=DR_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=16)

        # Auto-save threshold row
        row = tk.Frame(frame, bg=DR_BG)
        row.pack(fill=tk.X, pady=6)
        tk.Label(row, text="Auto-Speichern nach N Labels:", bg=DR_BG, fg=DR_COMMENT,
                 font=(FONT_FAMILY, 10), anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        threshold_var = tk.StringVar(value=str(self.auto_save_threshold))
        spinbox = tk.Spinbox(
            row, from_=1, to=100, textvariable=threshold_var,
            width=5, bg=DR_COMMENT, fg=DR_FG, buttonbackground=DR_COMMENT,
            insertbackground=DR_FG, relief=tk.FLAT, font=(FONT_FAMILY, 10),
        )
        spinbox.pack(side=tk.LEFT, padx=4)

        def on_save() -> None:
            try:
                val = int(threshold_var.get())
                if val < 1:
                    raise ValueError("Auto-save threshold must be at least 1")
                self.auto_save_threshold = val
            except ValueError:
                messagebox.showerror(
                    "Ungültiger Wert",
                    "Bitte eine ganze Zahl ≥ 1 eingeben.",
                    parent=dlg,
                )
                return
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg=DR_BG)
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="Speichern", command=on_save,
                  bg=DR_GREEN, fg=DR_BG, relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2", font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Abbrechen", command=dlg.destroy,
                  bg=DR_RED, fg=DR_BG, relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2", font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=6)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PDFViewer()
    app.mainloop()
