"""
Component 5 — Terminal UI
Entry point: python main.py
"""

import os
import sys
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from langchain_core.messages import HumanMessage
from src.agents.graph import graph
from src.agents import REGISTRY

# --- LangFuse observability (optional) ---
_langfuse_handler = None
try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        # Langfuse v4+: CallbackHandler reads secret_key and base_url from env vars automatically
        _langfuse_handler = LangfuseCallbackHandler(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        )
except ImportError:
    pass  # langfuse not installed, skip silently

console = Console()

BANNER = """\
[bold blue]KnowledgeHub Assistant[/bold blue]
[dim]Multi-Agent RAG Chatbot | Sistem Tanya-Jawab Berbasis Dokumen Internal[/dim]"""

AGENT_LABELS = {
    "TECHNICAL_AGENT": ("[bold yellow][Technical Agent][/bold yellow]", "yellow"),
    "HR_AGENT":        ("[bold magenta][HR Agent][/bold magenta]", "magenta"),
    "GENERAL_AGENT":   ("[bold cyan][General Agent][/bold cyan]", "cyan"),
}

COMMANDS = {
    "help":    "tampilkan daftar perintah",
    "history": "tampilkan riwayat percakapan sesi ini",
    "clear":   "bersihkan layar",
    "q / quit / exit": "akhiri sesi",
}


def print_banner():
    console.print(Panel(BANNER, border_style="blue", padding=(1, 4)))
    console.print("[dim]Ketik [bold]help[/bold] untuk bantuan, [bold]q[/bold] untuk keluar.[/dim]\n")


def print_help():
    console.print(Rule("[bold]Perintah Tersedia[/bold]"))
    table = Table(show_header=False, box=None, padding=(0, 2))
    for cmd, desc in COMMANDS.items():
        table.add_row(f"[cyan]{cmd}[/cyan]", desc)
    console.print(table)
    console.print()


def print_history(chat_history: list):
    console.print(Rule("[bold]Riwayat Percakapan[/bold]"))
    if not chat_history:
        console.print("[dim]Belum ada percakapan dalam sesi ini.[/dim]\n")
        return
    for entry in chat_history:
        if entry["role"] == "user":
            console.print(f"[bold green][USER][/bold green]  {entry['content']}")
        else:
            label, _ = AGENT_LABELS.get(entry.get("agent", "GENERAL_AGENT"), ("[AGENT]", "blue"))
            console.print(f"{label}  {entry['content']}")
        console.print()


def run():
    print_banner()

    state = {
        "messages": [],
        "current_agent": "",
        "routing_decision": "",
    }
    chat_history = []

    while True:
        try:
            user_input = console.input("[bold green][USER][/bold green] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Sesi diakhiri.[/dim]")
            sys.exit(0)

        if not user_input:
            continue

        lower = user_input.lower()

        if lower in ("q", "quit", "exit"):
            console.print("[dim]Terima kasih telah menggunakan KnowledgeHub. Sampai jumpa![/dim]")
            break

        if lower == "help":
            print_help()
            continue

        if lower == "clear":
            console.clear()
            print_banner()
            continue

        if lower == "history":
            print_history(chat_history)
            continue

        # --- Run graph ---
        console.print()
        state["messages"] = list(state["messages"]) + [HumanMessage(content=user_input)]

        callbacks = [_langfuse_handler] if _langfuse_handler else []
        with console.status("[yellow]Memproses pertanyaan...[/yellow]", spinner="dots"):
            result = graph.invoke(state, config={"callbacks": callbacks})

        state = result

        agent_used = result.get("current_agent", "GENERAL_AGENT")
        agent_label, border_color = AGENT_LABELS.get(
            agent_used, ("[AGENT]", "blue")
        )

        # Transparency output
        console.print(f"  [dim]> Diarahkan ke:[/dim] {agent_label}")
        spec = REGISTRY.get(agent_used)
        if spec and spec.collection:
            console.print(
                f"  [dim]> Mengakses koleksi:[/dim] [{border_color}]{spec.collection}[/{border_color}]"
            )
        console.print()

        # Final answer
        final_message = result["messages"][-1]
        answer = final_message.content if hasattr(final_message, "content") else str(final_message)

        console.print(Panel(
            answer,
            title=agent_label,
            border_style=border_color,
            padding=(1, 2),
        ))
        console.print()

        # Save history
        chat_history.append({"role": "user", "content": user_input})
        chat_history.append({"role": "agent", "content": answer, "agent": agent_used})


if __name__ == "__main__":
    run()
