# Putting __init__.py in a directory, makes it a package.
# https://qiita.com/miyuki_samitani/items/a7758ba44bf00ef30f26

from .booking import booking_router
from .authentication import authentication_router
from .user import user_router
from .timeline import timeline_router
