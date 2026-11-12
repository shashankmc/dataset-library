"""Provider task tags onto the host's task types (legal-ml-core's TASK_TYPES).

The host passes its task types; a tag whose type the host does not offer is
dropped, so the library never offers a task the host cannot train."""

# Hugging Face `task_categories` -> task type. Tags not listed (question
# answering, text generation, retrieval...) have no task type in legal-ml-core.
HUGGING_FACE = {
    "text-classification": "classification",
    "token-classification": "ner",
    "summarization": "summarization",
}


def hugging_face_tasks(tags, task_types):
    found = []
    for tag in tags:
        if not tag.startswith("task_categories:"):
            continue
        task = HUGGING_FACE.get(tag.removeprefix("task_categories:"))
        if task and task in task_types and task not in found:
            found.append(task)
    return found


def hugging_face_filter(task):
    """The Hub tag for a task type, or None when the Hub has none."""
    for tag, mapped in HUGGING_FACE.items():
        if mapped == task:
            return f"task_categories:{tag}"
    return None
