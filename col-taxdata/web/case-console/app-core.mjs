export const TOP_LEVEL_SUCCESS_FIELDS = Object.freeze([
  "api_version",
  "request_fingerprints",
  "bundle",
]);

export const VIEW_BUNDLE_FIELDS = Object.freeze({
  result: Object.freeze([
    "kind",
    "contract_version",
    "bundle_ref",
    "status",
    "generated_at",
    "case_input",
  ]),
  intake: Object.freeze(["case_input", "intake_draft"]),
  research: Object.freeze(["research_plan", "research_result"]),
  evidence: Object.freeze([
    "sources",
    "authorities",
    "evidence_spans",
    "normative_relationships",
    "rule_fragments",
  ]),
  evaluations: Object.freeze([
    "deterministic_evaluations",
    "calculation_traces",
  ]),
  unresolved: Object.freeze(["unresolved"]),
});

export const SUPPORTED_RESPONSE_CONTRACTS = Object.freeze({
  "1.0.0": "4.0.0",
  "2.0.0": "5.0.0",
});

const LIMITATION_LABELS = Object.freeze({
  generic_scope: ["scope", "Generic/limited scope"],
  unplanned_scope: ["scope", "Unknown/unplanned scope"],
  missing_facts: ["fact", "Requires facts"],
  temporal_unassessed: ["temporal", "Temporal applicability unassessed"],
  context_gap: ["context", "Context gap"],
  authority_conflict: ["conflict", "Authority conflict"],
  budget_exhausted: ["budget", "Budget exhausted"],
  no_evidence: ["evidence", "No evidence found"],
  unsupported_topic: ["scope", "Unsupported topic"],
});

const OMISSION_LABELS = Object.freeze({
  budget_exhausted: ["budget", "Budget exhausted"],
  not_planned: ["research", "Not researched"],
  unsupported_scope: ["scope", "Unsupported scope"],
  blocked_by_facts: ["fact", "Requires facts"],
  context_unavailable: ["context", "Context gap"],
  integrity_failure: ["integrity", "Integrity failure"],
});

const UNRESOLVED_LABELS = Object.freeze({
  missing_fact: ["fact", "Missing fact"],
  ambiguous_fact: ["fact", "Ambiguous fact"],
  no_relevant_corpus_evidence: ["corpus", "Corpus gap"],
  corpus_gap: ["corpus", "Corpus gap"],
  unresolved_identity: ["authority", "Authority metadata unresolved"],
  temporal_uncertainty: ["temporal", "Temporal uncertainty"],
  conflicting_authority: ["conflict", "Authority conflict"],
  context_incomplete: ["context", "Context gap"],
  budget_exhausted: ["budget", "Budget exhausted"],
  unsupported_topic: ["scope", "Unsupported topic"],
  unplanned_scope: ["scope", "Unknown/unplanned scope"],
  integrity_failure: ["integrity", "Integrity failure"],
  unsupported_evaluator: ["synthesis", "Deterministic evaluator unavailable"],
  requires_interpretive_synthesis: ["synthesis", "External synthesis required"],
  other: ["other", "Research limitation"],
});

