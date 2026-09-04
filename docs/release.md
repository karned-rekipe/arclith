# Release PyPI

Cette procédure publie les deux distributions publiques :

- `arclith`, le framework Python.
- `arclith-cli`, la CLI de scaffold.

Les archives sont publiées par GitHub Actions via PyPI Trusted Publishing. Aucun token PyPI ne
doit être stocké dans les secrets du dépôt.

## Préparer la release

1. Partir d'un `main` à jour et propre.
2. Mettre à jour les versions :
   - `pyproject.toml` pour `arclith`.
   - `cli/pyproject.toml` et `cli/arclith_cli/__init__.py` pour `arclith-cli`.
   - La dépendance `arclith>=...` dans `cli/pyproject.toml`.
3. Mettre à jour `CHANGELOG.md`.
4. Régénérer les locks :

```bash
uv lock
cd cli
uv lock
```

## Valider localement

Depuis la racine du dépôt :

```bash
make precommit
make coverage
uv build --out-dir dist/check .
uv build --out-dir dist/check-cli cli
```

Les dossiers `dist/` sont ignorés par Git. Ils peuvent être supprimés après la validation locale.

## Configurer PyPI Trusted Publishing

Chaque projet PyPI doit déclarer son propre Trusted Publisher, car le jeton OIDC est borné au
projet PyPI ciblé.

| Projet PyPI | Owner GitHub | Repository | Workflow filename | Environment |
| --- | --- | --- | --- | --- |
| `arclith` | `karned-rekipe` | `arclith` | `publish.yml` | `pypi` |
| `arclith-cli` | `karned-rekipe` | `arclith` | `publish.yml` | `pypi-cli` |

Le fichier correspondant dans le dépôt est `.github/workflows/publish.yml`. Le champ PyPI demande
le nom du fichier workflow, pas un token GitHub. GitHub fournit un jeton OIDC court-vivant au job
grâce à la permission `id-token: write`, puis PyPI l'échange contre un jeton de publication limité
au projet ciblé.

Si `arclith-cli` utilise l'environnement `pypi` au lieu de `pypi-cli`, PyPI rejette la publication
avec une erreur `Invalid API Token: OIDC scoped token is not valid for project 'arclith-cli'`.

## Publier

Une fois la PR de release mergée :

```bash
git switch main
git pull --ff-only
git tag -s v0.23.0 -m "Release v0.23.0"
git push origin v0.23.0
```

Le tag déclenche `.github/workflows/publish.yml`. Le workflow exécute :

1. `make precommit`.
2. `make coverage`.
3. La construction des distributions `arclith` et `arclith-cli`.
4. La publication de chaque distribution dans son job PyPI dédié.

## Vérifier après publication

Contrôler les deux pages PyPI :

- <https://pypi.org/project/arclith/>
- <https://pypi.org/project/arclith-cli/>

Puis valider depuis un environnement consommateur isolé :

```bash
tmp_dir="$(mktemp -d)"
cd "$tmp_dir"
uvx --from arclith-cli==0.20.0 arclith-cli init pantry-agent --dir .
cd pantry-agent
uv sync
uv run python -c "import arclith; print(arclith.__version__ if hasattr(arclith, '__version__') else 'arclith import ok')"
uvx --from arclith-cli==0.20.0 arclith-cli capabilities
uvx --from arclith-cli==0.20.0 arclith-cli add-entity ShoppingItem
uvx --from arclith-cli==0.20.0 arclith-cli add-usecase PlanShoppingList
uvx --from arclith-cli==0.20.0 arclith-cli add-intent-interpreter ShoppingIntent
```
