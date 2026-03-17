"""
PDF Viewer with Labeling

Features:
- Display a PDF in a GUI (tkinter + PyMuPDF)
- Zoom and pan support
- Page navigation (buttons or Left/Right arrow keys)
- Label shortcuts:  1 = unwichtig, 2 = wichtig, 3 = sehr wichtig
- Save / load label progress (JSON)
- Extract pages labeled "wichtig" or "sehr wichtig" to a new PDF
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

        # ── Status bar (bottom) ──────────────────────────────────────────────
        status_bar = tk.Frame(self, bg="#3c3f41", pady=3)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.page_label = tk.Label(status_bar, text="Keine PDF geöffnet",
                                   bg="#3c3f41", fg="white", anchor="w")
        self.page_label.pack(side=tk.LEFT, padx=8)

        self.label_badge = tk.Label(status_bar, text="", bg="#3c3f41",
                                    fg="white", font=("Helvetica", 11, "bold"),
                                    width=14, anchor="center")
        self.label_badge.pack(side=tk.LEFT, padx=8)

        # Shortcut hint
        hint = (
            "Shortcuts:  ← → Seite blättern  |  "
            "1 = unwichtig   2 = wichtig   3 = sehr wichtig  |  "
            "Mausrad = Zoom  |  Mitteltaste/Leertaste + Ziehen = Verschieben"
        )
        tk.Label(status_bar, text=hint, bg="#3c3f41", fg="#888888",
                 font=("Helvetica", 9)).pack(side=tk.RIGHT, padx=8)

        # ── Main area: canvas + sidebar ──────────────────────────────────────
        main = tk.Frame(self, bg="#2b2b2b")
        main.pack(fill=tk.BOTH, expand=True)

        # Sidebar (page list + navigation)
        sidebar = tk.Frame(main, bg="#313335", width=180)
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
        self.bind("<Left>", lambda e: self._prev_page())
        self.bind("<Right>", lambda e: self._next_page())
        self.bind("<Prior>", lambda e: self._prev_page())   # Page Up
        self.bind("<Next>", lambda e: self._next_page())    # Page Down
        self.bind("1", lambda e: self._set_label(1))
        self.bind("2", lambda e: self._set_label(2))
        self.bind("3", lambda e: self._set_label(3))
        self.bind("<plus>", lambda e: self._zoom_in())
        self.bind("<minus>", lambda e: self._zoom_out())
        self.bind("<KP_Add>", lambda e: self._zoom_in())
        self.bind("<KP_Subtract>", lambda e: self._zoom_out())

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
        self.page_label.config(text=f"Seite {self.current_page + 1} / {n}")
        lbl_key = self.labels.get(self.current_page, 0)
        lbl_text = LABELS[lbl_key]
        color = LABEL_COLORS[lbl_key]
        if lbl_key == 0:
            self.label_badge.config(text="[kein Label]", bg="#3c3f41", fg="#888888")
        else:
            self.label_badge.config(text=f"[{lbl_text}]", bg=color, fg="white")
        self.zoom_label.config(text=f"{int(self.zoom * 100)} %")

    # ── Sidebar helpers ──────────────────────────────────────────────────────

    def _rebuild_sidebar(self):
        self.page_listbox.delete(0, tk.END)
        if not self.doc:
            return
        for i in range(len(self.doc)):
            lbl_key = self.labels.get(i, 0)
            prefix = {0: "  ", 1: "✗ ", 2: "★ ", 3: "★★"}[lbl_key]
            color = LABEL_COLORS[lbl_key]
            entry = f"{prefix}Seite {i + 1}"
            self.page_listbox.insert(tk.END, entry)
            self.page_listbox.itemconfig(i, fg=color if lbl_key else "#aaaaaa")

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


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PDFViewer()
    app.mainloop()
