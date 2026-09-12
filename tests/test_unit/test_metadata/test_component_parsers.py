import json
import sys
import textwrap
from http import HTTPMethod, HTTPStatus
from types import MappingProxyType
from typing import Any, Final, TypeAlias

import pydantic
import pytest
from dirty_equals import IsInstance
from django.http import HttpResponse
from typing_extensions import TypedDict

from dmr import (  # noqa: WPS235
    Body,
    Controller,
    Cookies,
    Headers,
    Path,
    Query,
    ResponseSpec,
    modify,
    validate,
)
from dmr.components import (
    BodyComponent,
    CookiesComponent,
    HeadersComponent,
    PathComponent,
    QueryComponent,
)
from dmr.plugins.pydantic import PydanticFastSerializer, PydanticSerializer
from dmr.serializer import BaseSerializer
from dmr.test import DMRRequestFactory

_ComponentTypes: TypeAlias = list[tuple[str, Any, tuple[Any, ...]]]

serializers: list[Any] = [PydanticSerializer, PydanticFastSerializer]

try:
    from dmr.plugins.msgspec import MsgspecSerializer
except ImportError:  # pragma: no cover
    pass  # do nothing then :(  # noqa: WPS420
else:
    serializers.append(MsgspecSerializer)


class _QueryModel(pydantic.BaseModel):
    search: str


class _BodyModel(pydantic.BaseModel):
    name: str


class _HeadersModel(pydantic.BaseModel):
    token: str


class _PathModel(pydantic.BaseModel):
    user_id: int


class _NoComponentsController(Controller[PydanticSerializer]):
    @modify()
    def get(self) -> list[int]:
        raise NotImplementedError

    def post(self) -> list[str]:
        raise NotImplementedError

    @validate(ResponseSpec(list[int], status_code=HTTPStatus.OK))
    def put(self) -> HttpResponse:
        raise NotImplementedError


@pytest.mark.parametrize(
    'method',
    [HTTPMethod.GET, HTTPMethod.POST, HTTPMethod.PUT],
)
def test_no_components(
    *,
    method: HTTPMethod,
) -> None:
    """Ensure controller without components has empty component_parsers."""
    endpoint = _NoComponentsController.api_endpoints[str(method)]
    assert endpoint.metadata.component_parsers == []


class _QueryController(
    Controller[PydanticSerializer],
):
    @modify()
    def get(self, parsed_query: Query[_QueryModel]) -> list[int]:
        raise NotImplementedError

    def post(self, parsed_query: Query[_QueryModel]) -> list[str]:
        raise NotImplementedError

    @validate(ResponseSpec(list[int], status_code=HTTPStatus.OK))
    def put(self, parsed_query: Query[_QueryModel]) -> HttpResponse:
        raise NotImplementedError


@pytest.mark.parametrize(
    'method',
    [HTTPMethod.GET, HTTPMethod.POST, HTTPMethod.PUT],
)
def test_single_component_query(
    *,
    method: HTTPMethod,
) -> None:
    """Ensure controller with Query component has it in component_parsers."""
    endpoint = _QueryController.api_endpoints[str(method)]
    assert [
        (component.context_name, model, meta)
        for component, model, meta in endpoint.metadata.component_parsers
    ] == [('parsed_query', _QueryModel, (IsInstance(QueryComponent),))]


class _MultiComponentController(Controller[PydanticSerializer]):
    """Controller with endpoint-level components."""

    @modify()
    def get(
        self,
        parsed_query: Query[_QueryModel],
        parsed_headers: Headers[_HeadersModel],
        parsed_path: Path[_PathModel],
    ) -> list[int]:
        raise NotImplementedError

    def post(
        self,
        parsed_query: Query[_QueryModel],
        parsed_body: Body[_BodyModel],
        parsed_headers: Headers[_HeadersModel],
        parsed_path: Path[_PathModel],
    ) -> list[str]:
        raise NotImplementedError

    @validate(ResponseSpec(list[int], status_code=HTTPStatus.OK))
    def put(
        self,
        parsed_query: Query[_QueryModel],
        parsed_body: Body[_BodyModel],
        parsed_headers: Headers[_HeadersModel],
        parsed_path: Path[_PathModel],
    ) -> HttpResponse:
        raise NotImplementedError


