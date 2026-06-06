import asyncio
import os
from asyncio.subprocess import PIPE
from typing import Awaitable, Callable, Tuple, Union

import discord


def check_os() -> Tuple[str, str]:
    if os.name == "posix":  # Unix-like system
        shell = "/bin/bash"
        ext = ""
    elif os.name == 'nt':  # Windows
        shell = "powershell.exe"
        ext = ".exe"
    else:
        raise OSError("Unsupported operating system")
    return shell, ext


SHELL, _ = check_os()


async def run_process_shell(cmd: str, timeout: float = 90.0) -> Tuple[str, str]:
    if os.name == 'posix':
        sequence = f"{SHELL} -c '{cmd}'"
        proc = await asyncio.create_subprocess_shell(sequence, stdout=PIPE, stderr=PIPE)
    else:  # Windows
        proc = await asyncio.create_subprocess_exec(SHELL, '-Command', cmd, stdout=PIPE, stderr=PIPE)

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise RuntimeError("Process timed out") from e
    else:
        return stdout.decode(), stderr.decode()


async def run_process_exec(
        program: str, *args: str, timeout: float = 90.0
) -> Tuple[str, str]:
    proc = await asyncio.create_subprocess_exec(
        program, *args, stdout=PIPE, stderr=PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise RuntimeError("Process timed out") from e
    else:
        return stdout.decode(), stderr.decode()


async def maybe_coroutine(func: Union[Awaitable, Callable], *args, **kwargs):
    if asyncio.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    else:
        return func(*args, **kwargs)


def rating() -> list:
    return [
        discord.SelectOption(label="Rating: ★☆☆☆☆", value="0"),
        discord.SelectOption(label="Rating: ★★☆☆☆", value="1"),
        discord.SelectOption(label="Rating: ★★★☆☆", value="2"),
        discord.SelectOption(label="Rating: ★★★★☆", value="3"),
        discord.SelectOption(label="Rating: ★★★★★", value="4"),
    ]
