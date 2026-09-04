from arclith_cli.capability_models import AdapterSpec, CapabilitySpec

CHANNEL_CAPABILITY = CapabilitySpec(
    name="channel",
    layer="bidirectional",
    description="Messages conversationnels entrants et sortants normalisés.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="memory",
            capability="channel",
            layer="bidirectional",
            description="Fake déterministe en mémoire pour tests et prototypes locaux.",
            config_path="config/adapters/bidirectional/memory.yaml",
            config_template="""\
enabled: true
""",
            entity_scoped=False,
        ),
    ),
)

__all__ = ["CHANNEL_CAPABILITY"]
