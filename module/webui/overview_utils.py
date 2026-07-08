def split_overview_tasks(pending_tasks, waiting_tasks, is_alive: bool):
    if not pending_tasks:
        return [], [], waiting_tasks
    if is_alive:
        return pending_tasks[:1], pending_tasks[1:], waiting_tasks
    return [], pending_tasks[:], waiting_tasks
