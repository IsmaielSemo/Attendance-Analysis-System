# database.py -> connects and retrieves information from SQL Server

import pyodbc
from config import ATTENDANCE_CONNECTION_STRING, AUTH_CONNECTION_STRING

def get_connection():
    """Creates and returns connection to the Live Attendance SQL Server database."""
    return pyodbc.connect(ATTENDANCE_CONNECTION_STRING)

def get_auth_connection():
    """Creates and returns connection to the Authentication SQL Server database."""
    conn = pyodbc.connect(AUTH_CONNECTION_STRING)
    # Let's ask SQL Server what database it is actually connected to right now!
    cursor = conn.cursor()
    cursor.execute("SELECT DB_NAME()")
    print("-> PYTHON IS CURRENTLY CONNECTED TO DATABASE:", cursor.fetchone()[0])
    return conn

def get_attendance(badge_id, start_date, end_date):
    with get_connection() as conn:
        cursor = conn.cursor()

        query = """
                SELECT BadgeID,
                       Datetime,
                       InOut,
                       Branch
                FROM Transaction_Log
                WHERE Datetime >= ?
                  AND Datetime < DATEADD(day,1, ?)
                """

        params = [start_date, end_date]

        if badge_id is not None:
            query += " AND BadgeID = ?"
            params.append(badge_id)

        query += """
        ORDER BY BadgeID, Datetime
        """

        cursor.execute(query, params)
        return cursor.fetchall()

def get_unique_badges():
    with get_connection() as conn:
        cursor = conn.cursor()

        query = """
                SELECT DISTINCT BadgeID
                FROM Transaction_Log
                ORDER BY BadgeID
                """

        cursor.execute(query)
        rows = cursor.fetchall()

        return [str(row[0]) for row in rows]
