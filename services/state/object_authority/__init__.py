"""Object Authority Service native package exports."""

from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.state.object_authority.component import MANIFEST
from services.state.object_authority.config import ObjectAuthoritySettings
from services.state.object_authority.domain import (
    ObjectGetResult,
    ObjectMetadata,
    ObjectRecord,
    ObjectRef,
)
from services.state.object_authority.implementation import DefaultObjectAuthorityService
from services.state.object_authority.service import ObjectAuthorityService

__all__ = [
    "MANIFEST",
    "ObjectAuthorityService",
    "ObjectAuthoritySettings",
    "DefaultObjectAuthorityService",
    "ObjectRef",
    "ObjectMetadata",
    "ObjectRecord",
    "ObjectGetResult",
    "Envelope",
    "EnvelopeKind",
    "EnvelopeMeta",
    "ErrorCategory",
    "ErrorDetail",
]