def test_multiple_components_get() -> None:
    """Ensure GET endpoint has components without Body."""
    endpoint = _MultiComponentController.api_endpoints['GET']
    assert isinstance(endpoint.metadata.component_parsers, list)
    components: _ComponentTypes = [
        ('parsed_query', _QueryModel, (IsInstance(QueryComponent),)),
        ('parsed_headers', _HeadersModel, (IsInstance(HeadersComponent),)),
        ('parsed_path', _PathModel, (IsInstance(PathComponent),)),
    ]
    assert sorted(components) == sorted([
        (component.context_name, model, meta)
        for component, model, meta in endpoint.metadata.component_parsers
    ])


@pytest.mark.parametrize(
    'method',
    [HTTPMethod.POST, HTTPMethod.PUT],
)
def test_multiple_components_with_body(
    *,
    method: HTTPMethod,
) -> None:
    """Ensure controller has all multiple components in component_parsers."""
    endpoint = _MultiComponentController.api_endpoints[str(method)]
    assert isinstance(endpoint.metadata.component_parsers, list)
    components: _ComponentTypes = [
        ('parsed_query', _QueryModel, (IsInstance(QueryComponent),)),
        ('parsed_headers', _HeadersModel, (IsInstance(HeadersComponent),)),
        ('parsed_path', _PathModel, (IsInstance(PathComponent),)),
        ('parsed_body', _BodyModel, (IsInstance(BodyComponent),)),
    ]
    assert sorted(components) == sorted([
        (component.context_name, model, meta)
        for component, model, meta in endpoint.metadata.component_parsers
    ])


class _CookiesModel(pydantic.BaseModel):
    session_id: int


class _UnifiedModel(TypedDict):
    age: int


#: All component forms: (param_name, component, model, expected class)
_COMPONENT_FORMS: Final = (
    ('parsed_body', 'Body', _BodyModel, BodyComponent),
    ('parsed_query', 'Query', _QueryModel, QueryComponent),
    ('parsed_headers', 'Headers', _HeadersModel, HeadersComponent),
    ('parsed_path', 'Path', _PathModel, PathComponent),
    ('parsed_cookies', 'Cookies', _CookiesModel, CookiesComponent),
)

#: Component aliases by name, injected into `exec` namespaces.
#: Keeps the imports alive, since `exec` strings are invisible to linters:
_COMPONENT_OBJECTS: Final = MappingProxyType({
    'Body': Body,
    'Query': Query,
    'Headers': Headers,
    'Path': Path,
    'Cookies': Cookies,
})


def _build_aliased_controller(
    alias_definition: str,
    param_name: str,
    *,
    serializer: type[BaseSerializer],
    model: Any,
) -> type[Controller[BaseSerializer]]:
    # We have to use `exec` here, because 3.12+ syntax
    # will cause `SyntaxError` for the whole test module.
    namespace: dict[str, Any] = {
        **globals(),  # noqa: WPS421
        **_COMPONENT_OBJECTS,
        'serializer': serializer,
        '_Model': model,
    }
    exec(  # noqa: S102, WPS421
        textwrap.dedent(
            f"""
            {alias_definition}

            class _AliasedController(Controller[serializer]):
                def post(self, {param_name}: _Alias) -> str:
                    raise NotImplementedError
            """,
        ),
        namespace,
    )
    controller: type[Controller[BaseSerializer]] = namespace[
        '_AliasedController'
    ]
    return controller


