"""Shared error code constants.

These constants are domain-agnostic and intended for stable machine-readable
handling across services. Service-specific codes should extend this set in local
service modules rather than modifying shared constants for one domain.
"""

# Validation
VALIDATION_ERROR = "VALIDATION_ERROR"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"

# Not found
NOT_FOUND = "NOT_FOUND"
RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"

# Conflict
CONFLICT = "CONFLICT"
ALREADY_EXISTS = "ALREADY_EXISTS"

# Policy / authorization
POLICY_VIOLATION = "POLICY_VIOLATION"
PERMISSION_DENIED = "PERMISSION_DENIED"

# Dependency / external system
DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
DEPENDENCY_TIMEOUT = "DEPENDENCY_TIMEOUT"
DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"

# Internal
INTERNAL_ERROR = "INTERNAL_ERROR"
UNEXPECTED_EXCEPTION = "UNEXPECTED_EXCEPTION"
