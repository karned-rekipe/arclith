# Structure D'une Capability

Une page capability est la référence complète d'une brique Arclith.

Elle ne remplace pas le quickstart ni la formation. Elle explique le contrat,
les limites, les adapters disponibles, les décisions de production et les
validations à appliquer.

## Structure Canonique

Chaque fiche capability suit le même ordre.

| Section | Objectif |
|---|---|
| Intention | Dire à quoi sert la capability et quand ne pas l'utiliser. |
| Position Hexagonale | Préciser la couche concernée: inbound, outbound, bidirectionnelle ou runtime. |
| Quickstart | Renvoyer vers le POC le plus court quand il existe. |
| Formation | Renvoyer vers le pas à pas qui apprend le geste de construction. |
| Contrat | Décrire ports, types, configuration, erreurs et invariants. |
| Adapters | Lister les implémentations disponibles et leurs compromis. |
| Production | Couvrir sécurité, secrets, observabilité, scaling et modes de panne. |
| Validation | Donner les commandes et tests qui prouvent que la capability fonctionne. |
| Troubleshooting | Documenter les erreurs fréquentes et les diagnostics rapides. |
| Projet | Montrer où la capability apparaît dans un projet end to end. |

## Gabarit

```markdown
# <Capability>

## Intention

## Position Hexagonale

## Quickstart

## Formation

## Contrat

## Adapters

## Production

## Validation

## Troubleshooting

## Projet
```

## Règle De Lien

Une fiche capability doit toujours renvoyer vers :

1. un quickstart si le flux existe ;
2. une page de formation quand un geste de construction est nécessaire ;
3. un projet end to end quand la capability est utilisée dans un contexte réel.

## Suite

Lire le [catalogue des capabilities](../capabilities.md).
