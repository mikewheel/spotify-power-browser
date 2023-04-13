from datetime import date
from json import dump
from pathlib import Path
from pprint import pprint
from time import sleep

import requests

BASE_DIR = Path(__file__).parent
SPOTIFY_API_TOKEN_FILE = BASE_DIR / "secrets" / "spotify_api_token.secret"
FOLLOWED_PLAYLISTS_OUTPUT_FILE = BASE_DIR / "data" / f"my_followed_playlists_on_spotify_{date.today().strftime('%Y-%m-%d')}.json"
SPOTIFY_FOLLOWED_PLAYLISTS_URL = "https://api.spotify.com/v1/me/playlists"

with open(SPOTIFY_API_TOKEN_FILE, "r") as f:
    SPOTIFY_API_TOKEN = f.read()

my_followed_playlists = []
next_request_url = SPOTIFY_FOLLOWED_PLAYLISTS_URL

while True:
    r = requests.get(next_request_url,
                     headers={"Authorization": f'Bearer {SPOTIFY_API_TOKEN}'})
    r.raise_for_status()

    response_contents = r.json()

    my_followed_playlists += response_contents["items"]
    print(f'{len(my_followed_playlists)} out of {response_contents["total"]}')

    if response_contents["next"] is None:
        print(f'Reached the end of pagination.')
        break
    else:
        next_request_url = response_contents["next"]
        sleep(1)

with open(FOLLOWED_PLAYLISTS_OUTPUT_FILE, "w") as f:
    dump(my_followed_playlists, f)

print(len(my_followed_playlists))
pprint(my_followed_playlists[0])
