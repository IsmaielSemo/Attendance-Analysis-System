# ml.py -> Handles the ML of the project
#
# Pipeline:
# 1. Build features utilizing native calculate_time_inside data
# 2. Normalize with StandardScaler
# 3. KMeans clustering -> discover natural peer/shift groups
# 4. One-Class SVM per cluster -> detect unusual patterns against similar employees
# 5. Relative anomaly score -> 10-100 review-priority scale using Robust Percentiles
# 6. Z-score classification -> Categorizes alerts into Workload, Attendance, or Data Quality

import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.svm import OneClassSVM
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from features import build_features, feature_matrix
from attendance import detect_missing_pairs


def find_optimal_clusters(X_scaled, random_state=42):
    n = len(X_scaled)
    if n < 6:
        return 1

    best_k = 2
    best_score = -1
    max_k = min(5, n // 3 + 1)

    for k in range(2, max_k):
        km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = km.fit_predict(X_scaled)
        try:
            score = silhouette_score(X_scaled, labels)
            if score > best_score:
                best_score = score
                best_k = k
        except ValueError:
            pass

    return best_k


def normalize_anomaly_scores(results):
    anomaly_results = [
        r for r in results
        if r["Prediction"] == "Flagged for Review" and isinstance(r.get("Score"), float)
    ]

    if not anomaly_results:
        return results

    strengths = [r["Score"] for r in anomaly_results]

    # Use Robust Scaling (5th and 95th percentiles) to prevent extreme outliers
    # from squashing the rest of the data.
    p_low = np.percentile(strengths, 5)
    p_high = np.percentile(strengths, 95)

    # Fallback if the data is too clumped
    if p_high - p_low == 0:
        p_low = min(strengths)
        p_high = max(strengths)

    strength_range = p_high - p_low

    if strength_range == 0:
        for r in anomaly_results:
            r["Score"] = 100.0
        return results

    for r in anomaly_results:
        # 1. Clip the extreme scores so they don't exceed our percentile boundaries
        clipped_score = max(p_low, min(r["Score"], p_high))

        # 2. Scale them from 10 to 100.
        # (A flagged anomaly shouldn't be a 0.00, it should have a baseline strength)
        scaled_score = 10.0 + ((clipped_score - p_low) / strength_range) * 90.0
        r["Score"] = round(scaled_score, 2)

    # Non-anomalous employees get a hard 0
    for r in results:
        if r["Prediction"] == "Normal":
            r["Score"] = 0.0

    return results


def build_pop_stats(cluster_features):
    pop_stats = {}
    for key in cluster_features[0].keys():
        if key == "BadgeID":
            continue
        vals = [emp[key] for emp in cluster_features]
        pop_stats[key] = {
            "mean": np.mean(vals),
            "std": np.std(vals) + 1e-9
        }
    return pop_stats


def explain_employee(employee, pop_stats, prediction):
    if prediction == 1:
        return "Within Range", "Behavior pattern is within the usual range for similar employees."

    categories = set()
    reasons = []

    def z_score(metric):
        return (employee[metric] - pop_stats[metric]["mean"]) / pop_stats[metric]["std"]

    # --- BEHAVIORAL DEVIATION MAPPING ---

    if "AverageDuration" in pop_stats:
        z = z_score("AverageDuration")
        if z < -1.2:
            reasons.append("Usually works shorter hours than similar employees")
            categories.add("Attendance Review")
        elif z > 1.5:
            reasons.append("Usually works longer hours than similar employees")
            categories.add("Workload / Wellbeing Review")

    if "AverageArrival" in pop_stats:
        z = z_score("AverageArrival")
        if z > 1.2:
            reasons.append("Often arrives later than similar employees")
            categories.add("Attendance Review")
        elif z < -1.2:
            reasons.append("Often arrives earlier than similar employees")
            categories.add("Workload / Wellbeing Review")

    if "AverageDeparture" in pop_stats:
        z = z_score("AverageDeparture")
        if z > 1.2:
            reasons.append("Often leaves later than similar employees")
            categories.add("Workload / Wellbeing Review")
        elif z < -1.2:
            reasons.append("Often leaves earlier than similar employees")
            categories.add("Attendance Review")

    if "ShortDayRatio" in pop_stats:
        z = z_score("ShortDayRatio")
        if z > 1.0:
            reasons.append("Frequently has short working days")
            categories.add("Attendance Review")

    if "LongDayRatio" in pop_stats:
        z = z_score("LongDayRatio")
        if z > 1.0:
            reasons.append("Frequently works unusually long days")
            categories.add("Workload / Wellbeing Review")

    if "ArrivalCV" in pop_stats:
        z = z_score("ArrivalCV")
        if z > 1.0:
            reasons.append("Arrival times vary significantly from similar employees")
            categories.add("Attendance Review")

    if "DepartureCV" in pop_stats:
        z = z_score("DepartureCV")
        if z > 1.0:
            reasons.append("Departure times vary significantly from similar employees")
            categories.add("Attendance Review")

    if "DurationCV" in pop_stats:
        z = z_score("DurationCV")
        if z > 1.0:
            reasons.append("Shift lengths are inconsistent compared to similar employees")
            categories.add("Attendance Review")

    if "MissingPunchRatio" in pop_stats:
        z = z_score("MissingPunchRatio")
        if z > 1.5:
            reasons.append("Has frequent missing IN/OUT records")
            categories.add("Data Quality")

    # If the SVM flagged them but no individual Z-score broke the hard threshold
    if not categories:
        categories.add("Attendance Review")

    if not reasons:
        reasons.append("Overall attendance pattern deviates from their specific shift group")

    # Limit to top 3 reasons to prevent UI bloat
    data_quality_reason = "Has frequent missing IN/OUT records"
    main_reasons = [r for r in reasons if r != data_quality_reason][:2]
    if data_quality_reason in reasons:
        main_reasons.append(data_quality_reason)

    risk_str = " | ".join(sorted(list(categories)))
    reasons_str = " | ".join(main_reasons)

    return risk_str, reasons_str


def detect_anomalies(records, contamination=0.10, random_state=42):
    raw_alerts = detect_missing_pairs(records)

    features = build_features(records, raw_alerts)
    ids, X = feature_matrix(records, raw_alerts)

    if len(X) < 2:
        return []

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    optimal_k = find_optimal_clusters(X_scaled, random_state)
    cluster_labels = [0] * len(X)

    if optimal_k > 1:
        km = KMeans(n_clusters=optimal_k, random_state=random_state, n_init=10)
        cluster_labels = km.fit_predict(X_scaled)

    raw_results = []

    for cluster_id in range(max(1, optimal_k)):
        cluster_indices = [i for i, cluster in enumerate(cluster_labels) if cluster == cluster_id]

        if len(cluster_indices) < 3:
            for i in cluster_indices:
                raw_results.append({
                    "BadgeID": features[i]["BadgeID"],
                    "Cluster": cluster_id,
                    "Prediction": "Flagged for Review",
                    "Score": 100.0,
                    "Risk": "Data Review",
                    "Reasons": "Assigned to an extremely isolated shift behavior group."
                })
            continue

        X_cluster = np.array([X_scaled[i] for i in cluster_indices])
        cluster_features = [features[i] for i in cluster_indices]
        pop_stats = build_pop_stats(cluster_features)

        pca = PCA(n_components=0.95, random_state=random_state)
        X_pca = pca.fit_transform(X_cluster)

        model = OneClassSVM(nu=contamination, kernel="rbf", gamma="scale")
        predictions = model.fit_predict(X_pca)
        decision_scores = model.decision_function(X_pca)

        for emp_idx, pred, decision_score in zip(cluster_indices, predictions, decision_scores):
            emp = features[emp_idx]
            anomaly_strength = round(float(-decision_score), 8)

            risk_cat, reasons_str = explain_employee(emp, pop_stats, pred)

            raw_results.append({
                "BadgeID": emp["BadgeID"],
                "Cluster": cluster_id,
                "Prediction": "Normal" if pred == 1 else "Flagged for Review",
                "Score": anomaly_strength,
                "Risk": risk_cat,
                "Reasons": reasons_str
            })

    raw_results = normalize_anomaly_scores(raw_results)

    raw_results.sort(
        key=lambda x: (
            0 if x["Prediction"] == "Flagged for Review" else 1,
            -(x["Score"] if isinstance(x["Score"], float) else -1)
        )
    )

    return raw_results


def top_anomalies(records, top_n=10):
    results = detect_anomalies(records)
    anomalies = [r for r in results if r["Prediction"] == "Flagged for Review"]
    return anomalies[:top_n]