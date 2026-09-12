# Guide interactif Arclith CLI

Le guide interactif transforme la CLI en session persistante : vous choisissez
le résultat attendu, Arclith construit un plan complet, affiche les commandes
équivalentes, puis attend une confirmation unique avant d'écrire.

```bash
arclith-cli
```

Dans un vrai terminal, cette commande ouvre le guide. Dans un pipe, un script,
une CI ou un terminal déclaré `TERM=dumb`, elle conserve le comportement
non-interactif historique et affiche l'aide avec un code de sortie `0`. Pour
ouvrir explicitement le guide :

```bash
arclith-cli guide
```

## Créer par intention

Le premier écran ne demande pas de connaître les commandes Arclith. Il propose
six résultats :

| Intention | Cœur généré | Décisions techniques explicites | Exposition |
|---|---|---|---|
| Socle minimal | projet vide, entité optionnelle | aucune | aucune |
| API REST CRUD | entité et cinq cas d'usage CRUD | repository + FastAPI | cinq routes REST |
| API REST sur mesure | entité et un cas d'usage | repository + FastAPI | une route typée |
| Serveur MCP | entité et un cas d'usage | repository + FastMCP | un outil MCP |
| Agent LangGraph | entité et un cas d'usage | repository + LangGraph | un nœud de graphe |
| Worker RabbitMQ | entité et un cas d'usage | repository + RabbitMQ | une commande versionnée |

Le repository n'est jamais déduit du transport. Pour chaque parcours complet,
vous choisissez explicitement `memory`, `mongodb` ou `postgresql`. De même, un
profil CRUD décrit le comportement applicatif ; il n'installe pas FastAPI tout
seul.

Avant génération, le récapitulatif présente chaque décision et sa commande
directe équivalente. Exemple :

```text
1  Initialiser catalog-service       arclith-cli init catalog-service
2  Ajouter l'entité Product (crud)   arclith-cli add-entity Product --profile crud
3  Ajouter repository/memory         arclith-cli add-adapter ...
4  Ajouter api/fastapi               arclith-cli add-adapter ...
5  Exposer la feature product        arclith-cli expose-feature ...
```

Ces commandes restent utilisables indépendamment dans un script. Les paramètres
secrets éventuellement saisis dans le parcours avancé sont masqués dans le plan
et dans `arclith.recipe.yaml`.

## Continuer dans le même menu

Après la création, le guide reste ouvert sur le nouveau projet. Lancé depuis
n'importe quel sous-répertoire d'un projet Arclith, il retrouve automatiquement
la racine et affiche :

- les entités détectées dans le domaine ;
- les ports inbound existants ;
- les features applicatives déclarées ;
- les adapters réellement installés ;
- les anomalies de manifeste ou de recette.

Le menu permet ensuite d'ajouter une entité, un cas d'usage ou n'importe quel
adapter du catalogue, puis d'exposer un cas d'usage via FastAPI, FastMCP,
LangGraph ou RabbitMQ. Une action impossible reste désactivée tant que ses
prérequis ne sont pas présents.

La CLI ne peut pas changer le répertoire courant du shell parent. À la fin d'une
création, elle affiche donc la commande `cd <projet>` à copier ; sa propre session
utilise immédiatement le nouveau projet sans demander de relancer la CLI.

## Écritures sûres et recette

Le plan d'un nouveau projet est exécuté dans un répertoire temporaire situé sur
le même système de fichiers. La cible finale n'apparaît qu'après la réussite de
toutes les étapes. Une erreur ou une interruption nettoie le staging et ne laisse
pas de projet partiel. Une cible existante n'est jamais remplacée.

Chaque étape réussie alimente `arclith.recipe.yaml` avec les mêmes informations
que sa commande directe : paramètres résolus, version et empreinte des
blueprints, fichiers créés ou modifiés, et références de secrets sans leur
valeur. Le menu « Rejouer une recette » reconstruit lui aussi une nouvelle cible
par staging atomique et utilise le mode de compatibilité strict.

## Inspection et automatisation

Le tableau de bord est également disponible hors du guide :

```bash
arclith-cli status
arclith-cli status --json
arclith-cli doctor
```

`status` lit l'état courant du disque ; il ne suppose pas que la recette reflète
encore exactement le projet. La sortie JSON est adaptée aux scripts. `doctor`
retourne un code non nul si le projet est introuvable ou si un manifeste ou la
recette est absent ou illisible.

Pour retrouver toutes les options spécialisées, utilisez toujours :

```bash
arclith-cli --help
arclith-cli <commande> --help
```
