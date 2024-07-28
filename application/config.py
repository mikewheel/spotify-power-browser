"""Lightweight config to direct the scraping process."""

###
# Which response topics are implemented and should be activated for this execution of the application
###
WRITE_RESPONSES_TO_DISK = True
WRITE_RESPONSES_TO_SQLITE = False
WRITE_RESPONSES_TO_NEO4J = False
FOLLOW_LINKS_IN_RESPONSES = True

# How many nearest-neighbors the application should pull before it stops searching
DEGREE_OF_LINKS_TO_FOLLOW = 1
