"""Módulo neutro para resolver o nome legível do curso a partir do sub_source do Exact.

Existe para quebrar o import circular: `exact_routes` importa `sync_exact_leads` de
`exact_spotter`, então `exact_spotter` NÃO pode importar de volta de `exact_routes`.
Ambos importam daqui.

REGRA: este módulo importa SOMENTE de `app.models` + SQLAlchemy.
NUNCA importar `routes`, `exact_routes` ou `exact_spotter` aqui — recria o ciclo.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import CourseAlias


async def resolve_course_name(sub_source: str, db: AsyncSession) -> str:
    """Resolve alias do curso para nome legivel via tabela course_aliases."""
    if not sub_source:
        return "Pós-Graduação"
    result = await db.execute(
        select(CourseAlias).where(
            func.lower(CourseAlias.alias) == func.lower(sub_source),
            CourseAlias.is_active == True,
        )
    )
    course = result.scalar_one_or_none()
    if course:
        return course.short_name
    # Fallback: remove prefixo pos e formata
    name = sub_source
    if name.lower().startswith("pos"):
        name = name[3:]
    name = name.replace("_", " ").replace("-", " ").strip()
    return name if name else "Pós-Graduação"
