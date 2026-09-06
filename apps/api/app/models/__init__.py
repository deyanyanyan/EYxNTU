"""Import every model here so Alembic autogenerate and `Base.metadata` see them."""
from app.models.asset import ApprovalState, Asset, AssetKind, Citation  # noqa: F401
from app.models.chunk import Chunk  # noqa: F401
from app.models.course import CoursePlan, Lesson, Module, PlanStatus  # noqa: F401
from app.models.job import Job, JobKind, JobStatus  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.prompt_version import PromptVersion  # noqa: F401
from app.models.rag_config import RagConfig  # noqa: F401
from app.models.review import Review  # noqa: F401
from app.models.source import Source, SourceStatus  # noqa: F401
from app.models.user import Role, User  # noqa: F401
