from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Iterable, Optional, Sequence

from sortdocs.config import SortdocsConfig
from sortdocs.models import ActionType, ClassificationResult, PlannedAction
from sortdocs.scanner import DiscoveredFile
from sortdocs.utils import sanitize_path_component


DEFAULT_CATEGORY = "uncategorized"
DEFAULT_SUBCATEGORY = "general"
DEFAULT_FILENAME_STEM = "document"
CANONICAL_DIRECTORY_ALIASES = {
    "bill": "bills",
    "bills": "bills",
    "contract": "contracts",
    "contracts": "contracts",
    "form": "forms",
    "forms": "forms",
    "image": "images",
    "images": "images",
    "invoice": "invoices",
    "invoices": "invoices",
    "note": "notes",
    "notes": "notes",
    "photo": "photos",
    "photos": "photos",
    "policy": "policies",
    "policies": "policies",
    "receipt": "receipts",
    "receipts": "receipts",
    "report": "reports",
    "reports": "reports",
    "reservation": "reservations",
    "reservations": "reservations",
    "statement": "statements",
    "statements": "statements",
    "ticket": "tickets",
    "tickets": "tickets",
    "utilities": "utility_bills",
    "utility": "utility_bills",
    "utility_bill": "utility_bills",
    "utility_bills": "utility_bills",
}
DIRECTORY_FAMILY_ALIASES = {
    "bill": "billing",
    "bills": "billing",
    "bills_paid": "billing",
    "paid_bill": "billing",
    "paid_bills": "billing",
    "bill_payment": "billing",
    "bill_payments": "billing",
    "invoice": "invoice",
    "invoices": "invoice",
    "receipt": "receipt",
    "receipts": "receipt",
    "statement": "statement",
    "statements": "statement",
    "utilities": "utility_billing",
    "utility": "utility_billing",
    "utility_bill": "utility_billing",
    "utility_bills": "utility_billing",
}
REUSABLE_FAMILY_MODIFIER_TOKENS = frozenset({"bill", "paid", "payment", "utility"})
PATH_HARMONIZATION_SIMILARITY_THRESHOLD = 0.45
SEMANTIC_TOKEN_ALIASES = {
    "certification": "certificate",
}
ROOT_CONTEXT_COLLAPSE_TOKENS = frozenset(
    {
        "book",
        "certificate",
        "photo",
        "image",
        "video",
        "music",
        "recipe",
        "manual",
        "guide",
    }
)
GENERIC_GROUP_TOKENS = frozenset(
    {
        "education",
        "reference",
        "general",
        "misc",
        "other",
        "uncategorized",
        "resource",
        "resources",
        "document",
        "documents",
        "library",
        "libraries",
        "book",
        "books",
    }
)


@dataclass(frozen=True)
class PlannerDirectories:
    library_dir: Path
    review_dir: Path


@dataclass(frozen=True)
class DirectorySemanticProfile:
    name: str
    semantic_key: str
    tokens: frozenset[str]
    family_key: Optional[str]


@dataclass(frozen=True)
class SuggestedPathProfile:
    category: str
    category_tokens: frozenset[str]
    normalized_path: str
    parts: tuple[str, ...]
    path_tokens: frozenset[str]
    evidence_tokens: frozenset[str]


