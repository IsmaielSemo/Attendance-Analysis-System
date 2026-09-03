#main.py -> Main file to start running
from gui import AttendanceGUI

AttendanceGUI().run()

#
# from datetime import date, timedelta
#
# from database import get_attendance
# from ml import detect_anomalies
#
#
# def main():
#
#     start = date.today() - timedelta(days=90)
#     end = date.today()
#
#     print("Loading attendance data...")
#
#     records = get_attendance(
#         None,
#         start,
#         end
#     )
#
#     print(f"Loaded {len(records)} records.")
#
#     print("\nRunning Machine Learning...\n")
#
#     results = detect_anomalies(records)
#
#     print("=" * 90)
#
#     for employee in results:
#
#         print(
#             f"BadgeID: {employee['BadgeID']}"
#         )
#
#         print(
#             f"Prediction : {employee['Prediction']}"
#         )
#
#         print(
#             f"Risk       : {employee['Risk']}"
#         )
#
#         print(
#             f"Score      : {employee['Score']}"
#         )
#
#         print(
#             f"Reasons    : {employee['Reasons']}"
#         )
#
#         print("-" * 90)
#
#
# if __name__ == "__main__":
#     main()
