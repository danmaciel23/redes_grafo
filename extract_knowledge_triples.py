r"""
Extrai triplas de conhecimento dos arquivos Markdown gerados pelo MinerU.

Uso:
    uv run .\extract_knowledge_triples.py
    uv run .\extract_knowledge_triples.py --mineru-dir .\mineru_output -o .\triplas_json

Saidas:
    triplas_json/
        documentos/<DOCUMENTO>.json      # array JSON de triplas por documento
        todas_triplas.json               # array JSON consolidado
        conexoes_pessoas.json            # somente triplas pessoa-pessoa
        resumo.json                      # contagens e caminhos processados
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

import spacy
from spacy.language import Language


DEFAULT_MINERU_DIR = Path("mineru_output")
DEFAULT_OUTPUT_DIR = Path("triplas_json")

PROMPT = """Você é um sistema de extração de grafos de conhecimento. Sua tarefa é analisar textos e extrair triplas de conhecimento em português.

Extraia entidades e relacionamentos que representem conhecimento factual do texto fornecido. Foque em:
- Pessoas, organizações, locais
- Eventos, datas, ações
- Relações causais
- Relações de parte-todo
- Quaisquer afirmações factuais

Todas as triplas devem estar em PORTUGUÊS. Use português para sujeitos, predicados e objetos.
Exemplos de predicados em português: "mora em", "trabalha para", "fundou", "acusado de", "responsável por", etc.

Retorne APENAS um array JSON válido de triplas, sem texto adicional. Cada tripla deve ser:
["sujeito", "predicado", "objeto"]

Exemplo de formato de saída:
[["João", "mora em", "Nova York"], ["Microsoft", "adquiriu", "GitHub"], ["Epstein", "foi acusado de", "tráfico"]]

Se nenhuma tripla significativa for encontrada, retorne um array vazio: []"""

PROMPT_TEMPLATE = """Extraia triplas de conhecimento do seguinte texto:

{content}

