# Securite Storage

La capability storage fournit des garde-fous de base. Elle ne remplace pas les
controles metier, les politiques cloud ou les services de securite du runtime.

## Path Traversal

Toutes les cles passent par `normalize_storage_key()` avant d'atteindre un
backend. Une cle ne peut pas etre absolue, contenir `..`, contenir `//`, finir
par `/` ou utiliser le separateur Windows `\`.

Regle d'application: ne jamais reutiliser directement un nom de fichier fourni
par l'utilisateur comme cle de stockage.

```python
from uuid6 import uuid7


def build_document_key(tenant_id: str, original_filename: str) -> str:
    extension = original_filename.rsplit(".", maxsplit=1)[-1].lower()
    return f"{tenant_id}/documents/{uuid7()}.{extension}"
```

Le nom original reste une metadata metier dans le repository, pas une partie
obligatoire de la cle objet.

## Content-Type

`content_type` est une indication de stockage, pas une preuve. Le service
consommateur doit verifier le type attendu selon son besoin: extension, magic
bytes, parseur metier ou service d'analyse.

Ne pas accepter un contenu executable uniquement parce que le client annonce
`text/plain` ou `image/png`.

## Taille Maximale

`FileStoragePort` ne decide pas d'une taille maximale globale. Le use case doit
refuser trop tot les fichiers qui depassent la politique du produit.

```python
MAX_BYTES = 10 * 1024 * 1024


def ensure_allowed_size(size: int) -> None:
    if size > MAX_BYTES:
        raise ValueError("file too large")
```

Pour les uploads HTTP, appliquer aussi une limite au niveau reverse proxy,
serveur ASGI ou middleware.

## Permissions Backend

Les credentials doivent etre bornes au strict necessaire:

- ecriture objet;
- lecture objet;
- lecture metadata;
- suppression objet si le use case le permet.

Ne pas donner de droits d'administration bucket/container a l'application. Les
operations de creation de bucket, lifecycle, retention, CORS et CDN restent de
la responsabilite de l'infrastructure.

## Isolation Tenant

En multitenant, choisir explicitement le niveau d'isolation:

| Strategie | Isolation | Cout operationnel |
|---|---|---|
| bucket ou container par tenant | forte | plus de ressources a gerer |
| prefixe par tenant | moyenne | policies plus fines et plus fragiles |
| volume filesystem par tenant | forte si volume dedie | montage et permissions a maintenir |

Le use case ne doit pas accepter un `tenant_id` arbitraire dans la cle. La cle
derive du contexte d'authentification ou du `TenantContext`.

## Hors Scope Initial

Ces controles sont volontairement hors du port initial:

- antivirus;
- quotas;
- lifecycle policies;
- CDN;
- URLs signees;
- upload multipart expose au client final;
- classification DLP;
- chiffrement applicatif bout en bout.

Ils peuvent etre ajoutes autour du use case ou dans un service specialise, sans
changer le contrat minimal de `FileStoragePort`.
