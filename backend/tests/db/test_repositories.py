"""Repository behavior and database integrity against real PostgreSQL."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Analysis, AnalysisStatus, AnalysisType, DiagnosticRecord, ProjectFile
from app.repositories.analyses import AnalysisRepository, DiagnosticRepository
from app.repositories.files import FileRepository
from app.repositories.projects import ProjectRepository
from app.services.analysis.models import Diagnostic, DiagnosticCategory, Severity
from app.services.file_content import file_values


def make_diagnostic(line: int = 1) -> Diagnostic:
    return Diagnostic(
        id="x",
        severity=Severity.ERROR,
        message="bad",
        source="python",
        code="SyntaxError",
        category=DiagnosticCategory.SYNTAX,
        file_path="a.py",
        line=line,
        column=1,
        end_line=line,
        end_column=2,
    )


def new_analysis(
    repo: AnalysisRepository, project_id: uuid.UUID, file_id: uuid.UUID | None = None
) -> Analysis:
    return repo.create(
        project_id=project_id,
        file_id=file_id,
        analysis_type=AnalysisType.CODE,
        status=AnalysisStatus.COMPLETED,
        duration_ms=1,
        diagnostic_count=0,
        details={},
    )


def test_project_crud(session: Session) -> None:
    repo = ProjectRepository(session)
    project = repo.create(name="Alpha", description="first", root_path=None)
    session.commit()
    assert repo.get(project.id) is not None
    assert repo.get_by_name("ALPHA") is not None  # case-insensitive lookup

    repo.update(project, description="changed")
    session.commit()
    assert repo.get(project.id).description == "changed"  # type: ignore[union-attr]

    items, total = repo.list(limit=10, offset=0)
    assert total == 1
    assert [p.name for p in items] == ["Alpha"]

    repo.delete(project)
    session.commit()
    assert repo.get(project.id) is None


def test_project_names_are_unique_case_insensitively(session: Session) -> None:
    repo = ProjectRepository(session)
    repo.create(name="Demo", description=None, root_path=None)
    session.commit()
    with pytest.raises(IntegrityError):
        repo.create(name="demo", description=None, root_path=None)
    session.rollback()


def test_file_crud_and_unique_path(session: Session) -> None:
    project = ProjectRepository(session).create(name="P", description=None, root_path=None)
    files = FileRepository(session)
    record = files.create(project_id=project.id, **file_values("src/a.py", "x = 1\n"))
    session.commit()
    assert record.language == "python"
    assert record.line_count == 1
    assert files.get_by_path(project.id, "src/a.py") is not None

    listed, total = files.list_metadata(project.id, limit=10, offset=0)
    assert total == 1
    assert listed[0].path == "src/a.py"

    with pytest.raises(IntegrityError):
        files.create(project_id=project.id, **file_values("src/a.py", ""))
    session.rollback()

    files.update(record, **file_values("src/b.py", "y = 2\n"))
    session.commit()
    assert files.get(project.id, record.id).path == "src/b.py"  # type: ignore[union-attr]
    files.delete(record)
    session.commit()
    assert files.get(project.id, record.id) is None


def test_foreign_keys_are_enforced(session: Session) -> None:
    with pytest.raises(IntegrityError):
        FileRepository(session).create(project_id=uuid.uuid4(), **file_values("a.py", ""))
    session.rollback()


def test_deleting_a_project_cascades(session: Session) -> None:
    project = ProjectRepository(session).create(name="Cascade", description=None, root_path=None)
    record = FileRepository(session).create(project_id=project.id, **file_values("a.py", "x"))
    analysis = new_analysis(AnalysisRepository(session), project.id, record.id)
    DiagnosticRepository(session).create_many(analysis.id, [make_diagnostic()])
    session.commit()

    ProjectRepository(session).delete(project)
    session.commit()
    for model in (ProjectFile, Analysis, DiagnosticRecord):
        assert session.scalar(select(func.count()).select_from(model)) == 0


def test_deleting_a_file_keeps_its_analysis_history(session: Session) -> None:
    project = ProjectRepository(session).create(name="Keep", description=None, root_path=None)
    record = FileRepository(session).create(project_id=project.id, **file_values("a.py", "x"))
    analysis = new_analysis(AnalysisRepository(session), project.id, record.id)
    session.commit()

    FileRepository(session).delete(record)
    session.commit()
    session.refresh(analysis)
    assert analysis.file_id is None  # ON DELETE SET NULL


def test_check_constraint_rejects_invalid_severity(session: Session) -> None:
    project = ProjectRepository(session).create(name="Check", description=None, root_path=None)
    analysis = new_analysis(AnalysisRepository(session), project.id)
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO diagnostics (id, analysis_id, severity, category, message, source, line, "
                "\"column\", end_line, end_column, fixable) VALUES (:id, :a, 'catastrophic', 'syntax', "
                "'m', 's', 1, 1, 1, 1, false)"
            ),
            {"id": uuid.uuid4(), "a": analysis.id},
        )
    session.rollback()


def test_rollback_discards_uncommitted_changes(session: Session) -> None:
    repo = ProjectRepository(session)
    repo.create(name="Transient", description=None, root_path=None)
    session.rollback()
    assert repo.get_by_name("Transient") is None


def test_diagnostics_persist_in_order(session: Session) -> None:
    project = ProjectRepository(session).create(name="Diag", description=None, root_path=None)
    analysis = new_analysis(AnalysisRepository(session), project.id)
    repo = DiagnosticRepository(session)
    assert repo.create_many(analysis.id, [make_diagnostic(3), make_diagnostic(1)]) == 2
    session.commit()
    stored = repo.list_by_analysis(analysis.id)
    assert [d.line for d in stored] == [1, 3]
    assert stored[0].severity is Severity.ERROR
    assert stored[0].rule_code == "SyntaxError"


def test_history_pruning_keeps_newest(session: Session) -> None:
    project = ProjectRepository(session).create(name="Prune", description=None, root_path=None)
    record = FileRepository(session).create(project_id=project.id, **file_values("a.py", "x"))
    repo = AnalysisRepository(session)
    for _ in range(5):
        new_analysis(repo, project.id, record.id)
        session.commit()
    assert repo.prune_file_history(record.id, keep=2) == 3
    session.commit()
    _, total = repo.list_by_project(project.id, limit=10, offset=0)
    assert total == 2
