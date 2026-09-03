# ml.py -> Handles the ML of project

import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.svm import OneClassSVM

from features import (
    build_features,
    feature_matrix
)


# ==========================================================
# TRAIN MODEL
# ==========================================================
def detect_anomalies(records, contamination=0.04, random_state=42):
    """Detect anomalous employees relative to the population."""
    features = build_features(records)
    ids, X = feature_matrix(records)

    if len(X) < 2:
        return []

    # 1. Calculate Population Statistics (Means and StDevs for explanations)
    pop_stats = {}
    for key in features[0].keys():
        if key != "BadgeID":
            vals = [emp[key] for emp in features]
            # Add tiny epsilon to std to prevent division by zero later
            pop_stats[key] = {"mean": np.mean(vals), "std": np.std(vals) + 1e-9}

    # 2. Normalize Data
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 3. Dimensionality Reduction (PCA)
    # Keeps 95% of the statistical variance, ignoring pure noise
    pca = PCA(n_components=0.95, random_state=random_state)
    X_pca = pca.fit_transform(X_scaled)

    # 4. One-Class SVM
    # Much better at drawing boundaries around dense normal clusters
    model = OneClassSVM(nu=contamination, kernel="rbf", gamma="scale")
    predictions = model.fit_predict(X_pca)
    scores = model.decision_function(X_pca)

    results = []
    for employee, prediction, score in zip(features, predictions, scores):
        # Multiply by 1000 to make the score readable (e.g., -0.0004 becomes -0.4)
        clean_score = round(float(score) * 1000, 2)

        results.append({
            "BadgeID": employee["BadgeID"],
            "Prediction": "Normal" if prediction == 1 else "Anomaly",
            "Score": clean_score,
            "Risk": calculate_risk(clean_score),
            "Reasons": explain_employee(employee, pop_stats, prediction)
        })

    results.sort(key=lambda x: x["Score"])
    return results


# ==========================================================
# RISK LEVEL
# ==========================================================
def calculate_risk(score):
    if score < -0.40:
        return "High"
    elif score < -0.15:
        return "Medium"
    else:
        return "Low"


# ==========================================================
# EXPLAIN EMPLOYEE (DATA-DRIVEN Z-SCORES)
# ==========================================================
def explain_employee(employee, pop_stats, prediction):
    if prediction == 1:
        return "Behavior falls within normal statistical variance."

    reasons = []

    def z_score(metric):
        return (employee[metric] - pop_stats[metric]["mean"]) / pop_stats[metric]["std"]

    # 1. Late Arrivals
    if "LateDays" in employee and "LateDays" in pop_stats:
        z_late = z_score("LateDays")
        if z_late > 0.8:
            reasons.append(f"Higher-than-average late arrival frequency (Late frequency is {z_late:.1f} std devs above average)")

    # 2. Early Departures
    if "EarlyLeaveDays" in employee and "EarlyLeaveDays" in pop_stats:
        z_early = z_score("EarlyLeaveDays")
        if z_early > 0.8:
            reasons.append(f"Higher-than-average early departures (Early departures are {z_early:.1f} std devs above average)")

    # 3. Short Days / Underworking
    if "AverageDuration" in employee and "AverageDuration" in pop_stats:
        z_short = z_score("AverageDuration")
        if z_short < -0.8:
            reasons.append(f"Below-average recorded shift duration (Shift duration is {abs(z_short):.1f} std devs below average)")
        elif z_short > 1.2:
            reasons.append(f"Excessive Shift Lengths (Shift duration is {z_short:.1f} std devs above average)")

    # 4. Arrival Variance / Erratic Schedule
    if "ArrivalStd" in employee and "ArrivalStd" in pop_stats:
        z_arrival_var = z_score("ArrivalStd")
        if z_arrival_var > 1.0:
            reasons.append(f"Erratic Arrival Times (Arrival variance is {z_arrival_var:.1f} std devs worse than average)")

    # 5. Missing Punches
    if "MissingOUT" in employee and "MissingOUT" in pop_stats:
        z_missing = z_score("MissingOUT")
        if z_missing > 0.8:
            reasons.append(f"Frequent missing attendance punches (Missing punches are {z_missing:.1f} std devs above average)")
    if not reasons:
        metric_scores = {}
        for m in ["LateDays", "EarlyLeaveDays", "AverageDuration", "ArrivalStd", "MissingOUT"]:
            if m in employee and m in pop_stats:
                metric_scores[m] = abs(z_score(m))

        if metric_scores:
            worst_metric = max(metric_scores, key=metric_scores.get)
            val = z_score(worst_metric)
            reasons.append(f"Elevated {worst_metric} pattern (Deviation factor: {val:.1f} std devs)")
        else:
            reasons.append("Slight behavioral deviation across multiple operational metrics")

    return " | ".join(reasons)


# ==========================================================
# TOP ANOMALIES
# ==========================================================
def top_anomalies(records, top_n=10):
    results = detect_anomalies(records)
    anomalies = [r for r in results if r["Prediction"] == "Anomaly"]
    return anomalies[:top_n]
