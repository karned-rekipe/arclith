from arclith_cli.recipe_models import RecipeStep


def step_summary(step: RecipeStep) -> str:
    """Return a compact, secret-free human summary for history and dry-run."""
    args = step.args
    if step.command in {"init", "new"}:
        return str(args.get("project_name") or "project")
    if step.command == "add-adapter":
        capability = args.get("capability", "repository")
        adapter = args.get("adapter", "?")
        entities = args.get("entities") or []
        suffix = f" ({', '.join(map(str, entities))})" if entities else ""
        return f"{capability}/{adapter}{suffix}"
    if step.command == "add-usecase":
        usecase = str(args.get("usecase") or "usecase")
        entity = args.get("entity") or args.get("new_entity")
        return f"{usecase} ({entity})" if entity else f"{usecase} (transverse)"
    if step.command == "add-blueprint":
        return f"{args.get('blueprint', '?')} ({args.get('entity', '?')})"
    if step.command == "expose-feature":
        return f"{args.get('feature', '?')} -> {args.get('via', '?')}"
    for key in ("entity", "usecase", "intent"):
        if key in args:
            return str(args[key])
    return ""
