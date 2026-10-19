"""Build the weekly summary with aggregate cancellation associations."""
from contextlib import closing
from pathlib import Path

from jinja2 import Template

from . import analysis, db, factors


def build(db_path=None, output_path="outbox/summary.md", include_factors=True, as_of=None):
    database = Path(db.DB_PATH if db_path is None else db_path).resolve(strict=True)
    output = Path(output_path).resolve()
    protected = {database, (Path(__file__).resolve().parents[2] / "data/customers.db").resolve()}
    for source in protected:
        if output == source or (output.exists() and source.exists() and output.samefile(source)):
            raise ValueError("Report output must not overwrite the input database")

    with closing(db.connect(database)) as conn:
        customers = db.get_factor_customers(conn) if include_factors else db.get_customers(conn)
        stats = analysis.cancellation_reasons(
            customers, db.get_factor_comments(conn), as_of=as_of
        ) if include_factors else None
    rate = analysis.cancellation_rate(customers)
    factor_rows, factor_notes = factors.report_content(stats) if stats is not None else ([], [])
    template_path = Path(__file__).resolve().parents[2] / "templates/weekly_summary.md.j2"
    tpl = Template(template_path.read_text(encoding="utf-8"))
    out = tpl.render(
        total=len(customers),
        cancellation_rate="N/A" if rate is None else f"{rate:.2%}",
        drivers=[],
        factor_rows=factor_rows,
        factor_notes=factor_notes,
        at_risk=[],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(out, encoding="utf-8")
    return output


if __name__ == "__main__":
    print(f"wrote {build()}")
