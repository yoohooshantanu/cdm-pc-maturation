"""
Pc Maturation Patterns — Scope Definitions (Phase 0)

All thresholds and constants are locked here before any analysis code runs.
Change these ONLY if you're intentionally redefining the study scope.
"""

from datetime import timedelta

# ---------------------------------------------------------------------------
# Critical event threshold
# ---------------------------------------------------------------------------
PC_CRITICAL_THRESHOLD = 1e-4  # Pc ≥ this at ANY point in the sequence

# ---------------------------------------------------------------------------
# Sequence definitions
# ---------------------------------------------------------------------------
MIN_CDMS_PER_SEQUENCE = 3       # Minimum CDMs to keep a sequence
EARLY_CDM_COUNT = 3             # "Early Pc" = first N CDMs in a sequence

# ---------------------------------------------------------------------------
# Event grouping
# ---------------------------------------------------------------------------
# Two CDMs belong to the same conjunction event if:
#   1. Same unordered object pair: sorted(SAT_1_ID, SAT_2_ID)
#   2. TCA values within this tolerance of each other
TCA_CLUSTER_TOLERANCE = timedelta(minutes=15)

# ---------------------------------------------------------------------------
# LEO filter
# ---------------------------------------------------------------------------
# Mean motion > 11.25 rev/day ≈ altitude < 2000 km
# At least ONE object in the pair must satisfy this.
LEO_MEAN_MOTION_THRESHOLD = 11.25  # rev/day

# ---------------------------------------------------------------------------
# Data pull window
# ---------------------------------------------------------------------------
# To run a full academic/research-grade analysis, increase this to 180 or 365 days.
# Note: A 180-day pull from Space-Track can take significantly longer and requires
# thousands of API calls due to pagination. Ensure your API limits allow it.
DATA_WINDOW_DAYS = 180  # Pull CDMs for events with TCA in the last N days

# ---------------------------------------------------------------------------
# Space-Track API rate limits
# ---------------------------------------------------------------------------
REQUEST_DELAY_SECONDS = 3        # Pause between paginated requests
PAGE_SIZE = 1000                 # Records per API page
