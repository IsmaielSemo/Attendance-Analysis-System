#gui.py -> Handles gui of application

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

from tkcalendar import DateEntry
from datetime import date, timedelta

from database import get_attendance, get_unique_badges
from attendance import *
from excel_export import export_excel
from pdf_export import export_pdf

# Import the ML function
from ml import top_anomalies


class AttendanceGUI:

    def __init__(self):

        self.root = tk.Tk()

        self.root.title("Attendance Analysis System")

        self.root.geometry("1600x900")

        self.root.minsize(1400, 800)

        self.root.configure(bg="#ECECEC")

        self.style = ttk.Style()

        self.style.theme_use("clam")

        self.create_header_frame()  # New Logo/Header Frame

        self.create_search_frame()

        self.create_summary_frame()

        self.create_notebook()

        self.create_status_bar()

        self.root.bind(
            "<Return>",
            lambda event: self.search()
        )

    # ======================================================
    # HEADER / LOGO FRAME
    # ======================================================
    def create_header_frame(self):

        frame = tk.Frame(self.root, bg="#ECECEC")
        frame.pack(fill="x", padx=10, pady=(10, 0))

        # Attempt to load the logo
        try:
            self.logo_img = tk.PhotoImage(file="static/logo.png")
            tk.Label(
                frame,
                image=self.logo_img,
                bg="#ECECEC"
            ).pack(side="left", padx=(0, 15))
        except Exception:
            pass  # If logo.png is missing, it just skips this without crashing

        tk.Label(
            frame,
            text="Attendance Analysis System",
            font=("Segoe UI", 24, "bold"),
            bg="#ECECEC",
            fg="#333333"
        ).pack(side="left")

    # ======================================================
    # SEARCH FRAME (DROPDOWN / COMBOBOX UPDATE)
    # ======================================================
    def create_search_frame(self):

        frame = ttk.LabelFrame(
            self.root,
            text="Search Attendance",
            padding=15
        )

        frame.pack(
            fill="x",
            padx=10,
            pady=10
        )

        ttk.Label(
            frame,
            text="Badge ID"
        ).grid(row=0, column=0, padx=5)

        # --------------------------------------------------
        # Fetch Unique Badges & Populate Combobox (Dropdown)
        # --------------------------------------------------
        try:
            badge_options = get_unique_badges()
        except Exception:
            badge_options = []

        # Add 'All' option at the beginning
        badge_options.insert(0, "All")

        self.badge_var = tk.StringVar()
        self.badge_dropdown = ttk.Combobox(
            frame,
            textvariable=self.badge_var,
            values=badge_options,
            state="readonly",  # Readonly dropdown to prevent invalid typing
            width=15
        )

        self.badge_dropdown.set("All")  # Default value
        self.badge_dropdown.grid(row=0, column=1, padx=5)

        ttk.Label(
            frame,
            text="Start Date"
        ).grid(row=0, column=2, padx=5)

        self.start_date = DateEntry(
            frame,
            width=12,
            firstweekday='sunday',
            weekenddays=[6, 7]
        )

        self.start_date.set_date(
            date.today() - timedelta(days=30)
        )

        self.start_date.grid(row=0, column=3, padx=5)

        ttk.Label(
            frame,
            text="End Date"
        ).grid(row=0, column=4, padx=5)

        self.end_date = DateEntry(
            frame,
            width=12,
            firstweekday='sunday',
            weekenddays=[6, 7]
        )

        self.end_date.set_date(date.today())

        self.end_date.grid(row=0, column=5, padx=5)

        ttk.Button(
            frame,
            text="Search",
            command=self.search
        ).grid(row=0, column=6, padx=10)

        ttk.Button(
            frame,
            text="Clear",
            command=self.clear_tables
        ).grid(row=0, column=7, padx=5)

        ttk.Button(
            frame,
            text="Export Excel",
            command=self.export_excel_report
        ).grid(row=0, column=8, padx=5)

        ttk.Button(
            frame,
            text="Export PDF",
            command=self.export_pdf_report
        ).grid(row=0, column=9, padx=5)

    # ======================================================
    # SUMMARY FRAME
    # ======================================================
    def create_summary_frame(self):

        frame = ttk.Frame(self.root)

        frame.pack(fill="x", padx=10, pady=5)

        self.summary_vars = {}

        cards = [
            "Employees",
            "Working Days",
            "Total Punches",
            "Average Arrival",
            "Average Departure",
            "Average Punches/Day"
        ]

        for i, title in enumerate(cards):
            card = ttk.LabelFrame(
                frame,
                text=title,
                padding=15
            )

            card.grid(row=0, column=i, padx=5, sticky="nsew")

            var = tk.StringVar()
            var.set("-")

            ttk.Label(
                card,
                textvariable=var,
                font=("Segoe UI", 18, "bold")
            ).pack()

            self.summary_vars[title] = var
            frame.columnconfigure(i, weight=1)

    # ======================================================
    # NOTEBOOK
    # ======================================================
    def create_notebook(self):

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.root.rowconfigure(2, weight=1)
        self.root.columnconfigure(0, weight=1)

        self.transactions_tab = ttk.Frame(self.notebook)
        self.daily_tab = ttk.Frame(self.notebook)
        self.overall_tab = ttk.Frame(self.notebook)
        self.statistics_tab = ttk.Frame(self.notebook)
        self.alerts_tab = ttk.Frame(self.notebook)
        self.ml_tab = ttk.Frame(self.notebook)  # New ML Tab

        self.notebook.add(self.transactions_tab, text="Transactions")
        self.notebook.add(self.daily_tab, text="Daily Summary")
        self.notebook.add(self.overall_tab, text="Overall Summary")
        self.notebook.add(self.statistics_tab, text="Statistics")
        self.notebook.add(self.alerts_tab, text="Alerts")
        self.notebook.add(self.ml_tab, text="AI Anomalies")  # Added ML Tab to Notebook

        self.create_transaction_table()
        self.create_daily_table()
        self.create_overall_table()
        self.create_statistics_table()
        self.create_alerts_table()
        self.create_ml_table()  # Build ML Table

    # ======================================================
    # STATUS BAR
    # ======================================================
    def create_status_bar(self):

        self.status = tk.StringVar()
        self.status.set("Ready")

        ttk.Label(
            self.root,
            textvariable=self.status,
            relief="sunken",
            anchor="w"
        ).pack(side="bottom", fill="x")

    # ======================================================
    # TRANSACTIONS TABLE
    # ======================================================
    def create_transaction_table(self):

        columns = ("BadgeID", "Datetime", "Status", "Branch")

        self.transactions_tree = ttk.Treeview(
            self.transactions_tab,
            columns=columns,
            show="headings"
        )

        for c in columns:
            self.transactions_tree.heading(c, text=c)
            self.transactions_tree.column(c, width=180, stretch=True, anchor="center")

        scrollbar = ttk.Scrollbar(
            self.transactions_tab,
            orient="vertical",
            command=self.transactions_tree.yview
        )

        self.transactions_tree.configure(yscrollcommand=scrollbar.set)
        self.transactions_tree.tag_configure("IN", background="#E8F5E9")
        self.transactions_tree.tag_configure("OUT", background="#FFEBEE")

        self.transactions_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ======================================================
    # DAILY SUMMARY TABLE
    # ======================================================
    def create_daily_table(self):

        columns = ("BadgeID", "Date", "First IN", "Last OUT", "Punches")

        self.daily_tree = ttk.Treeview(
            self.daily_tab,
            columns=columns,
            show="headings"
        )

        for c in columns:
            self.daily_tree.heading(c, text=c)
            self.daily_tree.column(c, width=170, anchor="center")

        scrollbar = ttk.Scrollbar(
            self.daily_tab,
            orient="vertical",
            command=self.daily_tree.yview
        )

        self.daily_tree.configure(yscrollcommand=scrollbar.set)
        self.daily_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ======================================================
    # OVERALL SUMMARY TABLE
    # ======================================================
    def create_overall_table(self):

        columns = ("BadgeID", "Working Days", "Total Punches", "First Entry", "Last Exit")

        self.overall_tree = ttk.Treeview(
            self.overall_tab,
            columns=columns,
            show="headings"
        )

        for c in columns:
            self.overall_tree.heading(c, text=c)
            self.overall_tree.column(c, width=190, anchor="center")

        scrollbar = ttk.Scrollbar(
            self.overall_tab,
            orient="vertical",
            command=self.overall_tree.yview
        )

        self.overall_tree.configure(yscrollcommand=scrollbar.set)
        self.overall_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ======================================================
    # STATISTICS TABLE
    # ======================================================
    def create_statistics_table(self):

        columns = ("Statistic", "Value")

        self.statistics_tree = ttk.Treeview(
            self.statistics_tab,
            columns=columns,
            show="headings"
        )

        for c in columns:
            self.statistics_tree.heading(c, text=c)
            self.statistics_tree.column(c, width=300, anchor="center")

        scrollbar = ttk.Scrollbar(
            self.statistics_tab,
            orient="vertical",
            command=self.statistics_tree.yview
        )

        self.statistics_tree.configure(yscrollcommand=scrollbar.set)
        self.statistics_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ======================================================
    # ALERTS TABLE
    # ======================================================
    def create_alerts_table(self):

        columns = ("BadgeID", "Date", "Datetime", "Problem")

        self.alerts_tree = ttk.Treeview(
            self.alerts_tab,
            columns=columns,
            show="headings"
        )

        for c in columns:
            self.alerts_tree.heading(c, text=c)
            self.alerts_tree.column(c, width=250, anchor="center")

        scrollbar = ttk.Scrollbar(
            self.alerts_tab,
            orient="vertical",
            command=self.alerts_tree.yview
        )

        self.alerts_tree.configure(yscrollcommand=scrollbar.set)
        self.alerts_tree.tag_configure("warning", background="#FFE5E5")

        self.alerts_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ======================================================
    # ML ANOMALIES TABLE
    # ======================================================
    def create_ml_table(self):

        columns = ("BadgeID", "Prediction", "Risk", "Score", "Reasons")

        self.ml_tree = ttk.Treeview(
            self.ml_tab,
            columns=columns,
            show="headings"
        )

        for c in columns:
            self.ml_tree.heading(c, text=c)

        # Set specific widths for the ML columns so reasons fit
        self.ml_tree.column("BadgeID", width=100, anchor="center")
        self.ml_tree.column("Prediction", width=120, anchor="center")
        self.ml_tree.column("Risk", width=120, anchor="center")
        self.ml_tree.column("Score", width=100, anchor="center")
        self.ml_tree.column("Reasons", width=700, anchor="w")

        scrollbar = ttk.Scrollbar(
            self.ml_tab,
            orient="vertical",
            command=self.ml_tree.yview
        )

        self.ml_tree.configure(yscrollcommand=scrollbar.set)

        # Color code the rows based on ML Risk Level
        self.ml_tree.tag_configure("Very High", background="#FFCDD2")  # Red
        self.ml_tree.tag_configure("High", background="#FFE0B2")  # Orange
        self.ml_tree.tag_configure("Medium", background="#FFF9C4")  # Yellow
        self.ml_tree.tag_configure("Low", background="#E8F5E9")  # Green

        self.ml_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ======================================================
    # SEARCH
    # ======================================================
    def search(self):

        badge_selection = self.badge_var.get().strip()
        badge = None

        if badge_selection != "" and badge_selection != "All":
            try:
                badge = int(badge_selection)
            except ValueError:
                messagebox.showerror("Error", "Badge ID must be an integer.")
                return

        start = self.start_date.get_date()
        end = self.end_date.get_date()

        if start > end:
            messagebox.showerror("Invalid Date Range", "The start date must not be after the end date.")
            return

        self.status.set("Loading attendance records...")

        try:
            records = get_attendance(badge, start, end)
        except Exception as e:
            messagebox.showerror("Database Error", str(e))
            self.status.set("Database Error")
            return

        if not records:
            self.clear_tables()
            messagebox.showinfo("No Records", "No attendance records found.")
            self.status.set("Ready")
            return

        raw_records = records
        cleaned_records = clean_records(raw_records)

        transactions = format_records(raw_records)
        daily = create_daily_summary(cleaned_records)
        overall = create_overall_summary(cleaned_records)
        statistics = employee_statistics(cleaned_records, start, end)
        alerts = detect_missing_pairs(raw_records)

        # ML Function (Top 30 anomalies)
        ml_results = top_anomalies(raw_records, top_n=30)

        self.transactions_data = transactions
        self.daily_data = daily
        self.overall_data = overall
        self.statistics_data = statistics
        self.alerts_data = alerts
        self.ml_data = ml_results

        self.populate_transactions(transactions)
        self.populate_daily(daily)
        self.populate_overall(overall)
        self.populate_statistics(statistics)
        self.populate_alerts(alerts)
        self.populate_ml(ml_results)

        self.summary_vars["Employees"].set(statistics["Employees"])
        self.summary_vars["Working Days"].set(statistics["WorkingDays"])
        self.summary_vars["Total Punches"].set(statistics["TotalPunches"])
        self.summary_vars["Average Arrival"].set(statistics["AverageArrival"])
        self.summary_vars["Average Departure"].set(statistics["AverageDeparture"])
        self.summary_vars["Average Punches/Day"].set(statistics["AveragePunchesPerDay"])

        self.status.set(f"Loaded {len(raw_records)} transactions for {statistics['Employees']} employee(s).")

    # ======================================================
    # EXPORTS
    # ======================================================
    def export_excel_report(self):
        if not hasattr(self, "transactions_data"):
            messagebox.showwarning("Nothing to Export", "Please perform a search first.")
            return
        try:
            filename = export_excel(
                self.transactions_data,
                self.daily_data,
                self.overall_data,
                self.statistics_data,
                self.alerts_data,
                self.ml_data
            )
            messagebox.showinfo("Export Successful", f"Excel report saved successfully.\n\n{filename}")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def export_pdf_report(self):
        if not hasattr(self, "transactions_data"):
            messagebox.showwarning("Nothing to Export", "Please perform a search first.")
            return
        try:
            filename = export_pdf(
                self.transactions_data,
                self.daily_data,
                self.overall_data,
                self.statistics_data,
                self.alerts_data,
                self.ml_data
            )
            messagebox.showinfo("Export Successful", f"PDF report saved successfully.\n\n{filename}")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    # ======================================================
    # POPULATORS
    # ======================================================
    def populate_transactions(self, records):
        self.transactions_tree.delete(*self.transactions_tree.get_children())
        for r in records:
            status = r["Status"].upper()
            self.transactions_tree.insert(
                "", "end",
                values=(r["BadgeID"], r["Datetime"], r["Status"], r["Branch"]),
                tags=(status,)
            )

    def populate_daily(self, daily):
        self.daily_tree.delete(*self.daily_tree.get_children())
        for row in daily:
            self.daily_tree.insert(
                "", "end",
                values=(row["BadgeID"], row["Date"], row["FirstIn"], row["LastOut"], row["Punches"])
            )

    def populate_overall(self, overall):
        self.overall_tree.delete(*self.overall_tree.get_children())
        for row in overall:
            self.overall_tree.insert(
                "", "end",
                values=(row["BadgeID"], row["WorkingDays"], row["TotalPunches"], row["FirstEntry"], row["LastExit"])
            )

    def populate_statistics(self, stats):
        self.statistics_tree.delete(*self.statistics_tree.get_children())
        for key, value in stats.items():
            self.statistics_tree.insert("", "end", values=(key, value))

    def populate_alerts(self, alerts):
        self.alerts_tree.delete(*self.alerts_tree.get_children())
        for row in alerts:
            self.alerts_tree.insert(
                "", "end",
                values=(row["BadgeID"], row["Date"], row["Datetime"], row["Problem"]),
                tags=("warning",)
            )

    def populate_ml(self, anomalies):
        self.ml_tree.delete(*self.ml_tree.get_children())
        for row in anomalies:
            self.ml_tree.insert(
                "", "end",
                values=(row["BadgeID"], row["Prediction"], row["Risk"], row["Score"], row["Reasons"]),
                tags=(row["Risk"],)
            )

    def clear_tables(self):
        for tree in (
                self.transactions_tree,
                self.daily_tree,
                self.overall_tree,
                self.statistics_tree,
                self.alerts_tree,
                self.ml_tree
        ):
            tree.delete(*tree.get_children())

        for var in self.summary_vars.values():
            var.set("-")

        self.badge_dropdown.set("All")
        self.status.set("Ready")

    def run(self):
        self.root.mainloop()
