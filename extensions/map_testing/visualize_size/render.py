#!/usr/bin/env python3
# Generates plots that visualize which images/sounds take up how much of the map size.
#
# Original author: Patiga (MIT). See README.md in this directory for the upstream
# source (a PR against ddnet-discordbot) and the map format references.
#
# Bot adaptation: the rendering uses matplotlib's object-oriented Figure API (no
# global pyplot state) so it can run safely inside a worker thread, since the bot
# calls it via asyncio.to_thread off the event loop. The sounds pie (previously an
# unused subplot) is now drawn as well.

import io

import matplotlib
matplotlib.use("Agg")  # headless, thread-safe backend; must be set before pyplot pulls one in
import numpy as np
from matplotlib.figure import Figure

from extensions.map_testing.visualize_size.tw_map_v4 import TwMapV4


def numbered_pie(ax, sizes, names, title):
    ax.set_title(title)
    if not sizes:
        ax.text(0.5, 0.5, f"No {title.lower()}", ha="center", va="center")
        return

    total_size = sum(sizes)
    percentages = [(s / total_size) * 100 for s in sizes]
    sorted_data = sorted(zip(names, sizes, percentages), key=lambda x: x[2], reverse=True)
    names, sizes, percentages = zip(*sorted_data)
    numbered_labels = [str(i + 1) for i in range(len(names))]
    wedges, _ = ax.pie(sizes, labels=numbered_labels, startangle=90)
    legend_entries = [
        f"{i + 1}. {name} - {perc:.1f}%"
        for i, (name, perc) in enumerate(zip(names, percentages))
    ]
    ax.legend(
        wedges,
        legend_entries,
        title=title,
        loc="center left",
        bbox_to_anchor=(1, 0, 0.5, 1)
    )


def visualize_from_bytes(data) -> io.BytesIO:
    map = TwMapV4.from_bytes(data)

    image_names = []
    image_sizes = []
    sound_names = []
    sound_sizes = []

    for item in map.items:
        if item.type_id == TwMapV4.ItemKind.image:
            image = item.content
            image_names.append(f"{image.name.string.strip(chr(0))} ({item.id})")
            if image.data_index is not TwMapV4.Optional.not_set:
                image_sizes.append(len(map._raw__raw_data_items[image.data_index]))
            else:
                image_sizes.append(0)
        elif item.type_id == TwMapV4.ItemKind.sound:
            sound = item.content
            sound_names.append(f"{sound.name.string.strip(chr(0))} ({item.id})")
            if sound.data_index is not TwMapV4.Optional.not_set:
                sound_sizes.append(len(map._raw__raw_data_items[sound.data_index]))
            else:
                sound_sizes.append(0)

    # https://stackoverflow.c   om/a/1094933
    def sizeof_fmt(num, suffix="B"):
        for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f}Yi{suffix}"

    total_images_size = sum(image_sizes)
    total_sounds_size = sum(sound_sizes)
    total_map_size = map.header.size
    other = total_map_size - total_images_size - total_sounds_size

    max_items = max(len(image_names), len(sound_names))
    width = 12
    height = 8 + max_items * 0.25

    fig = Figure(figsize=(width, height))
    ((total, single_items), (images, sounds)) = fig.subplots(2, 2)

    total.set_title("Total")
    total.pie(
        [total_images_size, total_sounds_size, other],
        labels=["Images", "Sounds", "Remaining"],
        autopct='%1.1f%%',
    )

    numbered_pie(images, image_sizes, image_names, "Images")
    numbered_pie(sounds, sound_sizes, sound_names, "Sounds")

    items = []
    for sizes, names, prefix in [(image_sizes, image_names, "I"), (sound_sizes, sound_names, "S")]:
        for size, name in zip(sizes, names):
            items.append((size, f"[{prefix}] {name}"))
    items = sorted(items, key=lambda item: item[0], reverse=True)

    y_pos = np.arange(len(items))
    single_items.set_title("Items")
    if items:
        bars = single_items.barh(
            y_pos,
            [size for size, _ in items],
            align='center',
        )
        single_items.bar_label(bars, fmt=sizeof_fmt)
        single_items.set_yticks(
            y_pos,
            labels=[name for _, name in items],
        )
        single_items.invert_yaxis()
    else:
        single_items.text(0.5, 0.5, "No items", ha="center", va="center")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches="tight")
    buf.seek(0)
    return buf
