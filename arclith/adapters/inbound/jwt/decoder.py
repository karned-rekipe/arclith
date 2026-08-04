from __future__ import annotations

import json

from arclith.domain.ports.outbound.cache import CachePort


class JWTDecoder:
    """Décoder JWT avec validation de signature via JWKS Keycloak.

    La clé publique (JWKS) est mise en cache via CachePort pour éviter
    un appel HTTP à chaque requête.
    """

    def __init__(
        self,
        jwks_uri: str,
        audience: str | None,
        cache: CachePort,
        ttl_s: int = 3600,
    ) -> None:
        self._jwks_uri = jwks_uri
        self._audience = audience
        self._cache = cache
        self._ttl_s = ttl_s

    async def decode(self, token: str) -> dict:
        try:
            import jwt
            from jwt.algorithms import RSAAlgorithm
        except ImportError:
            raise ImportError("PyJWT[cryptography] requis : uv add 'arclith[auth]'")

        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        jwks = await self._get_jwks()

        key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key_data is None:
            raise ValueError(f"Clé JWKS introuvable pour kid={kid!r}")

        public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))
        kwargs: dict = {"algorithms": ["RS256"]}
        if self._audience:
            kwargs["audience"] = self._audience
        else:
            # PyJWT raises InvalidAudienceError even when audience is not configured
            # if the token contains an 'aud' claim — disable verification explicitly
            kwargs["options"] = {"verify_aud": False}
        return jwt.decode(token, public_key, **kwargs)  # type: ignore[arg-type]

    async def _get_jwks(self) -> dict:
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx requis : uv add 'arclith[auth]'")

        key = f"jwks:{self._jwks_uri}"
        cached = await self._cache.get(key)
        if cached:
            return json.loads(cached)

        async with httpx.AsyncClient() as client:
            resp = await client.get(self._jwks_uri)
            resp.raise_for_status()
            data = resp.json()

        await self._cache.set(key, json.dumps(data), self._ttl_s)
        return data

