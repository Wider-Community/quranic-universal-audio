#!/usr/bin/env python3
"""
Test harness for the wraparound DP repetition detection algorithm (v2).

Runs both standard DP (v1) and wraparound DP (v2) on the repetition test set,
compares results against ground truth, and reports evaluation metrics.

Usage:
    python docs/repetition_detection/test_wraparound_dp.py [--model base|large] [--wrap-penalty 2.0] [--max-wraps 5]
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent          # quranic_universal_aligner/
REPO_ROOT = PROJECT_ROOT.parent                   # quranic-universal-audio/
DATA_DIR = REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# Config constants (mirrored from config.py to keep this standalone)
# ---------------------------------------------------------------------------
COST_SUBSTITUTION = 1.0
COST_DELETION = 0.8
COST_INSERTION = 1.0
START_PRIOR_WEIGHT = 0.005
MAX_EDIT_DISTANCE = 0.25

# New v2 defaults
WRAP_PENALTY = 2.0
MAX_WRAPS = 5

# ---------------------------------------------------------------------------
# Substitution cost matrix
# ---------------------------------------------------------------------------

def load_substitution_costs() -> Dict[Tuple[str, str], float]:
    path = PROJECT_ROOT / "data" / "phoneme_sub_costs.json"
    if not path.exists():
        return {}
    with open(path) as f:
        raw = json.load(f)
    costs = {}
    for key, section in raw.items():
        if key == "_meta":
            continue
        for pair_str, cost in section.items():
            a, b = pair_str.split("|")
            c = float(cost)
            costs[(a, b)] = c
            costs[(b, a)] = c
    return costs

SUB_COSTS = load_substitution_costs()

def get_sub_cost(p: str, r: str, default: float = COST_SUBSTITUTION) -> float:
    if p == r:
        return 0.0
    return SUB_COSTS.get((p, r), default)


# ---------------------------------------------------------------------------
# Standard DP (v1) — direct port from phoneme_matcher.py
# ---------------------------------------------------------------------------

def align_standard(
    P: List[str],
    R: List[str],
    R_phone_to_word: List[int],
    expected_word: int = 0,
    prior_weight: float = START_PRIOR_WEIGHT,
    cost_sub: float = COST_SUBSTITUTION,
    cost_del: float = COST_DELETION,
    cost_ins: float = COST_INSERTION,
) -> Tuple[Optional[int], Optional[int], float, float]:
    """Standard word-boundary-constrained substring alignment (v1)."""
    m, n = len(P), len(R)
    INF = float('inf')
    if m == 0 or n == 0:
        return None, None, INF, INF

    def is_start_boundary(j):
        if j >= n: return False
        if j == 0: return True
        return R_phone_to_word[j] != R_phone_to_word[j - 1]

    def is_end_boundary(j):
        if j == 0: return False
        if j == n: return True
        return R_phone_to_word[j] != R_phone_to_word[j - 1]

    prev_cost = [0.0 if is_start_boundary(j) else INF for j in range(n + 1)]
    prev_start = [j if is_start_boundary(j) else -1 for j in range(n + 1)]
    curr_cost = [0.0] * (n + 1)
    curr_start = [0] * (n + 1)

    for i in range(1, m + 1):
        curr_cost[0] = i * cost_del if is_start_boundary(0) else INF
        curr_start[0] = 0 if is_start_boundary(0) else -1
        for j in range(1, n + 1):
            del_opt = prev_cost[j] + cost_del
            ins_opt = curr_cost[j-1] + cost_ins
            sub_opt = prev_cost[j-1] + get_sub_cost(P[i-1], R[j-1], cost_sub)
            if sub_opt <= del_opt and sub_opt <= ins_opt:
                curr_cost[j] = sub_opt
                curr_start[j] = prev_start[j-1]
            elif del_opt <= ins_opt:
                curr_cost[j] = del_opt
                curr_start[j] = prev_start[j]
            else:
                curr_cost[j] = ins_opt
                curr_start[j] = curr_start[j-1]
        prev_cost, curr_cost = curr_cost, prev_cost
        prev_start, curr_start = curr_start, prev_start

    best_score = INF
    best_j = None
    best_j_start = None
    best_cost = INF
    best_norm_dist = INF

    for j in range(1, n + 1):
        if not is_end_boundary(j):
            continue
        if prev_cost[j] >= INF:
            continue
        dist = prev_cost[j]
        j_start = prev_start[j]
        ref_len = j - j_start
        denom = max(m, ref_len, 1)
        norm_dist = dist / denom
        start_word = R_phone_to_word[j_start] if j_start < n else R_phone_to_word[j - 1]
        prior = prior_weight * abs(start_word - expected_word)
        score = norm_dist + prior
        if score < best_score:
            best_score = score
            best_j = j
            best_j_start = j_start
            best_cost = dist
            best_norm_dist = norm_dist

    return best_j, best_j_start, best_cost, best_norm_dist


# ---------------------------------------------------------------------------
# Wraparound DP (v2)
# ---------------------------------------------------------------------------

def align_wraparound(
    P: List[str],
    R: List[str],
    R_phone_to_word: List[int],
    expected_word: int = 0,
    prior_weight: float = START_PRIOR_WEIGHT,
    cost_sub: float = COST_SUBSTITUTION,
    cost_del: float = COST_DELETION,
    cost_ins: float = COST_INSERTION,
    wrap_penalty: float = WRAP_PENALTY,
    max_wraps: int = MAX_WRAPS,
    scoring_mode: str = "subtract",  # "subtract" (v2 original), "no_subtract", "additive"
    wrap_score_cost: float = 0.01,   # per-wrap score penalty (only for "additive" mode)
) -> Tuple[Optional[int], Optional[int], float, float, int, int, List[Tuple[int, int, int]]]:
    """
    Wraparound DP with full traceback.

    scoring_mode:
        "subtract"    — original v2: phoneme_cost = dist - k*wrap_penalty (wrap is free in score)
        "no_subtract" — phoneme_cost = dist (wrap penalty stays in score)
        "additive"    — phoneme_cost = dist - k*wrap_penalty, score += k*wrap_score_cost

    Returns:
        (best_j_end, best_j_start, best_cost, best_norm_dist, n_wraps, best_max_j, wrap_points)
        wrap_points: list of (i, j_end, j_start) — P position and R positions of each wrap
    """
    m, n = len(P), len(R)
    INF = float('inf')

    if m == 0 or n == 0:
        return None, None, INF, INF, 0, 0, []

    # Precompute word boundary sets
    word_starts = set()
    word_ends = set()
    for j in range(n + 1):
        if j == 0 or (j < n and R_phone_to_word[j] != R_phone_to_word[j - 1]):
            word_starts.add(j)
        if j == n or (j > 0 and j < n and R_phone_to_word[j] != R_phone_to_word[j - 1]):
            word_ends.add(j)

    K = max_wraps

    # Full DP matrix for traceback: dp[i][k][j]
    # Parent pointers: parent[i][k][j] = (prev_i, prev_k, prev_j, transition_type)
    #   transition_type: 'S' = sub/match, 'D' = deletion, 'I' = insertion, 'W' = wrap
    dp = [[[INF] * (n + 1) for _ in range(K + 1)] for _ in range(m + 1)]
    parent = [[[None] * (n + 1) for _ in range(K + 1)] for _ in range(m + 1)]
    start_arr = [[[-1] * (n + 1) for _ in range(K + 1)] for _ in range(m + 1)]
    max_j_arr = [[[-1] * (n + 1) for _ in range(K + 1)] for _ in range(m + 1)]

    # Initialize: k=0, free starts at word boundaries
    for j in word_starts:
        dp[0][0][j] = 0.0
        start_arr[0][0][j] = j
        max_j_arr[0][0][j] = j

    # Fill DP
    for i in range(1, m + 1):
        for k in range(K + 1):
            # Column 0: deletion only for k=0
            if k == 0 and 0 in word_starts:
                dp[i][k][0] = i * cost_del
                parent[i][k][0] = (i - 1, k, 0, 'D')
                start_arr[i][k][0] = 0
                max_j_arr[i][k][0] = 0

            for j in range(1, n + 1):
                del_opt = dp[i-1][k][j] + cost_del if dp[i-1][k][j] < INF else INF
                ins_opt = dp[i][k][j-1] + cost_ins if dp[i][k][j-1] < INF else INF
                sub_opt = dp[i-1][k][j-1] + get_sub_cost(P[i-1], R[j-1], cost_sub) \
                          if dp[i-1][k][j-1] < INF else INF

                best = min(del_opt, ins_opt, sub_opt)
                if best < INF:
                    dp[i][k][j] = best
                    if best == sub_opt:
                        parent[i][k][j] = (i - 1, k, j - 1, 'S')
                        start_arr[i][k][j] = start_arr[i-1][k][j-1]
                        max_j_arr[i][k][j] = max(max_j_arr[i-1][k][j-1], j)
                    elif best == del_opt:
                        parent[i][k][j] = (i - 1, k, j, 'D')
                        start_arr[i][k][j] = start_arr[i-1][k][j]
                        max_j_arr[i][k][j] = max_j_arr[i-1][k][j]
                    else:
                        parent[i][k][j] = (i, k, j - 1, 'I')
                        start_arr[i][k][j] = start_arr[i][k][j-1]
                        max_j_arr[i][k][j] = max(max_j_arr[i][k][j-1], j)

        # Wrap transitions (within same row i)
        for k in range(K):
            for j_end in word_ends:
                if dp[i][k][j_end] >= INF:
                    continue
                cost_at_end = dp[i][k][j_end]
                for j_s in word_starts:
                    if j_s >= j_end:
                        continue
                    new_cost = cost_at_end + wrap_penalty
                    if new_cost < dp[i][k+1][j_s]:
                        dp[i][k+1][j_s] = new_cost
                        parent[i][k+1][j_s] = (i, k, j_end, 'W')
                        start_arr[i][k+1][j_s] = start_arr[i][k][j_end]
                        max_j_arr[i][k+1][j_s] = max(max_j_arr[i][k][j_end], j_end)

            # Re-propagate insertions from wrap positions
            for j in range(1, n + 1):
                ins_opt = dp[i][k+1][j-1] + cost_ins if dp[i][k+1][j-1] < INF else INF
                if ins_opt < dp[i][k+1][j]:
                    dp[i][k+1][j] = ins_opt
                    parent[i][k+1][j] = (i, k+1, j-1, 'I')
                    start_arr[i][k+1][j] = start_arr[i][k+1][j-1]
                    max_j_arr[i][k+1][j] = max(max_j_arr[i][k+1][j-1], j)

    # Find best end position across all k
    best_score = INF
    best_j = None
    best_j_start_val = None
    best_cost_val = INF
    best_norm = INF
    best_k = 0
    best_max_j_val = 0

    for k in range(K + 1):
        for j in range(1, n + 1):
            if j not in word_ends:
                continue
            if dp[m][k][j] >= INF:
                continue

            dist = dp[m][k][j]
            j_start_val = start_arr[m][k][j]
            if j_start_val < 0:
                continue

            max_j_reached = max_j_arr[m][k][j]
            ref_len = max(max_j_reached, j) - j_start_val
            if ref_len <= 0:
                continue
            denom = max(m, ref_len, 1)

            if scoring_mode == "no_subtract":
                phoneme_cost = dist
            else:
                phoneme_cost = dist - k * wrap_penalty
            norm_dist = phoneme_cost / denom

            start_word = R_phone_to_word[j_start_val] if j_start_val < n else R_phone_to_word[j - 1]
            prior = prior_weight * abs(start_word - expected_word)
            score = norm_dist + prior
            if scoring_mode == "additive":
                score += k * wrap_score_cost

            if score < best_score:
                best_score = score
                best_j = j
                best_j_start_val = j_start_val
                best_cost_val = dist
                best_norm = norm_dist
                best_k = k
                best_max_j_val = max_j_reached

    if best_j is None:
        return None, None, INF, INF, 0, 0, []

    # Traceback: walk parent pointers, collect wrap points
    wrap_points = []
    ci, ck, cj = m, best_k, best_j
    while parent[ci][ck][cj] is not None:
        pi, pk, pj, trans = parent[ci][ck][cj]
        if trans == 'W':
            # Wrap: at P position pi (=ci), R jumped from pj (j_end) back to cj (j_start)
            wrap_points.append((ci, pj, cj))
        ci, ck, cj = pi, pk, pj
    wrap_points.reverse()  # chronological order (by P position)

    return best_j, best_j_start_val, best_cost_val, best_norm, best_k, best_max_j_val, wrap_points


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_test_data(model: str) -> dict:
    fname = f"repetition_test_set_{model}.json"
    path = DATA_DIR / fname
    with open(path) as f:
        data = json.load(f)
    return data

def load_ref_phonemes() -> dict:
    path = DATA_DIR / "repetition_ref_phonemes.json"
    with open(path) as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if k != "_meta"}


# ---------------------------------------------------------------------------
# Build R and R_phone_to_word from ref phonemes string
# ---------------------------------------------------------------------------

def build_ref_arrays(ref_phonemes_str: str) -> Tuple[List[str], List[int]]:
    """
    Convert space-separated ref phonemes into R list and R_phone_to_word mapping.

    The ref phonemes use spaces between all phonemes. Word boundaries in the
    original are not explicitly marked, so we need the per-word phonemes from
    the phonemizer. However, for this test we use the pre-built ref phonemes
    which are a flat space-separated string of all phonemes for the verse.

    We'll reconstruct word boundaries by matching against the verse's word
    structure using the phonemizer.
    """
    phonemes = ref_phonemes_str.split()
    # For the ref phonemes file, all phonemes for the whole verse are
    # concatenated. We need word boundaries. We'll use a simple approach:
    # assign word indices by looking at the original per-word phonemization.
    # But since we don't have that here, we'll use word boundary markers.
    # Actually the ref phonemes DON'T have word boundary markers - they're flat.
    # We need to use the phonemizer to get per-word phonemes.
    return phonemes, None  # caller must handle word boundary construction


def build_ref_from_phonemizer(pm, surah: int, ayah: int):
    """
    Build reference phonemes with word boundary info using the phonemizer.

    Returns: (R, R_phone_to_word, word_phoneme_offsets)
      - R: flat list of phonemes
      - R_phone_to_word: maps each phoneme index to its 0-based word index
      - word_phoneme_offsets: start offset of each word in R
    """
    result = pm.phonemize(ref=f"{surah}:{ayah}")
    mapping = result.get_mapping()

    R = []
    R_phone_to_word = []
    word_offsets = []

    for word_idx, word in enumerate(mapping.words):
        word_offsets.append(len(R))
        for ph in word.phonemes:
            R.append(ph)
            R_phone_to_word.append(word_idx)

    return R, R_phone_to_word, word_offsets


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class VerseResult:
    verse_key: str
    reciter: str
    num_reps_gt: int          # ground truth repetition count
    # Standard DP (v1)
    v1_norm_dist: float = 0.0
    v1_confidence: float = 0.0
    v1_word_from: int = -1
    v1_word_to: int = -1
    v1_time_ms: float = 0.0
    # Wraparound DP (v2)
    v2_norm_dist: float = 0.0
    v2_confidence: float = 0.0
    v2_n_wraps: int = 0
    v2_word_from: int = -1
    v2_word_to: int = -1
    v2_time_ms: float = 0.0
    # Ground truth
    gt_word_from: int = -1
    gt_word_to: int = -1
    # Sizes
    p_len: int = 0
    r_len: int = 0
    # Traceback
    v2_wrap_points: List = field(default_factory=list)  # [(i, j_end, j_start), ...]
    # Debug
    error: str = ""


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def compute_dynamic_k(excess: int, global_max_wraps: int) -> int:
    """Compute per-verse max_wraps from excess phonemes (len(P) - len(R))."""
    if excess <= 0:
        return 0
    if excess < 5:
        return 1
    if excess < 10:
        return 2
    if excess < 15:
        return 3
    if excess < 20:
        return 4
    return global_max_wraps


def evaluate(
    model: str = "base",
    wrap_penalty: float = WRAP_PENALTY,
    max_wraps: int = MAX_WRAPS,
    verbose: bool = False,
    limit: int = 0,
    scoring_mode: str = "subtract",
    wrap_score_cost: float = 0.01,
    dynamic_k: bool = False,
):
    print(f"\n{'='*70}")
    print(f"  Wraparound DP (v2) Evaluation")
    print(f"  Model: {model} | WRAP_PENALTY: {wrap_penalty} | MAX_WRAPS: {max_wraps}")
    print(f"  Scoring: {scoring_mode}" + (f" (wrap_score_cost={wrap_score_cost})" if scoring_mode == "additive" else ""))
    if dynamic_k:
        print(f"  Dynamic-K: ON (per-verse max_wraps based on excess phonemes)")
    print(f"{'='*70}\n")

    # Load data
    print("Loading test data...", end=" ", flush=True)
    test_data = load_test_data(model)
    ref_phonemes = load_ref_phonemes()
    print("done.")

    # Initialize phonemizer (one-time cost)
    print("Initializing phonemizer...", end=" ", flush=True)
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.alignment.phonemizer_utils import get_phonemizer
    pm = get_phonemizer()
    print("done.")

    results: List[VerseResult] = []
    errors = []
    total_verses = 0
    total_expected = sum(len(v) for k, v in test_data.items() if k != "_meta")
    t_start = time.time()

    for reciter in [k for k in test_data if k != "_meta"]:
        verses = test_data[reciter]
        reciter_count = 0

        for verse_key, verse_data in verses.items():
            if limit and total_verses >= limit:
                break

            total_verses += 1
            reciter_count += 1

            if total_verses % 25 == 0:
                elapsed = time.time() - t_start
                rate = total_verses / elapsed if elapsed > 0 else 0
                eta = (total_expected - total_verses) / rate if rate > 0 else 0
                print(f"  [progress] {total_verses}/{total_expected} "
                      f"({total_verses/total_expected*100:.0f}%) "
                      f"{elapsed:.0f}s elapsed, ~{eta:.0f}s remaining", flush=True)
            vr = VerseResult(
                verse_key=verse_key,
                reciter=reciter,
                num_reps_gt=verse_data["num_reps"],
            )

            # Parse surah:ayah
            parts = verse_key.split(":")
            surah, ayah = int(parts[0]), int(parts[1])

            # Get ASR phonemes (P)
            asr_str = verse_data["asr_phonemes"]
            P = asr_str.split()
            vr.p_len = len(P)

            # Get ground truth word range (full verse span from segments)
            # GT uses 1-based word indices; algorithm uses 0-based → subtract 1
            segments = verse_data["segments"]
            vr.gt_word_from = segments[0][0] - 1  # first segment word_from (to 0-based)
            vr.gt_word_to = segments[-1][1] - 1    # last segment word_to (to 0-based)

            # Build reference phonemes with word boundaries
            try:
                R, R_phone_to_word, word_offsets = build_ref_from_phonemizer(pm, surah, ayah)
            except Exception as e:
                vr.error = f"Phonemizer error: {e}"
                errors.append(vr)
                results.append(vr)
                continue

            vr.r_len = len(R)

            if len(R) == 0:
                vr.error = "Empty reference"
                errors.append(vr)
                results.append(vr)
                continue

            # --- Run standard DP (v1) ---
            t0 = time.perf_counter()
            v1_j, v1_j_start, v1_cost, v1_norm = align_standard(
                P, R, R_phone_to_word,
                expected_word=0,
                prior_weight=0.0,  # no prior for test (full verse, expected=word 0)
            )
            vr.v1_time_ms = (time.perf_counter() - t0) * 1000

            if v1_j is not None:
                vr.v1_norm_dist = v1_norm
                vr.v1_confidence = 1.0 - v1_norm
                vr.v1_word_from = R_phone_to_word[v1_j_start] if v1_j_start < len(R_phone_to_word) else -1
                vr.v1_word_to = R_phone_to_word[v1_j - 1] if v1_j - 1 < len(R_phone_to_word) else -1

            # --- Run wraparound DP (v2) ---
            # Determine per-verse max_wraps
            if dynamic_k:
                excess = len(P) - len(R)
                verse_max_wraps = compute_dynamic_k(excess, max_wraps)
            else:
                excess = 0
                verse_max_wraps = max_wraps

            t0 = time.perf_counter()
            if dynamic_k and verse_max_wraps == 0:
                # No excess phonemes — skip wraparound, reuse v1 result
                v2_j, v2_j_start, v2_cost, v2_norm = v1_j, v1_j_start, v1_cost, v1_norm
                v2_k, v2_max_j, v2_wraps = 0, 0, []
            else:
                v2_j, v2_j_start, v2_cost, v2_norm, v2_k, v2_max_j, v2_wraps = align_wraparound(
                    P, R, R_phone_to_word,
                    expected_word=0,
                    prior_weight=0.0,
                    wrap_penalty=wrap_penalty,
                    max_wraps=verse_max_wraps,
                    scoring_mode=scoring_mode,
                    wrap_score_cost=wrap_score_cost,
                )
            vr.v2_time_ms = (time.perf_counter() - t0) * 1000

            if v2_j is not None:
                vr.v2_norm_dist = v2_norm
                vr.v2_confidence = 1.0 - v2_norm
                vr.v2_n_wraps = v2_k
                vr.v2_word_from = R_phone_to_word[v2_j_start] if v2_j_start < len(R_phone_to_word) else -1
                # Use max_j (furthest R reached) for the end word, not final j (which may have wrapped back)
                end_j = max(v2_max_j, v2_j) if v2_k > 0 else v2_j
                vr.v2_word_to = R_phone_to_word[end_j - 1] if end_j - 1 < len(R_phone_to_word) else -1
                vr.v2_wrap_points = v2_wraps

            results.append(vr)

            if verbose:
                wrap_str = f"wraps={v2_k}" if v2_k > 0 else "no-wrap"
                conf_delta = vr.v2_confidence - vr.v1_confidence
                print(f"  {reciter}/{verse_key}: reps={vr.num_reps_gt} | "
                      f"v1_conf={vr.v1_confidence:.3f} v2_conf={vr.v2_confidence:.3f} "
                      f"(Δ={conf_delta:+.3f}) | {wrap_str} | "
                      f"P={vr.p_len} R={vr.r_len} | "
                      f"v1={vr.v1_time_ms:.1f}ms v2={vr.v2_time_ms:.1f}ms")

        if limit and total_verses >= limit:
            break

        print(f"  {reciter}: processed {reciter_count} verses")

    # -----------------------------------------------------------------------
    # Compute metrics
    # -----------------------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"  RESULTS ({len(results)} verses, {len(errors)} errors)")
    print(f"{'='*70}\n")

    if errors:
        print(f"  Errors ({len(errors)}):")
        for e in errors[:10]:
            print(f"    {e.reciter}/{e.verse_key}: {e.error}")
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more")
        print()

    valid = [r for r in results if not r.error]

    # --- Metric 1: Binary detection P/R/F1 ---
    # All verses in the test set have repetitions (they were selected for that)
    # So: TP = v2 detected wrap, FN = v2 missed
    tp = sum(1 for r in valid if r.v2_n_wraps > 0)
    fn = sum(1 for r in valid if r.v2_n_wraps == 0)
    # FP requires non-repetition verses - we'll report separately
    total_valid = len(valid)
    recall = tp / total_valid if total_valid > 0 else 0
    # Precision requires FP data; for now report on rep-only set
    print(f"  1. Binary Detection (on repetition verses only):")
    print(f"     True positives:  {tp}/{total_valid} ({recall*100:.1f}% recall)")
    print(f"     False negatives: {fn}/{total_valid}")
    # Break down FN by num_reps
    if fn > 0:
        fn_by_reps = {}
        for r in valid:
            if r.v2_n_wraps == 0:
                fn_by_reps.setdefault(r.num_reps_gt, []).append(r)
        for k in sorted(fn_by_reps):
            examples = fn_by_reps[k][:3]
            ex_str = ", ".join(f"{e.reciter}/{e.verse_key}" for e in examples)
            print(f"       FN with num_reps={k}: {len(fn_by_reps[k])} "
                  f"(e.g. {ex_str})")
    print()

    # --- Metric 2: Wrap count accuracy ---
    tp_results = [r for r in valid if r.v2_n_wraps > 0]
    if tp_results:
        exact_match = sum(1 for r in tp_results if r.v2_n_wraps == r.num_reps_gt)
        mae = sum(abs(r.v2_n_wraps - r.num_reps_gt) for r in tp_results) / len(tp_results)
        print(f"  2. Wrap Count Accuracy (on {len(tp_results)} true positives):")
        print(f"     Exact match: {exact_match}/{len(tp_results)} ({exact_match/len(tp_results)*100:.1f}%)")
        print(f"     MAE: {mae:.2f}")
        # Distribution
        wrap_dist = {}
        for r in tp_results:
            key = (r.num_reps_gt, r.v2_n_wraps)
            wrap_dist[key] = wrap_dist.get(key, 0) + 1
        print(f"     (gt_reps, predicted_wraps) distribution:")
        for (gt, pred), count in sorted(wrap_dist.items()):
            print(f"       gt={gt}, pred={pred}: {count}")
    else:
        print(f"  2. Wrap Count Accuracy: N/A (no true positives)")
    print()

    # --- Metric 3: Confidence improvement ---
    print(f"  3. Confidence Improvement (v2 vs v1):")
    conf_deltas = [r.v2_confidence - r.v1_confidence for r in valid]
    if conf_deltas:
        mean_delta = sum(conf_deltas) / len(conf_deltas)
        sorted_deltas = sorted(conf_deltas)
        median_delta = sorted_deltas[len(sorted_deltas) // 2]
        min_delta = min(conf_deltas)
        max_delta = max(conf_deltas)
        improved = sum(1 for d in conf_deltas if d > 0.01)
        same = sum(1 for d in conf_deltas if abs(d) <= 0.01)
        worse = sum(1 for d in conf_deltas if d < -0.01)

        print(f"     Mean Δconfidence:   {mean_delta:+.4f}")
        print(f"     Median Δconfidence: {median_delta:+.4f}")
        print(f"     Min/Max:            {min_delta:+.4f} / {max_delta:+.4f}")
        print(f"     Improved (>0.01):   {improved}/{len(valid)}")
        print(f"     Same (±0.01):       {same}/{len(valid)}")
        print(f"     Worse (<-0.01):     {worse}/{len(valid)}")

        # Per-reciter breakdown
        for reciter in sorted(set(r.reciter for r in valid)):
            rv = [r for r in valid if r.reciter == reciter]
            rd = [r.v2_confidence - r.v1_confidence for r in rv]
            print(f"     {reciter}: mean={sum(rd)/len(rd):+.4f} "
                  f"v1_mean_conf={sum(r.v1_confidence for r in rv)/len(rv):.3f} "
                  f"v2_mean_conf={sum(r.v2_confidence for r in rv)/len(rv):.3f}")

        # Show top improvements
        top_improved = sorted(valid, key=lambda r: r.v2_confidence - r.v1_confidence, reverse=True)[:5]
        print(f"\n     Top 5 improvements:")
        for r in top_improved:
            delta = r.v2_confidence - r.v1_confidence
            print(f"       {r.reciter}/{r.verse_key}: "
                  f"v1={r.v1_confidence:.3f} → v2={r.v2_confidence:.3f} "
                  f"(Δ={delta:+.3f}, reps={r.num_reps_gt}, wraps={r.v2_n_wraps})")
    print()

    # --- Metric 4: False positive rate ---
    print(f"  4. False Positive Rate:")
    print(f"     N/A — requires real ASR on non-repetition verses (not in test set)")
    print()

    # --- Metric 5: Word range accuracy ---
    print(f"  5. Word Range Accuracy:")
    ious = []
    exact_boundaries = 0
    for r in valid:
        if r.v2_n_wraps > 0 and r.v2_word_from >= 0 and r.v2_word_to >= 0:
            # IoU of predicted [word_from, word_to] vs ground truth
            pred_set = set(range(r.v2_word_from, r.v2_word_to + 1))
            gt_set = set(range(r.gt_word_from, r.gt_word_to + 1))
            intersection = len(pred_set & gt_set)
            union = len(pred_set | gt_set)
            iou = intersection / union if union > 0 else 0
            ious.append(iou)
            if r.v2_word_from == r.gt_word_from and r.v2_word_to == r.gt_word_to:
                exact_boundaries += 1
    if ious:
        mean_iou = sum(ious) / len(ious)
        print(f"     Mean IoU: {mean_iou:.3f} (on {len(ious)} detected verses)")
        print(f"     Exact boundary match: {exact_boundaries}/{len(ious)} ({exact_boundaries/len(ious)*100:.1f}%)")
    else:
        print(f"     N/A (no true positive detections)")
    print()

    # --- Metric 6: Timing ---
    print(f"  6. Timing:")
    v1_times = [r.v1_time_ms for r in valid]
    v2_times = [r.v2_time_ms for r in valid]
    if v1_times:
        v1_mean = sum(v1_times) / len(v1_times)
        v2_mean = sum(v2_times) / len(v2_times)
        v1_sorted = sorted(v1_times)
        v2_sorted = sorted(v2_times)
        v1_p95 = v1_sorted[int(0.95 * len(v1_sorted))]
        v2_p95 = v2_sorted[int(0.95 * len(v2_sorted))]

        print(f"     Standard DP (v1): mean={v1_mean:.1f}ms, p95={v1_p95:.1f}ms")
        print(f"     Wraparound DP (v2): mean={v2_mean:.1f}ms, p95={v2_p95:.1f}ms")
        print(f"     Ratio (v2/v1): mean={v2_mean/v1_mean:.1f}x, p95={v2_p95/v1_p95:.1f}x")

        # By size bucket
        buckets = {"<50": [], "50-100": [], "100-200": [], "200+": []}
        for r in valid:
            if r.p_len < 50:
                buckets["<50"].append(r)
            elif r.p_len < 100:
                buckets["50-100"].append(r)
            elif r.p_len < 200:
                buckets["100-200"].append(r)
            else:
                buckets["200+"].append(r)

        print(f"     By P-length bucket:")
        for bucket, brs in buckets.items():
            if brs:
                b_v1 = sum(r.v1_time_ms for r in brs) / len(brs)
                b_v2 = sum(r.v2_time_ms for r in brs) / len(brs)
                print(f"       {bucket:>8}: n={len(brs):>4}, "
                      f"v1={b_v1:.1f}ms, v2={b_v2:.1f}ms, ratio={b_v2/b_v1:.1f}x")
    print()

    # --- Debug: worst cases ---
    if verbose:
        print(f"\n  Debug: Worst false negatives (missed repetitions, sorted by num_reps):")
        fn_list = sorted([r for r in valid if r.v2_n_wraps == 0],
                         key=lambda r: -r.num_reps_gt)
        for r in fn_list[:15]:
            print(f"    {r.reciter}/{r.verse_key}: reps={r.num_reps_gt} "
                  f"v1_conf={r.v1_confidence:.3f} v2_conf={r.v2_confidence:.3f} "
                  f"P={r.p_len} R={r.r_len} "
                  f"v1_range=[{r.v1_word_from},{r.v1_word_to}] "
                  f"gt_range=[{r.gt_word_from},{r.gt_word_to}]")

        print(f"\n  Debug: Cases where v2 is worse than v1:")
        worse_list = sorted([r for r in valid if r.v2_confidence < r.v1_confidence - 0.01],
                            key=lambda r: r.v2_confidence - r.v1_confidence)
        for r in worse_list[:10]:
            delta = r.v2_confidence - r.v1_confidence
            print(f"    {r.reciter}/{r.verse_key}: "
                  f"v1={r.v1_confidence:.3f} v2={r.v2_confidence:.3f} Δ={delta:+.3f} "
                  f"wraps={r.v2_n_wraps} reps={r.num_reps_gt} P={r.p_len} R={r.r_len}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Test wraparound DP (v2)")
    parser.add_argument("--model", default="base", choices=["base", "large"],
                        help="ASR model variant for test data")
    parser.add_argument("--wrap-penalty", type=float, default=WRAP_PENALTY,
                        help=f"Wrap penalty (default: {WRAP_PENALTY})")
    parser.add_argument("--max-wraps", type=int, default=MAX_WRAPS,
                        help=f"Max wraps (default: {MAX_WRAPS})")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose per-verse output")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit number of verses to process (0=all)")
    parser.add_argument("--scoring", default="subtract",
                        choices=["subtract", "no_subtract", "additive"],
                        help="Scoring mode for wrap penalty")
    parser.add_argument("--wrap-score-cost", type=float, default=0.01,
                        help="Per-wrap score penalty (additive mode only)")
    parser.add_argument("--dynamic-k", action="store_true",
                        help="Compute max_wraps per-verse from excess phonemes "
                             "(excess<5→k=1, <10→k=2, <15→k=3, <20→k=4, ≥20→k=max_wraps, ≤0→skip)")
    args = parser.parse_args()

    evaluate(
        model=args.model,
        wrap_penalty=args.wrap_penalty,
        max_wraps=args.max_wraps,
        verbose=args.verbose,
        limit=args.limit,
        scoring_mode=args.scoring,
        wrap_score_cost=args.wrap_score_cost,
        dynamic_k=args.dynamic_k,
    )


if __name__ == "__main__":
    main()
