#!/usr/bin/env python3
"""
Spending Tracker (PyQt6, finalized)
- Modern PyQt6 GUI with dark theme
- Add/Edit/Delete entries with Date + Time, Category, Description, Amount
- Filters by date range and category
- Totals (Income / Expense / Balance)
- Export current view to CSV
- Optional Charts tab (category breakdown) if PyQt6-Charts is installed

Data:
- SQLite DB at 'spending.db' next to this script (or next to the packaged .exe).
- Positive amounts = income; negative = expense.

Run:
    pip install PyQt6
    # optional for charts:
    pip install PyQt6-Charts
    py spend_tracker_pyqt_final.py

Package:
    pyinstaller --onefile --windowed --name SpendingTracker --icon money.ico spend_tracker_pyqt_final.py
"""

import os
import sys
import csv
import sqlite3
from datetime import datetime

from PyQt6 import QtCore, QtGui, QtWidgets

# Optional charts support
try:
    from PyQt6.QtCharts import QChart, QChartView, QPieSeries
    HAS_CHARTS = True
except Exception:
    HAS_CHARTS = False

APP_TITLE = "Spending Tracker"
CATEGORIES = [
    "Food", "Groceries", "Transport", "Entertainment",
    "Bills", "Rent", "Shopping", "Education", "Health",
    "Smoking", "Income", "Other"
]


