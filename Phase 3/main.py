# main.py -> Main file to start running

import os
import re
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_wtf.csrf import CSRFProtect, CSRFError


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


# Graceful handling for expired CSRF tokens (inactivity timeout)
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash("Your session expired due to inactivity. Please log in again.", "warning")
    return redirect(url_for('login'))


# ==========================================================
# AUDIT LOGGING (Database Handler)
# ==========================================================
def log_to_database(username, action_type, details):
    """Securely writes system events to the SQL Server audit_logs table."""
    try:
        conn = db.get_auth_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO audit_logs (username, action_type, details) VALUES (?, ?, ?)",
            (username, action_type, details)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"AUDIT LOG FAILED: {str(e)}")


# ==========================================================
# VALIDATION LOGIC
# ==========================================================
def validate_username(username):
    """Checks the username against strict enterprise security rules."""
    if len(username) < 4:
        return False, "Username must be at least 4 characters long."
    if " " in username:
        return False, "Username cannot contain spaces."
    if not re.match(r"^[A-Za-z]", username):
        return False, "Username must start with a letter (cannot start with a number or symbol)."
    return True, ""


def validate_password(password, username):
    """Checks the password against strict enterprise security rules."""
    if password == username:
        return False, "Password cannot be the same as the username."
    if len(password) < 4:
        return False, "Password must be at least 4 characters long."
    if " " in password:
        return False, "Password cannot contain spaces."
    if not re.match(r"^[A-Za-z]", password):
        return False, "Password must start with a letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least 1 lowercase letter."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least 1 uppercase letter."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least 1 number."

    return True, ""


# ==========================================================
# AUTHENTICATION
# ==========================================================

@app.before_request
def make_session_permanent():
    session.permanent = True


@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password_attempt = request.form['password']

        conn = db.get_auth_connection()
        cursor = conn.cursor()

        # Fetch the exact username back from the database to check capitalization
        cursor.execute("SELECT user_id, username, password_hash, role FROM dbo.users WHERE username = ?", (username,))
        user = cursor.fetchone()

        conn.close()

        # Verify user exists, EXACT capitalization matches, AND password matches
        if user and user[1] == username and user[2] == password_attempt:
            session['user_id'] = user[0]
            session['user'] = user[1]  # Save the exact casing into the session
            session['role'] = str(user[3]).strip()

            log_to_database(username, "LOGIN", "User authenticated via database.")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials.", "danger")
            log_to_database(username, "FAILED_LOGIN", "Invalid password or case-mismatched attempt.")

    return render_template('login.html')


@app.route('/changepassword', methods=['GET', 'POST'])
def changepassword():
    if "user" not in session:
        flash("You must be logged in to change your password.", "warning")
        return redirect(url_for("login"))

    username = session["user"]

    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not new_password or not confirm_password:
            flash("All fields are required.", "danger")
            return redirect(url_for('changepassword'))

        if new_password != confirm_password:
            flash("New passwords do not match.", "danger")
            return redirect(url_for('changepassword'))

        # Check against enterprise password rules
        is_valid, pwd_error_msg = validate_password(new_password, username)
        if not is_valid:
            flash(pwd_error_msg, "danger")
            return redirect(url_for('changepassword'))

        conn = db.get_auth_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT user_id, password_hash FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()

        if not user:
            flash("User not found.", "danger")
            conn.close()
            return redirect(url_for('changepassword'))

        if user[1] == new_password:
            flash("New password cannot be the same as the old password.", "danger")
            conn.close()
            return redirect(url_for('changepassword'))


        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (new_password, username)
        )
        conn.commit()
        conn.close()

        log_to_database(username, "CHANGE_PASSWORD", "User securely updated their password.")

        # 1. Clear the session FIRST so we don't accidentally erase the message
        session.clear()

        # 2. THEN create the flash message so it survives the redirect
        flash("PASSWORD UPDATED: Your password has been successfully changed. Please log in.", "success")

        # 3. Send them to the login screen
        return redirect(url_for('login'))
        return redirect(url_for('login'))

    return render_template('changepassword.html')


