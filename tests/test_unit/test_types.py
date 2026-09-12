import sys
import textwrap
from typing import Annotated, Any, Final, TypeVar

import pytest
from typing_extensions import TypeAliasType

from dmr.types import unwrap_annotation

_PEP695_REASON: Final = 'PEP-695 was added in 3.12'

_TypeVarT = TypeVar('_TypeVarT')

_AliasedList = TypeAliasType('_AliasedList', Annotated[list[int], 'meta'])
_GenericAlias = TypeAliasType(
    '_GenericAlias',
    Annotated[_TypeVarT, 'meta'],
    type_params=(_TypeVarT,),
)
_TypeVarAlias = TypeAliasType(
    '_TypeVarAlias',
    _TypeVarT,
    type_params=(_TypeVarT,),
)
_NonGenericAlias = TypeAliasType(
    '_NonGenericAlias',
    int,
    type_params=(_TypeVarT,),
)


def test_unwrap_plain_annotations() -> None:
    """Regular annotations are returned as-is."""
    assert unwrap_annotation(int) == (int, ())
    assert unwrap_annotation(list[int]) == (list[int], ())


def test_unwrap_annotated() -> None:
    """``Annotated`` layers are unwrapped and metadata is collected."""
    assert unwrap_annotation(Annotated[int, 'meta1', 'meta2']) == (
        int,
        ('meta1', 'meta2'),
    )


def test_unwrap_type_alias_type() -> None:
    """``TypeAliasType`` objects are resolved to their values."""
    assert unwrap_annotation(_AliasedList) == (list[int], ('meta',))


def test_unwrap_parameterized_type_alias() -> None:
    """Parameterized ``TypeAliasType`` objects substitute type arguments."""
    assert unwrap_annotation(_GenericAlias[str]) == (str, ('meta',))
    assert unwrap_annotation(_TypeVarAlias[str]) == (str, ())
    assert unwrap_annotation(_NonGenericAlias[str]) == (int, ())


def _exec_type_aliases() -> dict[str, Any]:  # pragma: no cover
    # We have to use `exec` here, because 3.12+ syntax
    # will cause `SyntaxError` for the whole test module.
    namespace = {'Annotated': Annotated}
    exec(  # noqa: S102, WPS421
        textwrap.dedent(
            """
            type _PlainAlias = list[int]
            type _NestedAlias = _PlainAlias
            type _AnnotatedAlias = Annotated[_NestedAlias, 'meta']
            type _RecursiveAlias = _RecursiveAlias
            """,
        ),
        namespace,
    )
    return namespace


@pytest.mark.skipif(sys.version_info < (3, 12), reason=_PEP695_REASON)
def test_unwrap_pep695_aliases() -> None:  # pragma: no cover
    """Regular ``type`` aliases are resolved, including nested ones."""
    namespace = _exec_type_aliases()
    assert unwrap_annotation(namespace['_PlainAlias']) == (list[int], ())
    assert unwrap_annotation(namespace['_NestedAlias']) == (list[int], ())
    assert unwrap_annotation(namespace['_AnnotatedAlias']) == (
        list[int],
        ('meta',),
    )


@pytest.mark.skipif(sys.version_info < (3, 12), reason=_PEP695_REASON)
def test_unwrap_recursive_pep695_alias() -> None:  # pragma: no cover
    """Recursive aliases can't be fully resolved and are kept as-is."""
    namespace = _exec_type_aliases()
    alias = namespace['_RecursiveAlias']
    assert unwrap_annotation(alias) == (alias, ())
