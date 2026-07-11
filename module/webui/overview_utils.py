def split_overview_tasks[T](
    pending_tasks: list[T],
    waiting_tasks: list[T],
    *,
    is_alive: bool,
) -> tuple[list[T], list[T], list[T]]:
    if not pending_tasks:
        return [], [], waiting_tasks
    if is_alive:
        return pending_tasks[:1], pending_tasks[1:], waiting_tasks
    return [], pending_tasks.copy(), waiting_tasks
