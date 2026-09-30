from .base import *  # noqa: F401,F403

DEBUG = True
# Sin "0.0.0.0": Bandit lo marca (B104) y no hace falta, se accede por localhost.
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
