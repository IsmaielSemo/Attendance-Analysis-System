# pdf_export.py -> Handles the pdf export

import os
from datetime import datetime
from fpdf import FPDF
import matplotlib  # ADDED FOR CHARTS

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


# ==========================================================
# HELPER: SANITIZE TEXT FOR FPDF (Prevents Unicode Crashes)
# ==========================================================
def clean_text(text):
    if text is None:
        return ""
    text = str(text)
    # Replace common mathematical/unicode symbols with ASCII equivalents
    text = text.replace('σ', 'std dev').replace('μ', 'mean').replace('±', '+/-').replace('–', '-')
    # Strip out any remaining characters that Helvetica (latin-1) cannot render
    return text.encode('latin-1', 'ignore').decode('latin-1')


# ==========================================================
# CUSTOM PDF CLASS (Handles Header & Footer automatically)
# ==========================================================
class AttendancePDF(FPDF):
    def __init__(self, stats, alerts_count, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stats = stats
        self.alerts_count = alerts_count

    def header(self):
        title_x_start = 10
        try:
            if os.path.exists("static/logo.png"):
                self.image("static/logo.png", 10, 8, 30)
                title_x_start = 45
        except Exception:
            pass

        self.set_x(title_x_start)
        self.set_font('helvetica', 'B', 18)
        self.set_text_color(31, 78, 120)
        self.cell(135, 8, 'Attendance Analysis System', border=0, align='L')

        self.set_font('helvetica', 'B', 10)
        self.cell(50, 6, 'Employees:', border=0, align='R')
        self.set_font('helvetica', '', 10)
        self.cell(30, 6, clean_text(self.stats.get('Employees', 0)), border=0, align='L', ln=True)

        self.set_x(title_x_start)
        self.set_font('helvetica', 'I', 10)
        self.set_text_color(89, 89, 89)
        date_str = datetime.now().strftime("%d-%m-%Y %H:%M")
        self.cell(135, 6, f'Generated: {date_str}', border=0, align='L')

        self.set_font('helvetica', 'B', 10)
        self.set_text_color(31, 78, 120)
        self.cell(50, 6, 'Total Punches:', border=0, align='R')
        self.set_font('helvetica', '', 10)
        self.cell(30, 6, clean_text(self.stats.get('TotalPunches', 0)), border=0, align='L', ln=True)

        self.set_x(180)
        self.set_font('helvetica', 'B', 10)
        self.set_text_color(31, 78, 120)
        self.cell(50, 6, 'Alerts:', border=0, align='R')
        self.set_font('helvetica', '', 10)
        self.cell(30, 6, clean_text(self.alerts_count), border=0, align='L', ln=True)

        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)

        self.cell(0, 10, 'Attendance Analysis System', align='L')
        self.set_x(10)
        self.cell(0, 10, f'Page {self.page_no()}', align='R')


# ==========================================================
# HELPER: DRAW TABLE
# ==========================================================
def draw_table(pdf, title, headers, data, col_widths, align='C'):
    pdf.add_page()

    pdf.set_font('helvetica', 'B', 14)
    pdf.set_text_color(51, 51, 51)
    pdf.cell(0, 10, clean_text(title), ln=True)
    pdf.ln(2)

    pdf.set_font('helvetica', 'B', 10)
    pdf.set_fill_color(31, 78, 120)
    pdf.set_text_color(255, 255, 255)
    pdf.set_draw_color(217, 217, 217)

    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, clean_text(header), border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font('helvetica', '', 10)
    pdf.set_text_color(0, 0, 0)

    fill = False
    for row in data:
        if pdf.get_y() > 175:
            pdf.add_page()
            pdf.set_font('helvetica', 'B', 10)
            pdf.set_fill_color(31, 78, 120)
            pdf.set_text_color(255, 255, 255)
            for i, header in enumerate(headers):
                pdf.cell(col_widths[i], 10, clean_text(header), border=1, align='C', fill=True)
            pdf.ln()
            pdf.set_font('helvetica', '', 10)
            pdf.set_text_color(0, 0, 0)

        if fill:
            pdf.set_fill_color(242, 246, 251)
        else:
            pdf.set_fill_color(255, 255, 255)

        for i, item in enumerate(row):
            val = clean_text(item)
            cell_align = 'L' if (align == 'MIXED' and i == len(row) - 1) else 'C'
            pdf.cell(col_widths[i], 8, val, border=1, align=cell_align, fill=True)
        pdf.ln()

        fill = not fill


