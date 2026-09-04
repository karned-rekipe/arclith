# Quickstarts

Ces pages servent à vérifier les flux les plus fréquents en quelques minutes.
Chaque quickstart valide un canal d'entrée Arclith, sans transformer ce test
rapide en tutoriel complet.

<div class="quickstarts-overview">
  <section class="academy-section" aria-labelledby="quickstarts-choose-title">
    <div class="academy-section__header">
      <p class="academy-eyebrow">Choisir</p>
      <h2 id="quickstarts-choose-title">Un flux, un objectif de validation</h2>
      <p>
        Commence par l'API pour voir le service tourner, puis ajoute les
        surfaces dont ton projet a besoin : MCP, bus RabbitMQ, canal conversationnel ou agent LangGraph.
      </p>
    </div>

    <div class="academy-grid academy-grid--categories">
      <a class="academy-card" href="api/">
        <img src="../assets/academy/quickstarts.png" alt="" decoding="async" loading="lazy" />
        <span class="academy-card__kicker">API</span>
        <strong>Démarrer un service HTTP</strong>
        <p>Initialiser un projet, lancer le mode API, vérifier la probe <code>/health</code> et ouvrir Swagger.</p>
      </a>

      <a class="academy-card" href="mcp/">
        <img src="../assets/academy/reference.png" alt="" decoding="async" loading="lazy" />
        <span class="academy-card__kicker">MCP</span>
        <strong>Exposer des tools</strong>
        <p>Lancer le transport MCP HTTP, contrôler <code>/info</code> et repérer l'URL FastMCP du serveur.</p>
      </a>

      <a class="academy-card" href="bus/">
        <img src="../assets/academy/production.png" alt="" decoding="async" loading="lazy" />
        <span class="academy-card__kicker">Bus</span>
        <strong>Ajouter RabbitMQ</strong>
        <p>Installer l'adapter command bus, charger la configuration et préparer le futur worker.</p>
      </a>

      <a class="academy-card" href="agent/">
        <img src="../assets/academy/training.png" alt="" decoding="async" loading="lazy" />
        <span class="academy-card__kicker">Agent</span>
        <strong>Préparer LangGraph</strong>
        <p>Ajouter l'adapter agent, générer <code>langgraph.json</code> et tester l'Agent Server local.</p>
      </a>

      <a class="academy-card" href="channel/">
        <img src="../assets/academy/reference.png" alt="" decoding="async" loading="lazy" />
        <span class="academy-card__kicker">Channel</span>
        <strong>Tester une conversation</strong>
        <p>Normaliser un message, résoudre son identité, répondre et vérifier la déduplication avec le fake mémoire.</p>
      </a>
    </div>
  </section>

  <section class="academy-section" aria-labelledby="quickstarts-path-title">
    <div class="academy-section__header">
      <p class="academy-eyebrow">Ordre recommandé</p>
      <h2 id="quickstarts-path-title">Avancer du runtime vers l'orchestration</h2>
      <p>
        L'ordre ci-dessous garde une progression simple : service local, surface
        outillée, traitement asynchrone, puis agent.
      </p>
    </div>

    <div class="academy-featured">
      <a href="api/">1. API locale</a>
      <a href="mcp/">2. MCP HTTP</a>
      <a href="bus/">3. Bus RabbitMQ</a>
      <a href="channel/">4. Channel mémoire</a>
      <a href="agent/">5. Agent LangGraph</a>
      <a href="../learning/local-ai-validation/">Validation IA locale</a>
      <a href="../tutorials/todo-list/">Projet Todo complet</a>
    </div>
  </section>
</div>

## Projet de départ

Si tu n'as pas encore de projet Arclith :

```bash
uvx --from arclith-cli arclith-cli init my-service --dir .
cd my-service
uv sync
```

Les quickstarts partent ensuite de ce dossier.

## Règle

Un quickstart valide seulement le bootstrap : l'application démarre, la
configuration est chargée et la surface technique répond.

Pour écrire du métier réel, suivre le [parcours Todo](../tutorials/todo-list/index.md).

## Suite

Commencer par [API](api.md).
