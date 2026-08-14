# Quickstart Filesystem

Ce quickstart stocke les fichiers dans un dossier conteneur `/data/files`. En
Docker, ce chemin est monte sur un volume persistant.

## Ajouter L'adapter

```bash
arclith-cli add-adapter \
  --capability storage \
  --adapter filesystem \
  --param root_path=/data/files \
  --param prefix=uploads \
  --param create_root=true \
  --param multitenant=false \
  --yes
```

Le CLI cree `config/adapters/outbound/storage.yaml`.

```yaml
# config/adapters/outbound/storage.yaml
adapter: filesystem
root_path: "/data/files"
prefix: "uploads"
create_root: true
multitenant: false
```

`load_config_dir("config")` mappe ce fichier vers `adapters.storage` puis valide
les champs avec Pydantic.

## Smoke Test Local

Creer `scripts/storage_smoke.py` dans le service consommateur:

```python
import asyncio
from collections.abc import AsyncIterator

from arclith import Arclith


async def chunks(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def main() -> None:
    storage = Arclith("config").file_storage()

    stored = await storage.put(
        "smoke/hello.txt",
        chunks(b"hello arclith\n"),
        content_type="text/plain",
        metadata={"source": "quickstart"},
    )
    assert stored.key == "smoke/hello.txt"
    assert stored.size == len(b"hello arclith\n")

    stream = await storage.get("smoke/hello.txt")
    payload = b"".join([chunk async for chunk in stream.body])
    assert payload == b"hello arclith\n"
    assert await storage.exists("smoke/hello.txt")

    await storage.delete("smoke/hello.txt")
    assert not await storage.exists("smoke/hello.txt")


asyncio.run(main())
```

Lancer le test en local si `/data/files` existe sur la machine:

```bash
sudo mkdir -p /data/files
sudo chown "$(id -u):$(id -g)" /data/files
uv run python scripts/storage_smoke.py
```

## Docker Compose Avec Volume

```yaml
# docker-compose.storage.yml
services:
  storage-smoke:
    build: .
    working_dir: /app
    command: uv run python scripts/storage_smoke.py
    volumes:
      - ./config:/app/config:ro
      - ./scripts:/app/scripts:ro
      - file-storage:/data/files

volumes:
  file-storage:
```

Validation:

```bash
docker compose -f docker-compose.storage.yml run --rm storage-smoke
docker compose -f docker-compose.storage.yml down
```

Le volume Docker conserve les objets entre deux lancements. Pour inspecter
facilement les fichiers depuis l'hote, remplacer le volume nomme par un bind
mount local:

```yaml
services:
  storage-smoke:
    volumes:
      - ./var/files:/data/files
```

## Suite

Lire [Filesystem](filesystem.md), puis [Configuration](configuration.md).
