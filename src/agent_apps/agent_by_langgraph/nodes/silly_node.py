import random

from agent_apps.agent_by_langgraph.states.state import State


def silly_node(state: State) -> dict:
    nouns = [
        "Cabbages",
        "Unicorns",
        "Toasters",
        "Penguins",
        "Bananas",
        "Eels",
        "Pickles",
    ]
    adjectives = [
        "outrageous",
        "smelly",
        "pedantic",
        "existential",
        "sparkly",
        "haunted",
    ]
    sentence = f"{random.choice(nouns)} are {random.choice(adjectives)}"
    return {"messages": [{"role": "assistant", "content": sentence}]}