# ==========================================================
# EXPORT FUNCTION
# ==========================================================
def export_pdf(transactions, daily, overall, statistics, alerts, ml_data=[], chart_labels=[], chart_data_in=[],
               chart_data_out=[]):
    pdf = AttendancePDF(stats=statistics, alerts_count=len(alerts), orientation='L', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)

    # 0. ACTIVITY TRENDS CHART (Rendered dynamically via Matplotlib)
    if chart_labels and chart_data_in and chart_data_out:
        plt.figure(figsize=(10, 4.5))
        x = np.arange(len(chart_labels))
        width = 0.35

        plt.bar(x - width / 2, chart_data_in, width, label='Entry (IN)', color='#198754')
        plt.bar(x + width / 2, chart_data_out, width, label='Exit (OUT)', color='#dc3545')

        plt.xticks(x, chart_labels, rotation=45, ha="right")
        plt.title('Peak Entry & Exit Activity', fontsize=14, fontweight='bold')
        plt.xlabel('Hour of Day', fontsize=11)
        plt.ylabel('Total Punches', fontsize=11)
        plt.legend()
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout()

        chart_filename = f"temp_chart_{datetime.now().strftime('%H%M%S')}.png"
        plt.savefig(chart_filename, dpi=200)
        plt.close()

        pdf.add_page()
        pdf.set_font('helvetica', 'B', 14)
        pdf.set_text_color(51, 51, 51)
        pdf.cell(0, 10, "Activity Trends Visualization", ln=True)
        pdf.ln(5)
        pdf.image(chart_filename, x=10, w=275)  # Scaled for landscape orientation

        if os.path.exists(chart_filename):
            os.remove(chart_filename)

    # 1. OVERALL SUMMARY
    overall_data = [
        [r["BadgeID"], r["WorkingDays"], r["TotalPunches"], r["FirstEntry"], r["LastExit"]]
        for r in overall
    ]
    draw_table(
        pdf, "Overall Employee Summary",
        ["Badge ID", "Working Days", "Total Punches", "First Entry", "Last Exit"],
        overall_data, [40, 40, 40, 78, 78]
    )

    # 2. DAILY SUMMARY
    daily_data = [
        [r["BadgeID"], r["Date"], r["FirstIn"], r["LastOut"], r["Punches"]]
        for r in daily
    ]
    draw_table(
        pdf, "Daily Attendance Summary",
        ["Badge ID", "Date", "First IN", "Last OUT", "Punches"],
        daily_data, [40, 55, 65, 65, 51]
    )

    # 3. ALERTS
    alerts_data = [
        [r["BadgeID"], r.get("Date", ""), r["Datetime"], r["Problem"]]
        for r in alerts
    ]
    draw_table(
        pdf, "Attendance Alerts",
        ["Badge ID", "Date", "Date & Time", "Problem"],
        alerts_data, [40, 50, 60, 126], align='MIXED'
    )

    # 4. TRANSACTIONS
    trans_data = [
        [r["BadgeID"], r["Datetime"], r["Status"], r["Branch"]]
        for r in transactions
    ]
    draw_table(
        pdf, "Raw Attendance Transactions",
        ["Badge ID", "Date & Time", "Status", "Branch"],
        trans_data, [40, 76, 50, 110]
    )

    # 5. STATISTICS
    stats_data = [[k, v] for k, v in statistics.items()]
    draw_table(
        pdf, "Attendance Statistics",
        ["Statistic", "Value"],
        stats_data, [138, 138]
    )

    # 6. AI ANOMALIES (Now placed last)
    if ml_data:
        ml_table_data = []
        for r in ml_data:
            reasons = r["Reasons"]
            if len(reasons) > 150:
                reasons = reasons[:82] + "..."
            ml_table_data.append([
                r["BadgeID"], r["Prediction"], r["Risk"], str(r["Score"]), reasons
            ])
        draw_table(
            pdf, "AI Anomaly Detection",
            ["Badge ID", "Prediction", "Risk", "Score", "Reasons (Truncated)"],
            ml_table_data, [25, 30, 25, 25, 171], align='MIXED'
        )

    reports_folder = "reports"
    if not os.path.exists(reports_folder):
        os.makedirs(reports_folder)
    filename = f"Attendance_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = os.path.join(reports_folder, filename)
    pdf.output(filepath)
    return filepath
