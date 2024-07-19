import requests

from json import dumps
from pathlib import Path
from time import sleep

from application.requests_factory import SpotifyRequestFactory
from application.authentication.refresh_token import refresh_spotify_auth

BASE_DIR = Path(__file__).parent.parent
SPOTIFY_API_TOKEN_FILE = BASE_DIR / "secrets" / "spotify_api_token.secret"
MAX_HTTP_500_ERROR_RETRIES_PER_REQUEST = 5

with open(SPOTIFY_API_TOKEN_FILE, "r") as f:
    SPOTIFY_API_TOKEN = f.read()


def make_spotify_api_call(msg):

    request_url = msg["request_url"]

    http_500_error_count = 0

    while True:
        print(f'GET: {request_url} ...')

        try:
            r = requests.get(
                request_url,
                headers={"Authorization": f'Bearer {SPOTIFY_API_TOKEN}'}
            )
        except requests.exceptions.ConnectionError:  # Connection reset by peer
            print("Connection reset by peer. Retrying...")
            sleep(5)
            continue

        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if r.status_code == 500:
                http_500_error_count += 1

                if http_500_error_count >= MAX_HTTP_500_ERROR_RETRIES_PER_REQUEST:
                    raise requests.exceptions.HTTPError(f'HTTP 500 errors for {request_url} have exceeded max retry '
                                                        f'count of {MAX_HTTP_500_ERROR_RETRIES_PER_REQUEST}')
                else:
                    print(f'HTTP 500 #{http_500_error_count} on request to {request_url}. '
                          f'Waiting 30 seconds to retry...')
                    sleep(30)
                    continue

            elif r.status_code == 429:
                # TODO: the correct behavior here might be to simply try again
                raise requests.exceptions.HTTPError(f'Rate limit exceeded!')

            elif r.status_code == 401:
                print(f'HTTP 401: Access token expired. Requesting new token...')
                refresh_spotify_auth()
                print(f'Success: new access token received.')
                continue

            else:
                raise e

        else:
            response = r.json()

            if response.get("next") is not None:
                next_request_url = response["next"]
                SpotifyRequestFactory.request_url(next_request_url)
            else:
                print(f'Reached the end of pagination.')

            # TODO: Write to queue "Spotify API responses",
            #       so that we can start the stream processing to ingest to a database and make more API calls
            return dumps(response)


def entrypoint():
    msg = None  # TODO: Read from queue "Spotify API requests"
    make_spotify_api_call(msg)
