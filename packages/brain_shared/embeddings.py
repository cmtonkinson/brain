"""Shared embedding-domain constants used by services and substrates.

Centralizing these values avoids drift between the Embedding Authority Service
and the Qdrant substrate when validating or mapping embedding distance metrics.
"""

DISTANCE_METRIC_COSINE = "cosine"
DISTANCE_METRIC_DOT = "dot"
DISTANCE_METRIC_EUCLID = "euclid"

SUPPORTED_DISTANCE_METRICS = (
    DISTANCE_METRIC_COSINE,
    DISTANCE_METRIC_DOT,
    DISTANCE_METRIC_EUCLID,
)
SUPPORTED_DISTANCE_METRICS_TEXT = ", ".join(SUPPORTED_DISTANCE_METRICS)