class Planner:
    def __init__(
        self,
        config: SortdocsConfig,
        *,
        library_dir: Path,
        review_dir: Path,
    ) -> None:
        self._config = config
        self._directories = PlannerDirectories(
            library_dir=library_dir.expanduser().resolve(),
            review_dir=review_dir.expanduser().resolve(),
        )
        self._occupied_paths: set[Path] = set()
        self._known_child_directories: dict[Path, set[str]] = {}

    def plan_file(
        self,
        discovered_file: DiscoveredFile,
        classification: ClassificationResult,
        *,
        inherited_warnings: Optional[Sequence[str]] = None,
    ) -> PlannedAction:
        source_path = discovered_file.absolute_path.resolve()
        warnings: list[str] = [*discovered_file.warnings, *(inherited_warnings or ())]

        target_filename = sanitize_filename(
            classification.suggested_filename,
            original_extension=discovered_file.extension,
            max_length=self._config.planner.max_filename_length,
            warnings=warnings,
        )

        category = sanitize_directory_component(
            classification.category,
            default=DEFAULT_CATEGORY,
            label="category",
            warnings=warnings,
        )
        subcategory = sanitize_directory_component(
            classification.subcategory,
            default=DEFAULT_SUBCATEGORY,
            label="subcategory",
            warnings=warnings,
        )

        category_not_allowed = (
            self._config.planner.allowed_categories is not None
            and category not in self._config.planner.allowed_categories
        )
        unsupported_source = not discovered_file.is_supported
        force_review = classification.needs_review or (
            classification.confidence < self._config.planner.review_confidence_threshold
        ) or category_not_allowed or unsupported_source
        if force_review:
            target_directory, target_filename = self._build_review_destination(
                source_path=source_path,
                target_filename=target_filename,
                warnings=warnings,
            )
            if classification.needs_review:
                warnings.append("Model explicitly flagged this file for manual review.")
            if classification.confidence < self._config.planner.review_confidence_threshold:
                warnings.append("Confidence below review threshold; file requires manual review.")
            if category_not_allowed:
                warnings.append("Category is not in the configured allow-list; file requires manual review.")
            if unsupported_source:
                warnings.append("Unsupported or high-risk source file requires manual review.")
            reason = classification.reason
        else:
            if classification.suggested_path:
                target_directory = self._build_ai_target_directory(
                    classification.suggested_path,
                    warnings=warnings,
                )
            else:
                target_directory = self._build_target_directory(
                    pattern=self._config.planner.target_path_pattern,
                    category=category,
                    subcategory=subcategory,
                    year=extract_year(discovered_file),
                    warnings=warnings,
                )
            reason = classification.reason

        desired_target_path = target_directory / target_filename
        target_path = resolve_collision(
            desired_target_path=desired_target_path,
            source_path=source_path,
            occupied_paths=self._occupied_paths,
            max_filename_length=self._config.planner.max_filename_length,
            warnings=warnings,
        )
        action_type = determine_action_type(
            source_path=source_path,
            target_path=target_path,
            force_review=force_review,
        )

        return PlannedAction(
            source_path=source_path,
            target_directory=target_path.parent,
            target_filename=target_path.name,
            target_path=target_path,
            action_type=action_type,
            confidence=classification.confidence,
            reason=reason,
            category=category,
            subcategory=subcategory,
            tags=list(classification.tags),
            suggested_path=classification.suggested_path,
            warnings=warnings,
            approved_roots=(self._directories.library_dir, self._directories.review_dir),
            cleanup_root=derive_source_root(discovered_file),
        )

    def plan_files(
        self,
        items: Sequence[tuple[DiscoveredFile, ClassificationResult]],
    ) -> list[PlannedAction]:
        harmonized_items, harmonization_warnings = self._harmonize_ai_suggested_paths(items)
        return [
            self.plan_file(
                discovered_file,
                classification,
                inherited_warnings=harmonization_warnings.get(index),
            )
            for index, (discovered_file, classification) in enumerate(harmonized_items)
        ]

    def _build_review_destination(
        self,
        *,
        source_path: Path,
        target_filename: str,
        warnings: list[str],
    ) -> tuple[Path, str]:
        if self._directories.review_dir == self._directories.library_dir:
            warnings.append("Review routing is configured in-place, so the file was kept in its current folder.")
            return source_path.parent, source_path.name
        return self._directories.review_dir, target_filename

    def _build_target_directory(
        self,
        *,
        pattern: str,
        category: str,
        subcategory: str,
        year: Optional[int],
        warnings: list[str],
    ) -> Path:
        path_parts = render_target_directory_parts(
            pattern=pattern,
            category=category,
            subcategory=subcategory,
            year=year,
            warnings=warnings,
        )

        current_dir = self._directories.library_dir
        for candidate_part in path_parts:
            chosen_part = self._reuse_equivalent_directory_name(
                parent_dir=current_dir,
                candidate_part=candidate_part,
                warnings=warnings,
            )
            current_dir = current_dir / chosen_part
            self._register_known_directory(current_dir)

        return current_dir

    def _build_ai_target_directory(self, suggested_path: str, *, warnings: list[str]) -> Path:
        current_dir = self._directories.library_dir
        raw_parts = [part for part in suggested_path.split("/") if part.strip()]
        path_parts = normalize_path_parts(
            suggested_path,
            root_tokens=active_root_context_tokens(self._directories.library_dir),
            warnings=warnings,
        )
        if path_parts != raw_parts:
            warnings.append("AI-suggested folder path was sanitized for filesystem safety.")
        if not path_parts:
            warnings.append("AI-suggested folder path became empty after sanitization; default folders were used.")
            return self._build_target_directory(
                pattern=self._config.planner.target_path_pattern,
                category=DEFAULT_CATEGORY,
                subcategory=DEFAULT_SUBCATEGORY,
                year=None,
                warnings=warnings,
            )

        for part in path_parts:
            chosen_part = self._reuse_equivalent_directory_name(
                parent_dir=current_dir,
                candidate_part=part,
                warnings=warnings,
            )
            current_dir = current_dir / chosen_part
            self._register_known_directory(current_dir)
        return current_dir

    def _harmonize_ai_suggested_paths(
        self,
        items: Sequence[tuple[DiscoveredFile, ClassificationResult]],
    ) -> tuple[list[tuple[DiscoveredFile, ClassificationResult]], dict[int, list[str]]]:
        harmonized_items = list(items)
        warnings_by_index: dict[int, list[str]] = {}
        indexed_profiles: list[tuple[int, SuggestedPathProfile]] = []
        root_tokens = active_root_context_tokens(self._directories.library_dir)

        for index, (_, classification) in enumerate(items):
            profile = build_suggested_path_profile(classification, root_tokens=root_tokens)
            if profile is not None:
                indexed_profiles.append((index, profile))

        if len(indexed_profiles) < 2:
            return harmonized_items, warnings_by_index

        for component in cluster_suggested_path_profiles(indexed_profiles):
            distinct_paths = {profile.normalized_path for _, profile in component}
            if len(component) < 2 or len(distinct_paths) < 2:
                continue
            if not component_is_harmonizable(component, root_dir=self._directories.library_dir):
                continue

            consensus_path = choose_consensus_suggested_path(
                component,
                root_dir=self._directories.library_dir,
            )
            for index, profile in component:
                if profile.normalized_path == consensus_path:
                    continue
                discovered_file, classification = harmonized_items[index]
                harmonized_items[index] = (
                    discovered_file,
                    classification.model_copy(update={"suggested_path": consensus_path}),
                )
                warnings_by_index.setdefault(index, []).append(
                    "Aligned AI-suggested folder path from "
                    f"'{profile.normalized_path}' to '{consensus_path}' to keep similar files together."
                )

        return harmonized_items, warnings_by_index

    def _reuse_equivalent_directory_name(
        self,
        *,
        parent_dir: Path,
        candidate_part: str,
        warnings: list[str],
    ) -> str:
        known_names = self._known_child_names(parent_dir)
        if candidate_part in known_names:
            return candidate_part

        candidate_profile = build_directory_profile(candidate_part)
        best_name: Optional[str] = None
        best_score = 0
        score_tie = False

        for known_name in sorted(known_names):
            score = directory_reuse_score(
                candidate_profile=candidate_profile,
                existing_profile=build_directory_profile(known_name),
            )
            if score <= 0:
                continue
            if score > best_score:
                best_name = known_name
                best_score = score
                score_tie = False
            elif score == best_score:
                score_tie = True

        if best_name is not None and not score_tie and best_name != candidate_part:
            warnings.append(
                f"Reused existing directory '{best_name}' instead of creating near-duplicate '{candidate_part}'."
            )
            return best_name

        return candidate_part

    def _known_child_names(self, parent_dir: Path) -> set[str]:
        resolved_parent = parent_dir.expanduser().resolve()
        cached = self._known_child_directories.get(resolved_parent)
        if cached is not None:
            return cached

        discovered_names: set[str] = set()
        if resolved_parent.exists():
            try:
                for child in resolved_parent.iterdir():
                    if child.is_dir():
                        discovered_names.add(child.name)
            except OSError:
                pass

        self._known_child_directories[resolved_parent] = discovered_names
        return discovered_names

    def _register_known_directory(self, directory: Path) -> None:
        resolved_directory = directory.expanduser().resolve()
        self._known_child_names(resolved_directory.parent).add(resolved_directory.name)


