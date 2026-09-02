# Documentation du POC Vault local

## Contexte

Les capabilities Vault étaient configurables par la CLI, mais le tutoriel Todo ne fournissait pas de
serveur local, de seed KV v2 ni de preuve exécutable pour les deux modes de résolution.

## Décisions

- utiliser Vault 2.1.0 avec `server -dev` explicite, lié à `127.0.0.1` et sans volume persistant ;
- conserver le token jetable hors Git et l'exiger par variable d'environnement dans le script ;
- fournir un script `set -euo pipefail` qui active le mount KV v2 et écrit des valeurs locales
  idempotentes pour le service et le tenant, avec timeouts réseau bornés et rejet d'un mount
  homonyme qui ne serait pas en KV v2 ;
- utiliser les commandes existantes `secrets/vault` et `tenant/vault`, sans placeholder ;
- vérifier le secret applicatif au chargement d'`Arclith` et les coordonnées tenant via le resolver,
  sans afficher les URI.

## Impact

Le développeur peut valider localement les deux contrats Vault sans compte managé ni modification du
domaine Todo. Le serveur dev et ses credentials de démonstration restent strictement hors production.

## Validation

- syntaxe du script avec `bash -n` et analyse `shellcheck` réussies ;
- commandes CLI exécutées dans un projet fraîchement généré ;
- smoke Docker avec Vault 2.1.0, seed rejoué deux fois, secret applicatif chargé et tenant
  `client-a` résolu ;
- `make docs` et `make precommit`.
