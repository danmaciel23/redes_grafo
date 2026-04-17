## Episten

Este projeto baixa os PDFs publicados na pagina do Departamento de Justica dos EUA referente ao data set 12 do caso Epstein.

No estado atual do repositorio, o script de coleta e download e `get_files_pdfs.py`. Se voce estava tentando executar `get_files.py`, esse nome nao existe neste workspace.

## Requisitos

- Python 3.12 ou superior
- `uv` instalado
- Google Chrome instalado

## O que e o uv

`uv` e uma ferramenta para gerenciar ambiente virtual, dependencias e execucao de projetos Python de forma rapida.

Neste projeto, ele serve para:

- criar ou reutilizar o ambiente virtual
- instalar as dependencias declaradas em `pyproject.toml`
- executar os scripts com o ambiente correto

## Comandos basicos com uv

### 1. Instalar o uv

Se ainda nao tiver o `uv`, instale conforme a documentacao oficial:

https://docs.astral.sh/uv/

### 2. Sincronizar as dependencias do projeto

No diretorio do projeto, execute:

```powershell
uv sync
```

Esse comando cria o ambiente virtual `.venv` e instala as dependencias listadas em `pyproject.toml`.

### 3. Ativar o ambiente virtual manualmente

Se quiser trabalhar com o ambiente ativo no terminal:

```powershell
.\.venv\Scripts\Activate.ps1
```

Isso e opcional quando voce usa `uv run`, porque o proprio `uv` ja executa o comando dentro do ambiente correto.

### 4. Executar um script com uv

Para rodar qualquer script Python do projeto:

```powershell
uv run .\nome_do_script.py
```

## Uso do script de download

### Script atual

O script presente no repositorio e:

```text
get_files_pdfs.py
```

Para executa-lo:

```powershell
uv run .\get_files_pdfs.py
```

## O que o script faz

O `get_files_pdfs.py` executa este fluxo:

1. abre a pagina inicial usando Selenium com Chrome em modo headless
2. identifica quantas paginas de resultados existem
3. coleta todos os links de arquivos PDF
4. remove links duplicados
5. copia os cookies da sessao do navegador para um `requests.Session()`
6. baixa os PDFs para a pasta `dataset12_pdfs/`

## Pasta de saida

Os arquivos baixados sao gravados em:

```text
dataset12_pdfs/
```

Se a pasta nao existir, ela e criada automaticamente.

## Exemplo de execucao

Fluxo recomendado no PowerShell:

```powershell
uv sync
uv run .\get_files_pdfs.py
```

## Converter PDFs para Markdown com MinerU

O projeto agora tambem possui um wrapper simples para o CLI do MinerU:

```text
convert_pdfs_to_markdown.py
```

Esse script:

1. localiza todos os arquivos `.pdf` de um diretorio
2. executa o comando `mineru` para cada arquivo
3. grava os resultados no diretorio de saida do MinerU
4. mostra no final quais arquivos `.md` foram gerados

### Requisito

O MinerU precisa estar instalado no ambiente do projeto. Exemplo:

```powershell
uv add "mineru[pipeline]"
```

### Uso basico

Para converter todos os PDFs da pasta `dataset12_pdfs`:

```powershell
uv run .\convert_pdfs_to_markdown.py .\dataset12_pdfs
```

### Escolhendo pasta de saida

```powershell
uv run .\convert_pdfs_to_markdown.py .\dataset12_pdfs -o .\mineru_output
```

### Busca recursiva

```powershell
uv run .\convert_pdfs_to_markdown.py .\dataset12_pdfs --recursive
```

### Parametros uteis

- `-o, --output-dir`: diretorio raiz de saida
- `-b, --backend`: backend do MinerU. Padrao: `pipeline`
- `-m, --method`: metodo de parsing (`auto`, `txt`, `ocr`)
- `-l, --lang`: idioma do documento
- `--recursive`: busca PDFs em subpastas

### Exemplo recomendado para CPU

Segundo a documentacao do MinerU, o backend `pipeline` e o indicado para uso simples em CPU:

```powershell
uv run .\convert_pdfs_to_markdown.py .\dataset12_pdfs -o .\mineru_output -b pipeline
```

### Estrutura de saida

O MinerU organiza a saida por documento. Exemplo:

```text
mineru_output/
	NOME_DO_ARQUIVO/
		auto/
			NOME_DO_ARQUIVO.md
			NOME_DO_ARQUIVO_content_list.json
			NOME_DO_ARQUIVO_middle.json
			images/
```

## Dependencias usadas pelo script

As dependencias atualmente declaradas no projeto sao:

- `beautifulsoup4`
- `requests`
- `selenium`
- `webdriver-manager`

Observacao: o script atual usa principalmente `requests`, `selenium` e `webdriver-manager`.

## Possiveis erros comuns

### Tentar rodar `get_files.py`

Se voce executar:

```powershell
uv run .\get_files.py
```

o comando vai falhar porque esse arquivo nao existe no repositorio atual.

Use:

```powershell
uv run .\get_files_pdfs.py
```

### Falha ao iniciar o Chrome

Verifique se o Google Chrome esta instalado. O Selenium usa o ChromeDriver gerenciado por `webdriver-manager`.

### Erros de rede ou timeout

Como o script acessa uma pagina externa e baixa varios arquivos, falhas temporarias de conexao podem ocorrer. Nesses casos, rode o script novamente.

### Arquivos ja existentes

Se um PDF ja estiver na pasta de destino, o script pula o download e mostra a mensagem `JA EXISTE`.

## Arquivos principais do projeto

- `pyproject.toml`: configuracao do projeto e dependencias
- `get_files_pdfs.py`: script principal de coleta e download dos PDFs
- `dataset12_pdfs/`: diretorio de saida dos arquivos baixados

