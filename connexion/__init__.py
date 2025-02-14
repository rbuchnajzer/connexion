"""
Connexion is a framework that automagically handles HTTP requests based on OpenAPI Specification
(formerly known as Swagger Spec) of your API described in YAML format. Connexion allows you to
write an OpenAPI specification, then maps the endpoints to your Python functions; this makes it
unique, as many tools generate the specification based on your Python code. You can describe your
REST API in as much detail as you want; then Connexion guarantees that it will work as you
specified.
"""

import werkzeug.exceptions as exceptions  # NOQA

from .apis import AbstractAPI  # NOQA
from .apps import AbstractApp  # NOQA
from .apps.async_app import AsyncApp
from .datastructures import NoContent  # NOQA
from .exceptions import ProblemException  # NOQA
from .problem import problem  # NOQA
from .resolver import Resolution, Resolver, RestyResolver  # NOQA
from .utils import not_installed_error  # NOQA

try:
    from flask import request  # NOQA

    from connexion.apis.flask_api import FlaskApi  # NOQA
    from connexion.apps.flask_app import FlaskApp
except ImportError as e:  # pragma: no cover
    _flask_not_installed_error = not_installed_error(e)
    FlaskApi = _flask_not_installed_error  # type: ignore
    FlaskApp = _flask_not_installed_error  # type: ignore

from connexion.apps.async_app import AsyncApi, AsyncApp, ConnexionMiddleware

App = FlaskApp
Api = FlaskApi

# This version is replaced during release process.
__version__ = "3.0.dev0"
