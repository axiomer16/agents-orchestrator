from __future__ import annotations
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table

from .workspace import Workspace, find_workspace_root, init_workspace, AGENTS_DIR
from agents_cli.loader import load_registry

from rich.table import Table
from .runner import add_task, load_queue, run_queue


app = typer.Typer(help="Orchestrateur multi-agents local.", no_args_is_help=True)
console = Console()


def _load_ws() -> Workspace:
    root = find_workspace_root()
    if root is None:
        console.print(f"[red]Aucun dossier {AGENTS_DIR}/ trouvé. Lance `agents init`.[/red]")
        raise typer.Exit(1)
    try:
        return Workspace.load(root)
    except Exception as e:  # erreurs de parsing → message clair
        console.print(f"[red]Erreur de chargement :[/red] {e}")
        raise typer.Exit(1)


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Racine du projet"),
    force: bool = typer.Option(False, "--force", "-f", help="Écrase les fichiers existants"),
):
    """Crée le squelette .agents/ dans un projet."""
    root = path.resolve()
    created = init_workspace(root, force=force)
    if not created:
        console.print(f"[yellow]{AGENTS_DIR}/ déjà présent, rien créé (utilise --force).[/yellow]")
        return
    console.print(f"[green] {len(created)} fichier(s) créé(s) dans {root / AGENTS_DIR}[/green]")
    for p in created:
        console.print(f"  • {p.relative_to(root)}")
    console.print("\n[bold]Prochaine étape :[/bold] remplis project.md et architecture.md.")


@app.command()
def status():
    """Affiche agents, modèles et skills détectés."""
    ws = _load_ws()
    console.print(f"[bold]Workspace :[/bold] {ws.root}\n")

    t = Table(title="Agents")
    for col in ("Agent", "Rôle", "Provider", "Modèle", "Fallback", "Skills", "Tools"):
        t.add_column(col)
    for name, a in ws.agents.items():
        m = ws.models.agents.get(name)
        t.add_row(
            name, a.role,
            m.provider if m else "[red]—[/red]",
            m.model if m else "[red]—[/red]",
            (m.fallback or "") if m else "",
            ", ".join(a.skills), ", ".join(a.tools),
        )
    console.print(t)

    s = Table(title="Skills")
    s.add_column("Nom"); s.add_column("Portée"); s.add_column("Description")
    for sk in ws.skills.values():
        s.add_row(sk.name, sk.scope, sk.description)
    console.print(s)

    if ws.warnings:
        console.print("\n[yellow] Avertissements :[/yellow]")
        for w in ws.warnings:
            console.print(f"  • {w}")
    else:
        console.print("\n[green] Configuration cohérente.[/green]")


@app.command()
def show(name: str):
    """Affiche le prompt système complet d'un agent, ou le corps d'un skill."""
    ws = _load_ws()
    if name in ws.agents:
        a = ws.agents[name]
        console.rule(f"Agent {a.name} — {a.path}")
        console.print(a.system_prompt)
    elif name in ws.skills:
        sk = ws.skills[name]
        console.rule(f"Skill {sk.name} — {sk.path}")
        console.print(sk.body)
    else:
        console.print(f"[red]'{name}' n'est ni un agent ni un skill.[/red]")
        raise typer.Exit(1)

PATH_ARG = typer.Argument(Path("."), help="Racine du projet")


@app.command("roles")
def cmd_roles(path: Path = PATH_ARG) -> None:
    """Liste les rôles disponibles pour ce projet."""
    reg = load_registry(path)
    table = Table("Rôle", "Alias", "Modèle", "Provider", "Skills")
    for role in reg.roles.values():
        model, provider = reg.resolve_model(role)
        table.add_row(
            role.name,
            role.model_alias,
            model,
            provider,
            ", ".join(role.skills) or "-",
        )
    console.print(table)


@app.command("skills")
def cmd_skills(path: Path = PATH_ARG) -> None:
    """Liste les skills disponibles pour ce projet."""
    reg = load_registry(path)
    table = Table("Skill", "Description")
    for skill in reg.skills.values():
        table.add_row(skill.name, skill.description)
    console.print(table)


@app.command("prompt")
def cmd_prompt(role: str, path: Path = PATH_ARG) -> None:
    """Affiche le prompt final d'un rôle (base + contexte projet + skills)."""
    reg = load_registry(path)
    if role not in reg.roles:
        console.print(f"[red]Rôle inconnu :[/] {role}")
        console.print("Rôles disponibles : " + ", ".join(reg.roles))
        raise typer.Exit(1)
    console.print(reg.roles[role].build_prompt(reg.skills, reg.context))

@app.command("task")
def cmd_task(goal: str, agent: str = "codeur",
             files: list[str] = typer.Option([], "--file", "-f"),
             path: Path = PATH_ARG) -> None:
    """Ajoute une tâche à la queue."""
    t = add_task(path, goal, agent, files)
    console.print(f"[green]✓[/] {t['id']} → {agent} : {goal}")


@app.command("tasks")
def cmd_tasks(path: Path = PATH_ARG) -> None:
    """Liste les tâches et leur statut."""
    table = Table("ID", "Agent", "Statut", "Essais", "Objectif")
    for t in load_queue(path):
        table.add_row(t["id"], t["agent"], t["status"], str(t.get("attempts", 0)), t["goal"][:60])
    console.print(table)


@app.command("run")
def cmd_run(task_id: str = typer.Argument(None), path: Path = PATH_ARG) -> None:
    """Exécute les tâches prêtes (ou une seule si ID donné), avec retries."""
    run_queue(path, console, only=task_id)

if __name__ == "__main__":
    app()
