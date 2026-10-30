from .base import *  # noqa: F401,F403

DEBUG = True
# Sin "0.0.0.0": Bandit lo marca (B104) y no hace falta, se accede por localhost.
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
# La página de error de DEBUG usa scripts en línea. En local la CSP solo reporta
# las violaciones en la consola del navegador; test y prod la aplican.
CONTENT_SECURITY_POLICY_REPORT_ONLY = True
