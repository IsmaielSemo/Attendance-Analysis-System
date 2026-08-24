# ml.py
# ============================================================
# Attendance Insights System
#
# Pipeline:
#
#   Attendance data
#        ↓
#   Feature engineering (behavioral metrics only)
#        ↓
#   Data quality gate (filter corrupted/insufficient records)
#        ↓
#   K-Means peer grouping (discover natural shift groups)
#        ↓
#   One-Class SVM per peer group (pattern detection)
#        ↓
#   Min-Max score normalization (0 to 100)
#        ↓
#   Review priority tiers: Follow Up Soon >= 70,
#                          Follow Up When Possible 40-69,
#                          Monitor < 40
#        ↓
#   Human-centered, conversation-prompting explanations
#
# Key design decisions:
#
# 1. build_features called ONCE, result passed to
#    feature_matrix_from_features — fixes the double-call bug
#    where the quality gate filtered features but not X,
#    allowing corrupted employees (e.g. only IN records,
#    AverageDuration=0) to slip into the ML pipeline.
#
# 2. ArrivalStd / DepartureStd instead of ArrivalCV / DepartureCV
#    CV = std/mean requires ratio data (zero means nothing).
#    Time of day is interval data — midnight is arbitrary.
#    Raw std is mathematically correct for time features.
#
# 3. MissingPunchRatio excluded from SVM input
#    Dominates StandardScaler when most employees have 0
#    missing punches — turns model into a punch detector.
#    Still used in explanations as secondary context.
#
# 4. Weekend attendance is a secondary note, not a primary reason
#    KMeans clusters weekend workers together.
#    Within-cluster weekend flags mean structural differences,
#    not behavioral problems.
#
# 5. Consistency metrics "below peer baseline" use a human-
#    centered message — being MORE consistent is not a problem.
#
# 6. Midnight crossing analysis: 79/21289 days (0.37%) affected.
#    Below threshold requiring cyclical timestamp encoding.
#    Linear time representation retained for this dataset.
#
# 7. Ethical framing: this system surfaces attendance patterns
#    for human review only. It does not make decisions.
#    Every flagged employee should be spoken to before any
#    action is taken. Patterns may reflect approved schedule
#    changes, medical circumstances, or data entry errors.
# ============================================================

import numpy as np

from sklearn.cluster import KMeans
from sklearn.svm import OneClassSVM
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

from features import build_features, feature_matrix_from_features
from attendance import detect_missing_pairs

# ============================================================
# Configuration
# ============================================================

CONTAMINATION    = 0.04   # expected fraction of flagged employees per cluster
MIN_MODEL_SIZE   = 8      # minimum employees to train SVM
MIN_CLUSTER_SIZE = 8      # minimum employees per cluster
MIN_WORKING_DAYS = 5      # minimum days for behavioral analysis
RANDOM_STATE     = 42


# ============================================================
# K-Means peer grouping
# ============================================================

def create_peer_groups(X_scaled):
    """
    Discovers natural employee shift groups using K-Means.
    Tries k=2 to k=5, selects best silhouette score.
    Falls back to k=1 if dataset is too small or no valid
    clustering is found.

    Uses sample_size for silhouette to reduce O(n²) cost.
    Uses n_init=5 instead of 20 — sufficient for this scale.
    """
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
        model  = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=5)
        labels = model.fit_predict(X_scaled)

        cluster_sizes = np.bincount(labels)
        if np.min(cluster_sizes) < MIN_CLUSTER_SIZE:
            continue

        try:
            # sample_size approximates silhouette in O(n) instead of O(n²)
            score = silhouette_score(
                X_scaled,
                labels,
                sample_size=min(200, len(X_scaled)),
                random_state=RANDOM_STATE
            )
        except ValueError:
            continue

        if score > best_score:
            best_score  = score
            best_k      = k
            best_labels = labels

    return best_labels, best_k


# ============================================================
# Score normalization (0 to 100)
# ============================================================

def calculate_global_scores(raw_results):
    """
    Normalizes pattern strengths to 0-100 scale.

    Only flagged employees are scaled — employees within
    peer range always receive 0.
    The most flagged employee receives 100.
    All others are scaled proportionally.
    """
    flagged_strengths = [
        r["AnomalyStrength"] for r in raw_results
        if r["Prediction"] == "Flagged for Review"
    ]

    if not flagged_strengths:
        for r in raw_results:
            r["Score"] = 0.0
        return raw_results

    min_s = min(flagged_strengths)
    max_s = max(flagged_strengths)
    rng   = max_s - min_s

    for result in raw_results:
        if result["Prediction"] == "Flagged for Review":
            if rng < 1e-9:
                result["Score"] = 100.0
            else:
                result["Score"] = round(
                    ((result["AnomalyStrength"] - min_s) / rng) * 100.0, 2
                )
        else:
            result["Score"] = 0.0

    return raw_results


