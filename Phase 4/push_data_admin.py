# push_data_admin.py -> Pushes all data to the transaction_log table

import database as db
from collections import defaultdict


def write_to_transactionZK():
    conn = db.get_connection()
    cursor = conn.cursor()

    zk_query = """
        SELECT code, Datetime, Ip
        FROM dbo.ZK_log
    """

    try:
        cursor.execute(zk_query)
        zk_entries = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching ZK entries: {e}")
        conn.close()
        return 0

    if not zk_entries:
        print("No ZK entries found in the database.")
        conn.close()
        return 0

    grouped_records = defaultdict(lambda: defaultdict(list))

    for row in zk_entries:
        badge_id = str(row[0]).strip() if row[0] is not None else ''
        dt_val   = row[1]
        ip_val   = str(row[2]).strip() if row[2] is not None else ''

        if not badge_id or not dt_val:
            continue

        if ip_val not in db.IP_MAPPING:
            continue

        day_key        = dt_val.date() if hasattr(dt_val, 'date') else str(dt_val).split(' ')[0]
        in_out, branch = db.IP_MAPPING.get(ip_val, ('UNKNOWN', 'UNKNOWN'))

        if in_out == 'UNKNOWN':
            continue

        grouped_records[badge_id][day_key].append({
            'badge_id': badge_id,
            'dt_val'  : dt_val,
            'day_key' : str(day_key),
            'ip_val'  : ip_val,
            'in_out'  : in_out,
            'branch'  : branch
        })

    records_to_push = []

    for badge, days in grouped_records.items():
        for day, records in days.items():
            records.sort(key=lambda x: x['dt_val'])
            in_records  = [r for r in records if r['in_out'] == 'IN']
            out_records = [r for r in records if r['in_out'] == 'OUT']
            if in_records:
                records_to_push.append(in_records[0])
            if out_records:
                records_to_push.append(out_records[-1])

    records_inserted = 0
    records_updated = 0

    for record in records_to_push:
        badge_id = record['badge_id']
        dt_val   = record['dt_val']
        day_str  = record['day_key']
        in_out   = record['in_out']
        branch   = record['branch']
        ip_val   = record['ip_val']
        location = branch.split('-')[0].strip() if '-' in branch else branch

        try:
            check_query = """
                SELECT Datetime FROM dbo.transaction_log 
                WHERE BadgeID = ? AND InOut = ? AND CAST(Datetime AS DATE) = ?
            """
            cursor.execute(check_query, (badge_id, in_out, day_str))
            existing_record = cursor.fetchone()

            if existing_record:
                existing_dt = existing_record[0]

                if in_out == 'OUT' and dt_val > existing_dt:
                    update_query = """
                        UPDATE dbo.transaction_log
                        SET Datetime = ?, Branch = ?, IP = ?, Location = ?, EntryDate = GETDATE()
                        WHERE BadgeID = ? AND InOut = 'OUT' AND CAST(Datetime AS DATE) = ?
                    """
                    cursor.execute(update_query, (dt_val, branch, ip_val, location, badge_id, day_str))
                    if cursor.rowcount > 0:
                        records_updated += 1

                elif in_out == 'IN' and dt_val < existing_dt:
                    update_query = """
                        UPDATE dbo.transaction_log
                        SET Datetime = ?, Branch = ?, IP = ?, Location = ?, EntryDate = GETDATE()
                        WHERE BadgeID = ? AND InOut = 'IN' AND CAST(Datetime AS DATE) = ?
                    """
                    cursor.execute(update_query, (dt_val, branch, ip_val, location, badge_id, day_str))
                    if cursor.rowcount > 0:
                        records_updated += 1
            else:
                insert_query = """
                    INSERT INTO dbo.transaction_log 
                    (BadgeID, Datetime, InOut, AXFlage, EntryDate, Branch, IP, Location)
                    VALUES (?, ?, ?, 0, GETDATE(), ?, ?, ?)
                """
                cursor.execute(insert_query, (badge_id, dt_val, in_out, branch, ip_val, location))
                if cursor.rowcount > 0:
                    records_inserted += 1

            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"Concurrency warning or error on Badge {badge_id} for date {day_str}: {str(e)}")

    conn.close()
    total_affected = records_inserted + records_updated
    print(f"ZK Push complete. {records_inserted} inserted, {records_updated} updated.")
    return total_affected


