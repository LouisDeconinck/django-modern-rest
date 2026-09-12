import json
import sys
from collections.abc import Mapping
from http import HTTPMethod, HTTPStatus
from typing import Annotated, Any, Final, TypeAlias

import pydantic
import pytest
from django.http import HttpResponse
from django.urls import path
from inline_snapshot import snapshot
from syrupy.assertion import SnapshotAssertion
from typing_extensions import TypedDict, override

from dmr import Body, Controller, ResponseSpec, modify, validate
from dmr.cookies import CookieSpec, NewCookie
from dmr.errors import ErrorModel
from dmr.headers import HeaderSpec, NewHeader
from dmr.metadata import ResponseSpecMetadata, get_annotated_metadata
from dmr.openapi import build_schema
from dmr.plugins.pydantic import PydanticFastSerializer, PydanticSerializer
from dmr.renderers import Renderer
from dmr.routing import Router
from dmr.serializer import BaseSerializer
from dmr.test import DMRRequestFactory

_HEADER_VALUE: Final = 'header_whatever'
_COOKIE_VALUE: Final = 'cookie_whatever'

serializers: list[Any] = [PydanticSerializer, PydanticFastSerializer]

try:
    from dmr.plugins.msgspec import MsgspecSerializer
except ImportError:  # pragma: no cover
    pass  # do nothing then :(  # noqa: WPS420
else:
    serializers.append(MsgspecSerializer)


class _BodyModel(pydantic.BaseModel):
    number: int


class _HeaderAndCookieController(Controller[PydanticSerializer]):
    error_model = Annotated[
        ErrorModel,
        ResponseSpecMetadata(
            headers={'X-Reply': HeaderSpec()},
            cookies={'x-test': CookieSpec()},
        ),
    ]

    @modify(
        headers={
            'X-Reply': NewHeader(value=_HEADER_VALUE),
            'X-Success': NewHeader(value='true'),
        },
        cookies={'x-test': NewCookie(value=_COOKIE_VALUE)},
    )
    def patch(self, parsed_body: Body[_BodyModel]) -> _BodyModel:
        return parsed_body

    @validate(
        ResponseSpec(
            _BodyModel,
            status_code=HTTPStatus.OK,
            headers={
                'X-Reply': HeaderSpec(),
                'X-Success': HeaderSpec(),
            },
            cookies={'x-test': CookieSpec()},
        ),
    )
    def put(self, parsed_body: Body[_BodyModel]) -> HttpResponse:
        return self.to_response(parsed_body, headers={'X-Success': 'true'})

    @override
    def to_response(
        self,
        raw_data: Any,
        *,
        status_code: HTTPStatus | None = None,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, NewCookie] | None = None,
        renderer: Renderer | None = None,
    ) -> HttpResponse:
        headers = dict(headers or {})
        headers.setdefault('X-Reply', _HEADER_VALUE)

        cookies = dict(cookies or {})
        cookies.setdefault(
            'x-test',
            NewCookie(value=_COOKIE_VALUE),
        )
        return super().to_response(
            raw_data,
            status_code=status_code,
            headers=headers,
            cookies=cookies,
            renderer=renderer,
        )


@pytest.mark.parametrize('method', [HTTPMethod.PATCH, HTTPMethod.PUT])
def test_header_and_cookie_success(
    dmr_rf: DMRRequestFactory,
    *,
    method: HTTPMethod,
) -> None:
    """Ensures that correct responses provide headers and cookies."""
    request_data = {'number': 1}
    request = dmr_rf.generic(
        str(method),
        '/any/',
        data=json.dumps(request_data),
    )

    response = _HeaderAndCookieController.as_view()(request)

    assert isinstance(response, HttpResponse)
    assert response.status_code == HTTPStatus.OK, response.content
    assert response.headers == {
        'Content-Type': 'application/json',
        'X-Reply': _HEADER_VALUE,
        'X-Success': 'true',
    }
    assert (
        response.cookies.output()
        == f'Set-Cookie: x-test={_COOKIE_VALUE}; Path=/; SameSite=lax'
    )
    assert json.loads(response.content) == request_data