def render_plan_table(actions: Iterable[PlannedAction], *, base_dir: Optional[Path] = None) -> str:
    action_list = list(actions)
    rows: list[tuple[str, str, str, str, str]] = []

    for action in action_list:
        source_label = display_path(action.source_path, base_dir)
        target_label = display_path(action.target_path, base_dir)
        warnings = " | ".join(action.warnings) if action.warnings else "-"
        rows.append(
            (
                action.action_type.value,
                f"{action.confidence:.2f}",
                source_label,
                target_label,
                warnings,
            )
        )

    headers = ("action", "conf", "source", "target", "warnings")
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(current, len(value)) for current, value in zip(widths, row)]

    header_line = " | ".join(header.ljust(width) for header, width in zip(headers, widths))
    separator = "-+-".join("-" * width for width in widths)
    data_lines = [
        " | ".join(value.ljust(width) for value, width in zip(row, widths))
        for row in rows
    ]
    return "\n".join([header_line, separator, *data_lines]) if data_lines else "\n".join([header_line, separator])


def render_target_directory_parts(
    *,
    pattern: str,
    category: str,
    subcategory: str,
    year: Optional[int],
    warnings: Optional[list[str]] = None,
) -> list[str]:
    warning_list = warnings if warnings is not None else []
    pattern_context = {
        "category": category,
        "subcategory": subcategory,
        "year": str(year) if year is not None else "",
    }
    formatter = Formatter()
    path_parts: list[str] = []

    for raw_segment in pattern.split("/"):
        rendered = formatter.vformat(raw_segment, (), pattern_context).strip()
        sanitized = sanitize_path_component(rendered, default="", lowercase=True)
        if sanitized:
            path_parts.append(sanitized)

    if not path_parts:
        warning_list.append("Configured target path pattern produced an empty path; default folders were used.")
        path_parts = [category, subcategory]

    return path_parts


