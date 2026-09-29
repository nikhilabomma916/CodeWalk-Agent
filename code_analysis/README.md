# Code Analysis Engine

Real-time syntax checking, linting, and static analysis for CodeWalk Agent.
Owns the "Code Analysis Engine" box in `docs/system-architecture.md` — a
standalone module, independent of the backend/API/DB layers, that turns
source text into structured diagnostics.

## Status

**Stage 1** (initial implementation):

- Python syntax error detection (`compile()`).
- Python static analysis / linting via `pyflakes` (undefined names, unused
  imports/variables, redefinitions).
- Diagnostics classified as `error` / `warning` / `suggestion` per
  `docs/PRD.md` section 13.
- Single-file/snippet analysis only. Project-wide scanning is out of scope
  here — see `docs/project-intelligence.md` (owned separately) — but this
  engine is designed to be called once per file by that scanner.

Not yet implemented (later stages): additional languages (JS/TS/etc.),
type checking (mypy), suggestion-tier code-quality heuristics beyond
unused-import/variable, project-level aggregation.

## Install

```bash
pip install -r code_analysis/requirements.txt
```

## Usage

```python
from code_analysis import analyze_code

result = analyze_code(source="print('hi'", language="python")

result.language        # "python"
result.error_count     # 1
result.diagnostics     # [Diagnostic(severity=Severity.ERROR, message="...", line=1, ...)]
```

`language` can be omitted if `file_path` is given — the language is then
inferred from the extension (see `language_detect.py`):

```python
result = analyze_code(source=open("app.py").read(), file_path="app.py")
```

Unsupported/undetectable languages raise `UnsupportedLanguageError` rather
than failing silently or crashing.

### CLI (manual testing/demo)

```bash
python -m code_analysis.cli path/to/file.py
```

## Integration contract for the backend

`docs/system-architecture.md` section 9 sketches
`backend/app/services/analysis_service.py` and `backend/app/api/analysis.py`
calling into a code analysis engine. This package is that engine — the
backend should import it directly rather than reimplementing parsing/linting:

```python
# backend/app/services/analysis_service.py (not part of this module)
from code_analysis import analyze_code, UnsupportedLanguageError

def analyze(request: AnalyzeCodeRequest) -> AnalyzeCodeResponse:
    try:
        result = analyze_code(
            source=request.source,
            language=request.language,
            file_path=request.file_path,
        )
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AnalyzeCodeResponse(**result.model_dump())
```

`AnalysisResult` and `Diagnostic` (in `models.py`) are Pydantic `BaseModel`s,
so they serialize to JSON directly and can be reused as (or wrapped by)
FastAPI response schemas without redefinition.

## Tests

Run from the repository root so `code_analysis` resolves as an import:

```bash
python -m pytest code_analysis/tests -v
```

## Design notes

- **Why `pyflakes` over `pylint`/`mypy` for Stage 1**: it's AST-based with
  no project-wide config step, so it's fast enough to run per-keystroke
  (behind the frontend's debounce) and returns structured `Message` objects
  rather than parsing stdout text. `mypy` runs a much heavier type-checking
  pass and is a candidate for a later, less latency-sensitive stage.
- **Why syntax errors short-circuit linting**: pyflakes requires a valid AST;
  running it against unparsable source either fails or produces noise, so
  the engine returns just the syntax diagnostic when `compile()` fails.
- **Extensibility**: new languages register a `LanguageAnalyzer` subclass in
  `analyzers/` and one line in `analyzers/__init__.py`'s registry —
  `engine.py` and `models.py` never need to change.
