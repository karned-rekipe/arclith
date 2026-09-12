# Cockpit et guide interactif Arclith CLI

Le cockpit plein écran transforme la CLI en espace de travail persistant : vous
choisissez le résultat attendu, Arclith construit un plan complet, affiche les
commandes équivalentes, génère le projet, puis permet de l'inspecter et de lancer
ses transports sans quitter l'interface.

```bash
arclith-cli
```

Dans un vrai terminal, cette commande ouvre la TUI plein écran. Dans un pipe, un script,
une CI ou un terminal déclaré `TERM=dumb`, elle conserve le comportement
non-interactif historique et affiche l'aide avec un code de sortie `0`. Pour
ouvrir explicitement le cockpit :

```bash
arclith-cli tui
```

Le guide Questionary historique reste disponible comme interface de repli et
pour le catalogue avancé complet :

```bash
arclith-cli guide
```

## Interface plein écran

La TUI repose sur des écrans distincts et conserve le moteur de planification
indépendant de l'interface :

- un accueil pour créer ou ouvrir un projet ;
- un formulaire adaptatif couvrant les six intentions Arclith ;
- un aperçu permanent du plan et des commandes directes ;
- une progression visible pendant la génération atomique ;
- un tableau de bord fondé sur l'état réel du disque ;
- un cockpit runtime avec sélection du transport, logs, démarrage, arrêt et
  redémarrage ;
- une disposition réduite automatiquement dans les terminaux étroits ;
- navigation clavier, footer de raccourcis et palette de commandes Textual.

Les raccourcis principaux du tableau de bord sont `s` pour démarrer, `x` pour
arrêter, `r` pour actualiser, `n` pour un nouveau projet, `g` pour le guide
avancé et `q` pour quitter. Un runtime actif est arrêté avant la fermeture de
l'application afin de ne pas laisser de processus orphelin.

## Créer par intention

L'écran de création ne demande pas de connaître les commandes Arclith. Il propose
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

## Continuer dans le tableau de bord

Après la création, le cockpit reste ouvert sur le nouveau projet. Lancé depuis
n'importe quel sous-répertoire d'un projet Arclith, il retrouve automatiquement
la racine et affiche :

- les entités détectées dans le domaine ;
- les ports inbound existants ;
- les features applicatives déclarées ;
- les adapters réellement installés ;
- les anomalies de manifeste ou de recette.

Le guide avancé permet ensuite d'ajouter une entité, un cas d'usage ou n'importe quel
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

## Lancer le projet

Le tableau de bord sélectionne les transports réellement installés et permet de
les démarrer, arrêter ou redémarrer tout en conservant leurs logs dans un panneau
dédié. La même opération reste disponible hors TUI, en avant-plan :

```bash
arclith-cli run api
```

La commande retrouve la racine depuis n'importe quel sous-répertoire, vérifie
que l'adapter correspondant est réellement installé, puis exécute le point
d'entrée généré avec `uv`. Le host, le port et le reload restent définis dans
`config/adapters/inbound/fastapi.yaml`; `run` n'introduit pas de seconde
configuration. L'URL locale est affichée avant le démarrage et `Ctrl+C` arrête
le processus.

Les autres modes du point d'entrée généré sont également disponibles lorsqu'ils
ont leurs adapters :

```bash
arclith-cli run mcp_http
arclith-cli run mcp_sse
arclith-cli run bus
arclith-cli run all
```

Le processus reste volontairement attaché au terminal : la CLI ne crée ni
daemon caché, ni fichier PID global, ni runtime concurrent. Cette propriété
garantit une propagation normale des logs, du code de sortie et des signaux.

Pour retrouver toutes les options spécialisées, utilisez toujours :

```bash
arclith-cli --help
arclith-cli <commande> --help
```
