"""Human review report for a mastering run (plan 03 T6).

Renders the clusters formed this run as markdown, sorted by descending
ambiguity — heuristic-only clusters with a duration spread over one second
first, since those are exactly where the heuristics are most likely wrong.
The loop: skim data/mastering_review.md, add overrides, rerun.
"""
from datetime import datetime, timezone

from application.config import DATA_DIR
from application.loggers import get_logger

logger = get_logger(__name__)

DEFAULT_REPORT_PATH = DATA_DIR / "mastering_review.md"
AMBIGUOUS_SPREAD_MS = 1000


def _ambiguity_key(cluster):
    """Sort key: most-review-worthy first."""
    return (
        # 1. heuristic-only AND spread > 1s (plan-specified top of the report)
        not (cluster.heuristic_only and cluster.duration_spread_ms > AMBIGUOUS_SPREAD_MS),
        # 2. any heuristic-only cluster
        not cluster.heuristic_only,
        # 3. wider duration spreads before tighter ones
        -cluster.duration_spread_ms,
        # 4. stable tie-break
        cluster.song_id,
    )


def _cluster_section(cluster):
    methods = sorted({m.method for m in cluster.members})
    flags = []
    if cluster.split_derived:
        flags.append("manual split")
    if cluster.heuristic_only:
        flags.append("heuristic-only")
    if cluster.duration_spread_ms > AMBIGUOUS_SPREAD_MS:
        flags.append(f"duration spread {cluster.duration_spread_ms} ms")
    flag_text = f" — **{', '.join(flags)}**" if flags else ""

    lines = [
        f"### `{cluster.song_id}` — {cluster.title}{flag_text}",
        "",
        f"{len(cluster.members)} versions · methods: {', '.join(methods)}",
        "",
        "| track id | title | kind | method | confidence | duration (ms) | isrc |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in cluster.members:
        lines.append(
            f"| `{m.track_id}` | {m.name or ''} | {m.kind} | {m.method} "
            f"| {m.confidence:.2f} | {m.duration_ms if m.duration_ms is not None else '?'} "
            f"| {m.isrc or '—'} |"
        )
    lines.append("")
    return lines


def render_review_report(result, now=None):
    """Render a MasteringResult to markdown (ambiguity-sorted)."""
    now = now or datetime.now(timezone.utc)
    multi = sorted(result.multi_member_clusters, key=_ambiguity_key)
    singletons = len(result.clusters) - len(multi)
    review_first = [
        c for c in multi
        if c.heuristic_only and c.duration_spread_ms > AMBIGUOUS_SPREAD_MS
    ]

    lines = [
        "# Mastering review",
        "",
        f"_Generated {now.strftime('%Y-%m-%d %H:%M:%S %Z')} by "
        f"`python -m application.mastering.run`._",
        "",
        f"- **{len(result.clusters)}** Songs "
        f"({len(multi)} with multiple versions, {singletons} singletons)",
        f"- **{sum(len(c.members) for c in result.clusters)}** Tracks assigned",
        f"- **{len(result.remix_edges)}** REMIX_OF edges",
        f"- **{len(review_first)}** clusters flagged for review "
        f"(heuristic-only, duration spread > {AMBIGUOUS_SPREAD_MS} ms)",
        "",
        "Wrong merge? Wrong split? Add the track ids to the overrides file",
        "(see `application/mastering/overrides.example.yaml`) and rerun — ",
        "overrides always win.",
        "",
    ]

    if result.warnings:
        lines += ["## Warnings", ""]
        lines += [f"- {w}" for w in result.warnings]
        lines.append("")

    lines += ["## Clusters (most ambiguous first)", ""]
    if multi:
        for cluster in multi:
            lines += _cluster_section(cluster)
    else:
        lines += ["_No multi-version clusters were formed this run._", ""]

    # Split-derived Songs are usually singletons (which get no cluster section
    # of their own), so list every one here — the reviewer can confirm the
    # override actually took effect (and spot the ':split:'-suffixed ids the
    # shared-ISRC case produces).
    split_clusters = [c for c in result.clusters if c.split_derived]
    if split_clusters:
        lines += ["## Manual splits", ""]
        lines += [
            f"- `{c.song_id}` — {c.title} "
            f"({', '.join(f'`{m.track_id}`' for m in c.members)})"
            for c in split_clusters
        ]
        lines.append("")

    if result.remix_edges:
        lines += ["## Remix edges", ""]
        lines += [
            f"- `{e.remix_song_id}` -REMIX_OF-> `{e.parent_song_id}` "
            f"(confidence {e.confidence:.2f})"
            for e in result.remix_edges
        ]
        lines.append("")

    return "\n".join(lines)


def write_review_report(result, output_path=None):
    """Render and write the report; returns the path written."""
    output_path = output_path or DEFAULT_REPORT_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(render_review_report(result))
    logger.info(f"Wrote mastering review report to {output_path}")
    return output_path
