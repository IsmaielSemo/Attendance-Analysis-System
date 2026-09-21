# push_data.py -> Handles pushing the manual_entry data to the transaction_log table

import database as db


def write_to_transaction():
    # 1. Establish database connection
    conn = db.get_connection()
    cursor = conn.cursor()

    # 2. Fetch ALL Manual Entries (Removed the 3-day filter so it catches older data)
    manual_query = """
        SELECT code, Datetime, Ip
        FROM dbo.ManualEntry
    """
    cursor.execute(manual_query)
    manual_entries = cursor.fetchall()

    if not manual_entries:
        print("No manual entries found in the database.")
        conn.close()
        return 0

    # 3. Prepare the INSERT query with DUPLICATE PREVENTION
    # This SQL query attempts to insert, but strictly skips if the BadgeID and Datetime already exist.
    insert_query = """
        INSERT INTO dbo.transaction_log
        (BadgeID, Datetime, InOut, AXFlage, EntryDate, Branch, IP, Location)
        SELECT ?, ?, ?, 0, GETDATE(), ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM dbo.transaction_log
            WHERE BadgeID = ? AND Datetime = ?
        )
    """

    records_added = 0

    # 4. Process each manual entry and push it safely
    for row in manual_entries:
        badge_id = str(row[0]).strip() if row[0] is not None else ''
        dt_val = row[1]
        ip_val = str(row[2]).strip() if row[2] is not None else ''

        # Skip broken rows
        if not badge_id or not dt_val:
            continue

        # Use IP_MAPPING from database.py to determine InOut and Branch
        in_out, branch = db.IP_MAPPING.get(ip_val, ('UNKNOWN', 'UNKNOWN'))

        # For Location, grab the first part of the Branch name (e.g., "Plaza" from "Plaza - Gate1-IN")
        location = branch.split('-')[0].strip() if '-' in branch else branch

        # Set up the parameters for the SQL query
        params = (
            badge_id, dt_val, in_out, branch, ip_val, location,  # Values to INSERT
            badge_id, dt_val  # Values to check for NOT EXISTS
        )

        # Execute the safe insert
        cursor.execute(insert_query, params)

        # cursor.rowcount will be 1 if a new row was added, and 0 if it was skipped as a duplicate
        if cursor.rowcount > 0:
            records_added += 1

    # 5. Commit the changes and close the connection
    conn.commit()
    conn.close()

    print(f"Push complete. {records_added} new entries were added to transaction_log.")
    return records_added


if __name__ == "__main__":
    write_to_transaction()