@pytest.mark.parametrize('serializer', serializers)
@pytest.mark.parametrize(
    ('param_name', 'component', 'model', 'component_cls'),
    _COMPONENT_FORMS,
)
@pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason='PEP-695 was added in 3.12',
)
def test_pep695_component_alias(
    *,
    serializer: type[BaseSerializer],
    param_name: str,
    component: str,
    model: Any,
    component_cls: type[Any],
) -> None:  # pragma: no cover
    """Ensure that ``type X = Component[Model]`` defines component parsers."""
    controller = _build_aliased_controller(
        f'type _Alias = {component}[_Model]',
        param_name,
        serializer=serializer,
        model=model,
    )

    endpoint = controller.api_endpoints['POST']
    assert [
        (parser.context_name, parser_model, meta)
        for parser, parser_model, meta in endpoint.metadata.component_parsers
    ] == [(param_name, model, (IsInstance(component_cls),))]


@pytest.mark.parametrize('serializer', serializers)
@pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason='PEP-695 was added in 3.12',
)
def test_pep695_generic_component_alias(
    *,
    serializer: type[BaseSerializer],
) -> None:  # pragma: no cover
    """Ensure that ``type X[T] = Component[T]`` defines component parsers."""
    namespace: dict[str, Any] = {
        **globals(),  # noqa: WPS421
        'serializer': serializer,
        '_Model': _BodyModel,
    }
    exec(  # noqa: S102, WPS421
        textwrap.dedent(
            """
            type _Alias[T] = Body[T]

            class _GenericAliasController(Controller[serializer]):
                def post(self, parsed_body: _Alias[_Model]) -> str:
                    raise NotImplementedError
            """,
        ),
        namespace,
    )

    endpoint = namespace['_GenericAliasController'].api_endpoints['POST']
    assert [
        (parser.context_name, parser_model, meta)
        for parser, parser_model, meta in endpoint.metadata.component_parsers
    ] == [('parsed_body', _BodyModel, (IsInstance(BodyComponent),))]


@pytest.mark.parametrize('serializer', serializers)
@pytest.mark.parametrize(
    ('param_name', 'component', 'model', 'component_cls'),
    _COMPONENT_FORMS,
)
def test_type_alias_component(
    *,
    serializer: type[BaseSerializer],
    param_name: str,
    component: str,
    model: Any,
    component_cls: type[Any],
) -> None:
    """Ensure that ``X: TypeAlias = Component[Model]`` defines parsers."""
    controller = _build_aliased_controller(
        f'_Alias: TypeAlias = {component}[_Model]',
        param_name,
        serializer=serializer,
        model=model,
    )

    endpoint = controller.api_endpoints['POST']
    assert [
        (parser.context_name, parser_model, meta)
        for parser, parser_model, meta in endpoint.metadata.component_parsers
    ] == [(param_name, model, (IsInstance(component_cls),))]


@pytest.mark.parametrize('serializer', serializers)
@pytest.mark.parametrize(
    'alias_definition',
    [
        pytest.param(
            'type _Alias = Body[_UnifiedModel]',
            marks=pytest.mark.skipif(
                sys.version_info < (3, 12),
                reason='PEP-695 was added in 3.12',
            ),
            id='pep695',
        ),
        pytest.param(
            '_Alias: TypeAlias = Body[_UnifiedModel]',
            id='type_alias',
        ),
    ],
)
def test_component_alias_parsing(
    dmr_rf: DMRRequestFactory,
    *,
    serializer: type[BaseSerializer],
    alias_definition: str,
) -> None:
    """Ensure that aliased ``Body`` component parses real requests."""
    namespace: dict[str, Any] = {
        **globals(),  # noqa: WPS421
        'serializer': serializer,
        '_UnifiedModel': _UnifiedModel,
    }
    exec(  # noqa: S102, WPS421
        textwrap.dedent(
            f"""
            {alias_definition}

            class _AliasedBodyController(Controller[serializer]):
                def post(self, parsed_body: _Alias) -> _UnifiedModel:
                    return parsed_body
            """,
        ),
        namespace,
    )
    request = dmr_rf.post(
        '/whatever/',
        data={'age': 1},
    )

    response = namespace['_AliasedBodyController'].as_view()(request)

    assert isinstance(response, HttpResponse)
    assert response.status_code == HTTPStatus.CREATED, response.content
    assert json.loads(response.content) == {'age': 1}
