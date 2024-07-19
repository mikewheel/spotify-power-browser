# Spotify Power Browser

For tastemakers and audiophiles of all kinds.

## How to Run

This assumes that you have registered yourself a personal Spotify app with which to make API calls. This app should have
a client ID and a corresponding client secret, which can be stored in `secrets/spotify_client_id.secret` and 
`secrets/spotify_client_secret.secret`.
### `spotify_auth_service.py`: Serves a local web app that requests API authorization from Spotify
  - First, navigate to the page `http://localhost:8000/login` in your web browser. This will redirect you to Spotify's
    login page. Authenticate with Spotify, and then authorize the app to access your music data.
  - Then, Spotify will redirect you to the page `http://localhost:8000/callback`. Here, the web server accepts the 
  authorization code from Spotify's request body and writes it to disk in the `secrets/` directory. It then makes its 
  own call to Spotify to exchange the authorization code for an API access token and a refresh token, also stored in 
  `secrets/`.
  - Finally, it returns a web page that displays all the credentials it has received. Once you land on the callback 
  page, you can inspect these values by hand, or you can simply shut down the web server.

### `pull_liked_songs_from_spotify.py`: Fetches data from Spotify for the contents of the "Liked Songs" playlist
  - This module hits `https://api.spotify.com/v1/me/tracks`: it makes paginated requests for 20 songs at a time, each
    spaced three seconds apart to avoid hitting the rate limit. It also makes calls to refresh its API token as 
    needed.
  - It then takes the response contents and appends them to a list. Once all the songs have been fetched and there
  are no more requests to page through, it takes everything and writes it to disk at 
  `data/my_liked_songs_on_spotify_YYYY-MM-DD.json`

### `convert_liked_songs_to_excel.py`: Transforms the "Liked Songs" playlist data into a tabular format
  - Reads in the JSON file to get the list of songs.
  - For each song, digs through the nested data structure to pull out the attributes that we want.
  - Collects the flattened data into a Pandas Dataframe and writes them out to an Excel file.

### `pull_followed_playlists_from_spotify.py`
  - Does pretty much the same thing as the "Liked Songs" script, but instead it's hitting 
  `https://api.spotify.com/v1/me/playlists`.
  - There are some minor differences: the error handling is better in the other script and the rate limiting pause is 
  one second instead of three.
