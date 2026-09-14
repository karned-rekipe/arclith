# Blueprint state-machine paramétré

## Contexte

L'issue #223 est la phase 2 de l'epic #221, après le blueprint append-only livré
par #222. Elle introduit le premier blueprint dont les opérations viennent d'une
spécification métier plutôt que d'un catalogue statique.

## Décisions

- La spec V1 est chargée et validée dans un module dédié, puis convertie en
  paramètres canoniques indépendants de son chemin local.
- Les états, sources et transitions sont triés pour rendre génération et digest
  insensibles à l'ordre accidentel des listes YAML.
- Un état inaccessible est refusé. La V1 ne génère pas de code mort assorti d'un
  simple warning.
- Chaque transition devient une méthode de domaine, un port inbound et un use
  case nommés. Aucun dispatcher dynamique par chaîne n'est introduit.
- Le champ d'état créé avec l'entité est typé, validé à l'affectation et frozen.
  `model_copy` rejette aussi ce champ ; le service passe par une copie privée
  dédiée. Une entité existante doit fournir explicitement un enum vérifiable ou
  un `Literal` avec les mêmes protections ; la CLI ne patche pas son fichier.
- L'enum de matrice générée utilise le module dédié `<entité>_lifecycle_state.py`,
  afin de préserver sans collision une enum métier existante importée depuis le
  chemin conventionnel `<entité>_state.py`.
- Les annotations `Literal` et les bases `Enum` sont résolues jusqu'à leur origine
  `typing`/stdlib, y compris via alias et réexports de packages `__init__.py` ;
  les homonymes locaux et helpers de copie asynchrones sont refusés, comme
  `use_enum_values=True` pour un champ enum. Une
  seule affectation effective et statique de `model_config` est admise ; les
  helpers doivent garder leurs signatures d’instance sans décorateur, tester
  `update is not None` avant l'appartenance et appeler le builtin `super` non
  masqué au module comme dans les helpers. La garde publique doit lever le builtin
  `ValueError` avec un message `lifecycle`, et toute liaison de `__setattr__` dans
  le scope de classe est refusée. Les defaults enum ou `Literal` doivent être
  statiquement vérifiables ; `default_factory`, les expansions dynamiques et les
  dépendances redéfinies dans le scope de classe ou un contrôle de flux module
  sont refusés. Les racines d'import du projet ne peuvent pas masquer `abc`,
  `arclith`, `collections`, `dataclasses`, `datetime`, `enum`, `pydantic`,
  `pytest`, `typing`, `typing_extensions` ou `uuid`, y compris avant la création
  d'une entité. Les captures `except ... as` et les motifs `match ... as` comptent aussi
  comme des liaisons et ne peuvent pas masquer les builtins ou helpers contrôlés.
  Les décorateurs, bases, mots-clés de classe et defaults de fonctions ou lambdas
  sont inspectés dans le scope où ils s'exécutent, y compris pour un callable
  imbriqué, sans confondre son corps avec le scope englobant.
  Le champ d'état ne peut avoir qu'une liaison dans la classe, ses alias et enums
  doivent être disponibles au runtime avant son usage, et une enum ne peut pas
  cacher des membres runtime derrière un contrôle de flux, une expression
  dynamique, une base mixte autre que `str, Enum`, une méthode ou un décorateur.
  Les tests générés dérivent la valeur de l'annotation réelle et
  en vérifient le type. Les erreurs not-found conservent l'objet UUID demandé
  dans un attribut typé ; les
  conflits exposent toujours les versions observée/attendue, avant le CAS comme
  lors d'une course atomique dans l'adapter.
  Les modules d'entités existants doivent être des identifiants Python non
  réservés, et les helpers standard des artefacts générés sont importés sous des
  alias internes pour accepter sans collision des entités telles que `Enum` ou
  `ValidationError`.
  Une entité existante doit avoir une unique base directe résolue vers le vrai
  `Entity` Arclith, sans mixin, décorateur ni mot-clé de classe. Les enums
  qualifiées par un alias de module et leurs defaults qualifiés sont résolues
  statiquement ; les alias de `Literal` réexportés par un module ou package du
  projet sont suivis récursivement jusqu'à `typing` ou `typing_extensions`.
- La persistance dépend d'un port outbound spécialisé `compare_and_swap`. Son
  contrat exige une comparaison atomique de version ; une lecture suivie d'un
  update inconditionnel n'est pas présentée comme sûre.
- Le manifeste paramétré passe en version 2 et embarque `parameters`, le digest
  du template et le digest des paramètres. Les manifests V1 restent strictement
  lisibles et rejouables sans conversion.
- La recette stocke la configuration résolue, jamais le chemin de `--spec`, et
  exige ses deux digests, la version du blueprint et les opérations canoniques
  lors du préflight global, avant toute écriture de replay.
  Les paramètres absents ou mal formés et les noms de blueprint absents ou
  inconnus sont normalisés en `RecipeError`. Un profil `minimal` refuse les
  métadonnées d'un blueprint paramétré au lieu de les ignorer.
  Cette règle est appliquée aussi par les APIs partagées de métadonnées et de
  planification, même lorsqu'elles sont appelées sans passer par la CLI.
  Le digest du template couvre le source complet des renderers, des helpers de
  nommage, chemins, inspection d'entité et initialisation de packages, et
  versionne aussi le contrat de validation des entités existantes, sans modifier
  les anciens digests CRUD/append-only.
- `new` planifie le profil et valide le nom d'entité contre un layout `src`
  virtuel avant toute initialisation. Les `__init__.py` vides que `init` créera
  sont les seuls snapshots intermédiaires anticipés ; une entrée invalide ne
  laisse donc aucun projet partiel et reçoit le diagnostic CLI normalisé.
- La création de l'entité et l'application du blueprint partagent une frontière
  de compensation. Une collision apparue après le plan ou une erreur d'écriture
  détache atomiquement les fichiers déjà publiés vers une quarantaine privée,
  puis ne retire que les publications dont l'inode, le device et le contenu
  correspondent encore à la commande. Un remplacement concurrent est restauré
  sans écrasement, et les répertoires ne sont compensés que si leur identité
  prouve qu'ils ont été créés par cette commande. Les fichiers sont entièrement
  écrits et synchronisés dans un temporaire du même répertoire avant publication
  atomique sans remplacement ; aucun fichier tronqué ou contenu concurrent
  supprimé n'est donc exposé.

## Validation

- `uv run --project cli python -m pytest cli/tests -q` : 730 tests passés ;
- smoke test du projet généré : 19 tests passés ;
- `make precommit` : Ruff, mypy (232 fichiers) et Bandit passés ;
- `make coverage` : 2 488 tests passés, 5 ignorés et 91,34 % sur 9 264
  statements et 2 142 branches ;
- `make docs` : build MkDocs strict passé ;
- `uv build cli` : sdist et wheel `arclith-cli` 0.27.0 construits ;
- installation isolée sans cache du wheel, génération et compilation d'un projet
  frais contre `arclith` 0.30.0, puis refus de la copie générique et transition
  `draft -> submitted` vérifiés.
