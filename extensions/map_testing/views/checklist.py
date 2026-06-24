import re
import discord
from typing import List, Set

from utils.text import extract_ids_from_mentions, user_ids_to_mentions

CHECKLIST_TASKS = [
    "1. Map follows all [mapping rules](https://ddnet.org/rules).",
    "2. Checked for escapes and other skips: weapons, /spec, teleporter, team 0, keeping powerups.",
    "3. Teleporters and switches are working and used properly.",
    "4. Special tiles are only used where necessary.",
    "5. Difficulty is kept consistent.",
    "6. No spacing issues (for the respective map type).",
    "7. Equal amount of playtime for all players.",
    "8. Server settings are working as intended.",
    "9. Unfreeze is used conveniently.",
    "10. Reviewed testing bot warnings.",
    "11. Checked for entity bugs.",
    "12. Checked for design bugs, HD decoration layers, and optimized assets.",
]

CHECKLIST_COLOUR = discord.Color.blurple()
MENTION_PREFIX = "-> "
# backwards compatibility
TASK_LINE_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?(?:\(x\d+\)\s*)?\d+\.\s")


def normalize_mention_line(line: str) -> str:
    return line.strip().removeprefix("-# ").lstrip()


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
        if TASK_LINE_RE.match(line):
            next_index = line_index + 1
            mention_line = normalize_mention_line(lines[next_index]) if next_index < len(lines) else ""
            if mention_line.startswith(MENTION_PREFIX):
                ids = extract_ids_from_mentions(mention_line, MENTION_PREFIX)
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

        sections = [
            discord.ui.Section(
                self.render_task(task_index),
                accessory=TaskCheckButton(task_index, checked=bool(completed_user_ids)),
            )
            for task_index, completed_user_ids in enumerate(self.task_completion_users)
        ]
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## Checklist"),
                *sections,
                accent_colour=CHECKLIST_COLOUR,
            )
        )

    def render_task(self, task_index: int) -> str:
        # No "[ ]"/"[x]" marker: the accessory button shows the checkmark, and the
        # mention subtext (if any) shows who completed the task.
        completed_user_ids = self.task_completion_users[task_index]
        line = CHECKLIST_TASKS[task_index]
        if completed_user_ids:
            line += f"\n-# {MENTION_PREFIX}{user_ids_to_mentions(completed_user_ids)}"
        return line


class TaskCheckButton(discord.ui.Button):
    """A single checklist task; clicking toggles the user's completion"""

    def __init__(self, task_index: int, checked: bool = False):
        super().__init__(
            label="[✓]" if checked else "[ ]",
            style=discord.ButtonStyle.success if checked else discord.ButtonStyle.secondary,
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