def app_base_dir() -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(app_base_dir(), "spending.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dt TEXT NOT NULL,            -- YYYY-MM-DD
    tm TEXT,                     -- HH:MM
    category TEXT NOT NULL,
    description TEXT,
    amount REAL NOT NULL
);
"""


class DB:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute(SCHEMA_SQL)
        self.conn.commit()
        self._maybe_add_time_column()

    def _maybe_add_time_column(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(entries)")
        cols = [r[1] for r in cur.fetchall()]
        if "tm" not in cols:
            self.conn.execute("ALTER TABLE entries ADD COLUMN tm TEXT;")
            self.conn.commit()

    def add(self, dt, tm, category, description, amount):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO entries (dt, tm, category, description, amount) VALUES (?, ?, ?, ?, ?)",
            (dt, tm, category, description, amount)
        )
        self.conn.commit()
        return cur.lastrowid

    def update(self, entry_id, dt, tm, category, description, amount):
        self.conn.execute(
            "UPDATE entries SET dt=?, tm=?, category=?, description=?, amount=? WHERE id=?",
            (dt, tm, category, description, amount, entry_id)
        )
        self.conn.commit()

    def delete(self, entry_id):
        self.conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        self.conn.commit()

    def fetch(self, dt_from=None, dt_to=None, category=None):
        q = "SELECT id, dt, tm, category, description, amount FROM entries WHERE 1=1"
        params = []
        if dt_from:
            q += " AND date(dt) >= date(?)"
            params.append(dt_from)
        if dt_to:
            q += " AND date(dt) <= date(?)"
            params.append(dt_to)
        if category and category != "All":
            q += " AND category = ?"
            params.append(category)
        q += " ORDER BY date(dt) DESC, ifnull(tm,'00:00') DESC, id DESC"
        cur = self.conn.cursor()
        cur.execute(q, params)
        return cur.fetchall()

    def totals(self, dt_from=None, dt_to=None, category=None):
        rows = self.fetch(dt_from, dt_to, category)
        income = sum(a for *_rest, a in rows if a >= 0)
        expense = sum(a for *_rest, a in rows if a < 0)
        return income, expense, income + expense

    def by_category(self, dt_from=None, dt_to=None, category=None):
        """Aggregate sum(amount) by category for current filter (ignores 'category' filter)."""
        q = "SELECT category, SUM(amount) FROM entries WHERE 1=1"
        params = []
        if dt_from:
            q += " AND date(dt) >= date(?)"
            params.append(dt_from)
        if dt_to:
            q += " AND date(dt) <= date(?)"
            params.append(dt_to)
        q += " GROUP BY category ORDER BY category ASC"
        cur = self.conn.cursor()
        cur.execute(q, params)
        return cur.fetchall()


class SpendingApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = DB()
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 720)
        self._apply_dark_theme()

        # Main tabs
        tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(tabs)

        # --- Tab 1: Tracker ---
        self.tracker_tab = QtWidgets.QWidget()
        tabs.addTab(self.tracker_tab, "Tracker")
        tracker_layout = QtWidgets.QVBoxLayout(self.tracker_tab)

        # Form
        form_group = QtWidgets.QGroupBox("Add / Edit Entry")
        form_layout = QtWidgets.QGridLayout(form_group)

        self.date_edit = QtWidgets.QDateEdit()
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QtCore.QDate.currentDate())

        self.time_edit = QtWidgets.QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTime(QtCore.QTime.currentTime())

        self.cat_combo = QtWidgets.QComboBox()
        self.cat_combo.addItems(CATEGORIES)

        self.desc_edit = QtWidgets.QLineEdit()
        self.amount_edit = QtWidgets.QLineEdit("0.00")
        self.amount_edit.setPlaceholderText("Use negative for expenses, positive for income")

        # Buttons with standard icons (no external files required)
        style = self.style()
        self.btn_add = QtWidgets.QPushButton("Add")
        self.btn_add.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton))
        self.btn_update = QtWidgets.QPushButton("Update Selected")
        self.btn_update.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
        self.btn_delete = QtWidgets.QPushButton("Delete Selected")
        self.btn_delete.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_TrashIcon))
        self.btn_clear = QtWidgets.QPushButton("Clear Form")
        self.btn_clear.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_LineEditClearButton))
        self.btn_export = QtWidgets.QPushButton("Export CSV")
        self.btn_export.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DriveFDIcon))
        self.btn_quit = QtWidgets.QPushButton("Quit")
        self.btn_quit.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogCloseButton))

        r = 0
        form_layout.addWidget(QtWidgets.QLabel("Date:"), r, 0)
        form_layout.addWidget(self.date_edit, r, 1)
        form_layout.addWidget(QtWidgets.QLabel("Time:"), r, 2)
        form_layout.addWidget(self.time_edit, r, 3)
        form_layout.addWidget(QtWidgets.QLabel("Category:"), r, 4)
        form_layout.addWidget(self.cat_combo, r, 5)
        form_layout.addWidget(QtWidgets.QLabel("Amount:"), r, 6)
        form_layout.addWidget(self.amount_edit, r, 7)

        r += 1
        form_layout.addWidget(QtWidgets.QLabel("Description:"), r, 0)
        form_layout.addWidget(self.desc_edit, r, 1, 1, 7)

        r += 1
        form_layout.addWidget(self.btn_add, r, 0)
        form_layout.addWidget(self.btn_update, r, 1)
        form_layout.addWidget(self.btn_delete, r, 2)
        form_layout.addWidget(self.btn_clear, r, 3)
        form_layout.addWidget(self.btn_export, r, 4)
        form_layout.addWidget(self.btn_quit, r, 5)

        tracker_layout.addWidget(form_group)

        # Filters
        filter_group = QtWidgets.QGroupBox("Filters")
        filter_layout = QtWidgets.QGridLayout(filter_group)

        self.from_edit = QtWidgets.QDateEdit()
        self.from_edit.setDisplayFormat("yyyy-MM-dd")
        self.from_edit.setCalendarPopup(True)
        self.from_edit.setSpecialValueText("")
        self.from_edit.clear()

        self.to_edit = QtWidgets.QDateEdit()
        self.to_edit.setDisplayFormat("yyyy-MM-dd")
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setSpecialValueText("")
        self.to_edit.clear()

        self.filter_cat = QtWidgets.QComboBox()
        self.filter_cat.addItems(["All"] + CATEGORIES)

        self.btn_apply_filters = QtWidgets.QPushButton("Apply Filters")
        self.btn_apply_filters.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowForward))
        self.btn_reset_filters = QtWidgets.QPushButton("Reset Filters")
        self.btn_reset_filters.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserStop))

        filter_layout.addWidget(QtWidgets.QLabel("From:"), 0, 0)
        filter_layout.addWidget(self.from_edit, 0, 1)
        filter_layout.addWidget(QtWidgets.QLabel("To:"), 0, 2)
        filter_layout.addWidget(self.to_edit, 0, 3)
        filter_layout.addWidget(QtWidgets.QLabel("Category:"), 0, 4)
        filter_layout.addWidget(self.filter_cat, 0, 5)
        filter_layout.addWidget(self.btn_apply_filters, 0, 6)
        filter_layout.addWidget(self.btn_reset_filters, 0, 7)

        tracker_layout.addWidget(filter_group)

        # Table
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Date", "Time", "Category", "Description", "Amount"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 520)
        self.table.setColumnWidth(5, 120)

        tracker_layout.addWidget(self.table, 1)

        # Totals
        totals_layout = QtWidgets.QHBoxLayout()
        self.lbl_income = QtWidgets.QLabel("Income: $0.00")
        self.lbl_expense = QtWidgets.QLabel("Expense: $0.00")
        self.lbl_balance = QtWidgets.QLabel("Balance: $0.00")
        font = self.lbl_income.font()
        font.setBold(True)
        for w in (self.lbl_income, self.lbl_expense, self.lbl_balance):
            w.setFont(font)
        totals_layout.addWidget(self.lbl_income)
        totals_layout.addSpacing(18)
        totals_layout.addWidget(self.lbl_expense)
        totals_layout.addSpacing(18)
        totals_layout.addWidget(self.lbl_balance)
        totals_layout.addStretch(1)
        tracker_layout.addLayout(totals_layout)

        # Connections
        self.btn_add.clicked.connect(self.on_add)
        self.btn_update.clicked.connect(self.on_update)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_clear.clicked.connect(self.clear_form)
        self.btn_export.clicked.connect(self.on_export)
        self.btn_quit.clicked.connect(self.close)
        self.table.itemSelectionChanged.connect(self.on_table_select)
        self.btn_apply_filters.clicked.connect(self.refresh)
        self.btn_reset_filters.clicked.connect(self.reset_filters)

        # --- Tab 2: Charts (optional) ---
        charts_container = QtWidgets.QWidget()
        tabs.addTab(charts_container, "Charts")
        charts_layout = QtWidgets.QVBoxLayout(charts_container)
        if HAS_CHARTS:
            self.chart_view = QChartView()
            self.chart_view.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            charts_layout.addWidget(self.chart_view, 1)

            # Controls
            ctrl_row = QtWidgets.QHBoxLayout()
            self.btn_refresh_chart = QtWidgets.QPushButton("Refresh Chart")
            self.btn_refresh_chart.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
            ctrl_row.addWidget(self.btn_refresh_chart)
            ctrl_row.addStretch(1)
            charts_layout.addLayout(ctrl_row)
            self.btn_refresh_chart.clicked.connect(self.update_chart)
        else:
            msg = QtWidgets.QLabel(
                "Charts are optional.\nInstall PyQt6-Charts to enable:  pip install PyQt6-Charts"
            )
            msg.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            charts_layout.addWidget(msg, 1)

        # Initial fill
        self.refresh()
        if HAS_CHARTS:
            self.update_chart()

        # Status bar
        self.statusBar().showMessage("Ready")

    # ---- Theme ----
    def _apply_dark_theme(self):
        # Simple dark palette for a modern look
        app = QtWidgets.QApplication.instance()
        app.setStyle("Fusion")
        palette = QtGui.QPalette()
        base = QtGui.QColor(45, 45, 45)
        alt = QtGui.QColor(53, 53, 53)
        text = QtGui.QColor(220, 220, 220)
        highlight = QtGui.QColor(42, 130, 218)

        palette.setColor(QtGui.QPalette.ColorRole.Window, alt)
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, text)
        palette.setColor(QtGui.QPalette.ColorRole.Base, base)
        palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, alt)
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipBase, text)
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipText, text)
        palette.setColor(QtGui.QPalette.ColorRole.Text, text)
        palette.setColor(QtGui.QPalette.ColorRole.Button, alt)
        palette.setColor(QtGui.QPalette.ColorRole.ButtonText, text)
        palette.setColor(QtGui.QPalette.ColorRole.BrightText, QtCore.Qt.GlobalColor.red)
        palette.setColor(QtGui.QPalette.ColorRole.Highlight, highlight)
        palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtCore.Qt.GlobalColor.black)
        app.setPalette(palette)

        # Subtle table row height
        app.setStyleSheet("""
            QGroupBox { font-weight: bold; border: 1px solid #444; border-radius: 6px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 6px; }
            QTableWidget { gridline-color: #555; }
            QHeaderView::section { background: #404040; padding: 6px; border: none; }
            QPushButton { padding: 6px 10px; }
            QLineEdit, QComboBox, QDateEdit, QTimeEdit { padding: 4px; }
        """)

    # ---- Helpers ----
    def _current_filters(self):
        dt_from = self.from_edit.date().toString("yyyy-MM-dd") if self.from_edit.date().isValid() else None
        dt_to = self.to_edit.date().toString("yyyy-MM-dd") if self.to_edit.date().isValid() else None
        cat = self.filter_cat.currentText()
        return dt_from, dt_to, cat

    def _parse_amount(self, text: str) -> float:
        try:
            return float(text)
        except ValueError:
            raise ValueError("Amount must be a number (use negative for expenses).")

    def clear_form(self):
        self.date_edit.setDate(QtCore.QDate.currentDate())
        self.time_edit.setTime(QtCore.QTime.currentTime())
        self.cat_combo.setCurrentIndex(0)
        self.desc_edit.clear()
        self.amount_edit.setText("0.00")
        self.table.clearSelection()

    def _form_values(self):
        dt = self.date_edit.date().toString("yyyy-MM-dd")
        tm = self.time_edit.time().toString("HH:mm")
        cat = self.cat_combo.currentText()
        desc = self.desc_edit.text().strip()
        amt = self._parse_amount(self.amount_edit.text().strip())
        return dt, tm, cat, desc, amt

    def _selected_id(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        ridx = rows[0].row()
        item = self.table.item(ridx, 0)
        return int(item.text()) if item else None

    # ---- Actions ----
    def on_add(self):
        try:
            dt, tm, cat, desc, amt = self._form_values()
            new_id = self.db.add(dt, tm, cat, desc, amt)
            self.refresh(select_id=new_id)
            self._status(f"Added entry #{new_id}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Invalid input", str(e))

    def on_update(self):
        entry_id = self._selected_id()
        if not entry_id:
            QtWidgets.QMessageBox.information(self, "No selection", "Select a row to update.")
            return
        try:
            dt, tm, cat, desc, amt = self._form_values()
            self.db.update(entry_id, dt, tm, cat, desc, amt)
            self.refresh(select_id=entry_id)
            self._status(f"Updated entry #{entry_id}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Invalid input", str(e))

    def on_delete(self):
        entry_id = self._selected_id()
        if not entry_id:
            QtWidgets.QMessageBox.information(self, "No selection", "Select a row to delete.")
            return
        if QtWidgets.QMessageBox.question(self, "Confirm Delete",
                                          f"Delete entry #{entry_id}?") == QtWidgets.QMessageBox.StandardButton.Yes:
            self.db.delete(entry_id)
            self.refresh()
            self._status(f"Deleted entry #{entry_id}")

    def on_table_select(self):
        entry_id = self._selected_id()
        if entry_id is None:
            return
        r = self.table.selectionModel().selectedRows()[0].row()
        dt = self.table.item(r, 1).text()
        tm = self.table.item(r, 2).text()
        cat = self.table.item(r, 3).text()
        desc = self.table.item(r, 4).text()
        amt = self.table.item(r, 5).text()
        self.date_edit.setDate(QtCore.QDate.fromString(dt, "yyyy-MM-dd"))
        self.time_edit.setTime(QtCore.QTime.fromString(tm or "00:00", "HH:mm"))
        self.cat_combo.setCurrentText(cat)
        self.desc_edit.setText(desc)
        self.amount_edit.setText(f"{float(amt):.2f}")

    def on_export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export to CSV", "spending.csv", "CSV Files (*.csv)")
        if not path:
            return
        dt_from, dt_to, cat = self._current_filters()
        rows = self.db.fetch(dt_from, dt_to, cat)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Date", "Time", "Category", "Description", "Amount"])
            for r in rows:
                writer.writerow(r)
        QtWidgets.QMessageBox.information(self, "Export Complete", f"Saved {len(rows)} rows to:\n{path}")

    def reset_filters(self):
        self.from_edit.clear()
        self.to_edit.clear()
        self.filter_cat.setCurrentIndex(0)
        self.refresh()

    def refresh(self, select_id=None):
        dt_from, dt_to, cat = self._current_filters()
        rows = self.db.fetch(dt_from, dt_to, cat)
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, val in enumerate(row):
                item = QtWidgets.QTableWidgetItem("" if val is None else str(val))
                if c == 0:
                    item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if c == 5:
                    item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)

        income, expense, balance = self.db.totals(dt_from, dt_to, cat)
        self.lbl_income.setText(f"Income: ${income:,.2f}")
        self.lbl_expense.setText(f"Expense: ${expense:,.2f}")
        self.lbl_balance.setText(f"Balance: ${balance:,.2f}")

        if select_id is not None:
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).text() == str(select_id):
                    self.table.selectRow(r)
                    self.table.scrollToItem(self.table.item(r, 0))
                    break

        if HAS_CHARTS:
            self.update_chart()

    def update_chart(self):
        if not HAS_CHARTS:
            return
        dt_from, dt_to, _cat = self._current_filters()
        data = self.db.by_category(dt_from, dt_to)

        series = QPieSeries()
        # Only show expenses (negative amounts) by absolute value
        total = 0.0
        for cat, amt in data:
            if amt < 0:
                val = abs(amt)
                if val > 0:
                    series.append(f"{cat}", val)
                    total += val

        if series.slices():
            for s in series.slices():
                s.setLabel(f"{s.label()} — ${s.value():,.2f}")
                s.setLabelVisible(True)

        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Expenses by Category" + (f" — Total ${total:,.2f}" if total else ""))
        chart.legend().setVisible(True)
        chart.legend().setAlignment(QtCore.Qt.AlignmentFlag.AlignBottom)
        self.chart_view.setChart(chart)

    def _status(self, msg: str, msec: int = 2000):
        self.statusBar().showMessage(msg, msec)


def _build_tracker_ui_stub():
    """Create missing attributes used by logic but belonging to UI; used during __init__."""
    pass


def main():
    # Improve HiDPI behavior on Windows
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)

    win = SpendingApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