Retorne APENAS um array JSON de triplas no formato: [["sujeito", "predicado", "objeto"], ...]"""

PERSON_BLOCKLIST = {
    "Your Honor",
    "Honor",
    "Court",
    "Exhibit",
    "Government",
    "Plaintiff",
    "Defendant",
    "Counsel",
    "Attorney",
    "Judge",
    "Justice",
    "John Doe",
    "Jane Doe",
    "Doe",
    "Victim",
    "Witness",
    "FBI",
    "DOJ",
    "CIA",
    "U.S.",
    "United States",
    "United States District Court",
    "District Court",
    "Southern District",
    "New York Residence",
    "Little Saint James",
    "Zorro",
    "Zorro Ranch",
    "Minor",
    "Busts",
    "Torso",
    "Twor",
    "to'schedule",
    "SectLon",
    "Selzure Warant",
    "Seizure Warrant",
    "Scizure Warrant",
    "Megistrate",
    "Magistrate",
    "bispecial Agent",
    "Special Agent",
    "aout Ju",
    "lcate",
}

PERSON_FALSE_POSITIVE_TERMS = {
    "court",
    "district",
    "residence",
    "saint",
    "ranch",
    "minor",
    "bust",
    "torso",
    "schedule",
    "warrant",
    "warant",
    "agent",
    "magistrate",
    "megistrate",
    "section",
    "sectlon",
    "seizure",
    "selzure",
    "scizure",
}

FIELD_PREDICATES = {
    "FBI Name": "tem nome no FBI",
    "FBI No": "tem número do FBI",
    "FBINo": "tem número do FBI",
    "Trans ID": "tem identificação de transação",
    "Package ID": "tem identificação de pacote",
    "Date Arrested": "foi preso em",
    "Received": "foi recebido em",
    "Charges": "foi acusado de",
    "Aliases": "tem apelido",
    "Address": "tem endereço",
    "Location": "esteve localizado em",
    "Gender": "tem gênero",
    "Race": "tem raça registrada",
    "Ethnicity": "tem etnia registrada",
    "DOB": "nasceu em",
    "Birth City": "nasceu em",
    "Occupation": "tem ocupação",
    "Marital Status": "tem estado civil",
}

INVALID_FIELD_VALUES = {
    "Package is Current",
    "Hair",
    "Eye",
    "Health Status",
    "Education",
    "Birth Country",
    "Medications",
    "NONE",
    "N/A",
    "NULL",
}

PAIR_RULES = (
    (re.compile(r"\b(husband|wife|spouse|married|marriage)\b", re.I), "foi casado com"),
    (re.compile(r"\b(father|mother|son|daughter|brother|sister|parent|child)\b", re.I), "tem relação familiar com"),
    (re.compile(r"\b(employ|worked|employee|assistant|staff|secretary)\b", re.I), "trabalhou com"),
    (re.compile(r"\b(friend|associate|relationship|knew|met|introduced)\b", re.I), "foi associado a"),
    (re.compile(r"\b(accus|charge|indict|convict|plead|guilty)\b", re.I), "foi relacionado em acusação com"),
    (re.compile(r"\b(testif|deposition|interview|statement)\b", re.I), "foi mencionado em depoimento com"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai arrays JSON de triplas a partir dos Markdowns do MinerU."
    )
    parser.add_argument(
        "--mineru-dir",
        type=Path,
        default=DEFAULT_MINERU_DIR,
        help=f"Diretório raiz do MinerU. Padrão: {DEFAULT_MINERU_DIR}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Pasta para salvar os JSONs. Padrão: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Modelo spaCy a usar. Se omitido, tenta en_core_web_lg/md/sm.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=180_000,
        help="Limite de caracteres analisados por documento. Padrão: 180000.",
    )
    return parser.parse_args()


def load_spacy(model_name: str | None) -> Language:
    candidates = [model_name] if model_name else [
        "en_core_web_lg",
        "en_core_web_md",
        "en_core_web_sm",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            nlp = spacy.load(candidate)
            nlp.max_length = max(nlp.max_length, 250_000)
            print(f"Modelo spaCy: {candidate}")
            return nlp
        except OSError:
            pass
    raise RuntimeError(
        "Nenhum modelo spaCy encontrado. Execute: uv run python -m spacy download en_core_web_lg"
    )


def find_markdowns(mineru_dir: Path) -> list[Path]:
    if not mineru_dir.exists():
        return []
    return sorted(mineru_dir.rglob("*.md"))


def clean_markdown(text: str) -> str:
    text = re.sub(r"!\[.*?\]\(.*?\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`{1,3}.*?`{1,3}", " ", text, flags=re.S)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_entity(value: str) -> str:
    value = re.sub(r"\b(Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Hon\.?|Sir)\s+", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" \t\r\n.,;:()[]{}")
    if re.fullmatch(r"[A-Z][A-Z ,.'-]+", value) and "," in value:
        parts = [part.strip() for part in value.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            value = f"{parts[1]} {parts[0]}"
    if re.fullmatch(r"[A-Z][A-Z .'-]+", value):
        value = value.title().replace("S.", "S.").replace("W.", "W.")
    if re.fullmatch(r"eps[a-z]{2,7}in", value.lower()):
        value = "Epstein"
    value = re.sub(r"\bJEFFREY\s+EPS?TEIN\b", "Jeffrey Epstein", value, flags=re.I)
    value = re.sub(r"\bGHISLAINE\s+MAXWELL\b", "Ghislaine Maxwell", value, flags=re.I)
    return value


def valid_person(name: str) -> bool:
    if len(name) < 4 or name in PERSON_BLOCKLIST:
        return False
    if any(block.lower() == name.lower() for block in PERSON_BLOCKLIST):
        return False
    lowered = name.lower()
    if any(term in lowered for term in PERSON_FALSE_POSITIVE_TERMS):
        return False
    if re.search(r"\d", name):
        return False
    tokens = [token for token in re.split(r"\s+", name) if token]
    if len(tokens) == 1 and name.lower() not in {"epstein", "maxwell"}:
        return False
    if name.isupper() and len(name) <= 6:
        return False
    return True


def unique_triples(triples: Iterable[list[str]]) -> list[list[str]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[list[str]] = []
    for triple in triples:
        if len(triple) != 3:
            continue
        subject, predicate, obj = [normalize_entity(part) for part in triple]
        if not subject or not predicate or not obj or subject == obj:
            continue
        key = (subject, predicate.lower(), obj)
        if key in seen:
            continue
        seen.add(key)
        result.append([subject, predicate, obj])
    return result


def current_subject_from_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip("# ").strip()
        if not stripped:
            continue
        candidate = normalize_entity(stripped)
        if valid_person(candidate):
            return candidate
    return None


def next_meaningful_value(lines: list[str], start: int) -> str | None:
    if start + 1 >= len(lines):
        return None
    value = lines[start + 1].strip()
    if not value or value.startswith("#"):
        return None
    if value.rstrip(":") in FIELD_PREDICATES:
        return None
    if value in INVALID_FIELD_VALUES:
        return None
    if ":" in value:
        return None
    return value
    return None


def extract_structured_field_triples(text: str) -> list[list[str]]:
    subject = current_subject_from_heading(text)
    if not subject:
        return []

    triples: list[list[str]] = []
    lines = [line.strip() for line in text.splitlines()]
    for i, line in enumerate(lines):
        if not line:
            continue
        key, value = None, None
        inline = re.match(r"^([^:]{2,40}):\s*(.+)$", line)
        if inline:
            key, value = inline.group(1).strip(), inline.group(2).strip()
        else:
            maybe_key = line.rstrip(":")
            if maybe_key in FIELD_PREDICATES:
                key = maybe_key
                value = next_meaningful_value(lines, i)

        if not key or not value:
            continue
        predicate = FIELD_PREDICATES.get(key)
        if not predicate:
            continue
        value = normalize_entity(value)
        if len(value) < 2 or value in INVALID_FIELD_VALUES or ":" in value:
            continue
        triples.append([subject, predicate, value])

    return triples


def entities_by_label(doc) -> dict[str, list[str]]:
    labels: dict[str, list[str]] = {"PERSON": [], "ORG": [], "GPE": [], "LOC": [], "DATE": [], "EVENT": []}
    for ent in doc.ents:
        if ent.label_ not in labels:
            continue
        value = normalize_entity(ent.text)
        if ent.label_ == "PERSON" and not valid_person(value):
            continue
        if len(value) < 2:
            continue
        labels[ent.label_].append(value)
    return {label: sorted(set(values)) for label, values in labels.items()}


def choose_pair_predicate(sentence: str) -> str:
    for pattern, predicate in PAIR_RULES:
        if pattern.search(sentence):
            return predicate
    return "foi mencionado com"


def extract_sentence_triples(text: str, nlp: Language, max_chars: int) -> list[list[str]]:
    doc = nlp(text[:max_chars])
    triples: list[list[str]] = []

    for sent in doc.sents:
        sentence = sent.text.strip()
        if len(sentence) < 20:
            continue
        labels = entities_by_label(sent.as_doc())
        people = labels.get("PERSON", [])
        orgs = labels.get("ORG", [])
        places = labels.get("GPE", []) + labels.get("LOC", [])
        dates = labels.get("DATE", [])
        events = labels.get("EVENT", [])

        if len(people) >= 2:
            predicate = choose_pair_predicate(sentence)
            for left, right in itertools.combinations(people[:8], 2):
                triples.append([left, predicate, right])

        for person in people[:5]:
            for org in orgs[:4]:
                triples.append([person, "foi associado a organização", org])
            for place in places[:4]:
                triples.append([person, "foi associado a local", place])
            for date in dates[:3]:
                triples.append([person, "foi associado a data", date])
            for event in events[:3]:
                triples.append([person, "foi associado a evento", event])

    return triples


def extract_triples(text: str, nlp: Language, max_chars: int) -> list[list[str]]:
    cleaned = clean_markdown(text)
    triples = []
    triples.extend(extract_structured_field_triples(cleaned))
    triples.extend(extract_sentence_triples(cleaned, nlp, max_chars))
    return unique_triples(triples)


def collect_people(text: str, nlp: Language, max_chars: int) -> set[str]:
    cleaned = clean_markdown(text)
    doc = nlp(cleaned[:max_chars])
    people = {
        normalize_entity(ent.text)
        for ent in doc.ents
        if ent.label_ == "PERSON" and valid_person(normalize_entity(ent.text))
    }
    structured_subject = current_subject_from_heading(cleaned)
    if structured_subject:
        people.add(structured_subject)
    return people


def is_person_connection(triple: list[str], all_people: set[str]) -> bool:
    pair_predicates = {predicate for _, predicate in PAIR_RULES}
    pair_predicates.add("foi mencionado com")
    return (
        triple[1] in pair_predicates
        and triple[0] in all_people
        and triple[2] in all_people
    )


def main() -> int:
    args = parse_args()
    mineru_dir = args.mineru_dir.resolve()
    output_dir = args.output_dir.resolve()
    docs_dir = output_dir / "documentos"
    docs_dir.mkdir(parents=True, exist_ok=True)

    markdowns = find_markdowns(mineru_dir)
    print(f"Diretório MinerU: {mineru_dir}")
    print(f"Saída JSON: {output_dir}")
    print(f"Markdowns encontrados: {len(markdowns)}")
    if not markdowns:
        return 1

    nlp = load_spacy(args.model)

    all_triples: list[list[str]] = []
    people_counter: Counter[str] = Counter()
    all_people: set[str] = set()
    per_doc_counts: dict[str, int] = {}

    for index, md_path in enumerate(markdowns, 1):
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        triples = extract_triples(text, nlp, args.max_chars)
        doc_people = collect_people(text, nlp, args.max_chars)
        all_people.update(doc_people)
        doc_name = md_path.stem
        (docs_dir / f"{doc_name}.json").write_text(
            json.dumps(triples, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        all_triples.extend(triples)
        per_doc_counts[doc_name] = len(triples)
        people_counter.update(doc_people)
        print(f"[{index}/{len(markdowns)}] {doc_name}: {len(triples)} triplas")

    all_triples = unique_triples(all_triples)
    person_connections = [
        triple for triple in all_triples if is_person_connection(triple, all_people)
    ]

    (output_dir / "todas_triplas.json").write_text(
        json.dumps(all_triples, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "conexoes_pessoas.json").write_text(
        json.dumps(person_connections, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "resumo.json").write_text(
        json.dumps(
            {
                "prompt": PROMPT,
                "prompt_template": PROMPT_TEMPLATE,
                "mineru_dir": str(mineru_dir),
                "markdowns_processados": [str(path) for path in markdowns],
                "quantidade_markdowns": len(markdowns),
                "quantidade_triplas_consolidadas": len(all_triples),
                "quantidade_conexoes_pessoa_pessoa": len(person_connections),
                "triplas_por_documento": per_doc_counts,
                "pessoas_mais_mencionadas": people_counter.most_common(50),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nTriplas consolidadas: {len(all_triples)}")
    print(f"Conexões pessoa-pessoa: {len(person_connections)}")
    print(f"Arquivos salvos em: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
