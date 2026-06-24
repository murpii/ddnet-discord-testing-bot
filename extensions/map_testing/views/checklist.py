import discord
from typing import List, Set

from utils.text import extract_ids_from_mentions, user_ids_to_mentions

CHECKLIST_TASKS = [
    "1. Map follows all mapping rules (https://ddnet.org/rules)",
    "2. Checked for ways to escape the map",
    "3. Checked for other skips: weapons, /spec, teleporter, team 0, keeping powerups",
    "4. Teleporters are working and used properly",
    "5. Switches are working and used properly",
    "6. Special tiles are only used where necessary",
    "7. Difficulty is kept consistent",
    "8. No spacing issues (for the respective map type)",
    "9. Equal amount of playtime for all players",
    "10. Server settings are working as intended",
    "11. Unfreeze is used conveniently",
    "12. Reviewed testing bot warnings",
    "13. Checked for entity bugs",
    "14. Decoration layers are marked as HD",
    "15. Used assets are as optimized as possible",
    "16. Checked for design bugs",
]

BUTTONS_PER_ROW = 5  # 5 is the Discord maximum per row
CHECKLIST_COLOUR = discord.Color.blurple()
MENTION_PREFIX = "-> "


def checklist_text_from_message(message: discord.Message) -> str:
    def walk(components):
        for comp in components:
            content = getattr(comp, "content", None)
            if isinstance(content, str):
                yield content
            children = getattr(comp, "children", None)
            if children:
                yield from walk(children)

    parts = list(walk(message.components))
    # backwards compatibility
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            parts.append(f"{field.name}\n{field.value}")

    return "\n".join(parts)


def parse_checklist_state(text: str) -> List[Set[int]]:
    """Reconstruct per-task completion sets from rendered checklist text.

    Walks the lines in order: each ``[ ]``/``[x]`` line is the next task, and an
    immediately following ``-> <mentions>`` line lists who completed it.
    """
    state: List[Set[int]] = [set() for _ in range(len(CHECKLIST_TASKS))]
    lines = text.split("\n")

    line_index = 0
    task_index = 0
    while line_index < len(lines) and task_index < len(CHECKLIST_TASKS):
        line = lines[line_index]
        if line.startswith("["):
            next_index = line_index + 1
            if next_index < len(lines) and lines[next_index].strip().startswith(MENTION_PREFIX):
                ids = extract_ids_from_mentions(lines[next_index], MENTION_PREFIX)
                state[task_index].update(ids)
                line_index = next_index + 1
            else:
                line_index = next_index
            task_index += 1
        else:
            line_index += 1

    return state


class ChecklistView(discord.ui.LayoutView):
    """Testers toggle tasks, the text updates"""

    def __init__(self, task_completion_users: List[Set[int]] | None = None):
        super().__init__(timeout=None)
        self.task_completion_users: List[Set[int]] = (
            task_completion_users
            if task_completion_users is not None
            else [set() for _ in range(len(CHECKLIST_TASKS))]
        )

        container = discord.ui.Container(
            discord.ui.TextDisplay(self._render_checklist()),
            accent_colour=CHECKLIST_COLOUR,
        )
        buttons = [TaskCheckButton(task_index=i) for i in range(len(CHECKLIST_TASKS))]
        for start in range(0, len(buttons), BUTTONS_PER_ROW):
            container.add_item(discord.ui.ActionRow(*buttons[start:start + BUTTONS_PER_ROW]))
        self.add_item(container)

    def _render_checklist(self) -> str:
        unchecked, checked = "[ ]", "[x]"
        entries = []
        for task_index, completed_user_ids in enumerate(self.task_completion_users):
            count = len(completed_user_ids)
            if count == 0:
                status = unchecked
            elif count == 1:
                status = checked
            else:
                status = f"{checked} (x{count})"

            line = f"{status} {CHECKLIST_TASKS[task_index]}"
            if completed_user_ids:
                line += f"\n{MENTION_PREFIX}{user_ids_to_mentions(completed_user_ids)}"
            entries.append(line)

        return "## Checklist\n" + "\n".join(entries)


class TaskCheckButton(discord.ui.Button):
    """A single checklist task; clicking toggles the user's completion"""

    def __init__(self, task_index: int):
        super().__init__(
            label=str(task_index + 1),
            style=discord.ButtonStyle.secondary,
            custom_id=f"check_task_{task_index}",
        )
        self.task_index = task_index

    async def callback(self, interaction: discord.Interaction) -> None:
        state = parse_checklist_state(checklist_text_from_message(interaction.message))

        task_users = state[self.task_index]
        if interaction.user.id in task_users:
            task_users.discard(interaction.user.id)
        else:
            task_users.add(interaction.user.id)

        await interaction.response.edit_message(
            content=None,
            embed=None,
            attachments=[],
            view=ChecklistView(state),
            allowed_mentions=discord.AllowedMentions.none(),
        )
