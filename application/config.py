"""Lightweight config to direct the scraping process."""

###
# Which searches to kick off
###
CRAWL_LIKED_SONGS = True
CRAWL_FOLLOWED_PLAYLISTS = False
CRAWL_FOLLOWED_ARTISTS = False

###
# Which response topics are implemented and should be activated for this execution of the application
###
WRITE_RESPONSES_TO_DISK = True
WRITE_RESPONSES_TO_NEO4J = True
FOLLOW_LINKS_IN_RESPONSES = True
WRITE_RESPONSES_TO_SQLITE = False

# How many nearest-neighbors the application should pull before it stops searching
DEPTH_OF_SEARCH = 1
