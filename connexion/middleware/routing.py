import functools
import pathlib
import re
import typing as t
from contextvars import ContextVar

import starlette.convertors
from starlette.routing import Router
from starlette.types import ASGIApp, Receive, Scope, Send

from connexion.apis import AbstractRoutingAPI
from connexion.middleware.abstract import ROUTING_CONTEXT, AppMiddleware
from connexion.operations import AbstractOperation
from connexion.resolver import Resolver

_scope: ContextVar[dict] = ContextVar("SCOPE")


class RoutingOperation:
    def __init__(self, operation_id: t.Optional[str], next_app: ASGIApp) -> None:
        self.operation_id = operation_id
        self.next_app = next_app

    @classmethod
    def from_operation(cls, operation: AbstractOperation, next_app: ASGIApp):
        return cls(operation.operation_id, next_app)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Attach operation to scope and pass it to the next app"""
        original_scope = _scope.get()
        # Pass resolved path params along
        original_scope.setdefault("path_params", {}).update(
            scope.get("path_params", {})
        )

        api_base_path = scope.get("root_path", "")[
            len(original_scope.get("root_path", "")) :
        ]

        extensions = original_scope.setdefault("extensions", {})
        connexion_routing = extensions.setdefault(ROUTING_CONTEXT, {})
        connexion_routing.update(
            {"api_base_path": api_base_path, "operation_id": self.operation_id}
        )
        await self.next_app(original_scope, receive, send)


class RoutingAPI(AbstractRoutingAPI):
    def __init__(
        self,
        specification: t.Union[pathlib.Path, str, dict],
        *,
        next_app: ASGIApp,
        base_path: t.Optional[str] = None,
        arguments: t.Optional[dict] = None,
        resolver: t.Optional[Resolver] = None,
        resolver_error_handler: t.Optional[t.Callable] = None,
        debug: bool = False,
        **kwargs,
    ) -> None:
        """API implementation on top of Starlette Router for Connexion middleware."""
        self.next_app = next_app
        self.router = Router(default=RoutingOperation(None, next_app))

        super().__init__(
            specification,
            base_path=base_path,
            arguments=arguments,
            resolver=resolver,
            resolver_error_handler=resolver_error_handler,
            debug=debug,
        )

    def add_operation(self, path: str, method: str) -> None:
        operation_cls = self.specification.operation_cls
        operation = operation_cls.from_spec(
            self.specification, self, path, method, self.resolver
        )
        routing_operation = RoutingOperation.from_operation(
            operation, next_app=self.next_app
        )
        types = operation.get_path_parameter_types()
        path = starlettify_path(path, types)
        self._add_operation_internal(method, path, routing_operation)

    def _add_operation_internal(
        self, method: str, path: str, operation: "RoutingOperation"
    ) -> None:
        self.router.add_route(path, operation, methods=[method])


class RoutingMiddleware(AppMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        """Middleware that resolves the Operation for an incoming request and attaches it to the
        scope.

        :param app: app to wrap in middleware.
        """
        self.app = app
        # Pass unknown routes to next app
        self.router = Router(default=RoutingOperation(None, self.app))
        starlette.convertors.register_url_convertor("float", FloatConverter())
        starlette.convertors.register_url_convertor("int", IntegerConverter())

    def add_api(
        self,
        specification: t.Union[pathlib.Path, str, dict],
        base_path: t.Optional[str] = None,
        arguments: t.Optional[dict] = None,
        **kwargs,
    ) -> None:
        """Add an API to the router based on a OpenAPI spec.

        :param specification: OpenAPI spec as dict or path to file.
        :param base_path: Base path where to add this API.
        :param arguments: Jinja arguments to replace in the spec.
        """
        api = RoutingAPI(
            specification,
            base_path=base_path,
            arguments=arguments,
            next_app=self.app,
            **kwargs,
        )
        self.router.mount(api.base_path, app=api.router)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Route request to matching operation, and attach it to the scope before calling the
        next app."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        _scope.set(scope.copy())  # type: ignore

        # Needs to be set so starlette router throws exceptions instead of returning error responses
        scope["app"] = self
        await self.router(scope, receive, send)


PATH_PARAMETER = re.compile(r"\{([^}]*)\}")
PATH_PARAMETER_CONVERTERS = {"integer": "int", "number": "float", "path": "path"}


def convert_path_parameter(match, types):
    name = match.group(1)
    swagger_type = types.get(name)
    converter = PATH_PARAMETER_CONVERTERS.get(swagger_type)
    return f'{{{name.replace("-", "_")}{":" if converter else ""}{converter or ""}}}'


def starlettify_path(swagger_path, types=None):
    """
    Convert swagger path templates to flask path templates

    :type swagger_path: str
    :type types: dict
    :rtype: str

    >>> starlettify_path('/foo-bar/{my-param}')
    '/foo-bar/{my_param}'

    >>> starlettify_path('/foo/{someint}', {'someint': 'int'})
    '/foo/{someint:int}'
    """
    if types is None:
        types = {}
    convert_match = functools.partial(convert_path_parameter, types=types)
    return PATH_PARAMETER.sub(convert_match, swagger_path)


class FloatConverter(starlette.convertors.FloatConvertor):
    """Starlette converter for OpenAPI number type"""

    regex = r"[+-]?[0-9]*(\.[0-9]*)?"


class IntegerConverter(starlette.convertors.IntegerConvertor):
    """Starlette converter for OpenAPI integer type"""

    regex = r"[+-]?[0-9]+"