# ============================================================
# Review priority classification
# ============================================================

def calculate_risk(score, prediction):
    """
    Review priority tiers on the normalized 0-100 scale.
    Named to reflect human judgment, not automated decisions:
      Follow Up Soon          >= 70
      Follow Up When Possible  40 - 69.99
      Monitor                 <  40
    """
    if prediction != "Flagged for Review":
        return "Within Range"
    if score >= 70.0:
        return "Follow Up Soon"
    if score >= 40.0:
        return "Follow Up When Possible"
    return "Monitor"


# ============================================================
# Feature Z-score
# ============================================================

def feature_z_score(employee, population, feature):
    """
    Z-score of one employee's feature value against
    the cluster peer distribution.
    Returns 0.0 if population std is near zero.
    """
    if feature not in population:
        return 0.0

    values = population[feature]
    if not values:
        return 0.0

    mean_val = np.mean(values)
    std_val  = np.std(values)

    if std_val < 1e-9:
        return 0.0

    return (employee[feature] - mean_val) / std_val


# ============================================================
# HR explanation
# ============================================================

def explain_employee(employee, peer_features):
    """
    Generates short, human-centered explanations.

    Framing: these are conversation starters, not verdicts.
    Language invites follow-up rather than implying conclusions.

    Rules:
    - Primary behavioral observations trigger at 1.2σ
    - Weekend treated as secondary note (structural, not behavioral)
    - Fallback fires only if no metric reaches 0.75σ
    - Consistency metrics "below peer baseline" use a neutral
      message — being more consistent is not a concern
    - Max 2 primary observations + 1 weekend note
    """
    reasons = []
    notes   = []
    z_map   = {}

    def track_z(metric):
        val = feature_z_score(employee, peer_features, metric)
        z_map[metric] = val
        return val

    # --------------------------------------------------------
    # PRIMARY BEHAVIORAL OBSERVATIONS (threshold: 1.2σ)
    # Language is descriptive and invites conversation,
    # not accusatory or conclusive.
    # --------------------------------------------------------

    if track_z("ArrivalStd") >= 1.2:
        reasons.append("Arrival times vary significantly from peer group")

    if track_z("DepartureStd") >= 1.2:
        reasons.append("Departure times vary significantly from peer group")

    if track_z("DurationCV") >= 1.2:
        reasons.append("Shift lengths are inconsistent")

    z_dur = track_z("AverageDuration")
    if z_dur <= -1.2:
        reasons.append("Working hours appear shorter than peers")
    elif z_dur >= 1.2:
        reasons.append("Working hours appear longer than peers")

    z_arr = track_z("AvgArrivalDeviation")
    if z_arr >= 1.2:
        reasons.append("Tends to arrive later than similar employees")
    elif z_arr <= -1.2:
        reasons.append("Tends to arrive earlier than similar employees")

    z_dep = track_z("AvgDepartureDeviation")
    if z_dep >= 1.2:
        reasons.append("Tends to leave later than similar employees")
    elif z_dep <= -1.2:
        reasons.append("Tends to leave earlier than similar employees")

    if track_z("ShortDayRatio") >= 1.2:
        reasons.append("Frequently has shorter working days")

    if track_z("LongDayRatio") >= 1.2:
        reasons.append("Frequently works long hours")

    # --------------------------------------------------------
    # WEEKEND NOTE (secondary — structural difference only)
    # --------------------------------------------------------

    if abs(track_z("WeekendRatio")) >= 1.75:
        notes.append("Works weekends more than usual for their group")

    # --------------------------------------------------------
    # FALLBACK
    # Fires only when no primary observation reached 1.2σ.
    # Requires at least 0.75σ to report anything at all.
    # --------------------------------------------------------

    if not reasons:
        consistency_metrics = {"ArrivalStd", "DepartureStd", "DurationCV"}

        candidates = {
            k: abs(v) for k, v in z_map.items()
            if k != "WeekendRatio" and abs(v) >= 0.75
        }

        if candidates:
            worst = max(candidates, key=candidates.get)
            val   = z_map[worst]

            # More consistent than peers = not a concern
            if worst in consistency_metrics and val < 0:
                reasons.append(
                    "No single standout factor. Overall pattern "
                    "differs from peer group;"
                )
            else:
                direction = "above" if val > 0 else "below"
                metric_names = {
                    "ArrivalStd"           : "arrival consistency",
                    "DepartureStd"         : "departure consistency",
                    "DurationCV"           : "shift length consistency",
                    "AverageDuration"      : "average shift duration",
                    "AvgArrivalDeviation"  : "average arrival time",
                    "AvgDepartureDeviation": "average departure time",
                    "ShortDayRatio"        : "short day frequency",
                    "LongDayRatio"         : "long day frequency",
                }
                friendly = metric_names.get(worst, worst)
                reasons.append(
                    f"Attendance pattern differs from peers "
                    f"({friendly} is {direction} group average)"
                )
        else:
            reasons.append(
                "No single standout factor. Overall pattern "
                "differs from peer group; review recommended"
            )

    # --------------------------------------------------------
    # ASSEMBLE: max 2 primary observations + weekend note
    # --------------------------------------------------------

    final = list(dict.fromkeys(reasons))[:2]
    if notes:
        final.append(notes[0])

    return " | ".join(final)


