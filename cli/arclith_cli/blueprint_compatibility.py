"""Audited source-only digest migration; rendered state-machine V1 is unchanged.

The V1 digest includes its catalogue/dispatcher module. Adding the independent
job/synchronization renderers changes that source without changing any state-machine output.
Only the exact audited source fingerprint is mapped; later changes still drift.
"""

_STATE_MACHINE_SOURCE_MIGRATIONS: dict[str, str] = {
    "sha256:f451d9ddea24d912e98e6e641e14d855d206922ed5c7fda0d08bd1bb9e80a2c3":
    "sha256:993831ea433cf4fef2d8b52b02c96c7dc9cbcae4141760b5151b4cba77142356",
    "sha256:d63e4f60051551aa4c65460363f4dec1f880919b9beaa4cea651dc963ce5bd14":
    "sha256:993831ea433cf4fef2d8b52b02c96c7dc9cbcae4141760b5151b4cba77142356",
    'sha256:5a67b2fb01e75d0d2c77f487600e7957cda4d79675165c67bd6d12078e927ce7':
    "sha256:993831ea433cf4fef2d8b52b02c96c7dc9cbcae4141760b5151b4cba77142356",
}


def compatible_state_machine_source_digest(digest: str) -> str:
    return _STATE_MACHINE_SOURCE_MIGRATIONS.get(digest, digest)
