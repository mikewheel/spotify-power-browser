"""Namespaced per-user token store (plan 06 T3).

Layout:
    secrets/spotify_api_token.secret            legacy single-user files -- kept,
    secrets/spotify_refresh_token.secret        see "primary user" below
    secrets/users/<spotify_user_id>/spotify_api_token.secret
    secrets/users/<spotify_user_id>/spotify_refresh_token.secret
    secrets/users/.primary_user                 the primary user's id (marker file)

PRIMARY-USER SEMANTICS: the first Spotify account to authorize through the
OAuth web service becomes the "primary" user. The primary's tokens are written
to BOTH their namespaced files and the legacy secrets/spotify_*.secret files,
and every refresh keeps the two in sync. This is load-bearing, not a
convenience: the docker compose auth-gate healthcheck tests
`-s /src/secrets/spotify_api_token.secret`, and every legacy code path
(user_id=None throughout the pipeline) reads the legacy files. Deleting the
legacy files or the marker breaks `docker compose up`'s wait-for-auth gate.

user_id=None everywhere in this module means "the legacy single-user files" —
exactly the pre-multiplayer behavior.
"""
import re

from application.config import SECRETS_DIR
from application.loggers import get_logger

logger = get_logger(__name__)

USERS_DIR = SECRETS_DIR / "users"
PRIMARY_USER_FILE = USERS_DIR / ".primary_user"

LEGACY_API_TOKEN_FILE = SECRETS_DIR / "spotify_api_token.secret"
LEGACY_REFRESH_TOKEN_FILE = SECRETS_DIR / "spotify_refresh_token.secret"

API_TOKEN_FILENAME = "spotify_api_token.secret"
REFRESH_TOKEN_FILENAME = "spotify_refresh_token.secret"

# Spotify user ids are URL-safe, but they come back from a remote API and are
# used as a filesystem path segment — validate defensively so a hostile value
# can't traverse out of secrets/users/.
_VALID_USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class InvalidUserIdError(ValueError):
    """A user id unsafe to use as a path segment (or empty)."""


def validate_user_id(user_id):
    """Return user_id if it is safe as a directory name, else raise."""
    if not isinstance(user_id, str) or not _VALID_USER_ID.match(user_id) or ".." in user_id:
        raise InvalidUserIdError(f"Refusing unsafe Spotify user id: {user_id!r}")
    return user_id


def user_dir(user_id):
    return USERS_DIR / validate_user_id(user_id)


def api_token_file(user_id=None):
    """The access-token path for a user (None -> the legacy file)."""
    if user_id is None:
        return LEGACY_API_TOKEN_FILE
    return user_dir(user_id) / API_TOKEN_FILENAME


def refresh_token_file(user_id=None):
    """The refresh-token path for a user (None -> the legacy file)."""
    if user_id is None:
        return LEGACY_REFRESH_TOKEN_FILE
    return user_dir(user_id) / REFRESH_TOKEN_FILENAME


def has_user(user_id):
    """True when a namespaced access token exists for this user id."""
    try:
        return api_token_file(user_id).is_file()
    except InvalidUserIdError:
        return False


def list_user_ids():
    """All authorized user ids (sorted), from the secrets/users/ directory."""
    if not USERS_DIR.is_dir():
        return []
    return sorted(
        entry.name for entry in USERS_DIR.iterdir()
        if entry.is_dir() and (entry / API_TOKEN_FILENAME).is_file()
    )


def get_primary_user_id():
    """The recorded primary user's id, or None (pure-legacy installs)."""
    if not PRIMARY_USER_FILE.is_file():
        return None
    primary = PRIMARY_USER_FILE.read_text().strip()
    return primary or None


def set_primary_user_id(user_id):
    """Record the primary user (first authorized account). Overwrites only
    when unset — the primary is sticky by design (compose gate + legacy
    consumers all key off it)."""
    existing = get_primary_user_id()
    if existing is not None:
        if existing != user_id:
            logger.info(
                f"Primary user already recorded ({existing}); NOT replacing with {user_id}."
            )
        return existing
    PRIMARY_USER_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRIMARY_USER_FILE.write_text(validate_user_id(user_id))
    logger.info(f"Recorded primary user: {user_id}")
    return user_id


def is_primary_user(user_id):
    return user_id is not None and user_id == get_primary_user_id()


def read_api_token(user_id=None):
    """Read the access token for a user (None -> legacy file). Raises
    FileNotFoundError like the legacy open() did."""
    return api_token_file(user_id).read_text()


def read_refresh_token(user_id=None):
    return refresh_token_file(user_id).read_text()


def save_tokens(user_id, access_token, refresh_token=None, claim_primary=False):
    """Persist tokens for a user.

    - user_id=None: legacy files only (pre-multiplayer behavior).
    - user_id given: the namespaced files; AND, when this user IS the
      primary, mirror to the legacy files so the compose healthcheck gate
      and legacy consumers stay live.
    - claim_primary=True: additionally claim the primary slot when none is
      recorded. ONLY the OAuth callback (a deliberate human login) passes
      this — background refresh saves must never claim an empty slot, or an
      arbitrary user's hourly 401 refresh would silently become the sticky
      primary during the runbook's §4 primary-deletion window ("the next
      LOGIN becomes the new primary").
    """
    if user_id is None:
        LEGACY_API_TOKEN_FILE.write_text(access_token)
        if refresh_token is not None:
            LEGACY_REFRESH_TOKEN_FILE.write_text(refresh_token)
        return None

    directory = user_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / API_TOKEN_FILENAME).write_text(access_token)
    if refresh_token is not None:
        (directory / REFRESH_TOKEN_FILENAME).write_text(refresh_token)

    if claim_primary:
        primary = set_primary_user_id(user_id)  # no-op (sticky) unless unset
    else:
        primary = get_primary_user_id()
    if primary == user_id:
        LEGACY_API_TOKEN_FILE.write_text(access_token)
        if refresh_token is not None:
            LEGACY_REFRESH_TOKEN_FILE.write_text(refresh_token)
        logger.debug(f"Mirrored primary user {user_id}'s tokens to the legacy files.")
    return primary