# ============================================================
# Main detector
# ============================================================

def detect_anomalies(
        records,
        contamination=CONTAMINATION,
        random_state=RANDOM_STATE
):
    if not records:
        return []

    # --------------------------------------------------------
    # Build features ONCE
    # Pass result to feature_matrix_from_features to avoid
    # the double-call bug where quality gate filtered features
    # but not X (causing corrupted employees to slip through).
    # --------------------------------------------------------

    raw_alerts = detect_missing_pairs(records)
    features   = build_features(records, raw_alerts)

    if len(features) < 2:
        return []

    ids, X = feature_matrix_from_features(features)

    X = np.asarray(X, dtype=float)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # --------------------------------------------------------
    # DATA QUALITY GATE
    # Excludes employees with:
    # - AverageDuration = 0: no valid IN/OUT pairs — corrupted
    #   punch records produce meaningless behavioral features.
    # - WorkingDays < MIN_WORKING_DAYS: insufficient history
    #   for reliable behavioral pattern analysis.
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

    cluster_labels, n_clusters = create_peer_groups(X_scaled)

    raw_results = []

    # ========================================================
    # One-Class SVM per cluster
    # ========================================================

    for cluster_id in range(n_clusters):

        cluster_indices = [
            i for i, lbl in enumerate(cluster_labels)
            if lbl == cluster_id
        ]

        if not cluster_indices:
            continue

        cluster_features = [features[i] for i in cluster_indices]

        # Too small to train SVM meaningfully
        if len(cluster_indices) < MIN_MODEL_SIZE:
            for i in cluster_indices:
                raw_results.append({
                    "BadgeID"        : features[i]["BadgeID"],
                    "Cluster"        : cluster_id,
                    "Prediction"     : "Within Peer Range",
                    "AnomalyStrength": 0.0,
                    "Score"          : 0.0,
                    "Risk"           : "Within Range",
                    "Reasons"        : "Insufficient peer data for pattern analysis."
                })
            continue

        cluster_X = X_scaled[cluster_indices]

        # ----------------------------------------------------
        # One-Class SVM
        # nu     = expected fraction of flagged employees
        # kernel = rbf for non-linear boundary
        # gamma  = scale adapts to feature spread
        # ----------------------------------------------------

        model = OneClassSVM(
            nu=min(float(contamination), 0.49),
            kernel="rbf",
            gamma="scale"
        )

        predictions       = model.fit_predict(cluster_X)
        decision_scores   = model.decision_function(cluster_X)
        anomaly_strengths = -np.asarray(decision_scores, dtype=float)

        # Peer statistics for Z-score explanations
        explainable = [
            "WeekendRatio", "AvgArrivalDeviation", "AvgDepartureDeviation",
            "AverageDuration", "ArrivalStd", "DepartureStd", "DurationCV",
            "ShortDayRatio", "LongDayRatio",
        ]

        peer_stats = {
            feat: [emp[feat] for emp in cluster_features]
            for feat in explainable
        }

        for local_idx, emp_idx in enumerate(cluster_indices):
            employee    = features[emp_idx]
            is_flagged  = (predictions[local_idx] == -1)
            prediction  = "Flagged for Review" if is_flagged else "Within Peer Range"
            strength    = float(anomaly_strengths[local_idx])

            reasons = (
                explain_employee(employee, peer_stats)
                if is_flagged
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
    # Normalize scores and assign review priority
    # ======================================================

    calculate_global_scores(raw_results)

    for result in raw_results:
        result["Risk"] = calculate_risk(result["Score"], result["Prediction"])

    raw_results.sort(
        key=lambda r: (r["Prediction"] != "Flagged for Review", -r["Score"])
    )

    return raw_results


# ============================================================
# Top flagged employees
# ============================================================

def top_anomalies(records, top_n=10):
    results = detect_anomalies(records)
    return [
        r for r in results
        if r["Prediction"] == "Flagged for Review"
        and r["Score"] > 5.0  # filter borderline edge cases
    ][:top_n]
