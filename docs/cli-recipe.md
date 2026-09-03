# Recettes Arclith CLI

Une recette CLI conserve la suite des décisions de scaffolding prises avec
`arclith-cli`. Chaque projet créé par `init` ou `new` reçoit un fichier
`arclith.recipe.yaml` à sa racine.

La recette répond à trois besoins :

- relire l'ordre des commandes mutantes réussies ;
- revoir les paramètres résolus après un wizard ou des options directes ;
- reconstruire un projet équivalent sans rejouer des commandes shell.

## Recette, Git et configuration exportée

Ces trois artefacts sont complémentaires :

| Artefact | Source de vérité pour | Ne contient pas |
|---|---|---|
| Git | l'historique exact du code et des modifications manuelles | une intention fonctionnelle rejouable hors des commits |
| `arclith.recipe.yaml` | les mutations réussies réalisées par la CLI | les modifications manuelles, les échecs ou les secrets |
| `arclith-cli export-config` | la configuration consolidée à déployer | l'ordre de construction du projet |

La recette ne remplace donc jamais Git. Elle décrit uniquement les opérations
Arclith connues de la CLI.

## Commandes enregistrées

La version 1 enregistre :

- `init` et `new` ;
- `add-entity` ;
- `add-usecase` ;
- `add-intent-interpreter` ;
- `add-adapter`.

Une étape est ajoutée uniquement après le succès complet de la commande. Une
confirmation refusée, une erreur de validation ou une génération échouée ne
modifie pas la recette.

Les fichiers créés ou mis à jour sont détectés après la commande. Leurs chemins
sont toujours relatifs à la racine du projet. Les environnements virtuels,
caches, métadonnées Git et la recette elle-même ne font pas partie du résultat.

## Format versionné

Le fichier est du YAML structuré, écrit atomiquement et validé au chargement.
La version initiale du schéma est `1` :

```yaml
version: 1
project:
  name: todo-service
  package: todo_service
created_at: "2026-09-01T10:00:00+00:00"
updated_at: "2026-09-01T10:04:00+00:00"
steps:
  - id: "0001"
    at: "2026-09-01T10:00:00+00:00"
    cli_version: "0.19.0"
    command: init
    status: success
    args:
      project_name: todo-service
      directory: .
    result:
      generated_files:
        - path: pyproject.toml
          action: created
  - id: "0002"
    at: "2026-09-01T10:04:00+00:00"
    cli_version: "0.19.0"
    command: add-entity
    status: success
    args:
      entity: Todo
    result:
      generated_files:
        - path: src/todo_service/domain/models/todo.py
          action: created
```

Les timestamps ISO 8601 incluent toujours leur fuseau. Les identifiants à
quatre chiffres restent stables pour sélectionner une plage de replay.

## Lire l'historique

Depuis la racine du projet :

```bash
arclith-cli history
```

Pour inspecter un autre fichier :

```bash
arclith-cli history --recipe ../service/arclith.recipe.yaml
```

La timeline affiche l'id, la date, la commande et un résumé sans secret.

## Prévisualiser un replay

Le dry-run valide la recette et affiche les actions sans créer le dossier cible :

```bash
arclith-cli replay arclith.recipe.yaml \
  --dir ../todo-service-rebuilt \
  --dry-run
```

La valeur de `--dir` désigne la racine exacte du projet cible. Le nom et le
package fonctionnels restent ceux de la recette, même si le dossier cible porte
un autre nom.

Une plage inclusive peut être sélectionnée :

```bash
arclith-cli replay arclith.recipe.yaml \
  --dir ../existing-service \
  --from-step 0003 \
  --to-step 0008 \
  --dry-run
```

Si la plage ne contient pas `init` ou `new`, la cible doit déjà être un projet
compatible. Le plan affiche chaque étape comme `rejouer` ou
`ignorer (non supportée)` et compte uniquement les étapes réellement
exécutables. Les secrets d'une étape ignorée ne sont pas demandés. `--strict`
refuse au contraire toute commande que la version courante de la CLI ne sait
pas rejouer.

## Exécuter un replay

Retirer `--dry-run` pour reconstruire le projet :

```bash
arclith-cli replay arclith.recipe.yaml --dir ../todo-service-rebuilt
```

Le replay appelle directement `init_project_cmd`, `add_entity_cmd`,
`add_usecase_cmd`, `add_intent_interpreter_cmd` et `add_adapter_cmd`. Il ne
construit pas une ligne de commande shell, ce qui évite les différences de
quoting et garde les erreurs testables.

Les étapes rejouées ne sont pas enregistrées une seconde fois. Pour une cible
nouvelle, la recette sélectionnée est copiée une seule fois après le succès du
replay. Pour un projet existant qui possède déjà sa recette, celle-ci n'est pas
modifiée implicitement.

## Secrets

Une recette ne stocke jamais de secret en clair. La CLI combine :

- les paramètres `secret` du catalogue d'adapters ;
- les mappings vers les variables d'environnement déjà déclarés par les
  adapters ;
- une heuristique défensive sur `password`, `passwd`, `secret`, `token`,
  `api_key`, `apikey`, `credential` et les URI/URL avec credentials.

Une valeur sensible est remplacée par `<redacted>` et accompagnée d'une
référence :

```yaml
args:
  capability: cache
  adapter: redis
  params:
    redis_url: <redacted>
secrets:
  - field_path: args.params.redis_url
    source: env
    key: REDIS_URL
    value: <redacted>
```

Le dry-run liste les variables nécessaires sans lire ni afficher leur valeur.
Le replay réel exige leur présence dans l'environnement :

```bash
REDIS_URL='redis://redis:6379/0' \
  arclith-cli replay arclith.recipe.yaml --dir ../service-rebuilt
```

Une référence de secret de configuration, par exemple
`adapters.mongodb.uri -> MONGODB_URI`, reste informative lorsque la génération
produit déjà `config/secrets.yaml`. Seuls les champs `args.*` sont injectés dans
les paramètres du replay.

Les chemins absolus externes ne sont pas portables : ils sont remplacés par
`<external-path>` et doivent être corrigés avant un replay réel.

## Limites de la version 1

- les changements manuels ne sont ni détectés comme commandes ni rejoués ;
- les échecs et annulations ne forment pas un audit log ;
- une version de schéma inconnue est refusée plutôt que devinée ;
- `new` recharge le template depuis le `repo_ref` enregistré : pour des
  reconstructions durables, utiliser un tag ou une référence Git stable.
