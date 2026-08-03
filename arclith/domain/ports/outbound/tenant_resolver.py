from abc import ABC, abstractmethod

from arclith.domain.models.tenant import TenantContext


class TenantResolver(ABC):
    @abstractmethod
    async def resolve(self, tenant_id: str) -> TenantContext: ...

