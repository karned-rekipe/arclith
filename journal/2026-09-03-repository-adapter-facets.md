# Facets et matrice de choix des adapters repository

## Contexte

L'issue #159 demande d'aider un développeur ou un agent de code à choisir un
adapter repository à partir de garanties explicites. Le catalogue listait déjà
`memory`, `mongodb`, `duckdb`, `mariadb` et `postgresql`, mais sa sortie JSON ne
décrivait ni leur runtime, ni leur partage multi-processus, ni leurs compromis
de transaction et de schéma.

## Décisions

- ajouter un objet `AdapterFacets` optionnel et typé à `AdapterSpec` ;
- sérialiser une forme stable contenant modèle de stockage, runtime, maturité
  production, partage multi-processus, transactions, stratégie de schéma,
  usages recommandés et limites ;
- renseigner les cinq adapters repository déjà présents sans modifier leur
  configuration ni le contrat `Repository[T]` ;
- conserver l'affichage texte compact et exposer le détail dans
  `arclith-cli capabilities --json` ;
- maintenir un seul port repository : SQL et NoSQL restent des familles
  d'implémentation tant qu'aucune responsabilité relationnelle spécifique
  n'entre dans le contrat ;
- documenter explicitement les frontières avec `storage` et `vector-store`.

## Impact

Les consommateurs JSON peuvent comparer les adapters sans analyser du texte
libre. Les autres capabilities sérialisent `facets: null`, ce qui permet une
adoption progressive sans leur imposer la taxonomie de persistance.

Il n'y a aucun changement de configuration, de dépendance, de port du domaine
ou de comportement runtime.

## Documentation

La page `docs/capabilities/repository.md` suit désormais la structure canonique
et contient deux matrices : choix fonctionnel et garanties techniques. L'index
des capabilities et le quickstart historique renvoient vers cette décision.

## Validation

- tests ciblés du catalogue : 23 passés ;
- `make quality` : 1 837 passés, 5 ignorés, couverture 90,64 % ;
- `make precommit` : Ruff, mypy et Bandit passés ;
- suite CLI complète : 149 passés, 1 ignoré ;
- lint CLI ciblé : passé ;
- `make docs` : build MkDocs strict passé.
