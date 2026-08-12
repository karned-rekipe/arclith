# Format D'une Page

Une page de formation Arclith traite une seule idée.

## Structure

Chaque page suit ce format :

1. objectif ;
2. prérequis ;
3. étapes ;
4. validation ;
5. erreur fréquente ;
6. capture ou vidéo ;
7. page suivante.

## Règle

Si une page devient longue, elle doit être découpée.

Le détail technique va dans une page d'approfondissement. Le parcours principal doit rester
exécutable sans changer de contexte.

## Bloc Média

Utiliser ce bloc quand une capture ou une vidéo doit être ajoutée :

```md
!!! note "Média à produire"
    Capture attendue : écran, terminal ou schéma.
    Vidéo attendue : durée cible et scénario.
```

Les règles de production sont dans [Captures et vidéos](media.md).

## Validation

Chaque page opérationnelle doit fournir une commande ou une observation concrète.

Exemples :

```bash
curl -fsS http://127.0.0.1:9000/health
uv run pytest
docker compose ps
```