def extract_year(discovered_file: DiscoveredFile) -> Optional[int]:
    if discovered_file.created_at is not None:
        return discovered_file.created_at.year
    if discovered_file.modified_at is not None:
        return discovered_file.modified_at.year
    return None


def sanitize_filename(
    raw_filename: str,
    *,
    original_extension: str,
    max_length: int,
    warnings: Optional[list[str]] = None,
) -> str:
    warning_list = warnings if warnings is not None else []
    candidate = raw_filename.strip()
    input_extension = Path(candidate).suffix.lower()
    candidate_stem = Path(candidate).stem if input_extension else candidate
    if input_extension and input_extension != original_extension.lower():
        warning_list.append("Suggested filename extension differed from the source; original extension was preserved.")

    sanitized_stem = sanitize_path_component(candidate_stem, default=DEFAULT_FILENAME_STEM, lowercase=True)
    if not sanitized_stem:
        sanitized_stem = DEFAULT_FILENAME_STEM
        warning_list.append("Suggested filename became empty after sanitization; a fallback name was used.")
    elif candidate_stem != sanitized_stem:
        warning_list.append("Suggested filename was sanitized for filesystem safety.")

    extension = original_extension.lower()
    max_stem_length = max(1, max_length - len(extension))
    if len(sanitized_stem) > max_stem_length:
        sanitized_stem = sanitized_stem[:max_stem_length].rstrip("._-") or DEFAULT_FILENAME_STEM
        warning_list.append("Suggested filename was truncated to fit the configured length limit.")

    return f"{sanitized_stem}{extension}"


def sanitize_directory_component(
    value: str,
    *,
    default: str,
    label: str,
    warnings: Optional[list[str]] = None,
) -> str:
    warning_list = warnings if warnings is not None else []
    sanitized = sanitize_path_component(value, default=default, lowercase=True)
    canonical = canonicalize_directory_label(sanitized, label=label)
    if canonical != sanitized:
        warning_list.append(f"{label.capitalize()} was normalized to the canonical folder name '{canonical}'.")
        sanitized = canonical
    if sanitized != value.strip().lower():
        warning_list.append(f"{label.capitalize()} was sanitized for filesystem safety.")
    if sanitized == default and value.strip():
        warning_list.append(f"{label.capitalize()} could not be used as-is and fell back to '{default}'.")
    return sanitized