@app.route("/logout")
def logout():
    if "user" in session:
        log_to_database(session["user"], "LOGOUT", "User safely terminated session.")
    session.pop("user", None)
    session.pop("role", None)
    session.pop("user_id", None)
    return redirect(url_for("login"))


# ==========================================================
# ADMIN DASHBOARD
# ==========================================================

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    current_user_role = str(session.get("role")).strip()

    # 1. Access Check: Must be Admin or SuperAdmin
    if "user" not in session or current_user_role not in ["Admin", "SuperAdmin"]:
        flash("Access Denied. You do not have administrator privileges.", "danger")
        return redirect(url_for("dashboard"))

    conn = db.get_auth_connection()
    cursor = conn.cursor()

    current_sort = request.args.get('sort', 'id_asc')

    if request.method == 'POST':
        action = request.form.get("action")

        # --- CREATE USER ---
        if action == "create_user":
            new_username = request.form.get('new_username', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            new_role = request.form.get('new_role', '').strip()

            if not new_username or not new_password or not confirm_password or not new_role:
                flash("All fields are required to create a user.", "danger")
            elif new_password != confirm_password:
                flash("The passwords do not match. Please try again.", "danger")
            elif new_role in ["SuperAdmin"] and current_user_role != "SuperAdmin":
                flash("Security Alert: Only SuperAdmins can create other SuperAdmin accounts.", "danger")
            else:
                # ENFORCE VALIDATION RULES
                is_valid_user, user_error_msg = validate_username(new_username)
                is_valid_pwd, pwd_error_msg = validate_password(new_password, new_username)

                if not is_valid_user:
                    flash(user_error_msg, "danger")
                elif not is_valid_pwd:
                    flash(pwd_error_msg, "danger")
                else:
                    # ENFORCE SINGLE SUPERADMIN POLICY
                    can_create_user = True
                    if new_role == "SuperAdmin":
                        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'SuperAdmin'")
                        if cursor.fetchone()[0] >= 1:
                            flash("System Policy: Only one SuperAdmin account can exist in the database.", "danger")
                            can_create_user = False

                    if can_create_user:
                        cursor.execute(
                            "SELECT user_id FROM users WHERE username COLLATE SQL_Latin1_General_CP1_CS_AS = ?",
                            (new_username,))
                        if cursor.fetchone():
                            flash("That username already exists. Choose another.", "warning")
                        else:
                            cursor.execute(
                                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                                (new_username, new_password, new_role)
                            )
                            conn.commit()
                            log_to_database(session["user"], "ADMIN_CREATE_USER",
                                            f"{current_user_role} created new {new_role}: {new_username}")
                            flash(f"User '{new_username}' successfully created!", "success")

        # --- CHANGE USERNAME ---
        elif action == "change_username":
            old_username = request.form.get('old_username', '').strip()
            new_username = request.form.get('new_username', '').strip()

            if not old_username or not new_username:
                flash("Both current and new usernames are required.", "danger")
            elif old_username == new_username:
                flash("New username must be different from the old one.", "warning")
            else:
                # Verify standard Admins aren't trying to rename SuperAdmins/Admins
                cursor.execute("SELECT role FROM users WHERE username = ?", (old_username,))
                target = cursor.fetchone()

                if target and target[0] in ["Admin", "SuperAdmin"] and current_user_role != "SuperAdmin":
                    flash("Security Alert: You do not have permission to rename Administrative accounts.", "danger")
                else:
                    is_valid_user, user_error_msg = validate_username(new_username)
                    if not is_valid_user:
                        flash(user_error_msg, "danger")
                    else:
                        cursor.execute("SELECT user_id FROM users WHERE username = ? AND username != ?",
                                       (new_username, old_username))
                        if cursor.fetchone():
                            flash(f"The username '{new_username}' is already taken.", "warning")
                        else:
                            cursor.execute("UPDATE users SET username = ? WHERE username = ?",
                                           (new_username, old_username))
                            conn.commit()
                            log_to_database(session["user"], "ADMIN_CHANGE_USERNAME",
                                            f"{current_user_role} renamed '{old_username}' to '{new_username}'")
                            flash(f"Successfully changed username from '{old_username}' to '{new_username}'.",
                                  "success")

        # --- DELETE USER ---
        elif action == "delete_user":
            target_user_id = request.form.get('target_user_id', '').strip()

            if str(target_user_id) == str(session.get("user_id")):
                flash("CRITICAL: You cannot delete your own account!", "danger")
            else:
                cursor.execute("SELECT username, role FROM users WHERE user_id = ?", (target_user_id,))
                user_to_delete = cursor.fetchone()

                if user_to_delete:
                    deleted_username = user_to_delete[0]
                    target_role = user_to_delete[1]

                    # Prevent standard Admins from deleting higher roles
                    if target_role in ["SuperAdmin"] and current_user_role != "SuperAdmin":
                        flash("Security Alert: You do not have permission to delete SuperAdmin accounts.", "danger")
                        log_to_database(session["user"], "FAILED_DELETE_ATTEMPT",
                                        f"Standard Admin tried to delete higher role: {deleted_username}")
                    else:
                        cursor.execute("DELETE FROM users WHERE user_id = ?", (target_user_id,))
                        conn.commit()
                        log_to_database(session["user"], "ADMIN_DELETE_USER",
                                        f"{current_user_role} deleted {target_role}: {deleted_username} (ID: {target_user_id})")
                        flash(f"{target_role} '{deleted_username}' has been permanently deleted.", "success")
                else:
                    flash("Error: User could not be found.", "danger")

        return redirect(url_for('admin_dashboard', sort=current_sort))

    if current_sort == 'id_desc':
        order_query = "ORDER BY user_id DESC"
    elif current_sort == 'role_admin':
        # SuperAdmin first, then Admin, then User
        order_query = """
                ORDER BY 
                CASE role 
                    WHEN 'SuperAdmin' THEN 1 
                    WHEN 'Admin' THEN 2 
                    ELSE 3 
                END ASC, user_id ASC
            """
    elif current_sort == 'role_user':
        # Regular Users first (1), Admin second (2), SuperAdmin at the very end (3)
        order_query = """
                ORDER BY 
                CASE role 
                    WHEN 'User' THEN 1 
                    WHEN 'Admin' THEN 2 
                    ELSE 3 
                END ASC, user_id ASC
            """
    else:
        order_query = "ORDER BY user_id ASC"

    cursor.execute(f"SELECT user_id, username, role FROM dbo.users {order_query}")
    all_users = cursor.fetchall()
    conn.close()

    return render_template('admin_dashboard.html', users=all_users, current_sort=current_sort)


# ==========================================================
# MAIN DASHBOARD ROUTE
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
            log_to_database(session["user"], "CLEAR_FILTERS", "Reset search dashboard parameters.")
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
            flash("The end date must be after the start date.")
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
                    log_to_database(session["user"], "SEARCH",
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
                    log_to_database(session["user"], "EXPORT_EXCEL", f"Exported dataset to Excel: {filename}")
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
                    log_to_database(session["user"], "EXPORT_PDF", f"Exported dataset to PDF: {filename}")
                    return send_file(filename, as_attachment=True)
                except Exception as e:
                    flash(f"PDF Export Failed: {str(e)}")

    return render_template(
        "dashboard.html",
        username=session["user"],
        user_role=session.get("role", "User"),  # Passed to HTML so you can conditionally show an "Admin Panel" button
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
    # host='0.0.0.0' exposes the app to your local network
    app.run(host='0.0.0.0', port=5000, debug=False)
