r"""
build_graph.py
==============
Le os JSONs de triplas gerados por extract_knowledge_triples.py e monta um
grafo navegavel no browser usando PyVis.

Uso:
    uv run .\build_graph.py
    uv run .\build_graph.py --input-json .\triplas_json\todas_triplas.json
    uv run .\build_graph.py --input-json .\triplas_json\conexoes_pessoas.json -o .\grafo_output_pessoas

Entrada esperada:
    [
      ["sujeito", "predicado", "objeto"],
      ...
    ]

Saidas:
    grafo_output/
        grafo_triplas.html
        grafo_triplas.json
        grafo_triplas.graphml
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import networkx as nx
from pyvis.network import Network


DEFAULT_INPUT_JSON = Path("triplas_json") / "todas_triplas.json"
DEFAULT_OUTPUT_DIR = Path("grafo_output")

GENERIC_VALUES = {
    "",
    "none",
    "n/a",
    "null",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Constroi um grafo PyVis a partir das triplas JSON extraidas."
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        default=DEFAULT_INPUT_JSON,
        help=f"Arquivo JSON de triplas. Padrao: {DEFAULT_INPUT_JSON}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Pasta onde salvar o grafo. Padrao: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--min-edge",
        type=int,
        default=1,
        help="Peso minimo de uma relacao agregada para entrar no grafo. Padrao: 1",
    )
    parser.add_argument(
        "--max-label-length",
        type=int,
        default=45,
        help="Tamanho maximo do texto visivel em cada no. Padrao: 45",
    )
    parser.add_argument(
        "--undirected",
        action="store_true",
        help="Gera grafo nao direcionado. Por padrao, usa sujeito -> objeto.",
    )
    return parser.parse_args()


def normalizar_texto(value: object) -> str:
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n;")


def carregar_triplas(path: Path) -> list[tuple[str, str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de triplas nao encontrado: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("O JSON de entrada precisa ser um array de triplas.")

    triplas: list[tuple[str, str, str]] = []
    for item in raw:
        if not isinstance(item, list | tuple) or len(item) != 3:
            continue
        sujeito, predicado, objeto = [normalizar_texto(part) for part in item]
        if not sujeito or not predicado or not objeto:
            continue
        if sujeito.lower() in GENERIC_VALUES or objeto.lower() in GENERIC_VALUES:
            continue
        if sujeito == objeto:
            continue
        triplas.append((sujeito, predicado, objeto))

    return triplas


def construir_grafo(
    triplas: Iterable[tuple[str, str, str]],
    min_edge: int,
    directed: bool,
) -> nx.Graph | nx.DiGraph:
    graph: nx.Graph | nx.DiGraph = nx.DiGraph() if directed else nx.Graph()

    node_freq: Counter[str] = Counter()
    edges: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)

    for sujeito, predicado, objeto in triplas:
        node_freq[sujeito] += 1
        node_freq[objeto] += 1

        if directed:
            edge_key = (sujeito, objeto)
        else:
            edge_key = tuple(sorted((sujeito, objeto)))
        edges[edge_key][predicado] += 1

    for node, freq in node_freq.items():
        graph.add_node(node, frequencia=freq)

    for (source, target), predicates in edges.items():
        weight = sum(predicates.values())
        if weight < min_edge:
            continue
        predicate_summary = "; ".join(
            f"{predicate} ({count})" if count > 1 else predicate
            for predicate, count in predicates.most_common()
        )
        graph.add_edge(
            source,
            target,
            weight=weight,
            predicates=predicate_summary,
            label=", ".join(predicates.keys()),
        )

    isolated = list(nx.isolates(graph))
    graph.remove_nodes_from(isolated)
    return graph


def salvar_graphml(graph: nx.Graph | nx.DiGraph, path: Path) -> None:
    nx.write_graphml(graph, path)
    print(f"GraphML salvo : {path}")


def salvar_json(graph: nx.Graph | nx.DiGraph, path: Path) -> None:
    data = {
        "directed": graph.is_directed(),
        "nodes": [
            {
                "id": node,
                "frequencia": attrs.get("frequencia", 0),
                "grau": graph.degree(node),
            }
            for node, attrs in graph.nodes(data=True)
        ],
        "links": [
            {
                "source": source,
                "target": target,
                "weight": attrs.get("weight", 1),
                "predicates": attrs.get("predicates", ""),
                "label": attrs.get("label", ""),
            }
            for source, target, attrs in graph.edges(data=True)
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON salvo    : {path}")


def encurtar_label(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "..."


def node_color(freq: int, max_freq: int) -> str:
    ratio = freq / max_freq if max_freq else 0
    if ratio >= 0.66:
        return "#ef5350"
    if ratio >= 0.33:
        return "#ffb74d"
    return "#4fc3f7"


def gerar_html(
    graph: nx.Graph | nx.DiGraph,
    path: Path,
    input_json: Path,
    max_label_length: int,
) -> None:
    if graph.number_of_nodes() == 0:
        print("Grafo vazio, HTML nao gerado.")
        return

    net = Network(
        height="95vh",
        width="100%",
        bgcolor="#0d1117",
        font_color="#e6edf3",
        heading="Grafo de triplas de conhecimento",
        directed=graph.is_directed(),
    )
    net.barnes_hut(
        gravity=-6500,
        central_gravity=0.22,
        spring_length=170,
        spring_strength=0.035,
        damping=0.09,
    )

    max_freq = max(
        (attrs.get("frequencia", 1) for _, attrs in graph.nodes(data=True)),
        default=1,
    )
    max_weight = max(
        (attrs.get("weight", 1) for _, _, attrs in graph.edges(data=True)),
        default=1,
    )

    for node, attrs in graph.nodes(data=True):
        freq = attrs.get("frequencia", 1)
        degree = graph.degree(node)
        size = 12 + (freq / max_freq) * 42
        net.add_node(
            node,
            label=encurtar_label(node, max_label_length),
            title=(
                f"<b>{node}</b><br>"
                f"Ocorrencias em triplas: {freq}<br>"
                f"Conexoes: {degree}<br>"
                f"Fonte: {input_json.name}"
            ),
            size=size,
            color=node_color(freq, max_freq),
            font={"size": max(11, int(size * 0.45)), "color": "#e6edf3"},
        )

    for source, target, attrs in graph.edges(data=True):
        weight = attrs.get("weight", 1)
        width = 1 + (weight / max_weight) * 7
        predicates = attrs.get("predicates", "")
        label = attrs.get("label", "")
        net.add_edge(
            source,
            target,
            label=encurtar_label(label, 55),
            title=(
                f"<b>{source}</b> -> <b>{target}</b><br>"
                f"Relacao: {predicates}<br>"
                f"Peso: {weight}"
            ),
            width=width,
            color={"color": "#30363d", "highlight": "#f78166"},
            arrows="to" if graph.is_directed() else "",
            font={"size": 10, "color": "#c9d1d9", "strokeWidth": 3},
        )

    net.show_buttons(filter_=["physics"])
    net.show(str(path), notebook=False)
    print(f"HTML salvo    : {path}")


def imprimir_estatisticas(graph: nx.Graph | nx.DiGraph, triplas_count: int) -> None:
    print("\nEstatisticas")
    print(f"  Triplas lidas : {triplas_count}")
    print(f"  Nos           : {graph.number_of_nodes()}")
    print(f"  Arestas       : {graph.number_of_edges()}")

    if graph.number_of_nodes() == 0:
        return

    components = (
        list(nx.weakly_connected_components(graph))
        if graph.is_directed()
        else list(nx.connected_components(graph))
    )
    print(f"  Componentes   : {len(components)}")
    print(f"  Maior comp.   : {max(len(component) for component in components)} nos")

    print("\n  Top 20 - mais conectados:")
    top_nodes = sorted(graph.degree(), key=lambda item: item[1], reverse=True)[:20]
    for node, degree in top_nodes:
        freq = graph.nodes[node].get("frequencia", "?")
        print(f"    {node:<45} grau={degree:>3}  freq={freq}")


def main() -> int:
    args = parse_args()
    input_json = args.input_json.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"JSON de entrada : {input_json}")
    print(f"Saida do grafo  : {output_dir}")
    print(f"Direcionado     : {not args.undirected}")

    triplas = carregar_triplas(input_json)
    print(f"Triplas validas : {len(triplas)}")
    if not triplas:
        print("Nenhuma tripla valida encontrada.")
        return 1

    graph = construir_grafo(
        triplas=triplas,
        min_edge=args.min_edge,
        directed=not args.undirected,
    )
    imprimir_estatisticas(graph, len(triplas))

    if graph.number_of_nodes() == 0:
        print("\nGrafo vazio. Tente reduzir --min-edge.")
        return 1

    print()
    salvar_graphml(graph, output_dir / "grafo_triplas.graphml")
    salvar_json(graph, output_dir / "grafo_triplas.json")
    gerar_html(
        graph,
        output_dir / "grafo_triplas.html",
        input_json=input_json,
        max_label_length=args.max_label_length,
    )

    print(f"\nPronto. Abra no navegador: {output_dir / 'grafo_triplas.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
