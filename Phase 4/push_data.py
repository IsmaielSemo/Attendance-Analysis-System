# push_data.py -> Handles pushing the manual_entry data to the transaction_log table

import database as db
from collections import defaultdict


def write_to_transaction():
    # 1. Establish database connection
    conn = db.get_connection()
    cursor = conn.cursor()

    # 2. Fetch ALL Manual Entries
    manual_query = """
        SELECT code, Datetime, Ip
        FROM dbo.ManualEntry
    """
    try:
        cursor.execute(manual_query)
        manual_entries = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching manual entries: {e}")
        conn.close()
        return 0

    if not manual_entries:
        print("No manual entries found in the database.")
        conn.close()
        return 0

    # 3. Group and Filter for strictly First IN and Last OUT per day
    grouped_records = defaultdict(lambda: defaultdict(list))

    for row in manual_entries:
        badge_id = str(row[0]).strip() if row[0] is not None else ''
        dt_val = row[1]
        ip_val = str(row[2]).strip() if row[2] is not None else ''

        if not badge_id or not dt_val:
            continue

        day_key = dt_val.date() if hasattr(dt_val, 'date') else str(dt_val).split(' ')[0]
        in_out, branch = db.IP_MAPPING.get(ip_val, ('UNKNOWN', 'UNKNOWN'))

        grouped_records[badge_id][day_key].append({
            'badge_id': badge_id,
            'dt_val': dt_val,
            'day_key': str(day_key),
            'ip_val': ip_val,
            'in_out': in_out,
            'branch': branch
        })

    records_to_push = []

    for badge, days in grouped_records.items():
        for day, records in days.items():
            records.sort(key=lambda x: x['dt_val'])

            in_records = [r for r in records if r['in_out'] == 'IN']
            out_records = [r for r in records if r['in_out'] == 'OUT']

            if in_records:
                records_to_push.append(in_records[0])  # First IN of the day
            if out_records:
                records_to_push.append(out_records[-1])  # Last OUT of the day

    # 4. UPDATED INSERT QUERY: Prevents multiple INs or OUTs on the SAME CALENDAR DAY
    # CAST(Datetime AS DATE) ensures we check by day, ignoring hour/minute/second differences.
    insert_query = """
        INSERT INTO dbo.transaction_log 
        (BadgeID, Datetime, InOut, AXFlage, EntryDate, Branch, IP, Location)
        SELECT ?, ?, ?, 0, GETDATE(), ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM dbo.transaction_log 
            WHERE BadgeID = ? 
              AND InOut = ? 
              AND CAST(Datetime AS DATE) = ?
        )
    """

    records_added = 0

    # 5. Process the filtered records and push safely with row-by-row commits
    for record in records_to_push:
        badge_id = record['badge_id']
        dt_val = record['dt_val']
        day_str = record['day_key']
        in_out = record['in_out']
        branch = record['branch']
        ip_val = record['ip_val']

        location = branch.split('-')[0].strip() if '-' in branch else branch

        # Parameters mapped to both INSERT and the DATE-LEVEL NOT EXISTS check
        params = (
            badge_id, dt_val, in_out, branch, ip_val, location,  # Values to INSERT
            badge_id, in_out, day_str  # Values to check for NOT EXISTS by Date & Status
        )

        try:
            cursor.execute(insert_query, params)

            if cursor.rowcount > 0:
                records_added += 1

            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"Concurrency warning or error on Badge {badge_id} for date {day_str}: {str(e)}")

    conn.close()

    print(f"Push complete. {records_added} unique entries were added to transaction_log.")
    return records_added


if __name__ == "__main__":
    write_to_transaction()