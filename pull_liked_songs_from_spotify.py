from datetime import date
from json import dump
from pathlib import Path
from pprint import pprint
from time import sleep

import requests

BASE_DIR = Path(__file__).parent
SPOTIFY_API_TOKEN_FILE = BASE_DIR / "secrets" / "spotify_api_token.secret"
LIKED_SONGS_OUTPUT_FILE = BASE_DIR / "data" / f"my_liked_songs_on_spotify_{date.today().strftime('%Y-%m-%d')}.json"
SPOTIFY_LIKED_SONGS_URL = "https://api.spotify.com/v1/me/tracks"

with open(SPOTIFY_API_TOKEN_FILE, "r") as f:
    SPOTIFY_API_TOKEN = f.read()

my_liked_songs = []
next_request_url = SPOTIFY_LIKED_SONGS_URL

while True:
    r = requests.get(next_request_url,
                     headers={"Authorization": f'Bearer {SPOTIFY_API_TOKEN}'})
    r.raise_for_status()

    response_contents = r.json()

    my_liked_songs += response_contents["items"]
    print(f'{len(my_liked_songs)} out of {response_contents["total"]}')

    if response_contents["next"] is None:
        print(f'Reached the end of pagination.')
        break
    else:
        next_request_url = response_contents["next"]
        sleep(1)

with open(LIKED_SONGS_OUTPUT_FILE, "w") as f:
    dump(my_liked_songs, f)

print(len(my_liked_songs))
pprint(my_liked_songs[0])
