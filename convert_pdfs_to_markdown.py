from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Converte todos os PDFs de um diretorio para Markdown usando o CLI do MinerU."
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Diretorio contendo os arquivos PDF.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("mineru_output"),
        help="Diretorio raiz de saida do MinerU. Padrao: ./mineru_output",
    )
    parser.add_argument(
        "-b",
        "--backend",
        default="pipeline",
        choices=[
            "pipeline",
            "hybrid-auto-engine",
            "hybrid-http-client",
            "vlm-auto-engine",
            "vlm-http-client",
        ],
        help="Backend do MinerU. Padrao: pipeline",
    )
    parser.add_argument(
        "-m",
        "--method",
        default="auto",
        choices=["auto", "txt", "ocr"],
        help="Metodo de parsing. Padrao: auto",
    )
    parser.add_argument(
        "-l",
        "--lang",
        default=None,
        help="Idioma do documento, por exemplo: en, ch, latin. Opcional.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Busca PDFs recursivamente dentro do diretorio informado.",
    )
    return parser.parse_args()


def find_pdfs(input_dir: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(path for path in input_dir.glob(pattern) if path.is_file())


def expected_markdown_path(output_dir: Path, pdf_path: Path, backend: str, method: str) -> Path:
    stem = pdf_path.stem
    if backend.startswith("pipeline"):
        parse_dir = output_dir / stem / method
    elif backend.startswith("vlm"):
        parse_dir = output_dir / stem / "vlm"
    elif backend.startswith("hybrid"):
        parse_dir = output_dir / stem / f"hybrid_{method}"
    else:
        parse_dir = output_dir / stem / method

    return parse_dir / f"{stem}.md"


def build_command(pdf_path: Path, output_dir: Path, backend: str, method: str, lang: str | None) -> list[str]:
    command = [
        "mineru",
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-b",
        backend,
        "-m",
        method,
    ]
    if lang:
        command.extend(["-l", lang])
    return command


def main() -> int:
    args = parse_args()

    if shutil.which("mineru") is None:
        print("Erro: comando 'mineru' nao encontrado no ambiente atual.", file=sys.stderr)
        print("Instale com: uv add 'mineru[pipeline]'", file=sys.stderr)
        return 1

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Erro: diretorio invalido: {input_dir}", file=sys.stderr)
        return 1

    pdf_files = find_pdfs(input_dir, args.recursive)
    if not pdf_files:
        print(f"Nenhum PDF encontrado em: {input_dir}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Diretorio de entrada: {input_dir}")
    print(f"Diretorio de saida : {output_dir}")
    print(f"Backend            : {args.backend}")
    print(f"Metodo             : {args.method}")
    if args.lang:
        print(f"Idioma             : {args.lang}")
    print(f"PDFs encontrados   : {len(pdf_files)}")
    print()

    successes: list[Path] = []
    failures: list[Path] = []

    for index, pdf_path in enumerate(pdf_files, start=1):
        print(f"[{index}/{len(pdf_files)}] Convertendo {pdf_path.name}")
        command = build_command(pdf_path, output_dir, args.backend, args.method, args.lang)

        result = subprocess.run(command, check=False)
        markdown_path = expected_markdown_path(output_dir, pdf_path, args.backend, args.method)

        if result.returncode == 0 and markdown_path.exists():
            successes.append(markdown_path)
            print(f"  OK -> {markdown_path}")
        else:
            failures.append(pdf_path)
            print(f"  FALHOU -> {pdf_path}")

        print()

    print("Resumo")
    print(f"  Convertidos com sucesso: {len(successes)}")
    print(f"  Falhas                : {len(failures)}")

    if successes:
        print("\nMarkdowns gerados:")
        for markdown_path in successes:
            print(f"  - {markdown_path}")

    if failures:
        print("\nArquivos com falha:")
        for pdf_path in failures:
            print(f"  - {pdf_path}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())