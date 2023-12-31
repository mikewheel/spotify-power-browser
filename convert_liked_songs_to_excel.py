import pandas
from pathlib import Path
from json import load

BASE_DIR = Path(__file__).parent
LIKED_SONGS_JSON_FILE = BASE_DIR / "data" / f"my_liked_songs_on_spotify_2023-12-30.json"
LIKED_SONGS_EXCEL_FILE = BASE_DIR / "data" / f"my_liked_songs_on_spotify_2023-12-30.xlsx"

with open(LIKED_SONGS_JSON_FILE, 'r') as f:
    liked_songs_data = load(f)

rows_list = []

for song in liked_songs_data:
    try:
        # Own data
        song_name = song["track"]["name"]
        song_external_url_spotify = song["track"]["external_urls"]["spotify"]
        song_id = song["track"]["id"]
        song_uri = song["track"]["uri"]
        song_is_explicit = song["track"]["explicit"]
        song_popularity = song["track"]["popularity"]

        # Album data
        song_album_name = song["track"]["album"]["name"]
        song_album_external_url_spotify = song["track"]["album"]["external_urls"]["spotify"]
        song_album_id = song["track"]["album"]["id"]
        song_album_uri = song["track"]["album"]["uri"]

        # First artist data
        song_first_artist_name = song["track"]["artists"][0]["name"]
        song_first_artist_external_url_spotify = song["track"]["artists"][0]["external_urls"]["spotify"]
        song_first_artist_id = song["track"]["artists"][0]["id"]
        song_first_artist_uri = song["track"]["artists"][0]["uri"]

    except KeyError as e:
        raise KeyError(f'{str(e)}\n\n{song}')

    else:
        rows_list.append({
            "song_name": song_name,
            "song_first_artist_name": song_first_artist_name,
            "song_album_name": song_album_name,
            "song_is_explicit": song_is_explicit,
            "song_popularity": song_popularity,

            "song_external_url_spotify": song_external_url_spotify,
            "song_id": song_id,
            "song_uri": song_uri,
            "song_album_external_url_spotify": song_album_external_url_spotify,
            "song_album_id": song_album_id,
            "song_album_uri": song_album_uri,
            "song_first_artist_external_url_spotify": song_first_artist_external_url_spotify,
            "song_first_artist_id": song_first_artist_id,
            "song_first_artist_uri": song_first_artist_uri
        })

df = pandas.DataFrame(rows_list)
df.to_excel(LIKED_SONGS_EXCEL_FILE)
