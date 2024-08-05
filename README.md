# Spotify Power Browser

For tastemakers and audiophiles of all kinds.

## How to Run

This assumes that you have registered yourself a personal Spotify app with which to make API calls. This app should have
a client ID and a corresponding client secret, which can be stored in `secrets/spotify_client_id.secret` and 
`secrets/spotify_client_secret.secret`. It also assumes that you have set `secrets/neo4j_credentials.yaml` to be in
agreement with the Docker Compose file.

1. Authenticate and Authorize with Spotify using the Spotify authentication service: 
   `python3 application/spotify_authentication/api_authorization_web_service.py`
2. Start up the rest of the application components: `docker compose up`
