from datetime import date
from json import dump
from pathlib import Path
from pprint import pprint
from time import sleep

import requests

from spotify_auth_refresh_token import refresh_spotify_auth

BASE_DIR = Path(__file__).parent
SPOTIFY_API_TOKEN_FILE = BASE_DIR / "secrets" / "spotify_api_token.secret"
LIKED_SONGS_OUTPUT_FILE = BASE_DIR / "data" / f"my_liked_songs_on_spotify_{date.today().strftime('%Y-%m-%d')}.json"
SPOTIFY_LIKED_SONGS_URL = "https://api.spotify.com/v1/me/tracks"

with open(SPOTIFY_API_TOKEN_FILE, "r") as f:
    SPOTIFY_API_TOKEN = f.read()

my_liked_songs = []
next_request_url = SPOTIFY_LIKED_SONGS_URL
http_500_error_count = 0
MAX_HTTP_500_ERROR_RETRIES_PER_REQUEST = 5

while True:
    print(f'GET: {next_request_url} ...')
    r = requests.get(next_request_url,
                     headers={"Authorization": f'Bearer {SPOTIFY_API_TOKEN}'})

    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 500:
            http_500_error_count += 1

            if http_500_error_count >= MAX_HTTP_500_ERROR_RETRIES_PER_REQUEST:
                raise requests.exceptions.HTTPError(f'HTTP 500 errors for {next_request_url} have exceeded max retry '
                                                    f'count of {MAX_HTTP_500_ERROR_RETRIES_PER_REQUEST}')
            else:
                print(f'HTTP 500 #{http_500_error_count} on request to {next_request_url}. '
                      f'Waiting 30 seconds to retry...')
                sleep(30)
                continue

        elif r.status_code == 429:
            raise requests.exceptions.HTTPError(f'Rate limit exceeded!')

        elif r.status_code == 401:
            print(f'HTTP 401: Access token expired. Requesting new token...')
            refresh_spotify_auth()
            print(f'Success: new access token received.')
            continue

        else:
            raise e
    else:
        http_500_error_count = 0

    response_contents = r.json()

    my_liked_songs += response_contents["items"]
    print(f'{len(my_liked_songs)} songs out of {response_contents["total"]}')

    if response_contents["next"] is None:
        print(f'Reached the end of pagination.')
        break
    else:
        next_request_url = response_contents["next"]
        sleep(3)

with open(LIKED_SONGS_OUTPUT_FILE, "w") as f:
    dump(my_liked_songs, f)
