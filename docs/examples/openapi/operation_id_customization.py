import re

from dmr.metadata import EndpointMetadata
from dmr.openapi import OpenAPIConfig, OpenAPIContext, build_schema
from dmr.openapi.views import OpenAPIJsonView, SwaggerView
from dmr.routing import Router, path
from dmr.serializer import BaseSerializer
from examples.getting_started.msgspec_controller import UserController


def generate_operation_id(
    path: str,
    suffix: str,
    metadata: EndpointMetadata,
    serializer: type[BaseSerializer],
) -> str:
    """Generate ``operationId`` values like ``api_post_user``."""
    clean_path = re.sub(r'[{}/]+', '_', path).strip('_')
    method = metadata.method.lower()
    return f'api_{method}_{clean_path}'


router = Router(
    'api/',
    [
        path('user/', UserController.as_view(), name='users'),
    ],
)

context = OpenAPIContext(
    OpenAPIConfig(title='My awesome API', version='1.0.0'),
    operation_id_generator=generate_operation_id,
)
schema = build_schema(router, context=context)

urlpatterns = [
    router.to_urlpatterns(namespace='api'),
    path(
        'docs/openapi.json/',
        OpenAPIJsonView.as_view(schema),
        name='openapi',
    ),
    path('docs/swagger/', SwaggerView.as_view(schema), name='swagger'),
]

# openapi: {"openapi_url": "/docs/openapi.json/", "use_urlpatterns": true}  # noqa: ERA001
