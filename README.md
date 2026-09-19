# Agents Orchestrator

Orchestrateur d'agents IA local, conçu pour piloter plusieurs agents spécialisés
(codage, recherche, tests, revue, etc.) sur mes projets de développement, avec
gestion des connaissances projet, des skills, et des modèles locaux.

## Objectifs du projet

- Avoir un orchestrateur central capable de distribuer des tâches à des
  agents spécialisés, de relancer les agents en cas de blocage/erreur, et de
  suivre leur avancement.
- Générer automatiquement un dossier `.agents/` dans chaque projet, contenant
  l'architecture, les besoins et le contexte nécessaires aux agents.
- Permettre d'ajouter facilement des skills (Claude, communauté, custom) et
  des prompts/directives spécialisés par agent.
- Rester agnostique du modèle : possibilité de tester et brancher rapidement
  les derniers modèles locaux disponibles (Ollama, LM Studio, etc.).

## Stack technique

- Langage : Python 3.13 (portage progressif de certains modules critiques
  vers Rust à des fins d'apprentissage et de performance)
- Packaging : pyproject.toml + installation via pipx (https://pipx.pypa.io/)
- IDE : Zed

## Installation

### Prérequis

- Python >= 3.10
- pipx installé et configuré dans le PATH (https://pipx.pypa.io/stable/installation/)

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
# rouvrir le terminal
Installation du CLI
git clone <url-du-repo> agents-orchestrator
cd agents-orchestrator
pipx install -e .
Vérifier que la commande est bien accessible globalement :
agents status
Utilisation
# Initialiser un dossier .agents/ dans le projet courant
agents init

# Voir l'état des agents et de l'orchestrateur
agents status

# Lancer une tâche via l'orchestrateur
agents run "<description de la tâche>"

# Lister les agents disponibles
agents list

# Ajouter un skill à un agent
agents skill add <agent> <skill>
```

Liste de commandes à mettre à jour au fur et à mesure de l'implémentation réelle.

## Structure du projet
```
agents-orchestrator/
├── src/
│   └── agents_orchestrator/
│       ├── cli.py            # Point d'entrée CLI
│       ├── orchestrator.py   # Logique centrale de distribution des tâches
│       ├── agents/           # Définition des agents et de leurs rôles
│       ├── skills/           # Skills réutilisables par les agents
│       └── models/           # Config/connecteurs vers les modèles locaux
├── pyproject.toml
├── README.md
└── .gitignore
```

## Structure .agents/ générée dans un projet cible
Quand tu lances agents init dans un de tes projets, l'outil crée :
```
mon-projet/
└── .agents/
    ├── architecture.md   # Architecture du projet détectée/décrite
    ├── needs.md           # Besoins fonctionnels du projet
    ├── agents.yaml        # Config des agents affectés à ce projet
    └── skills/            # Skills spécifiques activés pour ce projet

```

## Rôles des agents (en cours de définition)

| Agent | Rôle |
|---|---|
| orchestrator | Distribue les tâches, supervise, relance en cas d'échec |
| coder | Implémente les features / corrige des bugs |
| reviewer | Relit le code, propose des améliorations |
| tester | Écrit et exécute les tests |
| researcher | Recherche des solutions, documentation, veille techno |

| À affiner selon l'avancement du projet.

## Modèles supportés

- Modèles locaux (Ollama / LM Studio) — testés et remplacés régulièrement pour garder la meilleure performance disponible localement.
- Intégration future : connexion à Claude via extension navigateur (Tampermonkey) — prévue plus tard.

# Développement
```
# Réinstaller après modification du code (pipx détecte les changements en mode -e)
pipx install -e . --force

# Nettoyer les métadonnées générées
rm -rf *.egg-info
```

## Roadmap

- [x] Setup CLI installable globalement (pipx)
- [x] Génération du dossier `.agents/`
- [ ] Définition complète des rôles d'agents
- [ ] Système de skills modulaire
- [ ] Relance automatique des agents en erreur
- [ ] Intégration multi-modèles locaux
- [ ] Connexion Claude via Tampermonkey
