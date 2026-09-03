# database.py -> connects and retrieves information from SQL Server

import pyodbc
from config import CONNECTION_STRING


def get_connection():  # Creates and returns connection to SQL Server
    return pyodbc.connect(CONNECTION_STRING)


def get_attendance(badge_id, start_date, end_date):
    conn = get_connection()
    cursor = conn.cursor()

    query = """
            SELECT BadgeID,
                   Datetime,
                   InOut,
                   Branch
            FROM Transaction_Log
            WHERE Datetime >= ?
              AND Datetime < DATEADD(day,1, ?) \
            """

    params = [start_date, end_date]

    if badge_id is not None:
        query += " AND BadgeID = ?"
        params.append(badge_id)

    query += """
    ORDER BY BadgeID, Datetime
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return rows


# ==========================================================
# GET BADGE IDS FOR DROPDOWN
# ==========================================================
def get_unique_badges():
    """
    Retrieves a list of all unique Badge IDs from the database
    to populate the dropdown menu in the GUI.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Query all distinct Badge IDs and order them numerically
    query = """
            SELECT DISTINCT BadgeID
            FROM Transaction_Log
            ORDER BY BadgeID \
            """

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    # Convert the results into a simple list of strings
    badge_list = [str(row[0]) for row in rows]

    return badge_list