def write_to_transactionHIK():
    conn = db.get_connection()
    cursor = conn.cursor()

    hik_query = """
        SELECT UserID, EventTime, DeviceIP
        FROM dbo.HikAccessLog
    """
    try:
        cursor.execute(hik_query)
        hik_entries = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching HIK entries: {e}")
        conn.close()
        return 0

    if not hik_entries:
        print("No HIK entries found in the database.")
        conn.close()
        return 0

    grouped_records = defaultdict(lambda: defaultdict(list))

    for row in hik_entries:
        badge_id = str(row[0]).strip() if row[0] is not None else ''
        dt_val = row[1]
        ip_val = str(row[2]).strip() if row[2] is not None else ''

        if not badge_id or not dt_val:
            continue

        day_key = dt_val.date() if hasattr(dt_val, 'date') else str(dt_val).split(' ')[0]
        in_out, branch = db.IP_MAPPING.get(ip_val, ('UNKNOWN', 'UNKNOWN'))

        if in_out == 'UNKNOWN':
            continue

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
                records_to_push.append(in_records[0])
            if out_records:
                records_to_push.append(out_records[-1])

    records_inserted = 0
    records_updated = 0

    for record in records_to_push:
        badge_id = record['badge_id']
        dt_val = record['dt_val']
        day_str = record['day_key']
        in_out = record['in_out']
        branch = record['branch']
        ip_val = record['ip_val']
        location = branch.split('-')[0].strip() if '-' in branch else branch

        try:
            check_query = """
                SELECT Datetime FROM dbo.transaction_log 
                WHERE BadgeID = ? AND InOut = ? AND CAST(Datetime AS DATE) = ?
            """
            cursor.execute(check_query, (badge_id, in_out, day_str))
            existing_record = cursor.fetchone()

            if existing_record:
                existing_dt = existing_record[0]

                if in_out == 'OUT' and dt_val > existing_dt:
                    update_query = """
                        UPDATE dbo.transaction_log
                        SET Datetime = ?, Branch = ?, IP = ?, Location = ?, EntryDate = GETDATE()
                        WHERE BadgeID = ? AND InOut = 'OUT' AND CAST(Datetime AS DATE) = ?
                    """
                    cursor.execute(update_query, (dt_val, branch, ip_val, location, badge_id, day_str))
                    if cursor.rowcount > 0:
                        records_updated += 1

                elif in_out == 'IN' and dt_val < existing_dt:
                    update_query = """
                        UPDATE dbo.transaction_log
                        SET Datetime = ?, Branch = ?, IP = ?, Location = ?, EntryDate = GETDATE()
                        WHERE BadgeID = ? AND InOut = 'IN' AND CAST(Datetime AS DATE) = ?
                    """
                    cursor.execute(update_query, (dt_val, branch, ip_val, location, badge_id, day_str))
                    if cursor.rowcount > 0:
                        records_updated += 1
            else:
                insert_query = """
                    INSERT INTO dbo.transaction_log 
                    (BadgeID, Datetime, InOut, AXFlage, EntryDate, Branch, IP, Location)
                    VALUES (?, ?, ?, 0, GETDATE(), ?, ?, ?)
                """
                cursor.execute(insert_query, (badge_id, dt_val, in_out, branch, ip_val, location))
                if cursor.rowcount > 0:
                    records_inserted += 1

            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"Concurrency warning or error on Badge {badge_id} for date {day_str}: {str(e)}")

    conn.close()
    total_affected = records_inserted + records_updated
    print(f"HIK Push complete. {records_inserted} inserted, {records_updated} updated.")
    return total_affected


def write_to_transactionManual():
    conn = db.get_connection()
    cursor = conn.cursor()

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

    grouped_records = defaultdict(lambda: defaultdict(list))

    for row in manual_entries:
        badge_id = str(row[0]).strip() if row[0] is not None else ''
        dt_val = row[1]
        ip_val = str(row[2]).strip() if row[2] is not None else ''

        if not badge_id or not dt_val:
            continue

        day_key = dt_val.date() if hasattr(dt_val, 'date') else str(dt_val).split(' ')[0]
        in_out, branch = db.IP_MAPPING.get(ip_val, ('UNKNOWN', 'UNKNOWN'))

        if in_out == 'UNKNOWN':
            continue

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
                records_to_push.append(in_records[0])
            if out_records:
                records_to_push.append(out_records[-1])

    records_inserted = 0
    records_updated = 0

    for record in records_to_push:
        badge_id = record['badge_id']
        dt_val = record['dt_val']
        day_str = record['day_key']
        in_out = record['in_out']
        branch = record['branch']
        ip_val = record['ip_val']
        location = branch.split('-')[0].strip() if '-' in branch else branch

        try:
            check_query = """
                SELECT Datetime FROM dbo.transaction_log 
                WHERE BadgeID = ? AND InOut = ? AND CAST(Datetime AS DATE) = ?
            """
            cursor.execute(check_query, (badge_id, in_out, day_str))
            existing_record = cursor.fetchone()

            if existing_record:
                existing_dt = existing_record[0]

                if in_out == 'OUT' and dt_val > existing_dt:
                    update_query = """
                        UPDATE dbo.transaction_log
                        SET Datetime = ?, Branch = ?, IP = ?, Location = ?, EntryDate = GETDATE()
                        WHERE BadgeID = ? AND InOut = 'OUT' AND CAST(Datetime AS DATE) = ?
                    """
                    cursor.execute(update_query, (dt_val, branch, ip_val, location, badge_id, day_str))
                    if cursor.rowcount > 0:
                        records_updated += 1

                elif in_out == 'IN' and dt_val < existing_dt:
                    update_query = """
                        UPDATE dbo.transaction_log
                        SET Datetime = ?, Branch = ?, IP = ?, Location = ?, EntryDate = GETDATE()
                        WHERE BadgeID = ? AND InOut = 'IN' AND CAST(Datetime AS DATE) = ?
                    """
                    cursor.execute(update_query, (dt_val, branch, ip_val, location, badge_id, day_str))
                    if cursor.rowcount > 0:
                        records_updated += 1
            else:
                insert_query = """
                    INSERT INTO dbo.transaction_log 
                    (BadgeID, Datetime, InOut, AXFlage, EntryDate, Branch, IP, Location)
                    VALUES (?, ?, ?, 0, GETDATE(), ?, ?, ?)
                """
                cursor.execute(insert_query, (badge_id, dt_val, in_out, branch, ip_val, location))
                if cursor.rowcount > 0:
                    records_inserted += 1

            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"Concurrency warning or error on Badge {badge_id} for date {day_str}: {str(e)}")

    conn.close()
    total_affected = records_inserted + records_updated
    print(f"Manual Push complete. {records_inserted} inserted, {records_updated} updated.")
    return total_affected


def write_to_transaction():
    """Wrapper function to execute both ZK and HIK data pushes and return the total rows added."""
    zk_added = write_to_transactionZK()
    hik_added = write_to_transactionHIK()
    manual_added = write_to_transactionManual()
    return zk_added + hik_added + manual_added


if __name__ == "__main__":
    write_to_transaction()