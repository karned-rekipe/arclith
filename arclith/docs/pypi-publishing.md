# Publication PyPI — arclith

Ce guide couvre la publication initiale et les mises à jour du package `arclith` sur PyPI.

## Prérequis

- Compte PyPI : [pypi.org](https://pypi.org)
- Token API PyPI (créer dans *Account Settings > API tokens*)
- `uv` installé et à jour

## Configuration du token

Stocker le token dans `~/.pypirc` ou via variable d'environnement :

```bash
# Option 1 — fichier ~/.pypirc
[distutils]
index-servers = pypi

[pypi]
username = __token__
password = pypi-VOTRE_TOKEN_ICI
```

```bash
# Option 2 — variable d'environnement (recommandé en CI)
export UV_PUBLISH_TOKEN=pypi-VOTRE_TOKEN_ICI
```

## Première publication

```bash
cd arclith

# 1. Vérifier la version dans pyproject.toml
grep '^version' pyproject.toml

# 2. Builder le package
uv build

# 3. Publier sur PyPI
uv publish
```

Le dossier `dist/` contient la wheel (`.whl`) et le sdist (`.tar.gz`) générés.

## Mise à jour (nouvelle version)

1. **Bump de version** dans `pyproject.toml` (Semantic Versioning) :
   - `PATCH` (0.1.x) : correctifs rétrocompatibles
   - `MINOR` (0.x.0) : nouvelles fonctionnalités rétrocompatibles
   - `MAJOR` (x.0.0) : breaking changes

2. **Mettre à jour le changelog** avant de publier.

3. **Builder et publier** :

```bash
uv build
uv publish
```

PyPI rejette automatiquement toute tentative de republier la même version — le bump est obligatoire.

## Vérification post-publication

```bash
# Installer depuis PyPI dans un environnement de test
uv run --with arclith==X.Y.Z python -c "import arclith; print(arclith.__version__)"
```

## Publication sur TestPyPI (optionnel)

Pour valider avant la vraie publication :

```bash
uv publish --publish-url https://test.pypi.org/legacy/
```

Installer depuis TestPyPI :

```bash
uv run --index https://test.pypi.org/simple/ --with arclith==X.Y.Z python -c "import arclith"
```

## CI/CD

En GitHub Actions, stocker le token dans les *Secrets* du repo (`UV_PUBLISH_TOKEN`) et déclencher la publication sur création de tag :

```yaml
- name: Build & publish
  run: uv build && uv publish
  env:
    UV_PUBLISH_TOKEN: ${{ secrets.UV_PUBLISH_TOKEN }}
```
