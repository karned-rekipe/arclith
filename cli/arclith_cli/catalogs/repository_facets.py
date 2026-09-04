from arclith_cli.capability_models import AdapterFacets

MEMORY_FACETS = AdapterFacets(
    storage_model="memory",
    runtime="in_process",
    production_ready=False,
    multi_process=False,
    transactions="none",
    schema_strategy="flexible",
    recommended_for=(
        "tests unitaires",
        "développement et smoke dans un seul processus",
    ),
    limits=(
        "données perdues à l'arrêt",
        "état non partagé entre processus",
    ),
)

MONGODB_FACETS = AdapterFacets(
    storage_model="document",
    runtime="server",
    production_ready=True,
    multi_process=True,
    transactions="limited",
    schema_strategy="flexible",
    recommended_for=(
        "API, MCP et agents avec état partagé",
        "données métier document-first ou à schéma évolutif",
    ),
    limits=(
        "pas de modèle relationnel riche via Repository[T]",
        "pas de transaction multi-opérations exposée par le port",
    ),
)

DUCKDB_FACETS = AdapterFacets(
    storage_model="embedded_analytics",
    runtime="file",
    production_ready=False,
    multi_process=False,
    transactions="limited",
    schema_strategy="structured_tables",
    recommended_for=(
        "démonstrations et traitements analytiques locaux",
        "données persistées dans des fichiers locaux",
    ),
    limits=(
        "pas conçu comme base applicative serveur multi-process",
        "concurrence d'écriture et formats de fichier à encadrer",
    ),
)

MARIADB_FACETS = AdapterFacets(
    storage_model="relational_json",
    runtime="server",
    production_ready=True,
    multi_process=True,
    transactions="strong",
    schema_strategy="json_table",
    recommended_for=(
        "SI existant basé sur MariaDB",
        "état partagé nécessitant un serveur SQL",
    ),
    limits=(
        "entité stockée comme payload JSON générique",
        "pas de relations, joins ou migrations métier via le port",
    ),
)

POSTGRESQL_FACETS = AdapterFacets(
    storage_model="relational_json",
    runtime="server",
    production_ready=True,
    multi_process=True,
    transactions="strong",
    schema_strategy="json_table",
    recommended_for=(
        "services nécessitant un SQL serveur robuste",
        "payload JSONB par défaut ou colonnes typées explicitement mappées",
    ),
    limits=(
        "le mapping structuré est opt-in et fourni par l'application",
        "pas de relations, joins ou migrations automatiques via le port",
    ),
)

__all__ = [
    "DUCKDB_FACETS",
    "MARIADB_FACETS",
    "MEMORY_FACETS",
    "MONGODB_FACETS",
    "POSTGRESQL_FACETS",
]
