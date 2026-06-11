r"""
normalize_graph.py
==================
Normaliza o grafo ja gerado em grafo_output/grafo_triplas.json.

O objetivo e manter um fluxo simples e ajustavel:
1. mesclar entidades via dicionario ALIASES;
2. remover nos claramente quebrados por OCR/IDs soltos;
3. recalcular pesos/frequencias;
4. aplicar Louvain para colorir comunidades no HTML.

Uso:
    uv run .\normalize_graph.py
    .\.venv\Scripts\python.exe .\normalize_graph.py
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
from pyvis.network import Network


DEFAULT_INPUT_JSON = Path("grafo_output") / "grafo_triplas.json"
DEFAULT_OUTPUT_DIR = Path("grafo_output")
OUTPUT_STEM = "grafo_triplas_normalizado"


ALIASES = {
    # Pessoas
    "Epstein": "Jeffrey Epstein",
    "JErFREy EPsTEIN": "Jeffrey Epstein",
    "JEFEREY EPsTEIN": "Jeffrey Epstein",
    "Jeferey Epstein": "Jeffrey Epstein",
    "Jeffrey Epsteln": "Jeffrey Epstein",
    "Eps'Tein": "Jeffrey Epstein",
    "JEFFREY EPS'TEIN's": "Jeffrey Epstein",
    "Ghislaine": "Ghislaine Maxwell",
    "Maxwell": "Ghislaine Maxwell",
    "Ghislaine Noelle Maxwell": "Ghislaine Maxwell",
    "Barbare Moses": "Barbara Moses",
    "Henry B. Pitman": "Henry Pitman",
    # Locais/organizacoes
    "Ny": "New York",
    "New Yoxk": "New York",
    "Ne York": "New York",
    "United states": "United States",
    "United States of America": "United States",
    "The United States Of America": "United States",
    "the United states": "United States",
    "the United States": "United States",
    "U.S": "United States",
    "U.s": "United States",
    "Us": "United States",
    "United": "United States",
    "# UNITED STATES": "United States",
    "Fbi": "Federal Bureau of Investigation",
    "Cbp": "U.S. Customs and Border Protection",
    "FLorida": "Florida",
    "Palm Beachy": "Palm Beach",
    "the Southern District": "Southern District of New York",
    "Southern District": "Southern District of New York",
    "the Southem District": "Southern District of New York",
    "the Southexn District": "Southern District of New York",
    "the Southern Distxict of New York": "Southern District of New York",
    "the New York Residence": "New York Residence",
    'the "New York Residence': "New York Residence",
    "the New Yoxk Residence": "New York Residence",
    "the Palm Beach Residence": "Palm Beach Residence",
    'the "Palm Beach Residence': "Palm Beach Residence",
    "the Subject Premises": "Subject Premises",
    "Searehed——Subject Premises": "Subject Premises",
}


DROP_NODES = {
    "61235657",
    "8AREFN06X",
    "F5C9BC0CBA14407D96D14A1BF0900815",
    "June 27, 2019 S",
    "January , 2020 S/",
    "identi te erson",
    "Attachment A",
    "Additionallyr",
    "enticer harbor",
    "1591(a),(b)(2",
    "1594;Title 21",
    "18 0.s",
    "anauthorie theofficerexecuting",
    "tria",
    "menoffcrao f ho",
    "Imei",
    "follows1: a. A",
    "Specia aent d",
    "EaststSte",
    "Npa",
    "-5",
    "-6",
    "Esi",
    "Iteims",
    "follows1",
    "Cnhiant Ttome",
    "byr",
    "anc",
    "18 u.s.C.ss 371,1591(a)，(b)(2)，and2",
    "Probation Violation Petition Supervised",
    "Seizaro Warrant",
    "b. Bvidence",
    "Copy&#x27;of",
    "anentor shuldefedundr",
    "Usmj",
    "exceed3",
    "justifyingthelatetspecif dateof",
    "MSpeil Aent Ke Mayuiref",
    "That same day",
    "Attachmenta",
    "SireWar P",
    "the Seized Discs",
    "the Search Team",
}


LABEL_FIXES = {
    "organizaÃ§Ã£o": "organizacao",
    "relaÃ§Ã£o": "relacao",
}


COMMUNITY_COLORS = [
    "#4cc9f0",
    "#f72585",
    "#b8de6f",
    "#f9c74f",
    "#90be6d",
    "#f8961e",
    "#43aa8b",
    "#577590",
    "#ff6b6b",
    "#a78bfa",
    "#2dd4bf",
    "#fb7185",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normaliza e colore o grafo de triplas.")
    parser.add_argument("--input-json", type=Path, default=DEFAULT_INPUT_JSON)
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stem", default=OUTPUT_STEM, help="Prefixo dos arquivos gerados.")
    parser.add_argument("--min-degree", type=int, default=1)
    parser.add_argument("--max-label-length", type=int, default=42)
    return parser.parse_args()


def clean_text(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n;")


def fix_label(value: str) -> str:
    text = value
    text = text.replace("organiza\u00c3\u00a7\u00c3\u00a3o", "organizacao")
    text = text.replace("rela\u00c3\u00a7\u00c3\u00a3o", "relacao")
    for old, new in LABEL_FIXES.items():
        text = text.replace(old, new)
    return text


def canonical_node(node: str) -> str | None:
    node = clean_text(node)
    if not node:
        return None
    if node in DROP_NODES:
        return None
    if is_noise_node(node):
        return None
    return ALIASES.get(node, node)


def is_noise_node(node: str) -> bool:
    lowered = node.lower()
    if lowered in {"days", "months", "years", "court", "corporation", "minor"}:
        return True
    if re.fullmatch(r"[-+]?\d+", node):
        return True
    if re.fullmatch(r"\d{4}", node):
        return True
    if re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b", lowered):
        return True
    if re.fullmatch(r"\d+\s*days?", lowered):
        return True
    if re.search(r"\b(about|around|between|at least|in at least|1n at least)\b", lowered) and re.search(r"\d{4}", lowered):
        return True
    if re.fullmatch(r"\d+\s+years?", lowered):
        return True
    if lowered in {"many years", "several years"}:
        return True
    if "years old" in lowered or "years" == lowered:
        return True
    if "age of" in lowered or "under 18" in lowered or "less than" in lowered:
        return True
    letters = re.sub(r"[^A-Za-z]", "", node)
    if len(node) > 18 and letters and sum(ch.islower() for ch in letters) / len(letters) > 0.82:
        return True
    if re.search(r"\d", node) and re.search(r"[;(),，]", node):
        return True
    return False


def load_graph(path: Path) -> nx.DiGraph:
    raw = json.loads(path.read_text(encoding="utf-8"))
    graph = nx.DiGraph() if raw.get("directed", True) else nx.Graph()

    node_freq = {
        clean_text(node["id"]): int(node.get("frequencia", 1))
        for node in raw.get("nodes", [])
        if "id" in node
    }

    merged_freq: Counter[str] = Counter()
    merged_edges: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)

    for original_node, freq in node_freq.items():
        canonical = canonical_node(original_node)
        if canonical:
            merged_freq[canonical] += freq

    for edge in raw.get("links", []):
        source = canonical_node(edge.get("source", ""))
        target = canonical_node(edge.get("target", ""))
        if not source or not target or source == target:
            continue

        weight = max(1, int(edge.get("weight", 1)))
        predicates = split_predicates(edge.get("predicates") or edge.get("label") or "")
        for predicate in predicates or ["relacao"]:
            merged_edges[(source, target)][fix_label(predicate)] += weight

    for node, freq in merged_freq.items():
        graph.add_node(node, frequencia=freq)

    for (source, target), predicates in merged_edges.items():
        weight = sum(predicates.values())
        graph.add_edge(
            source,
            target,
            weight=weight,
            predicates="; ".join(
                f"{predicate} ({count})" if count > 1 else predicate
                for predicate, count in predicates.most_common()
            ),
            label=", ".join(predicates.keys()),
        )

    return graph


def split_predicates(value: str) -> list[str]:
    return [clean_text(part) for part in re.split(r";|,", value) if clean_text(part)]


def apply_min_degree(graph: nx.DiGraph, min_degree: int) -> None:
    graph.remove_nodes_from(list(nx.isolates(graph)))
    if min_degree <= 1:
        return
    remove = [node for node, degree in graph.degree() if degree < min_degree]
    graph.remove_nodes_from(remove)
    graph.remove_nodes_from(list(nx.isolates(graph)))


def detect_communities(graph: nx.DiGraph) -> None:
    undirected = graph.to_undirected()
    if undirected.number_of_nodes() == 0:
        return

    if undirected.number_of_edges() == 0:
        communities = [{node} for node in undirected.nodes()]
    else:
        communities = nx.community.louvain_communities(undirected, weight="weight", seed=42)

    communities = sorted(communities, key=len, reverse=True)
    for community_id, members in enumerate(communities):
        for node in members:
            graph.nodes[node]["community"] = community_id
            graph.nodes[node]["color"] = COMMUNITY_COLORS[community_id % len(COMMUNITY_COLORS)]


def save_json(graph: nx.DiGraph, path: Path) -> None:
    data = {
        "directed": graph.is_directed(),
        "nodes": [
            {
                "id": node,
                "frequencia": attrs.get("frequencia", 0),
                "grau": graph.degree(node),
                "community": attrs.get("community", -1),
                "color": attrs.get("color", "#cccccc"),
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


def save_graphml(graph: nx.DiGraph, path: Path) -> None:
    nx.write_graphml(graph, path)
    print(f"GraphML salvo : {path}")


def short_label(text: str, max_length: int) -> str:
    return text if len(text) <= max_length else text[: max_length - 1].rstrip() + "..."


def save_html(graph: nx.DiGraph, path: Path, max_label_length: int) -> None:
    net = Network(
        height="95vh",
        width="100%",
        bgcolor="#0d1117",
        font_color="#e6edf3",
        heading="Grafo de triplas normalizado por comunidades",
        directed=graph.is_directed(),
    )
    net.barnes_hut(
        gravity=-6000,
        central_gravity=0.2,
        spring_length=165,
        spring_strength=0.035,
        damping=0.09,
    )

    max_freq = max((attrs.get("frequencia", 1) for _, attrs in graph.nodes(data=True)), default=1)
    max_weight = max((attrs.get("weight", 1) for _, _, attrs in graph.edges(data=True)), default=1)

    for node, attrs in graph.nodes(data=True):
        freq = attrs.get("frequencia", 1)
        degree = graph.degree(node)
        community = attrs.get("community", -1)
        size = 11 + math.sqrt(freq / max_freq) * 36
        net.add_node(
            node,
            label=short_label(node, max_label_length),
            title=(
                f"<b>{node}</b><br>"
                f"Comunidade: {community}<br>"
                f"Ocorrencias agregadas: {freq}<br>"
                f"Conexoes: {degree}"
            ),
            size=size,
            color={
                "background": attrs.get("color", "#cccccc"),
                "border": "#e6edf3",
                "highlight": {"background": "#ffffff", "border": attrs.get("color", "#cccccc")},
            },
            font={"size": max(11, int(size * 0.42)), "color": "#e6edf3", "strokeWidth": 3},
            group=community,
        )

    for source, target, attrs in graph.edges(data=True):
        weight = attrs.get("weight", 1)
        width = 1 + (weight / max_weight) * 7
        predicates = attrs.get("predicates", "")
        label = attrs.get("label", "")
        net.add_edge(
            source,
            target,
            label=short_label(label, 55),
            title=f"<b>{source}</b> -> <b>{target}</b><br>Relacao: {predicates}<br>Peso: {weight}",
            width=width,
            color={"color": "#3b424d", "highlight": "#ffffff"},
            arrows="to",
            font={"size": 10, "color": "#c9d1d9", "strokeWidth": 3},
        )

    net.show_buttons(filter_=["physics"])
    net.show(str(path), notebook=False)
    print(f"HTML salvo    : {path}")


def print_stats(graph: nx.DiGraph) -> None:
    communities = Counter(attrs.get("community", -1) for _, attrs in graph.nodes(data=True))
    print("\nEstatisticas normalizadas")
    print(f"  Nos         : {graph.number_of_nodes()}")
    print(f"  Arestas     : {graph.number_of_edges()}")
    print(f"  Comunidades : {len(communities)}")
    print("\n  Top 20 - mais conectados:")
    for node, degree in sorted(graph.degree(), key=lambda item: item[1], reverse=True)[:20]:
        attrs = graph.nodes[node]
        print(
            f"    {node:<36} grau={degree:>3} "
            f"freq={attrs.get('frequencia', 0):>3} comunidade={attrs.get('community', -1)}"
        )


def main() -> int:
    args = parse_args()
    input_json = args.input_json.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    graph = load_graph(input_json)
    apply_min_degree(graph, args.min_degree)
    detect_communities(graph)
    print_stats(graph)

    save_graphml(graph, output_dir / f"{args.stem}.graphml")
    save_json(graph, output_dir / f"{args.stem}.json")
    save_html(graph, output_dir / f"{args.stem}.html", args.max_label_length)

    print(f"\nPronto. Abra no navegador: {output_dir / f'{args.stem}.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