def canonicalize_directory_label(value: str, *, label: str) -> str:
    if label != "subcategory":
        return value
    return CANONICAL_DIRECTORY_ALIASES.get(value, value)


def build_directory_profile(value: str) -> DirectorySemanticProfile:
    semantic_key = directory_semantic_key(value)
    tokens = frozenset(part for part in semantic_key.split("_") if part)
    family_key = resolve_directory_family_key(value, tokens)
    return DirectorySemanticProfile(
        name=value,
        semantic_key=semantic_key,
        tokens=tokens,
        family_key=family_key,
    )


def resolve_directory_family_key(value: str, tokens: frozenset[str]) -> Optional[str]:
    if value in DIRECTORY_FAMILY_ALIASES:
        return DIRECTORY_FAMILY_ALIASES[value]

    families = {
        DIRECTORY_FAMILY_ALIASES[token]
        for token in tokens
        if token in DIRECTORY_FAMILY_ALIASES
    }
    if len(families) == 1:
        return next(iter(families))
    return None


def directory_reuse_score(
    *,
    candidate_profile: DirectorySemanticProfile,
    existing_profile: DirectorySemanticProfile,
) -> int:
    if existing_profile.semantic_key == candidate_profile.semantic_key:
        return 100

    if candidate_profile.family_key is None or existing_profile.family_key != candidate_profile.family_key:
        return 0

    candidate_extra = candidate_profile.tokens - existing_profile.tokens
    existing_extra = existing_profile.tokens - candidate_profile.tokens
    if candidate_extra and not candidate_extra <= REUSABLE_FAMILY_MODIFIER_TOKENS:
        return 0
    if existing_extra and not existing_extra <= REUSABLE_FAMILY_MODIFIER_TOKENS:
        return 0

    overlap = candidate_profile.tokens & existing_profile.tokens
    if not overlap:
        return 0

    return 80 - abs(len(candidate_profile.tokens) - len(existing_profile.tokens))


def directory_semantic_key(value: str) -> str:
    parts = [part for part in value.split("_") if part]
    normalized_parts = [_normalize_semantic_token(_singularize_token(part)) for part in parts]
    return "_".join(normalized_parts)


def build_suggested_path_profile(
    classification: ClassificationResult,
    *,
    root_tokens: frozenset[str] = frozenset(),
) -> Optional[SuggestedPathProfile]:
    if not classification.suggested_path or classification.needs_review:
        return None

    category = sanitize_path_component(classification.category, default="", lowercase=True)
    path_parts = normalize_path_parts(classification.suggested_path, root_tokens=root_tokens)
    if not category or not path_parts:
        return None

    category_tokens = frozenset(
        token
        for token in semantic_tokens_from_value(category)
        if token not in root_tokens
    )
    path_tokens = semantic_tokens_from_parts(path_parts)
    evidence_tokens = set(path_tokens)
    evidence_tokens.update(category_tokens)
    evidence_tokens.update(
        token
        for token in semantic_tokens_from_value(classification.subcategory)
        if token not in root_tokens
    )
    for tag in classification.tags:
        evidence_tokens.update(
            token
            for token in semantic_tokens_from_value(tag)
            if token not in root_tokens
        )

    return SuggestedPathProfile(
        category=category,
        category_tokens=category_tokens,
        normalized_path="/".join(path_parts),
        parts=tuple(path_parts),
        path_tokens=frozenset(path_tokens),
        evidence_tokens=frozenset(evidence_tokens),
    )


def normalize_path_parts(
    raw_path: str,
    *,
    root_tokens: frozenset[str] = frozenset(),
    warnings: Optional[list[str]] = None,
) -> list[str]:
    normalized_parts: list[str] = []
    warning_list = warnings if warnings is not None else []

    for raw_part in raw_path.split("/"):
        if not raw_part.strip():
            continue
        sanitized = sanitize_path_component(raw_part, default="", lowercase=True)
        if not sanitized:
            continue
        root_adjusted = strip_root_context_from_part(sanitized, root_tokens=root_tokens)
        if root_adjusted is None:
            if root_tokens:
                warning_list.append(
                    f"Dropped redundant root folder segment '{sanitized}' from the AI-suggested path."
                )
            continue
        if root_adjusted != sanitized:
            warning_list.append(
                f"Removed redundant root context from AI-suggested folder segment '{sanitized}'."
            )
        normalized_parts.append(root_adjusted)

    if root_tokens:
        normalized_parts = collapse_generic_leading_group(normalized_parts, warnings=warning_list)

    return normalized_parts


