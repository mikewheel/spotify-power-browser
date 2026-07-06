"""Playlist generators (plan 08 T4): each one is a self-contained Cypher +
params + an order-significance flag, producing the ordered target track-id
list the sync module realizes on Spotify.

v1 generators:
  adjacent-discoveries        plan 01's ranked collab frontier (top 50,
                              popularity-capped), one representative track per
                              candidate artist — order-significant
  exploration-queue <artist>  albums by <artist> with zero liked tracks,
                              flattened to track ids in release-date order —
                              order-significant

Both degrade gracefully when Artist.popularity is null (pre-backfill graphs):
unknown -> included, flagged through the popularity_unknown column; the CLI
logs how many artists that affected.

Future generators as their plans land (time-capsule <year> — plan 09,
blend <user_a> <user_b> — plan 06's bridge query already exists at
graph_database/queries/overlap/bridge_playlist.cypher) register in
build_generator below.

Multiplayer (plan 06): every generator takes user_id (CLI --user). None keeps
the legacy any-user behavior AND the legacy identity_params hash, so managed
playlists created before multiplayer keep resolving; a user scope forks a
per-user managed playlist (see _user_identity).
"""
from dataclasses import dataclass, field

from application.config import APPLICATION_DIR
from application.loggers import get_logger

logger = get_logger(__name__)

PLAYLIST_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries" / "playlists"

GENERATOR_NAMES = ("adjacent-discoveries", "exploration-queue")

# adjacent-discoveries tuning defaults: popularity <= 40 keeps the frontier
# obscure (Spotify popularity is 0-100, log-scaled toward the head); two
# independent collaborator bridges filters one-off feature noise. Tuning knobs
# only — they do NOT fork a new managed playlist (see identity_params).
DEFAULT_MAX_POPULARITY = 40
DEFAULT_MIN_BRIDGES = 2


def _load_query(name):
    with open(PLAYLIST_QUERIES_DIR / f"{name}.cypher", "r") as f:
        return f.read()


ADJACENT_DISCOVERIES_TRACKS_QUERY = _load_query("adjacent_discoveries_tracks")
EXPLORATION_QUEUE_TRACKS_QUERY = _load_query("exploration_queue_tracks")


@dataclass(frozen=True)
class GeneratorSpec:
    """Everything sync needs from a generator: identity (key +
    identity_params name ONE managed playlist), the Cypher + params that
    produce the target rows, and whether the row order is significant."""
    key: str
    display_name: str
    playlist_name: str
    identity_params: dict = field(default_factory=dict)
    order_significant: bool = True
    query: str = ""
    params: dict = field(default_factory=dict)


def _user_identity(user_id):
    """Identity-params fragment for a user scope (plan 06). None (legacy /
    any-user) contributes NOTHING so pre-multiplayer managed playlists keep
    their params_hash — a --user run forks a per-user playlist instead."""
    return {} if user_id is None else {"user_id": user_id}


def build_adjacent_discoveries(max_popularity=DEFAULT_MAX_POPULARITY,
                               min_bridges=DEFAULT_MIN_BRIDGES,
                               user_id=None):
    suffix = f" ({user_id})" if user_id else ""
    return GeneratorSpec(
        key="adjacent-discoveries",
        display_name="adjacent-discoveries" + (f" --user {user_id}" if user_id else ""),
        playlist_name=f"[SPB] Adjacent Discoveries{suffix}",
        # tuning knobs update THE discoveries playlist, not fork one — but a
        # user scope DOES fork one (each user gets their own discoveries)
        identity_params=_user_identity(user_id),
        order_significant=True,  # ranked frontier: bridges desc, obscurity asc
        query=ADJACENT_DISCOVERIES_TRACKS_QUERY,
        params={"max_popularity": int(max_popularity), "min_bridges": int(min_bridges),
                "user_id": user_id},
    )


def build_exploration_queue(artist_name, user_id=None):
    artist_name = (artist_name or "").strip()
    if not artist_name:
        raise ValueError("exploration-queue requires an artist name argument")
    suffix = f" ({user_id})" if user_id else ""
    return GeneratorSpec(
        key="exploration-queue",
        display_name=f"exploration-queue {artist_name}"
                     + (f" --user {user_id}" if user_id else ""),
        playlist_name=f"[SPB] Exploration Queue - {artist_name}{suffix}",
        # one playlist per (artist, user scope)
        identity_params={"artist_name": artist_name.lower(), **_user_identity(user_id)},
        order_significant=True,  # a queue: oldest album first, play through
        query=EXPLORATION_QUEUE_TRACKS_QUERY,
        params={"artist_name": artist_name, "user_id": user_id},
    )


def build_generator(name, generator_args=(),
                    max_popularity=DEFAULT_MAX_POPULARITY,
                    min_bridges=DEFAULT_MIN_BRIDGES,
                    user_id=None):
    """CLI dispatcher: generator name + positional args -> GeneratorSpec."""
    if name == "adjacent-discoveries":
        if generator_args:
            raise ValueError("adjacent-discoveries takes no positional arguments "
                             "(use --max-popularity / --min-bridges)")
        return build_adjacent_discoveries(max_popularity=max_popularity,
                                          min_bridges=min_bridges,
                                          user_id=user_id)
    if name == "exploration-queue":
        return build_exploration_queue(" ".join(generator_args), user_id=user_id)
    raise ValueError(f"unknown generator {name!r}; expected one of {GENERATOR_NAMES}")


def run_generator(driver, spec, database="neo4j"):
    """Execute the spec's Cypher. Returns (target_track_ids, unknown_popularity):
    the ordered, deduped track ids plus how many distinct artists in the result
    have no popularity value (unknown -> included, flagged)."""
    records, _, _ = driver.execute_query(spec.query, database_=database, **spec.params)
    rows = [dict(record) for record in records]

    seen = set()
    track_ids = [
        row["track_id"] for row in rows
        if row["track_id"] is not None
        and not (row["track_id"] in seen or seen.add(row["track_id"]))
    ]
    unknown_popularity = len({
        row.get("artist_name") for row in rows if row.get("popularity_unknown")
    })

    logger.info(
        f"Generator {spec.display_name!r}: {len(track_ids)} target track(s), "
        f"{unknown_popularity} artist(s) with unknown popularity."
    )
    return track_ids, unknown_popularity
