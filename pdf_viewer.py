"""
PDF Viewer with Labeling

Features:
- Display a PDF in a GUI (tkinter + PyMuPDF)
- Zoom and pan support
- Page navigation (buttons or configurable keyboard shortcuts)
- Label shortcuts: configurable (default 1 = unwichtig, 2 = wichtig, 3 = sehr wichtig)
- Auto-advance to next page after labeling
- Save / load label progress (JSON)
- Extract pages labeled "wichtig" or "sehr wichtig" to a new PDF
- Page statistics panel (unlabeled / unwichtig / wichtig / sehr wichtig counts)
- Configurable keyboard shortcuts dialog
"""

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
from PIL import Image, ImageTk

# ── Constants ───────────────────────────────────────────────────────────────

LABELS = {
    0: "",           # unlabeled
    1: "unwichtig",
    2: "wichtig",
    3: "sehr wichtig",
}

LABEL_COLORS = {
    0: "#cccccc",
    1: "#f28b82",   # soft red  → unimportant
    2: "#fbbc04",   # amber     → important
    3: "#34a853",   # green     → very important
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
        self.configure(bg="#2b2b2b")

        # State
        self.pdf_path: str = ""
        self.doc: fitz.Document | None = None
        self.current_page: int = 0
        self.zoom: float = DEFAULT_ZOOM
        self.labels: dict[int, int] = {}   # page_index → label key (0–3)
        self.shortcuts: dict[str, str] = dict(DEFAULT_SHORTCUTS)
        self._bound_key_sequences: list[str] = []

        self._build_ui()
        self._bind_keys()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top toolbar ──────────────────────────────────────────────────────
        toolbar = tk.Frame(self, bg="#3c3f41", pady=4)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        btn_cfg = {"bg": "#4c5052", "fg": "white", "relief": tk.FLAT,
                   "padx": 8, "pady": 4, "cursor": "hand2"}

        tk.Button(toolbar, text="📂 PDF öffnen", command=self._open_pdf,
                  **btn_cfg).pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text="💾 Labels speichern", command=self._save_labels,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="📥 Labels laden", command=self._load_labels,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="📤 Wichtige Seiten exportieren",
                  command=self._export_important, **btn_cfg).pack(side=tk.LEFT, padx=2)

        # Separator
        tk.Label(toolbar, text="  ", bg="#3c3f41").pack(side=tk.LEFT)

        # Zoom controls
        tk.Button(toolbar, text="🔍 +", command=self._zoom_in,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="🔎 −", command=self._zoom_out,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="⟳ Reset Zoom", command=self._zoom_reset,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)
        self.zoom_label = tk.Label(toolbar, text=f"{int(DEFAULT_ZOOM*100)} %",
                                   bg="#3c3f41", fg="#aaaaaa", width=6)
        self.zoom_label.pack(side=tk.LEFT, padx=4)

        # Separator
        tk.Label(toolbar, text="|", bg="#3c3f41", fg="#555555").pack(side=tk.LEFT, padx=4)

        # Editable page navigation
        tk.Label(toolbar, text="Seite:", bg="#3c3f41", fg="#aaaaaa").pack(side=tk.LEFT, padx=(2, 1))
        self.page_entry = tk.Entry(
            toolbar, width=4, justify="center", bg="#4c5052", fg="white",
            insertbackground="white", relief=tk.FLAT, font=("Helvetica", 10)
        )
        self.page_entry.pack(side=tk.LEFT, padx=1)
        self.page_entry.bind("<Return>", self._on_page_entry)
        self.page_total_label = tk.Label(toolbar, text="/ --", bg="#3c3f41", fg="#aaaaaa")
        self.page_total_label.pack(side=tk.LEFT, padx=(1, 8))

        # Shortcuts config button
        tk.Button(toolbar, text="⚙ Shortcuts", command=self._open_shortcuts_dialog,
                  **btn_cfg).pack(side=tk.LEFT, padx=2)

        # ── Status bar (bottom) ──────────────────────────────────────────────
        status_bar = tk.Frame(self, bg="#3c3f41", pady=3)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.label_badge = tk.Label(status_bar, text="", bg="#3c3f41",
                                    fg="white", font=("Helvetica", 11, "bold"),
                                    width=14, anchor="center")
        self.label_badge.pack(side=tk.LEFT, padx=8)

        # Shortcut hint
        hint = (
            "Shortcuts konfigurierbar (⚙ Shortcuts)  |  "
            "Mausrad = Scrollen  |  Strg+Mausrad = Zoom  |  "
            "Mitteltaste/Rechtstaste + Ziehen = Verschieben"
        )
        tk.Label(status_bar, text=hint, bg="#3c3f41", fg="#888888",
                 font=("Helvetica", 9)).pack(side=tk.RIGHT, padx=8)

        # ── Main area: canvas + sidebar ──────────────────────────────────────
        main = tk.Frame(self, bg="#2b2b2b")
        main.pack(fill=tk.BOTH, expand=True)

        # Sidebar (page list + statistics + navigation)
        sidebar = tk.Frame(main, bg="#313335", width=220)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Seiten", bg="#313335", fg="#aaaaaa",
                 font=("Helvetica", 11, "bold")).pack(pady=(8, 4))

        # Page list box
        list_frame = tk.Frame(sidebar, bg="#313335")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4)

        sb_scroll = tk.Scrollbar(list_frame)
        sb_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.page_listbox = tk.Listbox(
            list_frame, bg="#2b2b2b", fg="white", selectbackground="#4a6fa5",
            activestyle="none", font=("Helvetica", 10), yscrollcommand=sb_scroll.set
        )
        self.page_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_scroll.config(command=self.page_listbox.yview)
        self.page_listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        # Statistics panel
        tk.Frame(sidebar, bg="#555555", height=1).pack(fill=tk.X, padx=4, pady=(4, 0))
        stats_outer = tk.Frame(sidebar, bg="#313335")
        stats_outer.pack(fill=tk.X, padx=6, pady=4)
        tk.Label(stats_outer, text="Statistik", bg="#313335", fg="#aaaaaa",
                 font=("Helvetica", 10, "bold")).pack(anchor="w", pady=(2, 4))
        self._stat_count_labels: dict[int, tk.Label] = {}
        for key, name, color in [
            (0, "Nicht gelabelt", LABEL_COLORS[0]),
            (1, "Unwichtig",      LABEL_COLORS[1]),
            (2, "Wichtig",        LABEL_COLORS[2]),
            (3, "Sehr wichtig",   LABEL_COLORS[3]),
        ]:
            row = tk.Frame(stats_outer, bg="#313335")
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text="●", fg=color, bg="#313335",
                     font=("Helvetica", 9)).pack(side=tk.LEFT)
            tk.Label(row, text=f" {name}:", bg="#313335", fg="#aaaaaa",
                     font=("Helvetica", 9), anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
            count_lbl = tk.Label(row, text="–", bg="#313335", fg="white",
                                 font=("Helvetica", 9, "bold"), width=4, anchor="e")
            count_lbl.pack(side=tk.RIGHT)
            self._stat_count_labels[key] = count_lbl
        tk.Frame(sidebar, bg="#555555", height=1).pack(fill=tk.X, padx=4, pady=(0, 4))

        # Navigation buttons
        nav = tk.Frame(sidebar, bg="#313335")
        nav.pack(pady=6)
        tk.Button(nav, text="◀ Zurück", command=self._prev_page,
                  bg="#4c5052", fg="white", relief=tk.FLAT,
                  padx=6, cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Button(nav, text="Weiter ▶", command=self._next_page,
                  bg="#4c5052", fg="white", relief=tk.FLAT,
                  padx=6, cursor="hand2").pack(side=tk.LEFT, padx=4)

        # ── PDF canvas with scrollbars ───────────────────────────────────────
        canvas_frame = tk.Frame(main, bg="#2b2b2b")
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        h_scroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        v_scroll = tk.Scrollbar(canvas_frame)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(
            canvas_frame,
            bg="#525659",
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
        self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_img)
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

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
            self.label_badge.config(text="[kein Label]", bg="#3c3f41", fg="#888888")
        else:
            self.label_badge.config(text=f"[{lbl_text}]", bg=color, fg="white")
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
            self.page_listbox.itemconfig(i, fg=color if lbl_key else "#aaaaaa")
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
        self.page_listbox.itemconfig(self.current_page, fg=color if lbl_key else "#aaaaaa")
        self._update_sidebar_selection()
        self._update_stats()
        # Auto-advance to next page after labeling
        self._next_page()

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
        dlg.configure(bg="#2b2b2b")
        dlg.geometry("420x370")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        temp: dict[str, str] = dict(self.shortcuts)
        key_buttons: dict[str, tk.Button] = {}
        waiting: list[str | None] = [None]

        tk.Label(dlg, text="Shortcuts konfigurieren", bg="#2b2b2b", fg="white",
                 font=("Helvetica", 12, "bold")).pack(pady=(12, 8))

        frame = tk.Frame(dlg, bg="#2b2b2b")
        frame.pack(fill=tk.BOTH, expand=True, padx=16)

        btn_cfg_dlg = dict(bg="#4c5052", fg="white", relief=tk.FLAT,
                           padx=6, pady=2, cursor="hand2", width=14)

        def start_capture(action: str) -> None:
            # Cancel any ongoing capture
            if waiting[0]:
                key_buttons[waiting[0]].config(text=temp[waiting[0]], bg="#4c5052")
            waiting[0] = action
            key_buttons[action].config(text="[Taste drücken…]", bg="#5a7fa5")
            dlg.bind("<Key>", capture_key)

        def capture_key(event: tk.Event) -> None:
            action = waiting[0]
            if action is None:
                return
            key = event.keysym
            binding = key if len(key) == 1 else f"<{key}>"
            temp[action] = binding
            key_buttons[action].config(text=binding, bg="#4c5052")
            waiting[0] = None
            dlg.unbind("<Key>")

        for action, label in SHORTCUT_LABELS.items():
            row = tk.Frame(frame, bg="#2b2b2b")
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, bg="#2b2b2b", fg="#aaaaaa",
                     font=("Helvetica", 10), width=24, anchor="w").pack(side=tk.LEFT)
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

        btn_row = tk.Frame(dlg, bg="#2b2b2b")
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="Speichern", command=on_save,
                  bg="#34a853", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Standard", command=on_reset,
                  bg="#4c5052", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Abbrechen", command=dlg.destroy,
                  bg="#f28b82", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PDFViewer()
    app.mainloop()