function isObject(value) {
  return value !== null && !Array.isArray(value) && typeof value === "object";
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function pickOwn(source, fields) {
  const selected = {};
  for (const field of fields) {
    if (Object.prototype.hasOwnProperty.call(source, field)) {
      selected[field] = source[field];
    }
  }
  return selected;
}

function indexBy(items, key) {
  return new Map(
    asArray(items)
      .filter((item) => isObject(item) && typeof item[key] === "string")
      .map((item) => [item[key], item]),
  );
}

function addWarning(target, seen, kind, code, label, detail = null) {
  const identity = `${kind}\u0000${code}\u0000${detail ?? ""}`;
  if (seen.has(identity)) return;
  seen.add(identity);
  target.push({ kind, code, label, detail });
}

function collectWarnings(aspect, coverage, omissions, unresolved) {
  const warnings = [];
  const seen = new Set();

  if (aspect.scope_status === "generic_limited") {
    addWarning(warnings, seen, "scope", "generic_scope", "Generic/limited scope");
  } else if (aspect.scope_status === "unknown_unplanned") {
    addWarning(warnings, seen, "scope", "unplanned_scope", "Unknown/unplanned scope");
  }

  if (!coverage) {
    addWarning(
      warnings,
      seen,
      "research",
      "coverage_record_missing",
      "Coverage record unavailable",
    );
  } else {
    if (coverage.execution_status === "not_started") {
      addWarning(warnings, seen, "research", "not_researched", "Not researched");
    } else if (coverage.execution_status === "budget_exhausted") {
      addWarning(warnings, seen, "budget", "budget_exhausted", "Budget exhausted");
    } else if (coverage.execution_status === "blocked") {
      addWarning(warnings, seen, "research", "research_blocked", "Research blocked");
    }

    if (coverage.evidence_status === "none_found") {
      addWarning(warnings, seen, "evidence", "no_evidence", "No evidence found");
    } else if (coverage.evidence_status === "context_incomplete") {
      addWarning(warnings, seen, "context", "context_gap", "Context gap");
    }

    if (coverage.authority_status === "ambiguous") {
      addWarning(warnings, seen, "authority", "authority_ambiguous", "Authority metadata ambiguous");
    } else if (coverage.authority_status === "conflicting") {
      addWarning(warnings, seen, "conflict", "authority_conflict", "Authority conflict");
    }

    if (coverage.temporal_status === "unassessed") {
      addWarning(
        warnings,
        seen,
        "temporal",
        "temporal_unassessed",
        "Temporal applicability unassessed",
      );
    } else if (coverage.temporal_status === "mixed") {
      addWarning(warnings, seen, "temporal", "temporal_mixed", "Mixed temporal support");
    } else if (coverage.temporal_status === "ambiguous") {
      addWarning(warnings, seen, "temporal", "temporal_ambiguous", "Temporal applicability ambiguous");
    }

    if (coverage.fact_status === "missing") {
      addWarning(warnings, seen, "fact", "missing_facts", "Requires facts");
    } else if (coverage.fact_status === "ambiguous") {
      addWarning(warnings, seen, "fact", "ambiguous_facts", "Facts ambiguous");
    }

    if (coverage.synthesis_status === "requires_facts") {
      addWarning(warnings, seen, "fact", "requires_facts", "Requires facts");
    } else if (coverage.synthesis_status === "requires_interpretive_synthesis") {
      addWarning(
        warnings,
        seen,
        "synthesis",
        "requires_interpretive_synthesis",
        "External synthesis required",
      );
    }

    if (coverage.support_closure === "unsupported_scope") {
      addWarning(warnings, seen, "scope", "unsupported_scope", "Unsupported scope");
    }

    for (const code of asArray(coverage.limitation_codes)) {
      const [kind, label] = LIMITATION_LABELS[code] ?? ["other", code];
      addWarning(warnings, seen, kind, code, label);
    }
  }

  for (const omission of omissions) {
    const [kind, label] = OMISSION_LABELS[omission.reason] ?? ["other", omission.reason];
    addWarning(
      warnings,
      seen,
      kind,
      `omission:${omission.reason ?? "unknown"}`,
      label,
      omission.description ?? null,
    );
  }

  for (const item of unresolved) {
    const [kind, label] = UNRESOLVED_LABELS[item.category] ?? ["other", item.category ?? "Research limitation"];
    addWarning(
      warnings,
      seen,
      kind,
      `unresolved:${item.category ?? "other"}`,
      label,
      item.description ?? null,
    );
  }

  return warnings;
}

function authoritySummary(authority) {
  if (!isObject(authority)) {
    return {
      authority_ref: null,
      display_name: null,
      document_type: null,
      issuer: null,
      jurisdiction_scope: null,
      classification_state: null,
      temporal_resolution_state: null,
      temporal_effective: null,
    };
  }
  const temporalState = isObject(authority.temporal_state)
    ? authority.temporal_state
    : {};
  return {
    authority_ref: authority.authority_ref ?? null,
    display_name: authority.display_name ?? null,
    document_type: authority.document_type ?? null,
    issuer: authority.issuer ?? null,
    jurisdiction_scope: authority.jurisdiction_scope ?? null,
    classification_state: authority.classification_state ?? null,
    temporal_resolution_state: temporalState.resolution_state ?? null,
    temporal_effective: Object.prototype.hasOwnProperty.call(
      temporalState,
      "effective",
    )
      ? temporalState.effective
      : null,
  };
}

function sourceSummary(source) {
  if (!isObject(source)) {
    return {
      source_ref: null,
      title: null,
      authority: null,
      source_uri: null,
    };
  }
  return {
    source_ref: source.source_ref ?? null,
    title: source.title ?? null,
    authority: source.authority ?? null,
    source_uri: source.source_uri ?? null,
  };
}

function selectedEvidenceForAspect(
  aspectRef,
  selections,
  evidenceByRef,
  authorityByRef,
  sourceByRef,
) {
  const evidence = [];
  for (const selection of selections.filter(
    (item) => item.aspect_ref === aspectRef,
  )) {
    const authority = authorityByRef.get(selection.authority_ref);
    for (const evidenceRef of asArray(selection.evidence_refs)) {
      const span = evidenceByRef.get(evidenceRef);
      const source = span ? sourceByRef.get(span.source_ref) : null;
      evidence.push({
        selection_ref: selection.selection_ref ?? null,
        evidence_ref: evidenceRef,
        exact_text: span?.exact_text ?? null,
        document_ref: span?.document_ref ?? null,
        provision_ref: span?.provision_ref ?? null,
        basis: selection.basis ?? null,
        context_status: selection.context_status ?? null,
        authority_status: selection.authority_status ?? null,
        temporal_status: selection.temporal_status ?? null,
        authority: authoritySummary(authority),
        source: sourceSummary(source),
      });
    }
  }
  return evidence;
}

function coverageStatusProjection(coverage) {
  if (!isObject(coverage)) return null;
  return pickOwn(coverage, [
    "execution_status",
    "evidence_status",
    "authority_status",
    "temporal_status",
    "fact_status",
    "synthesis_status",
    "support_closure",
    "limitation_codes",
  ]);
}

export function buildRequest(problemText, asOfDate, clientReference, callerMetadataText) {
  if (problemText.length === 0) {
    throw new Error("problem_text is required.");
  }

  const request = { problem_text: problemText };
  if (asOfDate.length > 0) request.as_of_date = asOfDate;
  if (clientReference.length > 0) request.client_reference = clientReference;

  if (callerMetadataText.length > 0) {
    let metadata;
    try {
      metadata = JSON.parse(callerMetadataText);
    } catch {
      throw new Error("caller_metadata must be valid JSON.");
    }
    if (!isObject(metadata)) {
      throw new Error("caller_metadata must be a JSON object.");
    }
    request.caller_metadata = metadata;
  }
  return request;
}

export function buildCoverageView(bundle) {
  if (!isObject(bundle) || bundle.contract_version !== "5.0.0") {
    return {
      available: false,
      compatibility: "legacy",
      version_message:
        `Structured coverage is unavailable for CASE ${bundle?.contract_version ?? "unknown"}. ` +
        "Historical bundle JSON remains available in the other views and raw export.",
    };
  }

  const questions = asArray(bundle.intake_draft?.questions);
  const aspects = asArray(bundle.research_plan?.aspects);
  const researchResult = isObject(bundle.research_result)
    ? bundle.research_result
    : {};
  const coverages = asArray(researchResult.aspect_coverage);
  const selections = asArray(researchResult.evidence_selections);
  const omittedWork = asArray(researchResult.omitted_work);
  const unresolvedItems = asArray(bundle.unresolved);

  const coverageByAspect = indexBy(coverages, "aspect_ref");
  const omissionByRef = indexBy(omittedWork, "omission_ref");
  const unresolvedByRef = indexBy(unresolvedItems, "unresolved_ref");
  const evidenceByRef = indexBy(bundle.evidence_spans, "evidence_ref");
  const authorityByRef = indexBy(bundle.authorities, "authority_ref");
  const sourceByRef = indexBy(bundle.sources, "source_ref");

  const questionByRef = indexBy(questions, "question_ref");
  const questionRefs = [];
  for (const question of questions) {
    if (!questionRefs.includes(question.question_ref)) {
      questionRefs.push(question.question_ref);
    }
  }
  for (const aspect of aspects) {
    if (
      typeof aspect.question_ref === "string" &&
      !questionRefs.includes(aspect.question_ref)
    ) {
      questionRefs.push(aspect.question_ref);
    }
  }

  const aspectViews = aspects
    .slice()
    .sort((left, right) => (left.sequence ?? 0) - (right.sequence ?? 0))
    .map((aspect) => {
      const coverage = coverageByAspect.get(aspect.aspect_ref) ?? null;
      const omissions = coverage
        ? asArray(coverage.omission_refs)
            .map((ref) => omissionByRef.get(ref))
            .filter(Boolean)
        : omittedWork.filter((item) => item.aspect_ref === aspect.aspect_ref);
      const unresolved = coverage
        ? asArray(coverage.unresolved_refs)
            .map((ref) => unresolvedByRef.get(ref))
            .filter(Boolean)
        : unresolvedItems.filter((item) =>
            asArray(item.related_aspect_refs).includes(aspect.aspect_ref),
          );

      return {
        aspect_ref: aspect.aspect_ref,
        question_ref: aspect.question_ref,
        dimension_key: aspect.dimension_key ?? null,
        research_goal: aspect.research_goal ?? null,
        origin: aspect.origin ?? null,
        scope_status: aspect.scope_status ?? null,
        decomposition_status: aspect.decomposition_status ?? null,
        required: aspect.required ?? null,
        fact_refs: asArray(aspect.fact_refs),
        coverage: coverageStatusProjection(coverage),
        warnings: collectWarnings(aspect, coverage, omissions, unresolved),
        omitted_work: omissions.map((item) =>
          pickOwn(item, [
            "omission_ref",
            "class",
            "reason",
            "required",
            "description",
          ]),
        ),
        unresolved: unresolved.map((item) =>
          pickOwn(item, [
            "unresolved_ref",
            "category",
            "description",
            "needed_information",
            "next_action",
          ]),
        ),
        selected_evidence: selectedEvidenceForAspect(
          aspect.aspect_ref,
          selections,
          evidenceByRef,
          authorityByRef,
          sourceByRef,
        ),
        external_synthesis:
          coverage?.synthesis_status === "requires_interpretive_synthesis",
      };
    });

  const caseInput = isObject(bundle.case_input) ? bundle.case_input : {};
  // Caller authority is the only source for the displayed temporal input.
  // A research-context value must never be promoted into an omitted CaseInput.
  const asOfDate = Object.prototype.hasOwnProperty.call(caseInput, "as_of_date")
    ? caseInput.as_of_date
    : null;

  return {
    available: true,
    compatibility: "current",
    api_contract: "2.0.0",
    bundle_contract: "5.0.0",
    bundle_status: bundle.status ?? null,
    research_status: researchResult.status ?? null,
    as_of_date: asOfDate ?? null,
    date_status: asOfDate ? "caller_supplied" : "unassessed",
    questions: questionRefs.map((questionRef) => {
      const question = questionByRef.get(questionRef);
      return {
        question_ref: questionRef,
        text: question?.text ?? null,
        category: question?.category ?? null,
        status: question?.status ?? null,
        aspects: aspectViews.filter(
          (aspect) => aspect.question_ref === questionRef,
        ),
      };
    }),
  };
}

function versionMessage(apiVersion, bundleVersion) {
  const expected = SUPPORTED_RESPONSE_CONTRACTS[apiVersion];
  if (expected === undefined) {
    return `Unsupported CASE REST API version ${apiVersion ?? "unknown"}. Raw JSON remains available.`;
  }
  return (
    `CASE REST API ${apiVersion} expects CASE ${expected}, but the response carries ` +
    `CASE ${bundleVersion ?? "unknown"}. The console will not reinterpret the mismatch.`
  );
}

export function buildRawExport(payload) {
  if (!isObject(payload)) {
    throw new Error("CASE response is not a JSON object.");
  }
  const apiVersion =
    typeof payload.api_version === "string" ? payload.api_version : "unknown";
  return {
    filename: `col-taxdata-case-response-${apiVersion}.json`,
    text: `${JSON.stringify(payload, null, 2)}\n`,
  };
}

export function buildViewModels(payload) {
  if (!isObject(payload)) {
    throw new Error("CASE response is not a JSON object.");
  }

  if (Object.prototype.hasOwnProperty.call(payload, "error")) {
    const diagnostics = {};
    if (Object.prototype.hasOwnProperty.call(payload, "api_version")) {
      diagnostics.api_version = payload.api_version;
    }
    if (Object.prototype.hasOwnProperty.call(payload, "request_fingerprints")) {
      diagnostics.request_fingerprints = payload.request_fingerprints;
    }
    return {
      result: { error: payload.error },
      intake: null,
      research: null,
      evidence: null,
      evaluations: null,
      unresolved: null,
      coverage: null,
      diagnostics,
      raw: payload,
    };
  }

  for (const field of TOP_LEVEL_SUCCESS_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(payload, field)) {
      throw new Error("CASE response does not match the published success envelope.");
    }
  }

  const bundle = payload.bundle;
  if (!isObject(bundle)) {
    throw new Error("CASE response bundle is not an object.");
  }

  const apiVersion = payload.api_version;
  const bundleVersion = bundle.contract_version;
  const expectedBundleVersion = SUPPORTED_RESPONSE_CONTRACTS[apiVersion];
  const compatible =
    expectedBundleVersion !== undefined &&
    expectedBundleVersion === bundleVersion;

  const diagnostics = {
    api_version: apiVersion,
    bundle_contract_version: bundleVersion ?? null,
    request_fingerprints: payload.request_fingerprints,
  };
  if (
    isObject(bundle.intake_draft) &&
    Object.prototype.hasOwnProperty.call(bundle.intake_draft, "model_metadata")
  ) {
    diagnostics.intake_model_metadata = bundle.intake_draft.model_metadata;
  }

  if (!compatible) {
    const message = versionMessage(apiVersion, bundleVersion);
    return {
      result: {
        version_message: message,
        api_version: apiVersion ?? null,
        bundle_contract_version: bundleVersion ?? null,
      },
      intake: null,
      research: null,
      evidence: null,
      evaluations: null,
      unresolved: null,
      coverage: {
        available: false,
        compatibility: "unsupported",
        version_message: message,
      },
      diagnostics,
      raw: payload,
    };
  }

  return {
    result: pickOwn(bundle, VIEW_BUNDLE_FIELDS.result),
    intake: pickOwn(bundle, VIEW_BUNDLE_FIELDS.intake),
    research: pickOwn(bundle, VIEW_BUNDLE_FIELDS.research),
    evidence: pickOwn(bundle, VIEW_BUNDLE_FIELDS.evidence),
    evaluations: pickOwn(bundle, VIEW_BUNDLE_FIELDS.evaluations),
    unresolved: pickOwn(bundle, VIEW_BUNDLE_FIELDS.unresolved),
    coverage:
      bundleVersion === "5.0.0"
        ? buildCoverageView(bundle)
        : {
            available: false,
            compatibility: "legacy",
            version_message:
              `REST ${apiVersion} / CASE ${bundleVersion} is a supported historical contract. ` +
              "Structured aspect coverage was introduced in CASE 5.0.0; inspect Research, Evidence and Raw JSON for this response.",
          },
    diagnostics,
    raw: payload,
  };
}
