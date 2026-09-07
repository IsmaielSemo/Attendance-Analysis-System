# ml.py
# ============================================================
# Attendance Anomaly Detection
#
# Pipeline:
#
#   Attendance data
#        ↓
#   Feature engineering (Behavioral metrics ONLY)
#        ↓
#   Data quality gate (filter corrupted employee records)
#        ↓
#   K-Means peer grouping
#        ↓
#   One-Class SVM inside each peer group
#        ↓
#   Min-Max scaled score (0 - 100) specifically for anomalies
#        ↓
#   Hardcoded Risk Tiers (High >= 70, Med 40-69, Low < 40)
#        ↓
#   Cascading HR-friendly explanations
#
# Key fixes in this version:
# 1. Data quality gate — employees with AverageDuration=0
#    or fewer than 5 working days are excluded before ML.
#    These have corrupted punch records and produce
#    meaningless anomaly scores.
#
# 2. Weekend attendance moved to secondary note —
#    it is a structural difference, not a behavioral problem.
#    It appears in explanations only when no primary reason
#    is found, or as a trailing note.
#
# 3. Explanation threshold lowered from 1.5σ to 1.2σ —
#    reduces fallback occurrences without over-flagging.
#
# 4. Score 0.0 anomalies filtered in top_anomalies —
#    borderline SVM boundary cases are noise, not signals.
# ============================================================

import numpy as np

from sklearn.cluster import KMeans
from sklearn.svm import OneClassSVM
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

from features import build_features, feature_matrix
from attendance import detect_missing_pairs

# ============================================================
# Configuration
# ============================================================

# Expected approximate proportion of anomalies.
CONTAMINATION = 0.04

# Minimum employees needed to train an anomaly model.
MIN_MODEL_SIZE = 8

# Minimum employees required for a useful peer cluster.
MIN_CLUSTER_SIZE = 8

# Minimum working days for an employee to be included in ML.
# Employees with fewer days don't have enough data for
# meaningful behavioral analysis.
MIN_WORKING_DAYS = 5

RANDOM_STATE = 42


# ============================================================
# K-Means peer grouping
# ============================================================

