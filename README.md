# Spotify Power Browser

For tastemakers and audiophiles of all kinds.

## How to Run

This assumes that you have registered yourself a personal Spotify app with which to make API calls. This app should have
a client ID and a corresponding client secret, which can be stored in `secrets/spotify_client_id.secret` and 
`secrets/spotify_client_secret.secret`.

1. Authenticate and Authorize with Spotify using the Spotify authentication service.
2. Start a RabbitMQ instance on your local machine. (I recommend their Docker image)
3. Start the API call engine.
4. Start the response handlers – at least one process per response type that you want handled.
5. Kick off the search with a call to the requests factory module.
