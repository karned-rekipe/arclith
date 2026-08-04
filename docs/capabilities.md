# Capacites standardisees

Arclith doit fournir une base stable pour assembler rapidement des services hexagonaux. La CLI s'appuie donc sur un catalogue de capacites plutot que sur des chemins codes au cas par cas.

## Principe

Une capacite decrit:

- le role architectural expose par la CLI;
- le layer hexagonal concerne, `inbound` ou `outbound`;
- les adapters disponibles;
- les parametres requis par adapter;
- le chemin de configuration;
- la cle d'activation dans `config/adapters/adapters.yaml`.

Le code metier reste dans `domain/` et `application/`. Les capacites ne doivent generer que du cablage, des ports, des schemas ou des adapters autour de ce coeur.

## Catalogue actuel

```bash
arclith-cli capabilities
arclith-cli capabilities --json
```

### `repository`

Capacite outbound pour la persistance des entites metier derriere un port repository.

Adapters disponibles:

- `memory`: stockage volatile pour dev, tests et smoke locaux;
- `mongodb`: repository async MongoDB, single-tenant ou multitenant;
- `duckdb`: repository fichier local pour SQL analytique et demos sans serveur;
- `mariadb`: repository MariaDB async optionnel, avec stockage generique JSON par entite.

Activation:

```yaml
repository: mongodb
```

## Ajouter un adapter

Le chemin standard est:

```bash
arclith-cli add-adapter --capability repository --adapter mongodb --entity Ingredient --yes
```

Les parametres d'adapter peuvent etre fournis de maniere generique:

```bash
arclith-cli add-adapter \
  --capability repository \
  --adapter mariadb \
  --entity Ingredient \
  --param host=127.0.0.1 \
  --param port=3306 \
  --param database=pantry_agent \
  --param user=app \
  --yes
```

Le mode interactif reste disponible:

```bash
arclith-cli add-adapter
```

## Regle d'evolution

Chaque nouvelle capacite doit d'abord etre ajoutee au catalogue, puis consommee par la CLI. Cela garde les futures briques, par exemple MariaDB, bus, planner LLM, tracing ou observability, declaratives et testables.

Une capacite ne doit pas introduire de dependance du core vers un adapter. Elle doit uniquement generer ou cabler les elements externes necessaires.

Les secrets ne doivent pas etre generes dans les fichiers d'adapter. Pour MariaDB, mapper `adapters.mariadb.password` ou `adapters.mariadb.url` via `config/secrets.yaml`, un resolver `env` ou Vault.
