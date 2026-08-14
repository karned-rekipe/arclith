def prefixed_object_key(normalized_key: str, prefix: str) -> str:
    if not prefix:
        return normalized_key
    return f"{prefix}/{normalized_key}"