def strip_root_context_from_part(
    value: str,
    *,
    root_tokens: frozenset[str],
) -> Optional[str]:
    if not value or not root_tokens:
        return value or None

    part_tokens = frozenset(semantic_tokens_from_value(value))
    if part_tokens and part_tokens == root_tokens:
        return None

    raw_tokens = [token for token in value.split("_") if token]
    if not raw_tokens:
        return None

    kept_tokens = [
        token
        for token in raw_tokens
        if _normalize_semantic_token(_singularize_token(token)) not in root_tokens
    ]
    if not kept_tokens:
        return None
    normalized = sanitize_path_component("_".join(kept_tokens), default="", lowercase=True)
    return normalized or None


def active_root_context_tokens(root_dir: Path) -> frozenset[str]:
    tokens = frozenset(semantic_tokens_from_value(root_dir.name))
    if len(tokens) != 1:
        return frozenset()
    if not tokens <= ROOT_CONTEXT_COLLAPSE_TOKENS:
        return frozenset()
    return tokens


def collapse_generic_leading_group(
    path_parts: list[str],
    *,
    warnings: Optional[list[str]] = None,
) -> list[str]:
    if len(path_parts) < 2:
        return path_parts

    leading_tokens = frozenset(semantic_tokens_from_value(path_parts[0]))
    if not leading_tokens or not leading_tokens <= GENERIC_GROUP_TOKENS:
        return path_parts

    trailing_tokens = semantic_tokens_from_parts(path_parts[1:])
    if not trailing_tokens:
        return path_parts

    warning_list = warnings if warnings is not None else []
    warning_list.append(
        f"Collapsed generic leading folder '{path_parts[0]}' to keep a collection-specific root simpler."
    )
    return path_parts[1:]


def semantic_tokens_from_parts(parts: Sequence[str]) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        tokens.update(semantic_tokens_from_value(part))
    return tokens


def semantic_tokens_from_value(value: str) -> set[str]:
    sanitized = sanitize_path_component(value, default="", lowercase=True)
    if not sanitized:
        return set()
    return {
        token
        for token in directory_semantic_key(sanitized).split("_")
        if token
    }


def cluster_suggested_path_profiles(
    indexed_profiles: Sequence[tuple[int, SuggestedPathProfile]],
) -> list[list[tuple[int, SuggestedPathProfile]]]:
    profile_map = dict(indexed_profiles)
    visited: set[int] = set()
    components: list[list[tuple[int, SuggestedPathProfile]]] = []

    for index, profile in indexed_profiles:
        if index in visited:
            continue

        stack = [index]
        component: list[tuple[int, SuggestedPathProfile]] = []
        while stack:
            current_index = stack.pop()
            if current_index in visited:
                continue
            visited.add(current_index)
            current_profile = profile_map[current_index]
            component.append((current_index, current_profile))

            for other_index, other_profile in indexed_profiles:
                if other_index in visited:
                    continue
                if should_harmonize_suggested_paths(current_profile, other_profile):
                    stack.append(other_index)

        components.append(component)

    return components


def should_harmonize_suggested_paths(
    left: SuggestedPathProfile,
    right: SuggestedPathProfile,
) -> bool:
    if left.category_tokens and right.category_tokens and left.category_tokens != right.category_tokens:
        return False
    return suggested_path_similarity(left, right) >= PATH_HARMONIZATION_SIMILARITY_THRESHOLD


def suggested_path_similarity(
    left: SuggestedPathProfile,
    right: SuggestedPathProfile,
) -> float:
    path_score = jaccard_similarity(left.path_tokens, right.path_tokens)
    evidence_score = jaccard_similarity(left.evidence_tokens, right.evidence_tokens)
    return (path_score * 0.4) + (evidence_score * 0.6)


