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
git tag -s v0.32.0 -m "Release v0.32.0"
git push origin v0.32.0
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
uvx --from arclith-cli==0.29.0 arclith-cli init pantry-agent --dir .
cd pantry-agent
uv sync
uv run python -c "import arclith; print(arclith.__version__ if hasattr(arclith, '__version__') else 'arclith import ok')"
uvx --from arclith-cli==0.29.0 arclith-cli capabilities
uvx --from arclith-cli==0.29.0 arclith-cli add-entity ShoppingItem --profile crud
uvx --from arclith-cli==0.29.0 arclith-cli add-adapter --capability api --adapter fastapi --yes
uvx --from arclith-cli==0.29.0 arclith-cli expose-feature shopping_item --via fastapi --path /v1/shopping-items
```

Pour vérifier le blueprint paramétré sans transport depuis les paquets publics :

```bash
state_machine_dir="$(mktemp -d)"
cat > "$state_machine_dir/invoice-lifecycle.yaml" <<'YAML'
version: 1
state_field: status
initial_state: draft
states: [draft, submitted, approved]
transitions:
  - name: submit
    from: [draft]
    to: submitted
  - name: approve
    from: [submitted]
    to: approved
YAML
uvx --from arclith-cli==0.29.0 --with arclith==0.32.0 \
  arclith-cli new Invoice invoice-service \
  --dir "$state_machine_dir" \
  --profile state-machine \
  --spec "$state_machine_dir/invoice-lifecycle.yaml"
cd "$state_machine_dir/invoice-service"
uv sync
uv run pytest tests/domain tests/application -q
```

Le smoke doit aussi vérifier le refus de l'affectation directe et de
`model_copy(update={"status": ...})`, puis la transition autorisée
`draft -> submitted` et le conflit de version du compare-and-swap.

## Release 0.32.0 : catalogue complet

Arclith **0.32.0** et arclith-cli **0.29.0** publient Job, Synchronization et
Workflow, en complément de CRUD, Append-only et State-machine. La CLI exige
`arclith>=0.32.0` ; les nouveaux projets reprennent la version du framework
installé comme minimum. Les formats et recettes historiques restent lisibles.

Après publication, installer les versions exactes depuis l'index officiel,
sans cache ni source locale :

```bash
uv venv .venv-release --python 3.13
uv pip install --python .venv-release/bin/python --no-cache \
  --default-index https://pypi.org/simple \
  arclith==0.32.0 arclith-cli==0.29.0 pytest pytest-asyncio
.venv-release/bin/arclith-cli version
.venv-release/bin/arclith-cli blueprints --json
```

Vérifier les six entrées du catalogue, puis générer un projet frais par
blueprint et exécuter ses tests. Les guides [Job](blueprints/job.md),
[Synchronization](blueprints/synchronization.md) et
[Workflow](blueprints/workflow.md) donnent les commandes et les specs publiques.
Valider aussi les scénarios d'exécution : soumission Job idempotente, reprise
incrémentale après page partielle, finalisation full et reprise Workflow après
un checkpoint non confirmé avec la même clé d'exécution.

Les stores et runners mémoire restent non durables. La publication des paquets
n'ajoute aucun transport ni adaptateur persistant aux projets consommateurs.
