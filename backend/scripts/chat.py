"""Chat with the agent in the terminal.

    make chat                    # new conversation, saved in Postgres
    make chat args="--thread demo-1"    # continue a saved conversation
    make chat args="--debug"     # also show route, search query, gate score and sources

Commands while chatting: /new (fresh conversation), /debug (toggle details), /quit
"""

import argparse
import logging
import uuid

from app.config import get_settings
from app.graph.agent import open_agent
from app.observability import flush_traces


def show(turn, debug: bool) -> None:
    print(f"\nbot> {turn.answer}\n")
    for c in turn.citations:
        where = c["url"] or c["file"] + (f", page {c['page']}" if c["page"] else "")
        print(f"     [{c['n']}] {c['heading']}  ({where})")
    if debug:
        if turn.top_score is None:
            gate = "no retrieval"
        elif turn.passed_gate is None:  # order answers: policy pages, no gate
            gate = f"top score {turn.top_score:.3f}"
        else:
            gate = f"gate {turn.top_score:.3f} {'pass' if turn.passed_gate else 'FAIL'}"
        details = f"route={turn.route} | query={turn.search_query!r} | {gate}"
        print(f"     -- {details} | {turn.latency_ms} ms")
        for s in turn.sources:
            score = f"{s['score']:.3f}" if s["score"] is not None else " live"  # catalog tool
            print(f"        {s['n']}. [{score}] {s['heading']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--thread", help="conversation id to continue")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-persist", action="store_true", help="keep memory in RAM only")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    # Tracing and retry notices must not interrupt the chat; real errors still surface
    for noisy in ("opentelemetry", "langchain_cohere.utils"):
        logging.getLogger(noisy).setLevel(logging.CRITICAL)
    settings = get_settings()
    thread = args.thread or f"cli-{uuid.uuid4().hex[:8]}"
    debug = args.debug
    print(f"VoltCart assistant ({settings.llm_model_main}). Conversation: {thread}")
    print("Type /new, /debug or /quit.\n")

    with open_agent(settings, persist=not args.no_persist) as agent:
        try:
            while True:
                message = input("you> ").strip()
                if not message:
                    continue
                if message == "/quit":
                    break
                if message == "/new":
                    thread = f"cli-{uuid.uuid4().hex[:8]}"
                    print(f"New conversation: {thread}\n")
                    continue
                if message == "/debug":
                    debug = not debug
                    print(f"debug {'on' if debug else 'off'}\n")
                    continue
                show(agent.ask(thread, message), debug)
        except (KeyboardInterrupt, EOFError):
            print()
        finally:
            flush_traces()


if __name__ == "__main__":
    main()
