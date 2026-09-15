# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@3ff208492908cc07a997a26b6fa469078fdaa26a",
# ]
# ///
"""Shared fail-closed inputs and provenance for generated product documents.

Generated documents are L3 observations: they never carry approval authority
and never flow back into design inputs. Every value written into a document
comes from the design graph or from a recorded projection; missing or
malformed inputs stop generation instead of being reported as "no problem".
"""

from __future__ import annotations

from product_doc_inputs.analysis import (
    ANALYSIS_KIND_TEMPLATE_KEYS,
    ANALYSIS_STATUS_TEMPLATE_KEYS,
    AnalysisArtifact,
    AnalysisBundle,
    analysis_summary,
    load_analysis_results,
)
from product_doc_inputs.common import (
    DOCUMENT_SCHEMA_VERSION,
    SUPPORTED_LANGUAGES,
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    format_number,
    int_attr,
    load_graph,
    load_json_object,
    load_template,
    node_by_id,
    nodes_of_kind,
    number_attr,
    relative_path,
    require_list,
    require_object,
    require_str,
    sha256_file,
    sha256_text,
    single_node_of_kind,
    text_attr,
    write_document,
)
from product_doc_inputs.figures import (
    ProjectionFigure,
    ThemeSongFigure,
    load_projection_figures,
    load_theme_song,
)
from product_doc_inputs.firmware import (
    FirmwareConfigReport,
    ReportDevice,
    ReportPin,
    guard_devices,
    guard_pins,
    guard_report,
    guard_revision,
    load_firmware_config_report,
    load_firmware_inspection_sequence,
)
from product_doc_inputs.quality import (
    DesignPredicates,
    DfmFinding,
    DfmReport,
    PredicateObservation,
    load_design_predicates,
    load_dfm_report,
)

__all__ = [
    "ANALYSIS_KIND_TEMPLATE_KEYS",
    "ANALYSIS_STATUS_TEMPLATE_KEYS",
    "DOCUMENT_SCHEMA_VERSION",
    "SUPPORTED_LANGUAGES",
    "AnalysisArtifact",
    "AnalysisBundle",
    "DesignPredicates",
    "DfmFinding",
    "DfmReport",
    "DocumentGenerationError",
    "DocumentInput",
    "DocumentTemplate",
    "FirmwareConfigReport",
    "PredicateObservation",
    "ProjectionFigure",
    "ReportDevice",
    "ReportPin",
    "ThemeSongFigure",
    "analysis_summary",
    "format_number",
    "guard_devices",
    "guard_pins",
    "guard_report",
    "guard_revision",
    "int_attr",
    "load_analysis_results",
    "load_design_predicates",
    "load_dfm_report",
    "load_firmware_config_report",
    "load_firmware_inspection_sequence",
    "load_graph",
    "load_json_object",
    "load_projection_figures",
    "load_template",
    "load_theme_song",
    "node_by_id",
    "nodes_of_kind",
    "number_attr",
    "relative_path",
    "require_list",
    "require_object",
    "require_str",
    "sha256_file",
    "sha256_text",
    "single_node_of_kind",
    "text_attr",
    "write_document",
]
