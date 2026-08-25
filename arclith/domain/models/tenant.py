from dataclasses import dataclass, field


@dataclass
class AdapterTenantCoords:
    """Coordonnées de connexion d'un tenant pour un adaptateur donné.

    Structure générique : aucune hypothèse sur les clés.
    Chaque adaptateur lit les paramètres dont il a besoin.

    Exemples :
    - MongoDB  : {"uri": "mongodb://...", "db_name": "tenant_foo"}
    - MariaDB  : {"uri": "mysql://...", "db_name": "tenant_schema"}
    - PostgreSQL : {"uri": "postgresql://...", "db_name": "tenant_db", "schema": "tenant_schema"}
    - S3       : {"endpoint_url": "https://...", "bucket_name": "tenant-foo", "region": "eu-west-1"}
    - Redis    : {"uri": "redis://...", "key_prefix": "tenant_foo"}

    Les paramètres proviennent directement du secret Vault (tous les champs sont conservés).
    """

    params: dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str | None = None) -> str | None:
        """Retourne la valeur ou ``default`` si la clé est absente."""
        return self.params.get(key, default)

    def require(self, key: str) -> str:
        """Retourne la valeur ou lève ``KeyError`` si la clé est absente."""
        value = self.params.get(key)
        if value is None:
            raise KeyError(f"Paramètre '{key}' manquant dans AdapterTenantCoords")
        return value


@dataclass
class TenantContext:
    """Contexte tenant multi-adaptateur.

    Clé = nom de l'adaptateur (``"mongodb"``, ``"s3"``, ``"mariadb"``, ``"postgresql"``...).
    Chaque adaptateur lit uniquement sa propre tranche via ``get(adapter_name)``.

    Exemple : MongoDB multitenant + S3 single-tenant → seul ``"mongodb"`` est présent.
    """

    adapters: dict[str, AdapterTenantCoords] = field(default_factory=dict)

    def get(self, adapter: str) -> AdapterTenantCoords | None:
        return self.adapters.get(adapter)
