
# main.py -> Main file to start running

import os
import hashlib
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_wtf.csrf import CSRFProtect

# --- YOUR BUSINESS & DATABASE LOGIC ---
from attendance import (
    clean_records,
    format_records,
    create_daily_summary,
    create_overall_summary,
    employee_statistics,
    detect_missing_pairs
)
from ml import top_anomalies
from excel_export import export_excel
from pdf_export import export_pdf
import database as db

app = Flask(__name__)

# Security Hardening: Fetch secret key from environment, fallback to dev key
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super_secret_enterprise_development_key")

# CSRF Protection
csrf = CSRFProtect(app)

# Session Security Configuration
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=15)

# ==========================================================
# AUDIT LOGGING (Rotating File Handler)
# ==========================================================
# Caps the log file at 5MB and keeps up to 3 backups.
audit_logger = logging.getLogger("audit_logger")
audit_logger.setLevel(logging.INFO)

log_handler = RotatingFileHandler("audit_trail.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
log_formatter = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
log_handler.setFormatter(log_formatter)
audit_logger.addHandler(log_handler)


def log_to_file(username, action, details=""):
    """Records audit events securely using the rotating logger."""
    audit_logger.info(f"USER: {username} | ACTION: {action} | DETAILS: {details}")


# ==========================================================
# AUTHENTICATION
# ==========================================================
def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


# Secure pre-hashed mock users dictionary
DUMMY_USERS = {
    "admin": hash_password("password123"),
    "supervisor": hash_password("boss123"),
    "ismaiel": hash_password("test")
}


@app.before_request
def make_session_permanent():
    session.permanent = True


@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        hashed_input_password = hash_password(password)

        if username in DUMMY_USERS and DUMMY_USERS[username] == hashed_input_password:
            session["user"] = username
            log_to_file(username, "LOGIN", "User successfully authenticated.")
            return redirect(url_for("dashboard"))
        else:
            log_to_file(username if username else "Unknown", "FAILED_LOGIN", "Invalid credentials provided.")
            flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    if "user" in session:
        log_to_file(session["user"], "LOGOUT", "User safely terminated session.")
    session.pop("user", None)
    return redirect(url_for("login"))


# ==========================================================
# DASHBOARD ROUTE
# ==========================================================
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    stats = None
    transactions = []
    daily_summary = []
    summary = []
    statistics_data = {}
    warnings = []
    anomalies = []
    chart_labels = []
    chart_data_in = []
    chart_data_out = []

    today = datetime.now()
    yesterday = today - timedelta(days=1)

    start_date_val = yesterday.strftime("%m/%d/%Y")
    end_date_val = today.strftime("%m/%d/%Y")
    selected_badge = "All"

    try:
        badge_list = db.get_unique_badges()
    except Exception:
        badge_list = []

    if request.method == "POST":
        action = request.form.get("action")

        if action == "clear":
            log_to_file(session["user"], "CLEAR_FILTERS", "Reset search dashboard parameters.")
            return redirect(url_for("dashboard"))

        selected_badge = request.form.get("badge_id")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")

        start_date_val = start_date_str if start_date_str else start_date_val
        end_date_val = end_date_str if end_date_str else end_date_val

        if not start_date_str or not end_date_str:
            flash("Please select both a Start Date and an End Date.")
            return redirect(url_for("dashboard"))

        badge_id = None if selected_badge == "All" or selected_badge == "" else int(selected_badge)

        try:
            start_date = datetime.strptime(start_date_str, "%m/%d/%Y").date()
            end_date = datetime.strptime(end_date_str, "%m/%d/%Y").date()
        except ValueError:
            flash("Invalid date format.")
            return redirect(url_for("dashboard"))

        if start_date > end_date:
            flash("The start date must not be after the end date.")
            return redirect(url_for("dashboard"))

        try:
            raw_records = db.get_attendance(badge_id, start_date, end_date)

            if raw_records:
                cleaned_records = clean_records(raw_records)
                transactions = format_records(raw_records)
                daily_summary = create_daily_summary(cleaned_records)
                summary = create_overall_summary(cleaned_records)
                statistics_data = employee_statistics(cleaned_records)
                warnings = detect_missing_pairs(raw_records)
                anomalies = top_anomalies(raw_records, top_n=30)
                stats = statistics_data

                # --- Dynamic Chart Data Preparation (Entry vs Exit: 6 AM to 12 AM) ---
                chart_hours = [str(i).zfill(2) + ":00" for i in range(6, 24)] + ["00:00"]

                hour_counts_in = {h: 0 for h in chart_hours}
                hour_counts_out = {h: 0 for h in chart_hours}

                for r in raw_records:
                    dt = r.Datetime if hasattr(r, 'Datetime') else r[1]
                    status = r.InOut.upper().strip() if hasattr(r, 'InOut') else r[2].upper().strip()

                    if isinstance(dt, str):
                        try:
                            dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            continue

                    if isinstance(dt, datetime):
                        hr_str = dt.strftime("%H:00")
                        if hr_str in hour_counts_in:
                            if status == 'IN':
                                hour_counts_in[hr_str] += 1
                            elif status == 'OUT':
                                hour_counts_out[hr_str] += 1

                chart_labels = list(hour_counts_in.keys())
                chart_data_in = list(hour_counts_in.values())
                chart_data_out = list(hour_counts_out.values())
                # ---------------------------------------------------

                if action == "search":
                    log_to_file(session["user"], "SEARCH",
                                f"Queried attendance for Badge: {selected_badge} between {start_date_str} and {end_date_str}")
            else:
                flash("No attendance records found for the selected criteria.")
        except Exception as e:
            flash(f"Data fetch error: {str(e)}")

        if action == "export_excel":
            if not transactions:
                flash("Please perform a search first before exporting.")
            else:
                try:
                    filename = export_excel(transactions, daily_summary, summary, statistics_data, warnings, anomalies,
                                            chart_labels, chart_data_in, chart_data_out)
                    log_to_file(session["user"], "EXPORT_EXCEL", f"Exported dataset to Excel: {filename}")
                    return send_file(filename, as_attachment=True)
                except Exception as e:
                    flash(f"Excel Export Failed: {str(e)}")

        elif action == "export_pdf":
            if not transactions:
                flash("Please perform a search first before exporting.")
            else:
                try:
                    filename = export_pdf(transactions, daily_summary, summary, statistics_data, warnings, anomalies,
                                          chart_labels, chart_data_in, chart_data_out)
                    log_to_file(session["user"], "EXPORT_PDF", f"Exported dataset to PDF: {filename}")
                    return send_file(filename, as_attachment=True)
                except Exception as e:
                    flash(f"PDF Export Failed: {str(e)}")

    return render_template(
        "dashboard.html",
        username=session["user"],
        badges=badge_list,
        stats=stats,
        transactions=transactions,
        daily_summary=daily_summary,
        summary=summary,
        statistics_data=statistics_data,
        warnings=warnings,
        anomalies=anomalies,
        start_date=start_date_val,
        end_date=end_date_val,
        selected_badge=selected_badge,
        chart_labels=chart_labels,
        chart_data_in=chart_data_in,
        chart_data_out=chart_data_out
    )


if __name__ == "__main__":
    # Local development server
    app.run(debug=False)