def create_peer_groups(X_scaled):
    n_employees = len(X_scaled)

    if n_employees < MIN_CLUSTER_SIZE * 2:
        return np.zeros(n_employees, dtype=int), 1

    max_k = min(5, n_employees // MIN_CLUSTER_SIZE)

    if max_k < 2:
        return np.zeros(n_employees, dtype=int), 1

    best_k      = 1
    best_score  = -1
    best_labels = np.zeros(n_employees, dtype=int)

    for k in range(2, max_k + 1):

        model  = KMeans(
            n_clusters=k,
            random_state=RANDOM_STATE,
            n_init=20
        )
        labels = model.fit_predict(X_scaled)

        cluster_sizes = np.bincount(labels)

        if np.min(cluster_sizes) < MIN_CLUSTER_SIZE:
            continue

        try:
            score = silhouette_score(X_scaled, labels)
        except ValueError:
            continue

        if score > best_score:
            best_score  = score
            best_k      = k
            best_labels = labels

    return best_labels, best_k


# ============================================================
# Global Score Calibration (0 to 100)
# ============================================================

def calculate_global_scores(raw_results):
    """
    Scales anomaly strengths from 0 to 100 based only on
    the flagged anomalous employees.

    Normal employees always receive 0.
    The most anomalous employee receives 100.
    All others are scaled proportionally between 0 and 100.
    """

    anomaly_strengths = [
        r["AnomalyStrength"] for r in raw_results
        if r["Prediction"] == "Anomaly"
    ]

    if not anomaly_strengths:
        for r in raw_results:
            r["Score"] = 0.0
        return raw_results

    min_strength  = min(anomaly_strengths)
    max_strength  = max(anomaly_strengths)
    strength_range = max_strength - min_strength

    for result in raw_results:
        if result["Prediction"] == "Anomaly":
            if strength_range < 1e-9:
                result["Score"] = 100.0
            else:
                normalized = (
                    (result["AnomalyStrength"] - min_strength)
                    / strength_range
                ) * 100.0
                result["Score"] = round(float(normalized), 2)
        else:
            result["Score"] = 0.0

    return raw_results


# ============================================================
# Risk classification
# ============================================================

def calculate_risk(score, prediction):
    """
    Hardcoded risk tiers:
      High   >= 70
      Medium  40 - 69.99
      Low    <  40
    """

    if prediction != "Anomaly":
        return "Low"

    if score >= 70.0:
        return "High"

    if score >= 40.0:
        return "Medium"

    return "Low"


# ============================================================
# Feature z-score
# ============================================================

def feature_z_score(employee, population, feature):
    if feature not in population:
        return 0.0

    values = population[feature]

    if not values:
        return 0.0

    mean_value = np.mean(values)
    std_value  = np.std(values)

    if std_value < 1e-9:
        return 0.0

    return (employee[feature] - mean_value) / std_value


# ============================================================
# HR explanation
# ============================================================

def explain_employee(employee, peer_features):
    """
    Produces short, evidence-based explanations for HR.

    Changes vs previous version:
    - Threshold lowered from 1.5σ to 1.2σ to reduce fallbacks
    - Weekend attendance moved to secondary note only —
      it is a structural group difference, not a behavioral problem
    - Fallback only fires if no metric reaches 0.75σ
    - Clear multivariate message when SVM finds subtle pattern
    """

    reasons = []
    notes   = []

    z_scores_map = {}

    def track_z(metric):
        val = feature_z_score(employee, peer_features, metric)
        z_scores_map[metric] = val
        return val

    # --------------------------------------------------------
    # PRIMARY BEHAVIORAL FEATURES
    # Threshold: 1.2σ (lowered from 1.5σ to reduce fallbacks)
    # --------------------------------------------------------

    z_arrival_cv = track_z("ArrivalCV")
    if z_arrival_cv >= 1.2:
        reasons.append("Highly erratic arrival times")

    z_departure_cv = track_z("DepartureCV")
    if z_departure_cv >= 1.2:
        reasons.append("Highly erratic departure times")

    z_duration_cv = track_z("DurationCV")
    if z_duration_cv >= 1.2:
        reasons.append("Highly variable shift lengths")

    z_duration = track_z("AverageDuration")
    if z_duration <= -1.2:
        reasons.append("Unusually short average working duration")
    elif z_duration >= 1.2:
        reasons.append("Unusually long average working duration")

    z_arrival = track_z("AvgArrivalDeviation")
    if z_arrival >= 1.2:
        reasons.append("Later-than-usual arrival pattern")
    elif z_arrival <= -1.2:
        reasons.append("Earlier-than-usual arrival pattern")

    z_departure = track_z("AvgDepartureDeviation")
    if z_departure >= 1.2:
        reasons.append("Later-than-usual departure pattern")
    elif z_departure <= -1.2:
        reasons.append("Earlier-than-usual departure pattern")

    z_short = track_z("ShortDayRatio")
    if z_short >= 1.2:
        reasons.append("Frequent short working days")

    z_long = track_z("LongDayRatio")
    if z_long >= 1.2:
        reasons.append("Frequent long working days")

    # --------------------------------------------------------
    # WEEKEND — secondary note only
    # Weekend attendance is a structural group difference.
    # KMeans clusters weekend workers together, so within-cluster
    # weekend flags mean this person works weekends MORE than
    # even their weekend-working peers — worth noting but not
    # a primary behavioral red flag.
    # --------------------------------------------------------

    z_weekend = track_z("WeekendRatio")
    if abs(z_weekend) >= 1.75:
        notes.append("Unusual weekend attendance pattern vs peer group")

    # --------------------------------------------------------
    # FALLBACK
    # Only fires if no primary reason reached 1.2σ.
    # Uses a minimum threshold of 0.75σ to avoid
    # reporting near-zero deviations as meaningful.
    # --------------------------------------------------------

    if not reasons:
        # Only consider pure behavioral metrics in fallback
        fallback_candidates = {
            k: v for k, v in z_scores_map.items()
            if k != "WeekendRatio"  # weekend handled separately
        }

        significant = {
            k: abs(v) for k, v in fallback_candidates.items()
            if abs(v) >= 0.75
        }

        if significant:
            worst     = max(significant, key=significant.get)
            val       = z_scores_map[worst]
            direction = "above" if val > 0 else "below"

            metric_names = {
                "ArrivalCV"           : "arrival consistency",
                "DepartureCV"         : "departure consistency",
                "DurationCV"          : "shift length consistency",
                "AverageDuration"     : "average shift duration",
                "AvgArrivalDeviation" : "average arrival time",
                "AvgDepartureDeviation": "average departure time",
                "ShortDayRatio"       : "short day frequency",
                "LongDayRatio"        : "long day frequency",
            }

            friendly = metric_names.get(worst, worst)
            reasons.append(
                f"Primary driver: {friendly} is {direction} peer baseline"
            )

        else:
            # SVM found a subtle multivariate pattern —
            # no single feature stands out individually
            reasons.append(
                "Complex multivariate deviation from shift peer group baseline"
            )

    # --------------------------------------------------------
    # ASSEMBLE FINAL EXPLANATION
    # Max 2 primary reasons + weekend note if applicable
    # --------------------------------------------------------

    final_reasons = list(dict.fromkeys(reasons))[:2]

    if notes:
        final_reasons.append(notes[0])

    return " | ".join(final_reasons)


# ============================================================
# Main anomaly detector
# ============================================================

def detect_anomalies(
        records,
        contamination=CONTAMINATION,
        random_state=RANDOM_STATE
):
    if not records:
        return []

    # --------------------------------------------------------
    # Missing-punch information
    # --------------------------------------------------------

    raw_alerts = detect_missing_pairs(records)

    # --------------------------------------------------------
    # Build features
    # --------------------------------------------------------

    features = build_features(records, raw_alerts)

    if len(features) < 2:
        return []

    ids, X = feature_matrix(records, raw_alerts)

    X = np.asarray(X, dtype=float)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # --------------------------------------------------------
    # FIX 1 — DATA QUALITY GATE
    # Employees with AverageDuration = 0 have no valid IN/OUT
    # pairs — their punch records are corrupted or incomplete.
    # Including them in ML produces meaningless scores because
    # their features are built on missing data.
    #
    # Employees with fewer than MIN_WORKING_DAYS don't have
    # enough attendance history for behavioral analysis.
    # --------------------------------------------------------

    valid_indices = [
        i for i, emp in enumerate(features)
        if emp["AverageDuration"] > 0
        and emp["WorkingDays"] >= MIN_WORKING_DAYS
    ]

    if len(valid_indices) < 2:
        return []

    features = [features[i] for i in valid_indices]
    ids      = [ids[i]      for i in valid_indices]
    X        = X[valid_indices]

    # --------------------------------------------------------
    # Standardize
    # --------------------------------------------------------

    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # --------------------------------------------------------
    # K-Means peer grouping
    # --------------------------------------------------------

    cluster_labels, number_of_clusters = create_peer_groups(X_scaled)

    # --------------------------------------------------------
    # DEBUG — remove before final submission
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Valid employees after quality gate: {len(features)}")
    print(f"Number of clusters: {number_of_clusters}")
    print(f"{'='*50}")

    for cluster_id in range(number_of_clusters):
        cluster_indices = [
            i for i, l in enumerate(cluster_labels)
            if l == cluster_id
        ]
        cluster_feats    = [features[i] for i in cluster_indices]
        weekend_ratios   = [f["WeekendRatio"]          for f in cluster_feats]
        arrival_devs     = [f["AvgArrivalDeviation"]   for f in cluster_feats]
        durations        = [f["AverageDuration"]        for f in cluster_feats]

        print(f"\nCluster {cluster_id} — {len(cluster_indices)} employees")
        print(f"  Avg WeekendRatio:      {np.mean(weekend_ratios):.3f}")
        print(f"  Avg ArrivalDeviation:  {np.mean(arrival_devs):.1f} mins from 9am")
        print(f"  Avg Duration:          {np.mean(durations):.1f} mins")

    print(f"{'='*50}\n")
    # --------------------------------------------------------

    raw_results = []

    # ========================================================
    # Analyze each peer group separately
    # ========================================================

    for cluster_id in range(number_of_clusters):

        cluster_indices = [
            i for i, label in enumerate(cluster_labels)
            if label == cluster_id
        ]

        if not cluster_indices:
            continue

        cluster_features = [features[i] for i in cluster_indices]

        # Too small to train SVM meaningfully
        if len(cluster_indices) < MIN_MODEL_SIZE:
            for i in cluster_indices:
                employee = features[i]
                raw_results.append({
                    "BadgeID"        : employee["BadgeID"],
                    "Cluster"        : cluster_id,
                    "Prediction"     : "Normal",
                    "AnomalyStrength": 0.0,
                    "Score"          : 0.0,
                    "Risk"           : "Low",
                    "Reasons"        : (
                        "Insufficient peer data for ML anomaly detection."
                    )
                })
            continue

        # ----------------------------------------------------
        # Train One-Class SVM
        # ----------------------------------------------------

        cluster_X = X_scaled[cluster_indices]

        model = OneClassSVM(
            nu=min(float(contamination), 0.49),
            kernel="rbf",
            gamma="scale"
        )

        predictions      = model.fit_predict(cluster_X)
        decision_scores  = model.decision_function(cluster_X)

        # Invert: higher positive = more anomalous
        anomaly_strengths = -np.asarray(decision_scores, dtype=float)

        # ----------------------------------------------------
        # Peer statistics for explanations
        # ----------------------------------------------------

        explainable_features = [
            "WeekendRatio",
            "AvgArrivalDeviation",
            "AvgDepartureDeviation",
            "AverageDuration",
            "ArrivalCV",
            "DepartureCV",
            "DurationCV",
            "ShortDayRatio",
            "LongDayRatio",
        ]

        peer_statistics = {
            feature: [emp[feature] for emp in cluster_features]
            for feature in explainable_features
        }

        # ----------------------------------------------------
        # Store results
        # ----------------------------------------------------

        for local_index, employee_index in enumerate(cluster_indices):

            employee   = features[employee_index]
            is_anomaly = (predictions[local_index] == -1)
            prediction = "Anomaly" if is_anomaly else "Normal"
            strength   = float(anomaly_strengths[local_index])

            reasons = (
                explain_employee(employee, peer_statistics)
                if is_anomaly
                else "Attendance pattern is consistent with similar employees"
            )

            raw_results.append({
                "BadgeID"        : employee["BadgeID"],
                "Cluster"        : cluster_id,
                "Prediction"     : prediction,
                "AnomalyStrength": strength,
                "Score"          : None,
                "Risk"           : None,
                "Reasons"        : reasons
            })

    # ======================================================
    # GLOBAL SCORE NORMALIZATION & RISK ASSIGNMENT
    # ======================================================

    calculate_global_scores(raw_results)

    for result in raw_results:
        result["Risk"] = calculate_risk(
            result["Score"],
            result["Prediction"]
        )

    # Sort: anomalies first, then by score descending
    raw_results.sort(
        key=lambda item: (
            item["Prediction"] != "Anomaly",
            -item["Score"]
        )
    )

    return raw_results


# ============================================================
# Top anomalies
# ============================================================

def top_anomalies(records, top_n=10):
    results = detect_anomalies(records)

    anomalies = [
        r for r in results
        if r["Prediction"] == "Anomaly"
        and r["Score"] > 5.0  # filter borderline noise at edge of SVM boundary
    ]

    return anomalies[:top_n]