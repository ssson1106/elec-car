import os
import threading
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from automation import open_chrome, run_all

_BASE_PORT = 9222
_MINI_LOG_LIMIT = 5

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class RowFrame(ctk.CTkFrame):
    def __init__(self, parent, port, log_cb, select_card_cb, **kwargs):
        super().__init__(
            parent,
            width=248,
            height=232,
            fg_color="#ffffff",
            border_width=1,
            border_color="#d9e2ec",
            corner_radius=8,
            **kwargs,
        )
        self.grid_propagate(False)

        self.port = port
        self._log = log_cb
        self._select_card = select_card_cb
        self.log_lines = []
        self._mini_log_lines = []

        self.env_var = tk.StringVar()
        self.file1_var = tk.StringVar()
        self._status_var = tk.StringVar(value="대기")

        self.grid_columnconfigure(0, weight=1)
        self._build_card()
        self._bind_select(self)

    def _build_card(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=8, pady=(6, 3), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=f":{self.port}",
            text_color="#0f172a",
            font=ctk.CTkFont(family="Malgun Gothic", size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self._status_label = ctk.CTkLabel(
            header,
            textvariable=self._status_var,
            width=48,
            height=20,
            fg_color="#f1f5f9",
            text_color="#334155",
            corner_radius=10,
            font=ctk.CTkFont(family="Malgun Gothic", size=11),
        )
        self._status_label.grid(row=0, column=1, sticky="e")

        self._make_picker_row(
            row=1,
            label="env",
            variable=self.env_var,
            placeholder="env 파일 선택",
            command=self._browse,
        )
        self._make_picker_row(
            row=2,
            label="FILE1",
            variable=self.file1_var,
            placeholder="첨부 파일 선택",
            command=self._browse_file1,
        )

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, padx=8, pady=(2, 4), sticky="ew")
        actions.grid_columnconfigure((0, 1, 2), weight=1, uniform="actions")

        ctk.CTkButton(
            actions,
            text="Chrome",
            height=26,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(family="Malgun Gothic", size=11),
            command=self._open_chrome,
        ).grid(row=0, column=0, padx=(0, 3), sticky="ew")
        ctk.CTkButton(
            actions,
            text="실행",
            height=26,
            fg_color="#16a34a",
            hover_color="#15803d",
            font=ctk.CTkFont(family="Malgun Gothic", size=11),
            command=self._run,
        ).grid(row=0, column=1, padx=3, sticky="ew")
        self.remove_btn = ctk.CTkButton(
            actions,
            text="삭제",
            height=26,
            fg_color="#fff1f2",
            hover_color="#ffe4e6",
            text_color="#be123c",
            font=ctk.CTkFont(family="Malgun Gothic", size=11),
        )
        self.remove_btn.grid(row=0, column=2, padx=(3, 0), sticky="ew")

        ctk.CTkLabel(
            self,
            text="최근 로그",
            text_color="#64748b",
            font=ctk.CTkFont(family="Malgun Gothic", size=11, weight="bold"),
        ).grid(row=4, column=0, padx=8, pady=(2, 2), sticky="w")

        self.mini_log = ctk.CTkTextbox(
            self,
            height=72,
            wrap="word",
            fg_color="#f8fafc",
            text_color="#334155",
            border_width=1,
            border_color="#e2e8f0",
            corner_radius=6,
            font=ctk.CTkFont(family="Malgun Gothic", size=11),
        )
        self.mini_log.grid(row=5, column=0, padx=8, pady=(0, 8), sticky="ew")
        self.mini_log.configure(state=tk.DISABLED)

    def _make_picker_row(self, row, label, variable, placeholder, command):
        line = ctk.CTkFrame(self, fg_color="transparent")
        line.grid(row=row, column=0, padx=8, pady=(0, 4), sticky="ew")
        line.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            line,
            text=label,
            width=36,
            text_color="#334155",
            font=ctk.CTkFont(family="Malgun Gothic", size=11, weight="bold"),
        ).grid(row=0, column=0, padx=(0, 4), sticky="w")
        ctk.CTkEntry(
            line,
            textvariable=variable,
            placeholder_text=placeholder,
            height=26,
            border_color="#cbd5e1",
            font=ctk.CTkFont(family="Malgun Gothic", size=11),
        ).grid(row=0, column=1, padx=(0, 4), sticky="ew")
        ctk.CTkButton(
            line,
            text="...",
            width=28,
            height=26,
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color="#1e293b",
            command=command,
        ).grid(row=0, column=2)

    def _bind_select(self, widget):
        widget.bind("<Button-1>", self._handle_select, add="+")
        for child in widget.winfo_children():
            self._bind_select(child)

    def _handle_select(self, event):
        self._select_card()
        if not self._is_text_editing_widget(event.widget):
            self.focus_set()

    def _is_text_editing_widget(self, widget):
        while widget is not None:
            class_name = widget.winfo_class()
            if class_name in {"Entry", "Text"} or "Textbox" in class_name:
                return True
            widget = widget.master
        return False

    def set_selected(self, selected):
        self.configure(border_width=2 if selected else 1)
        self.configure(border_color="#2563eb" if selected else "#d9e2ec")

    def display_name(self):
        path = self.env_var.get().strip()
        return os.path.basename(path)[:24] if path else f":{self.port}"

    def _set_status(self, text, bg, fg):
        self._status_var.set(text)
        self._status_label.configure(fg_color=bg, text_color=fg)

    def append_mini_log(self, msg):
        self._mini_log_lines.append(msg)
        self._mini_log_lines = self._mini_log_lines[-_MINI_LOG_LIMIT:]
        self.mini_log.configure(state=tk.NORMAL)
        self.mini_log.delete("1.0", tk.END)
        self.mini_log.insert(tk.END, "\n".join(self._mini_log_lines))
        self.mini_log.configure(state=tk.DISABLED)

    def clear_logs(self):
        self.log_lines.clear()
        self._mini_log_lines.clear()
        self.mini_log.configure(state=tk.NORMAL)
        self.mini_log.delete("1.0", tk.END)
        self.mini_log.configure(state=tk.DISABLED)

    def _browse(self):
        self._select_card()
        path = filedialog.askopenfilename(
            title="env 파일 선택",
            filetypes=[("env 파일", "*.env"), ("모든 파일", "*.*")],
        )
        if path:
            self.env_var.set(path)

    def _browse_file1(self):
        self._select_card()
        path = filedialog.askopenfilename(
            title="FILE1 첨부 파일 선택",
            filetypes=[
                ("PDF 파일", "*.pdf"),
                ("이미지 파일", "*.jpg *.jpeg *.png"),
                ("모든 파일", "*.*"),
            ],
        )
        if path:
            self.file1_var.set(path)

    def _open_chrome(self):
        self._select_card()
        try:
            open_chrome(self.port)
            self._log(f"Chrome 실행됨 (포트 :{self.port})")
            self._log("열린 브라우저에서 로그인한 뒤 [실행]을 클릭하세요.")
        except Exception as e:
            self._log(f"Chrome 열기 실패: {e}")

    def _run(self):
        self._select_card()
        path = self.env_var.get().strip()
        if not path:
            self._log("env 파일을 먼저 선택하세요.")
            return
        if not os.path.exists(path):
            self._log(f"env 파일 없음: {path}")
            return

        file1_path = self.file1_var.get().strip()
        if file1_path and not os.path.exists(file1_path):
            self._log(f"FILE1 파일 없음: {file1_path}")
            return

        self.after(0, lambda: self._set_status("실행중", "#dbeafe", "#1d4ed8"))

        def _task():
            try:
                run_all(path, self.port, self._log, file1_path=file1_path or None)
                self.after(0, lambda: self._set_status("완료", "#dcfce7", "#166534"))
            except Exception as e:
                self.after(0, lambda: self._set_status("오류", "#ffe4e6", "#be123c"))
                self._log(f"오류: {e}")

        threading.Thread(target=_task, daemon=True).start()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EV 보조금 신청 자동화")
        self.geometry("1120x640")
        self.minsize(980, 560)
        self.configure(fg_color="#f6f8fb")

        self._port_counter = _BASE_PORT
        self._rows = []
        self._selected_row = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self._build_rows_area()
        self._build_log_area()
        self._add_row()
        self.bind_all("<Delete>", self._delete_selected_row, add="+")
        self.bind_all("<KP_Delete>", self._delete_selected_row, add="+")

    def _build_rows_area(self):
        section = ctk.CTkFrame(self, fg_color="transparent")
        section.grid(row=0, column=0, padx=10, pady=(6, 4), sticky="ew")
        section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            section,
            text="신청 목록",
            text_color="#334155",
            font=ctk.CTkFont(family="Malgun Gothic", size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        ctk.CTkButton(
            section,
            text="+ 추가",
            width=80,
            height=28,
            fg_color="#0f766e",
            hover_color="#115e59",
            font=ctk.CTkFont(family="Malgun Gothic", size=12, weight="bold"),
            command=self._add_row,
        ).grid(row=0, column=1, sticky="e", pady=(0, 4))

        self._row_box = ctk.CTkScrollableFrame(
            section,
            height=252,
            orientation="horizontal",
            fg_color="#edf2f7",
            corner_radius=8,
            scrollbar_button_color="#cbd5e1",
            scrollbar_button_hover_color="#94a3b8",
        )
        self._row_box.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _build_log_area(self):
        log_frame = ctk.CTkFrame(self, fg_color="#ffffff", corner_radius=8)
        log_frame.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(log_frame, fg_color="transparent")
        header.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self._detail_title_var = tk.StringVar(value="선택 항목 상세 로그")
        ctk.CTkLabel(
            header,
            textvariable=self._detail_title_var,
            text_color="#334155",
            font=ctk.CTkFont(family="Malgun Gothic", size=15, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header,
            text="로그 지우기",
            width=92,
            height=28,
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color="#334155",
            font=ctk.CTkFont(family="Malgun Gothic", size=12),
            command=self._clear_selected_log,
        ).grid(row=0, column=1, sticky="e")

        self._detail_log = ctk.CTkTextbox(
            log_frame,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#0f172a",
            text_color="#e2e8f0",
            border_width=0,
            corner_radius=8,
        )
        self._detail_log.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="nsew")
        self._detail_log.configure(state=tk.DISABLED)

    def _clear_selected_log(self):
        if self._selected_row is not None:
            self._selected_row.clear_logs()
        self._detail_log.configure(state=tk.NORMAL)
        self._detail_log.delete("1.0", tk.END)
        self._detail_log.configure(state=tk.DISABLED)

    def _write_detail_log(self, lines):
        self._detail_log.configure(state=tk.NORMAL)
        self._detail_log.delete("1.0", tk.END)
        if lines:
            self._detail_log.insert(tk.END, "\n".join(lines) + "\n")
            self._detail_log.see(tk.END)
        self._detail_log.configure(state=tk.DISABLED)

    def _append_log(self, row, msg):
        if row not in self._rows:
            return
        row.log_lines.append(msg)
        row.append_mini_log(msg)
        if row is self._selected_row:
            self._detail_log.configure(state=tk.NORMAL)
            self._detail_log.insert(tk.END, msg + "\n")
            self._detail_log.see(tk.END)
            self._detail_log.configure(state=tk.DISABLED)

    def _select_row(self, row):
        if row not in self._rows:
            return
        if self._selected_row is not None:
            self._selected_row.set_selected(False)
        self._selected_row = row
        row.set_selected(True)
        self._detail_title_var.set(f"{row.display_name()} 상세 로그")
        self._write_detail_log(row.log_lines)

    def _add_row(self):
        port = self._port_counter
        self._port_counter += 1

        row_holder = {}

        def log_cb(msg):
            self.after(0, self._append_log, row_holder["row"], msg)

        def select_card_cb():
            self._select_row(row_holder["row"])

        row = RowFrame(
            self._row_box,
            port=port,
            log_cb=log_cb,
            select_card_cb=select_card_cb,
        )
        row_holder["row"] = row
        row.grid(row=0, column=len(self._rows), sticky="ns", padx=(6, 0), pady=6)
        self._rows.append(row)

        row.env_var.trace_add("write", lambda *_: self._refresh_selected_title(row))
        row.remove_btn.configure(command=lambda r=row: self._remove_row(r))
        self._select_row(row)

    def _refresh_selected_title(self, row):
        if row is self._selected_row:
            self._detail_title_var.set(f"{row.display_name()} 상세 로그")

    def _remove_row(self, row):
        was_selected = row is self._selected_row
        row.destroy()
        if row in self._rows:
            self._rows.remove(row)
        self._reflow_rows()

        if not self._rows:
            self._selected_row = None
            self._detail_title_var.set("선택 항목 상세 로그")
            self._write_detail_log([])
            return

        if was_selected:
            self._selected_row = None
            self._select_row(self._rows[0])

    def _reflow_rows(self):
        for index, row in enumerate(self._rows):
            row.grid_configure(row=0, column=index)

    def _delete_selected_row(self, event=None):
        if self._selected_row is None:
            return None
        if event is not None and self._is_text_editing_widget(event.widget):
            return None
        self._remove_row(self._selected_row)
        return "break"

    def _is_text_editing_widget(self, widget):
        while widget is not None:
            class_name = widget.winfo_class()
            if class_name in {"Entry", "Text"} or "Textbox" in class_name:
                return True
            widget = widget.master
        return False


if __name__ == "__main__":
    App().mainloop()
