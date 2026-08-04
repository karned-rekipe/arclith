from pydantic import BaseModel, Field


class MongoDBConfig(BaseModel):
    model_config = {"frozen": True}

    db_name: str = Field(
        description="Nom de la base de données MongoDB.",
        examples=["myapp", "rekipe"],
    )
    uri: str | None = Field(
        default=None,
        description="URI de connexion MongoDB. None si géré par le mode multitenant.",
        examples=["mongodb://localhost:27017", None],
    )
    collection_name: str | None = Field(
        default=None,
        description="Nom de la collection. Dérivé du nom de la classe entité si absent.",
        examples=["ingredient", None],
    )