@pytest.mark.parametrize('method', [HTTPMethod.PATCH, HTTPMethod.PUT])
def test_header_and_cookie_error(
    dmr_rf: DMRRequestFactory,
    *,
    method: HTTPMethod,
) -> None:
    """Ensures that error responses provide headers and cookies."""
    request = dmr_rf.generic(
        str(method),
        '/any/',
        data=json.dumps({'number': 'wrong'}),
    )

    response = _HeaderAndCookieController.as_view()(request)

    assert isinstance(response, HttpResponse)
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.content
    assert response.headers == {
        'Content-Type': 'application/json',
        'X-Reply': _HEADER_VALUE,
    }
    assert (
        response.cookies.output()
        == f'Set-Cookie: x-test={_COOKIE_VALUE}; Path=/; SameSite=lax'
    )
    assert json.loads(response.content) == snapshot({
        'detail': [
            {
                'msg': (
                    'Input should be a valid integer, '
                    'unable to parse string as an integer'
                ),
                'loc': ['parsed_body', 'number'],
                'type': 'value_error',
            },
        ],
    })


def test_error_model_with_metadata_schema(snapshot: SnapshotAssertion) -> None:
    """Ensure that schema is correct for error models with annotations."""
    assert (
        json.dumps(
            build_schema(
                Router(
                    'api/v1/',
                    [
                        path(
                            '/header-and-cookie',
                            _HeaderAndCookieController.as_view(),
                        ),
                    ],
                ),
            ).convert(),
            indent=2,
        )
        == snapshot
    )


class _UnionModel(TypedDict):
    age: int


_UnionReturn: TypeAlias = (
    Annotated[
        _UnionModel,
        ResponseSpecMetadata(headers={'X-Id': HeaderSpec()}),
    ]
    | str
)


class _UnionMetadataController(Controller[PydanticSerializer]):
    def get(self) -> _UnionReturn:
        return 'ok'


def test_union_member_metadata() -> None:
    """Ensure that ``ResponseSpecMetadata`` inside union members is used."""
    endpoint = _UnionMetadataController.api_endpoints['GET']
    assert endpoint.metadata.responses[HTTPStatus.OK].headers == {
        'X-Id': HeaderSpec(),
    }


def test_union_member_metadata_runtime(
    dmr_rf: DMRRequestFactory,
) -> None:
    """Ensure that endpoints with union member metadata still work."""
    request = dmr_rf.get('/any/')

    response = _UnionMetadataController.as_view()(request)

    assert isinstance(response, HttpResponse)
    assert response.status_code == HTTPStatus.OK, response.content
    assert json.loads(response.content) == 'ok'


def test_union_member_metadata_schema() -> None:
    """Ensure that union member metadata is used in the OpenAPI schema."""
    schema = build_schema(
        Router(
            'api/v1/',
            [path('/union', _UnionMetadataController.as_view())],
        ),
    ).convert()

    responses = schema['paths']['/api/v1/union']['get']['responses']
    assert 'X-Id' in responses['200']['headers']


@pytest.mark.parametrize('serializer', serializers)
@pytest.mark.parametrize('include_header', [True, False])
def test_union_member_metadata_validation(
    dmr_rf: DMRRequestFactory,
    *,
    serializer: type[BaseSerializer],
    include_header: bool,
) -> None:
    """Ensure that union member metadata is used for response validation."""

    class _UnionValidatedController(Controller[serializer]):  # type: ignore[valid-type]
        @validate(
            ResponseSpec(
                _UnionReturn,
                status_code=HTTPStatus.OK,
            ),
        )
        def get(self) -> HttpResponse:
            return self.to_response(
                'ok',
                status_code=HTTPStatus.OK,
                headers={'X-Id': _HEADER_VALUE} if include_header else None,
            )

    request = dmr_rf.get('/any/')

    response = _UnionValidatedController.as_view()(request)

    assert isinstance(response, HttpResponse)
    if include_header:
        assert response.status_code == HTTPStatus.OK, response.content
        assert response.headers['X-Id'] == _HEADER_VALUE
    else:
        assert response.status_code == (HTTPStatus.UNPROCESSABLE_ENTITY), (
            response.content
        )


def test_nested_union_metadata() -> None:
    """Ensure that nested union members are searched just once."""
    model = Annotated[int | str, 'meta'] | int

    assert get_annotated_metadata(model, ResponseSpecMetadata) is None


@pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason='PEP-695 was added in 3.12',
)
def test_recursive_union_alias_metadata() -> None:  # pragma: no cover
    """Ensure that recursive union aliases don't cause infinite recursion."""
    namespace: dict[str, Any] = {}
    # We have to use `exec` here, because 3.12+ syntax
    # will cause `SyntaxError` for the whole test module:
    exec(  # noqa: S102, WPS421
        'type _Recursive = int | _Recursive',
        namespace,
    )
    alias = namespace['_Recursive']

    assert get_annotated_metadata(alias, ResponseSpecMetadata) is None
    assert (
        get_annotated_metadata(
            int | alias,
            ResponseSpecMetadata,
        )
        is None
    )
