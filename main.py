"""Tkinter GUI for the PDF to audiobook converter.

All the actual PDF/TTS work lives in converter.py; this file only wires up
widgets and a background worker thread that calls into it.
"""
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from converter import (
    ACCENTS,
    LANGUAGES,
    convert_pdf_to_audio,
    extract_text_from_pdf,
    find_audio_player,
    get_page_count,
    play_audio,
)

# Drag-and-drop needs the optional tkinterdnd2 package. If it isn't
# installed, the app still works fully through the file dialog; it just
# skips the drop target instead of crashing.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False


BG = "#E6FFFD"
ACCENT = "#B799FF"


class QueueItem:
    """One PDF in the batch queue and its per-file settings/state."""

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        try:
            self.page_count = get_page_count(path)
        except Exception:
            self.page_count = 0
        self.start_page = 1
        self.end_page = self.page_count
        self.status = "Queued"
        self.output_path = None


class App:
    def __init__(self, root):
        self.root = root
        self.items = []  # list[QueueItem]
        self.progress_queue = queue.Queue()
        self.worker_thread = None

        root.config(bg=BG)
        root.title("PDF to Audiobook")
        root.geometry("980x720")
        root.minsize(880, 640)

        self._build_widgets()
        self._poll_progress_queue()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_widgets(self):
        title = tk.Label(self.root, text="PDF to Audiobook", font=("Arial", 24, "bold"), bg=BG, fg=ACCENT)
        title.pack(pady=(14, 2))

        subtitle_text = "Drag PDFs onto the window, or use Add Files" if DND_AVAILABLE else \
            "Use Add Files to queue PDFs (drag-and-drop unavailable: tkinterdnd2 not installed)"
        subtitle = tk.Label(self.root, text=subtitle_text, font=("Arial", 11), bg=BG, fg=ACCENT)
        subtitle.pack(pady=(0, 8))

        # --- Drop zone / queue ------------------------------------------------
        queue_frame = tk.Frame(self.root, bg=BG)
        queue_frame.pack(fill="both", expand=True, padx=16, pady=6)

        columns = ("pages", "range", "status")
        self.tree = ttk.Treeview(queue_frame, columns=columns, show="tree headings", height=10)
        self.tree.heading("#0", text="File")
        self.tree.heading("pages", text="Pages")
        self.tree.heading("range", text="Range")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", width=380)
        self.tree.column("pages", width=70, anchor="center")
        self.tree.column("range", width=110, anchor="center")
        self.tree.column("status", width=280, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(queue_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self.open_preview())

        if DND_AVAILABLE:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self._on_drop)

        # --- Queue buttons ------------------------------------------------
        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.pack(fill="x", padx=16, pady=4)

        tk.Button(btn_frame, text="Add Files", command=self.add_files, bg=ACCENT, fg=BG, width=14).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Remove Selected", command=self.remove_selected, bg=ACCENT, fg=BG, width=14).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Clear Queue", command=self.clear_queue, bg=ACCENT, fg=BG, width=14).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Preview / Page Range", command=self.open_preview, bg=ACCENT, fg=BG, width=18).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Play Selected Output", command=self.play_selected, bg=ACCENT, fg=BG, width=18).pack(side="left", padx=4)

        # --- Options --------------------------------------------------------
        options_frame = tk.LabelFrame(self.root, text="Voice options", bg=BG, fg=ACCENT, font=("Arial", 11, "bold"))
        options_frame.pack(fill="x", padx=16, pady=8)

        tk.Label(options_frame, text="Language:", bg=BG, fg=ACCENT).grid(row=0, column=0, padx=8, pady=8, sticky="e")
        self.language_var = tk.StringVar(value="English")
        ttk.Combobox(options_frame, textvariable=self.language_var, values=list(LANGUAGES.keys()),
                     state="readonly", width=18).grid(row=0, column=1, padx=8, pady=8)

        tk.Label(options_frame, text="Accent (TLD):", bg=BG, fg=ACCENT).grid(row=0, column=2, padx=8, pady=8, sticky="e")
        self.accent_var = tk.StringVar(value="Default (.com)")
        ttk.Combobox(options_frame, textvariable=self.accent_var, values=list(ACCENTS.keys()),
                     state="readonly", width=18).grid(row=0, column=3, padx=8, pady=8)

        self.slow_var = tk.BooleanVar(value=False)
        tk.Checkbutton(options_frame, text="Slow speech (gTTS rate control)", variable=self.slow_var,
                       bg=BG, fg=ACCENT, selectcolor=BG).grid(row=0, column=4, padx=8, pady=8)

        # --- Convert + progress ---------------------------------------------
        convert_frame = tk.Frame(self.root, bg=BG)
        convert_frame.pack(fill="x", padx=16, pady=6)

        self.convert_button = tk.Button(convert_frame, text="Convert All", command=self.start_conversion,
                                        bg=ACCENT, fg=BG, width=16, font=("Arial", 12, "bold"))
        self.convert_button.pack(side="left", padx=(0, 12))

        self.overall_progress = ttk.Progressbar(convert_frame, orient="horizontal", mode="determinate")
        self.overall_progress.pack(side="left", fill="x", expand=True)

        self.status_label = tk.Label(self.root, text="No files queued yet.", font=("Arial", 11), bg=BG, fg=ACCENT, wraplength=920, justify="left")
        self.status_label.pack(fill="x", padx=16, pady=(4, 14))

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------
    def _on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        pdfs = [p for p in paths if p.lower().endswith(".pdf")]
        if not pdfs:
            self.status_label.config(text="Dropped item(s) were not PDFs; ignored.", fg="red")
            return
        self._add_paths(pdfs)

    def add_files(self):
        paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        if paths:
            self._add_paths(list(paths))

    def _add_paths(self, paths):
        existing = {item.path for item in self.items}
        added = 0
        for path in paths:
            if path in existing:
                continue
            self.items.append(QueueItem(path))
            added += 1
        self._refresh_tree()
        if added:
            self.status_label.config(text=f"{added} file(s) queued. {len(self.items)} total in queue.", fg="green")
        else:
            self.status_label.config(text="Those file(s) are already in the queue.", fg="red")

    def remove_selected(self):
        selected_iids = self.tree.selection()
        if not selected_iids:
            return
        indices = {int(iid) for iid in selected_iids}
        self.items = [item for i, item in enumerate(self.items) if i not in indices]
        self._refresh_tree()

    def clear_queue(self):
        self.items = []
        self._refresh_tree()
        self.overall_progress["value"] = 0

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(self.items):
            range_text = f"{item.start_page}-{item.end_page}" if item.page_count else "n/a"
            self.tree.insert("", "end", iid=str(i), text=item.name,
                             values=(item.page_count or "?", range_text, item.status))

    def _selected_item(self):
        selected = self.tree.selection()
        if not selected:
            return None
        return self.items[int(selected[0])]

    # ------------------------------------------------------------------
    # Preview + page range
    # ------------------------------------------------------------------
    def open_preview(self):
        item = self._selected_item()
        if item is None:
            messagebox.showinfo("Preview", "Select a file in the queue first.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Preview: {item.name}")
        win.geometry("640x560")
        win.config(bg=BG)

        range_frame = tk.Frame(win, bg=BG)
        range_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(range_frame, text=f"Pages 1-{item.page_count}. Start:", bg=BG, fg=ACCENT).pack(side="left")
        start_var = tk.IntVar(value=item.start_page)
        tk.Spinbox(range_frame, from_=1, to=max(item.page_count, 1), textvariable=start_var, width=5).pack(side="left", padx=6)

        tk.Label(range_frame, text="End:", bg=BG, fg=ACCENT).pack(side="left")
        end_var = tk.IntVar(value=item.end_page)
        tk.Spinbox(range_frame, from_=1, to=max(item.page_count, 1), textvariable=end_var, width=5).pack(side="left", padx=6)

        text_widget = tk.Text(win, wrap="word")
        text_widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def load_preview():
            try:
                text = extract_text_from_pdf(item.path, start_var.get(), end_var.get())
            except Exception as exc:
                messagebox.showerror("Preview failed", str(exc))
                return
            text_widget.delete("1.0", "end")
            text_widget.insert("1.0", text if text.strip() else "(No extractable text in this range -- likely a scanned/image-only page.)")

        def save_range():
            item.start_page = min(start_var.get(), end_var.get())
            item.end_page = max(start_var.get(), end_var.get())
            self._refresh_tree()
            win.destroy()

        button_frame = tk.Frame(win, bg=BG)
        button_frame.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(button_frame, text="Load Preview Text", command=load_preview, bg=ACCENT, fg=BG).pack(side="left", padx=4)
        tk.Button(button_frame, text="Save Page Range", command=save_range, bg=ACCENT, fg=BG).pack(side="left", padx=4)

        load_preview()

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def play_selected(self):
        item = self._selected_item()
        if item is None:
            messagebox.showinfo("Play", "Select a converted file in the queue first.")
            return
        if not item.output_path or not os.path.exists(item.output_path):
            messagebox.showinfo("Play", "This file hasn't been converted yet.")
            return

        def _play():
            played = play_audio(item.output_path)
            if not played:
                self.root.after(0, lambda: messagebox.showinfo(
                    "No player found",
                    f"No local audio player (ffplay/mpv/afplay/aplay) was found.\n"
                    f"Open this file yourself:\n{item.output_path}"))

        threading.Thread(target=_play, daemon=True).start()

    # ------------------------------------------------------------------
    # Conversion (background thread + progress polling)
    # ------------------------------------------------------------------
    def start_conversion(self):
        if not self.items:
            self.status_label.config(text="No files queued yet.", fg="red")
            return
        if self.worker_thread is not None and self.worker_thread.is_alive():
            return

        lang = LANGUAGES[self.language_var.get()]
        tld = ACCENTS[self.accent_var.get()]
        slow = self.slow_var.get()

        self.convert_button.config(state="disabled")
        self.overall_progress["value"] = 0
        self.overall_progress["maximum"] = len(self.items)
        self.status_label.config(text="Converting...", fg="black")

        self.worker_thread = threading.Thread(
            target=self._convert_worker, args=(lang, tld, slow), daemon=True
        )
        self.worker_thread.start()

    def _convert_worker(self, lang, tld, slow):
        converted = 0
        for index, item in enumerate(self.items):
            self.progress_queue.put(("file_start", index))
            try:
                def on_page(done, total, index=index):
                    self.progress_queue.put(("page_progress", index, done, total))

                output_path = convert_pdf_to_audio(
                    item.path, lang=lang, tld=tld, slow=slow,
                    start_page=item.start_page, end_page=item.end_page,
                    progress_callback=on_page,
                )
                self.progress_queue.put(("file_done", index, output_path))
                converted += 1
            except Exception as exc:
                self.progress_queue.put(("file_error", index, str(exc)))
        self.progress_queue.put(("all_done", converted, len(self.items)))

    def _poll_progress_queue(self):
        try:
            while True:
                message = self.progress_queue.get_nowait()
                kind = message[0]
                if kind == "file_start":
                    index = message[1]
                    self.items[index].status = "Converting..."
                elif kind == "page_progress":
                    _, index, done, total = message
                    self.items[index].status = f"Converting page {done}/{total}"
                elif kind == "file_done":
                    _, index, output_path = message
                    self.items[index].status = "Done"
                    self.items[index].output_path = output_path
                    self.overall_progress["value"] += 1
                elif kind == "file_error":
                    _, index, error = message
                    self.items[index].status = f"Failed: {error}"
                    self.overall_progress["value"] += 1
                elif kind == "all_done":
                    _, converted, total = message
                    self.convert_button.config(state="normal")
                    if converted == total:
                        self.status_label.config(text=f"Converted {converted}/{total} file(s) successfully.", fg="green")
                    elif converted:
                        self.status_label.config(text=f"Converted {converted}/{total} file(s); some failed, see queue status.", fg="red")
                    else:
                        self.status_label.config(text="Conversion failed for all files, see queue status.", fg="red")
                self._refresh_tree()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_progress_queue)


def main():
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