def choose_consensus_suggested_path(
    component: Sequence[tuple[int, SuggestedPathProfile]],
    *,
    root_dir: Path,
) -> str:
    cluster_size = len(component)
    token_counter = Counter(
        token
        for _, profile in component
        for token in profile.path_tokens
    )
    core_tokens = {
        token
        for token, count in token_counter.items()
        if count >= max(2, (cluster_size + 1) // 2)
    }
    path_counts = Counter(profile.normalized_path for _, profile in component)

    ranked_candidates: list[tuple[float, int, int, int, str]] = []
    for _, profile in component:
        overlap_score = sum(
            suggested_path_similarity(profile, other_profile)
            for _, other_profile in component
            if other_profile is not profile
        )
        coverage = len(profile.path_tokens & core_tokens)
        extras = len(profile.path_tokens - core_tokens)
        exists_bonus = 1 if (root_dir / profile.normalized_path).exists() else 0
        ranked_candidates.append(
            (
                overlap_score + (coverage * 0.5) + (path_counts[profile.normalized_path] * 0.25) + exists_bonus,
                coverage,
                -extras,
                -len(profile.parts),
                profile.normalized_path,
            )
        )

    ranked_candidates.sort(reverse=True)
    return ranked_candidates[0][-1]


def component_is_harmonizable(
    component: Sequence[tuple[int, SuggestedPathProfile]],
    *,
    root_dir: Path,
) -> bool:
    if len(component) > 2:
        return True

    if any((root_dir / profile.normalized_path).exists() for _, profile in component):
        return True

    if len(component) != 2:
        return False

    left = component[0][1]
    right = component[1][1]
    return (
        left.path_tokens <= right.path_tokens
        or right.path_tokens <= left.path_tokens
    )


def _singularize_token(token: str) -> str:
    if len(token) <= 4:
        return token
    if token.endswith("ies"):
        return f"{token[:-3]}y"
    if token.endswith(("sses", "ss", "is", "us")):
        return token
    if token.endswith("s"):
        return token[:-1]
    return token


def _normalize_semantic_token(token: str) -> str:
    return SEMANTIC_TOKEN_ALIASES.get(token, token)


def jaccard_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def resolve_collision(
    *,
    desired_target_path: Path,
    source_path: Path,
    occupied_paths: set[Path],
    max_filename_length: int,
    warnings: Optional[list[str]] = None,
) -> Path:
    warning_list = warnings if warnings is not None else []
    resolved_desired = desired_target_path.resolve()

    if resolved_desired == source_path:
        occupied_paths.add(resolved_desired)
        return resolved_desired

    if resolved_desired not in occupied_paths and not resolved_desired.exists():
        occupied_paths.add(resolved_desired)
        return resolved_desired

    extension = resolved_desired.suffix
    stem = resolved_desired.stem
    counter = 1
    while True:
        suffix = f"__{counter}"
        max_stem_length = max(1, max_filename_length - len(extension) - len(suffix))
        truncated_stem = stem[:max_stem_length].rstrip("._-") or DEFAULT_FILENAME_STEM
        candidate = resolved_desired.with_name(f"{truncated_stem}{suffix}{extension}")
        if candidate == source_path:
            occupied_paths.add(candidate)
            warning_list.append("Name collision detected; reused the source path.")
            return candidate
        if candidate not in occupied_paths and not candidate.exists():
            occupied_paths.add(candidate)
            warning_list.append("Name collision detected; an incremental suffix was added.")
            return candidate
        counter += 1


def determine_action_type(
    *,
    source_path: Path,
    target_path: Path,
    force_review: bool,
) -> ActionType:
    if source_path == target_path:
        return ActionType.SKIP
    if force_review:
        return ActionType.REVIEW

    same_directory = source_path.parent == target_path.parent
    same_filename = source_path.name == target_path.name

    if same_directory and not same_filename:
        return ActionType.RENAME
    if not same_directory and same_filename:
        return ActionType.MOVE
    return ActionType.MOVE_AND_RENAME


def display_path(path: Path, base_dir: Optional[Path]) -> str:
    if base_dir is None:
        return str(path)
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def derive_source_root(discovered_file: DiscoveredFile) -> Path:
    relative_parts = discovered_file.relative_path.parts
    if not relative_parts:
        return discovered_file.absolute_path.parent.resolve()

    root_index = len(relative_parts) - 1
    try:
        return discovered_file.absolute_path.parents[root_index].resolve()
    except IndexError:
        return discovered_file.absolute_path.parent.resolve()
