from langchain_core.runnables.graph import Graph


def print_graph(graph: Graph) -> None:
    """Print an ASCII diagram, falling back to Mermaid if layout fails."""
    try:
        diagram = graph.draw_ascii()
    except ValueError:
        # The ASCII renderer can fail on the model's self-loop.
        print("ASCII layout failed; showing Mermaid diagram source instead:")
        diagram = graph.draw_mermaid()
    print(diagram)
