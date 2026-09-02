# POC Keycloak local pour le tutoriel Todo

## Contexte

Les capabilities `auth/keycloak`, `license/role` et `tenant/vault` existent déjà, mais le tutoriel
local ne proposait ni realm importable ni preuve reproductible du flux PKCE/JWKS et des claims.

## Décisions

- épingler l'image officielle Keycloak `26.7.3` et importer un realm jetable au démarrage ;
- lier le port à `127.0.0.1` et marquer explicitement tous les identifiants comme données de POC ;
- créer un client public `todo-swagger` limité au redirect URI local et imposant PKCE S256 ;
- ajouter l'audience `todo-api`, le rôle realm `rekipe:licensed` et le claim `tenant_id` attendu par
  les contrats Arclith existants ;
- fournir `alice` avec licence et tenant `client-a`, puis `bob` sans licence pour couvrir le refus
  `403` ;
- conserver le Direct Access Grant uniquement pour le smoke shell déterministe, Swagger utilisant
  Authorization Code avec PKCE ;
- fixer les access tokens à cinq minutes et documenter le lien entre rotation des clés et cache
  JWKS ;
- permettre de télécharger le realm et le script depuis un tag ou SHA via `ARCLITH_REF` ;
- sélectionner `python3`, puis `python` en fallback, tout en permettant une surcharge explicite par
  `PYTHON_BIN` pour rendre le smoke portable.

## Validation

- JSON validé avec `jq empty` ;
- syntaxe et règles shell vérifiées avec `bash -n` et `shellcheck` ;
- configuration `auth` + `license` + `tenant` générée par la CLI puis chargée par `Arclith` ;
- import réel du realm dans le container Keycloak épinglé ;
- document OIDC et JWKS lus depuis le realm local ;
- requête Authorization Code sans challenge rejetée par Keycloak avec `invalid_request` ;
- tokens `alice` et `bob` obtenus sans être affichés ;
- audience, issuer, rôle licence et `tenant_id=client-a` vérifiés ;
- signature et audience du token validées par le `JWTDecoder` Arclith contre le JWKS local ;
- claim `client-a` résolu jusqu'aux coordonnées MongoDB seedées dans Vault par le pipeline Arclith ;
- OpenAPI vérifié avec le schéma Authorization Code et PKCE activé ;
- route FastAPI réelle vérifiée avec les statuts `401`, `200` et `403` ;
- `make docs` ;
- `make precommit`.
